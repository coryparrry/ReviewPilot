#!/usr/bin/env python3
"""Prepare and score a bug-hunting pre-PR review."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CALIBRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "coderabbit-comment-calibration.json"
)
DEFAULT_PUBLIC_CALIBRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "public-coderabbit-calibration.json"
)
DEFAULT_FULL_REPO_SCAN_LIMIT = 20
DEFAULT_UNTRACKED_FILE_LIMIT = 12
DEFAULT_UNTRACKED_BYTES = 12000
JsonDict = dict[str, Any]


def run_cmd(cmd: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout


def repo_root(cwd: Path) -> Path:
    return Path(run_cmd(["git", "rev-parse", "--show-toplevel"], cwd).strip())


def current_branch(cwd: Path) -> str:
    return run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


def load_default_prompt(skill_dir: Path) -> str:
    config_path = skill_dir / "agents" / "openai.yaml"
    text = config_path.read_text(encoding="utf-8")
    marker = 'default_prompt: "'
    start = text.find(marker)
    if start == -1:
        raise ValueError(f"Could not find default_prompt in {config_path}")
    start += len(marker)
    end = text.find('"', start)
    if end == -1:
        raise ValueError(f"Could not parse default_prompt in {config_path}")
    return text[start:end]


def resolve_repo_path(repo: Path, requested: str | None) -> Path | None:
    if not requested:
        return None
    candidate = Path(requested)
    return (
        candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
    )


def is_probably_text_file(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:2048]
    except OSError:
        return False
    return b"\x00" not in sample


def git_untracked_files(repo: Path) -> list[Path]:
    output = run_cmd(["git", "ls-files", "--others", "--exclude-standard"], repo)
    return [repo / line.strip() for line in output.splitlines() if line.strip()]


def render_untracked_files(
    repo: Path, limit: int = DEFAULT_UNTRACKED_FILE_LIMIT
) -> tuple[str, list[str]]:
    sections: list[str] = []
    included: list[str] = []
    for path in git_untracked_files(repo)[:limit]:
        rel = path.relative_to(repo).as_posix()
        if not path.is_file() or not is_probably_text_file(path):
            sections.append(
                f"Untracked file: {rel}\n(Binary or unreadable file omitted)\n"
            )
            included.append(rel)
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = "[Could not read file contents]"
        sections.append(textwrap.dedent(f"""\
                Untracked file: {rel}
                ```
                {body[:DEFAULT_UNTRACKED_BYTES]}
                ```
                """).strip())
        included.append(rel)
    return ("\n\n".join(sections), included)


def get_diff(
    repo: Path, base: str | None, pr: str | None, mode: str
) -> tuple[str, str]:
    if pr:
        diff = run_cmd(["gh", "pr", "diff", pr, "--patch"], repo)
        try:
            meta = run_cmd(
                [
                    "gh",
                    "pr",
                    "view",
                    pr,
                    "--json",
                    "number,title,baseRefName,headRefName,url",
                ],
                repo,
            )
        except subprocess.CalledProcessError:
            meta = ""
        payload = json.loads(meta) if meta else {}
        payload["mode"] = "pull-request"
        payload["review_mode"] = mode
        return diff, json.dumps(payload, indent=2)

    resolved_base = base or "origin/main"
    branch = current_branch(repo)
    metadata: dict[str, Any] = {
        "head": branch,
        "review_mode": mode,
    }

    if mode == "changes":
        diff = run_cmd(["git", "diff", f"{resolved_base}...HEAD"], repo)
        metadata.update(
            {
                "mode": "local-branch",
                "base": resolved_base,
                "diff_basis": f"{resolved_base}...HEAD",
            }
        )
        return diff, json.dumps(metadata, indent=2)

    if mode == "dirty":
        diff = run_cmd(["git", "diff", "--patch", "HEAD"], repo)
        untracked_rendered, untracked_files = render_untracked_files(repo)
        if untracked_rendered:
            diff = "\n\n".join(
                chunk
                for chunk in [
                    diff.strip(),
                    "Untracked working tree files:\n" + untracked_rendered,
                ]
                if chunk
            )
        metadata.update(
            {
                "mode": "dirty-worktree",
                "base": "HEAD",
                "diff_basis": "HEAD vs working tree",
                "untracked_files": untracked_files,
            }
        )
        return diff or "No tracked dirty diff found.\n", json.dumps(metadata, indent=2)

    if mode == "full":
        diff = run_cmd(["git", "diff", f"{resolved_base}...HEAD"], repo)
        metadata.update(
            {
                "mode": "full-repo",
                "base": resolved_base,
                "diff_basis": f"{resolved_base}...HEAD",
                "full_repo_scan": True,
            }
        )
        if not diff.strip():
            diff = "No committed diff found for the selected base. Use the repo surface scan and hotspot hints."
        return diff, json.dumps(metadata, indent=2)

    raise ValueError(f"Unsupported review mode: {mode}")


def run_surface_scan(
    skill_dir: Path, repo: Path, base: str | None, mode: str
) -> JsonDict:
    scan_script = skill_dir / "scripts" / "review_surface_scan.py"
    cmd = [
        sys.executable,
        str(scan_script),
        "--repo",
        str(repo),
        "--mode",
        mode,
        "--json",
    ]
    if base and mode in {"changes", "full"}:
        cmd.extend(["--base", base])
    completed = subprocess.run(
        cmd,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("Surface scan output must be a JSON object.")
    return payload


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def accepted_calibration_focus(calibration_path: Path) -> list[str]:
    payload = load_json(calibration_path)
    if not isinstance(payload, list):
        return []
    focus: list[str] = []
    seen_uses: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("verdict") != "accept":
            continue
        use = str(entry.get("use", "")).strip()
        summary = str(entry.get("summary", "")).strip()
        if not summary:
            continue
        if use and use not in seen_uses:
            focus.append(f"{use}: {summary}")
            seen_uses.add(use)
        elif not use:
            focus.append(summary)
        if len(focus) == 6:
            break
    return focus


def public_calibration_focus(calibration_path: Path) -> list[str]:
    payload = load_json(calibration_path)
    if not isinstance(payload, list):
        return []
    focus: list[str] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        use = str(entry.get("use", "")).strip()
        summary = str(entry.get("summary", "")).strip()
        if not summary:
            continue
        focus.append(f"{use}: {summary}" if use else summary)
        if len(focus) == 8:
            break
    return focus


def comparison_focus(quality_comparison_path: Path | None) -> list[str]:
    if quality_comparison_path is None or not quality_comparison_path.is_file():
        return []
    payload = load_json(quality_comparison_path)
    prompt_focus = payload.get("prompt_focus")
    if not isinstance(prompt_focus, list):
        return []
    return [str(item).strip() for item in prompt_focus if str(item).strip()]


def render_surface_scan(scan_report: JsonDict, depth: str) -> str:
    lines = ["Surface scan summary:"]
    lines.append(f"- Changed files: {scan_report.get('changed_file_count', 0)}")

    layers = scan_report.get("layers")
    if isinstance(layers, dict) and layers:
        layer_parts: list[str] = []
        for layer_name, payload in sorted(layers.items()):
            if not isinstance(payload, dict):
                continue
            count = payload.get("count")
            if isinstance(count, int):
                layer_parts.append(f"{layer_name}={count}")
        if layer_parts:
            lines.append(f"- Changed layers: {', '.join(layer_parts[:6])}")

    risk_hits = scan_report.get("risk_hits")
    if isinstance(risk_hits, list) and risk_hits:
        lines.append("Risk prompts to verify:")
        limit = 4 if depth == "quick" else 7
        for risk in risk_hits[:limit]:
            if not isinstance(risk, dict):
                continue
            severity = str(risk.get("severity") or "unknown")
            title = str(risk.get("title") or "").strip()
            check = str(risk.get("check") or "").strip()
            if title and check:
                lines.append(f"- [{severity}] {title}: {check}")

    adjacent = scan_report.get("adjacent_paths_to_inspect")
    if isinstance(adjacent, list) and adjacent:
        lines.append("Adjacent paths worth opening:")
        limit = 6 if depth == "quick" else 10
        for path in adjacent[:limit]:
            value = str(path).strip()
            if value:
                lines.append(f"- {value}")

    hotspots = scan_report.get("repo_hotspots")
    if isinstance(hotspots, list) and hotspots:
        lines.append("Repo hotspots worth pressure-testing:")
        limit = 4 if depth == "quick" else 8
        for hotspot in hotspots[:limit]:
            if not isinstance(hotspot, dict):
                continue
            path = str(hotspot.get("path") or "").strip()
            tags = hotspot.get("tags")
            if not path:
                continue
            if isinstance(tags, list) and tags:
                lines.append(f"- {path} [{', '.join(str(tag) for tag in tags)}]")
            else:
                lines.append(f"- {path}")

    required_questions = scan_report.get("required_questions")
    if isinstance(required_questions, list) and required_questions:
        lines.append("Questions to explicitly answer before you stop:")
        limit = 4 if depth == "quick" else 7
        for question in required_questions[:limit]:
            value = str(question).strip()
            if value:
                lines.append(f"- {value}")

    return "\n".join(lines)


def render_miss_calibration_section(
    skill_dir: Path, quality_comparison_path: Path | None
) -> str:
    accepted_focus = accepted_calibration_focus(DEFAULT_CALIBRATION_PATH)
    public_focus = public_calibration_focus(DEFAULT_PUBLIC_CALIBRATION_PATH)
    live_focus = comparison_focus(quality_comparison_path)
    if not accepted_focus and not public_focus and not live_focus:
        return ""

    lines = ["Miss calibration focus:"]
    if live_focus:
        lines.append("Fresh live misses to bias toward:")
        lines.extend(f"- {item}" for item in live_focus[:4])

    durable_focus: list[str] = []
    for item in public_focus[:3]:
        if item not in durable_focus:
            durable_focus.append(item)
    for item in accepted_focus:
        if item in durable_focus:
            continue
        durable_focus.append(item)
        if len(durable_focus) == 5:
            break
    if durable_focus:
        lines.append("Durable miss patterns worth preserving:")
        lines.extend(f"- {item}" for item in durable_focus)
    return "\n".join(lines)


def build_prompt(
    default_prompt: str,
    metadata: str,
    scan: str,
    diff: str,
    mode: str,
    depth: str,
    calibration_section: str,
) -> str:
    mode_guidance = {
        "changes": "Review the committed diff as the primary surface, but trace into adjacent callers, tests, and contracts.",
        "dirty": "Review the local dirty worktree, including untracked files included below, and assume recent edits may be incomplete.",
        "full": "Treat the diff as only one clue. Use the repo surface scan and hotspot list to inspect broader repo behavior.",
    }[mode]
    depth_guidance = {
        "quick": "Keep the review fast and high-signal. Prefer a short list of the strongest findings over broad exploration.",
        "deep": "Spend extra review budget on cross-file tracing, negative paths, stale-state behavior, and source-of-truth drift.",
    }[depth]
    return textwrap.dedent(f"""\
        {default_prompt}

        Produce a release-blocking code review.
        Findings first. Prioritize correctness, security, AI-slop drift, stale state, broken paths, broken tests, and missing negative-path handling.
        Treat the diff as the entry point, not the review boundary. Use the scan hints to choose where to dig next, but verify every claim from the code.
        If there are no findings, say so explicitly and mention residual risk or test gaps briefly.

        Output contract:
        - Use the exact headings: Findings, Open questions, Change summary.
        - Each finding needs a short title, one short "Why this is a bug:" sentence, and one short "Evidence:" sentence.
        - Prioritize findings that are directly caused by the changed files, changed hunks, or the state transitions they now control.
        - Before reporting a finding, name the concrete trigger scenario and the changed code path that makes it newly possible.
        - For clear bugs and security issues, do not skip a real defect only because the trigger is narrow.
        - For lower-severity concerns, report only when you can confidently explain the failure path from source evidence.
        - Do not speculate about broken callers, missing definitions, or incomplete scopes unless the specific affected code path is visible in the review context.
        - If the visible diff ends at an opening scope such as `if`, `for`, `try`, or a function body, treat that as a context boundary, not automatically as incomplete code.
        - Name the concrete symbol, field, error type, or state surface that is wrong.
        - When the issue is stale state, source-of-truth drift, or contract mismatch, name both sides that disagree.
        - Prefer concrete API names, field names, functions, enums, and error names.
        - For every `[high]` risk prompt in Surface scan, either turn it into a finding or add an `Open questions` line starting `Verified high-risk prompt:` that names the prompt and the concrete code evidence that made it safe.
        - Do not claim a high-risk prompt is verified just because the happy path handles returned errors; for optimistic rollback, explicitly check thrown or rejected awaited mutations too.

        Review loop:
        1. Pressure-test the changed code first for missing guards, guard-then-write races, rollback gaps, stale-status cleanup, and read-vs-write drift.
        2. Use the scan section below to inspect every `[high]` risk prompt before lower-risk cleanup.
        3. If you find one real bug in a touched area, check the sibling branch or mirrored path for the same failure class.
        4. Only then spend time on broader repo drift.

        Review mode guidance:
        - Mode: {mode}
        - Depth: {depth}
        - {mode_guidance}
        - {depth_guidance}

        {calibration_section}

        Review context:
        {metadata}

        Surface scan:
        {scan}

        Diff or review surface:
        {diff}
        """).strip() + "\n"


def call_openai(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    payload = {
        "model": model,
        "input": prompt,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API request failed: {exc.code} {detail}") from exc

    if not isinstance(body, dict):
        raise RuntimeError("OpenAI response body must be a JSON object.")

    output = body.get("output_text")
    if isinstance(output, str) and output:
        return output

    pieces: list[str] = []
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                pieces.append(text)
    if pieces:
        return "\n".join(pieces)
    raise RuntimeError("OpenAI response did not contain output text.")


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_review_text(args: argparse.Namespace) -> str | None:
    if args.review_file:
        return Path(args.review_file).read_text(encoding="utf-8")
    review_text = args.review_text
    if isinstance(review_text, str):
        return review_text
    return None


def run_benchmarks(skill_dir: Path, review_file: Path, repo: Path) -> str:
    runner = skill_dir / "scripts" / "run_review_benchmarks.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--review-file", str(review_file)],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout


def prepare_review_artifacts(
    skill_dir: Path,
    repo: Path,
    *,
    base: str | None,
    pr: str | None,
    mode: str,
    depth: str,
    quality_comparison: str | None,
) -> dict[str, str]:
    default_prompt = load_default_prompt(skill_dir)
    diff, metadata = get_diff(repo, base, pr, mode)
    scan_report = run_surface_scan(skill_dir, repo, base if not pr else None, mode)
    scan = render_surface_scan(scan_report, depth)
    calibration_section = render_miss_calibration_section(
        skill_dir,
        resolve_repo_path(repo, quality_comparison),
    )
    prompt = build_prompt(
        default_prompt, metadata, scan, diff, mode, depth, calibration_section
    )
    return {
        "diff": diff,
        "metadata": metadata,
        "scan": scan,
        "prompt": prompt,
        "calibration_section": calibration_section,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and score a pre-PR bug-hunting review."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository path. Defaults to the current directory.",
    )
    parser.add_argument(
        "--base", help="Base branch for local diff mode. Defaults to origin/main."
    )
    parser.add_argument("--pr", help="PR number, URL, or branch to review via gh.")
    parser.add_argument(
        "--mode",
        default="changes",
        choices=["changes", "dirty", "full"],
        help="Review surface. changes=base...HEAD, dirty=local worktree, full=broader repo scan.",
    )
    parser.add_argument(
        "--depth",
        default="quick",
        choices=["quick", "deep"],
        help=(
            "Prompt depth. Defaults to quick to keep normal runs budget-safe; "
            "deep uses the fuller package and should be requested deliberately."
        ),
    )
    parser.add_argument(
        "--review-file", help="Path to an existing review artifact to score."
    )
    parser.add_argument("--review-text", help="Inline review text to score.")
    parser.add_argument(
        "--quality-comparison",
        help="Optional quality-comparison JSON artifact to include as live miss calibration in the prompt.",
    )
    parser.add_argument(
        "--use-openai-api",
        action="store_true",
        help="Optional legacy path: call the OpenAI Responses API when no review artifact is supplied.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("CODEX_REVIEW_MODEL", "gpt-5.4-mini"),
        help="OpenAI model to use with --use-openai-api. Defaults to CODEX_REVIEW_MODEL or gpt-5.4-mini.",
    )
    parser.add_argument(
        "--output-dir",
        default=".codex-review",
        help="Directory under the repo root for saved artifacts.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare diff, prompt, and scan artifacts without calling the OpenAI API.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.review_file and args.review_text is not None:
        raise SystemExit("Pass either --review-file or --review-text, not both.")

    skill_dir = Path(__file__).resolve().parent.parent
    repo = repo_root(Path(args.repo).resolve())
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = repo / args.output_dir / timestamp

    prepared = prepare_review_artifacts(
        skill_dir,
        repo,
        base=args.base,
        pr=args.pr,
        mode=args.mode,
        depth=args.depth,
        quality_comparison=args.quality_comparison,
    )

    write_file(out_dir / "diff.patch", prepared["diff"])
    write_file(out_dir / "review-metadata.json", prepared["metadata"])
    write_file(out_dir / "surface-scan.txt", prepared["scan"])
    write_file(out_dir / "review-prompt.txt", prepared["prompt"])
    if prepared["calibration_section"]:
        write_file(
            out_dir / "miss-calibration.txt", prepared["calibration_section"] + "\n"
        )

    if args.prepare_only:
        print(f"Prepared review artifacts in {out_dir}")
        return 0

    review_text = read_review_text(args)
    if review_text is None:
        if not args.use_openai_api:
            print(f"Prepared review artifacts in {out_dir}")
            print("No review artifact was supplied, so no model call was attempted.")
            print(
                f"Next step: review the prompt in {out_dir / 'review-prompt.txt'} and rerun with --review-file or --review-text."
            )
            return 0
        review_text = call_openai(prepared["prompt"], args.model)

    review_file = out_dir / "review.md"
    write_file(review_file, review_text)
    benchmark_output = run_benchmarks(skill_dir, review_file, repo)
    write_file(out_dir / "benchmark-summary.txt", benchmark_output)

    print(f"Artifacts: {out_dir}")
    print()
    print(benchmark_output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
