import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Tuple

JsonDict = dict[str, Any]

SECTION_HEADING_RE = re.compile(r"^\*\*(.+?)\*\*$")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
NUMBERED_ITEM_RE = re.compile(r"^\d+\.\s+", re.MULTILINE)
PLAIN_SECTION_HEADINGS = {
    "findings",
    "open questions",
    "change summary",
    "residual risk",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a bug-hunting review run, invoke Codex non-interactively, and benchmark the resulting review."
        )
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository path. Defaults to the current directory.",
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base branch for review diff mode. Defaults to origin/main.",
    )
    parser.add_argument(
        "--mode",
        default="changes",
        choices=["changes", "dirty", "full"],
        help="Review surface. changes=committed diff, dirty=local worktree, full=broader repo scan.",
    )
    parser.add_argument(
        "--depth",
        default="deep",
        choices=["quick", "deep"],
        help="Prompt depth. quick skips benchmarks by default; deep keeps the fuller review package.",
    )
    parser.add_argument(
        "--quality-comparison",
        help="Optional quality-comparison JSON artifact to include as live miss calibration in the prompt.",
    )
    parser.add_argument(
        "--output-dir",
        default=".codex-review",
        help="Directory under the repo root for saved review artifacts.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.4-mini",
        help="Codex model to use. Defaults to gpt-5.4-mini for cheaper local review runs.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare the shared run directory without invoking Codex.",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip benchmark scoring after the review is written.",
    )
    return parser.parse_args()


def load_pre_pr_module(skill_dir: Path) -> types.ModuleType:
    pre_pr_path = skill_dir / "scripts" / "run_pre_pr_review.py"
    spec = importlib.util.spec_from_file_location("bug_hunting_pre_pr", pre_pr_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load helper module from {pre_pr_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_text_if_present(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_codex_base_command() -> list[str]:
    direct = shutil.which("codex")
    if direct:
        try:
            completed = subprocess.run(
                [direct, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            if completed.stdout.strip():
                return [direct]
        except (OSError, subprocess.SubprocessError):
            pass
    npx_cmd = shutil.which("npx.cmd") or shutil.which("npx")
    if npx_cmd:
        return [npx_cmd, "-y", "@openai/codex"]
    raise FileNotFoundError(
        "Could not find a working Codex transport. Neither codex nor npx.cmd was usable."
    )


def run_json_benchmarks(skill_dir: Path, review_file: Path, repo: Path) -> JsonDict:
    runner = skill_dir / "scripts" / "run_review_benchmarks.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--review-file", str(review_file), "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Benchmark runner returned a non-object JSON payload.")
    return payload


def run_repair_plan(
    script_path: Path, review_file: Path, output_dir: Path, repo: Path
) -> str:
    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--review-file",
            str(review_file),
            "--output-dir",
            str(output_dir),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout


def review_file_has_content(review_file: Path) -> bool:
    return review_file.is_file() and bool(read_text_if_present(review_file).strip())


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_name = "body"
    sections[current_name] = []

    for line in text.splitlines():
        stripped = line.strip()
        match = SECTION_HEADING_RE.match(stripped)
        if match:
            current_name = match.group(1).strip().lower()
            sections.setdefault(current_name, [])
            continue
        markdown_match = MARKDOWN_HEADING_RE.match(stripped)
        if markdown_match:
            current_name = markdown_match.group(1).strip().rstrip(":").lower()
            sections.setdefault(current_name, [])
            continue
        plain_name = stripped.lower().rstrip(":")
        if plain_name in PLAIN_SECTION_HEADINGS:
            current_name = plain_name
            sections.setdefault(current_name, [])
            continue
        sections.setdefault(current_name, []).append(line)

    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def split_numbered_items(block: str) -> list[str]:
    if not block.strip():
        return []

    matches = list(NUMBERED_ITEM_RE.finditer(block))
    if not matches:
        return [block.strip()]

    items: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        item = block[start:end].strip()
        if item:
            items.append(item)
    return items


def extract_findings_items(review_text: str) -> list[str]:
    sections = split_sections(review_text)
    findings_block = sections.get("findings", "")
    if not findings_block:
        return []
    lowered = findings_block.strip().lower()
    if lowered.startswith("no findings"):
        return []
    return split_numbered_items(findings_block)


def build_pass_prompts(prompt: str, depth: str) -> list[tuple[str, str]]:
    if depth != "deep":
        return [("single", prompt)]

    return [
        (
            "changed-hunks",
            prompt
            + "\n\nFocus pass:\n"
            + "- Report only bugs directly caused by changed files, changed hunks, or the state transitions those hunks now control.\n"
            + "- Ignore unrelated pre-existing issues elsewhere unless the diff clearly routes through them.\n",
        ),
        (
            "concurrency-state",
            prompt
            + "\n\nFocus pass:\n"
            + "- Prioritize race conditions, TOCTOU bugs, rollback-on-throw gaps, stale status after reset, and source-of-truth drift.\n"
            + "- Re-check shared async helpers for state that is only updated after await, fetch, retry, delay, throttle, or detached-process dispatch.\n"
            + "- Re-check optimistic UI or workflow state for paths where thrown exceptions bypass rollback while returned error objects do not.\n"
            + "- Prefer findings in the touched functions and their immediate callers/callees.\n",
        ),
        (
            "validation-contract",
            prompt
            + "\n\nFocus pass:\n"
            + "- Prioritize missing input validation, NULL or bounds guards, return-value handling, cleanup failures, and changed contract mismatches.\n"
            + "- Re-scan sibling touched functions for the same low-level guard pattern once one missing NULL, parameter, bounds, or return-value check is found.\n"
            + "- Prefer mismatches where the write path stores one source of truth but the read path still uses a live default or fallback value.\n"
            + "- Prefer findings in the touched functions and their immediate callers/callees.\n",
        ),
        (
            "workflow-lifecycle",
            prompt
            + "\n\nFocus pass:\n"
            + "- Prioritize reset, cleanup, teardown, retry, process-launch, timeout, and refresh behavior.\n"
            + "- Check whether the first successful or failing request leaves behind durable state that the next request still interprets correctly.\n"
            + "- Check shell or external-process paths for verification-after-dispatch gaps, missing timeouts, or cleanup steps that depend on unrelated metadata.\n"
            + "- Prefer findings in the touched functions and their immediate callers/callees.\n",
        ),
        (
            "async-helpers",
            prompt
            + "\n\nFocus pass:\n"
            + "- Prioritize shared async helpers such as throttle, retry, backoff, queue, cache, and client wrappers.\n"
            + "- Check whether coordination state is read before await and only written after await, which lets concurrent callers bypass the intended guard.\n"
            + "- Check whether helper fallbacks, retries, and Retry-After handling preserve the intended delay semantics when headers or metadata are absent.\n"
            + "- Prefer findings in the touched helper and the immediate call site that depends on its coordination behavior.\n",
        ),
    ]


def combine_pass_reviews(pass_reviews: list[tuple[str, str]]) -> str:
    combined_items: list[str] = []
    seen: set[str] = set()

    for _, review_text in pass_reviews:
        for item in extract_findings_items(review_text):
            first_line = item.splitlines()[0].strip().lower()
            key = re.sub(r"\s+", " ", first_line)
            if key in seen:
                continue
            seen.add(key)
            combined_items.append(item)

    if not combined_items:
        return "No findings.\n\nResidual risk:\n- Multi-pass review did not surface a concrete release-blocking issue.\n"

    lines = ["**Findings**", ""]
    for index, item in enumerate(combined_items, start=1):
        lines.append(f"{index}. {item}")
        lines.append("")
    lines.extend(
        [
            "**Open questions**",
            "",
            "- None.",
            "",
            "**Change summary**",
            "",
            "- Combined multi-pass deep review from changed-hunk, concurrency-state, validation-contract, workflow-lifecycle, and async-helper passes.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_codex_attempt(
    codex_base_cmd: list[str],
    model: str | None,
    repo: Path,
    prompt: str,
    review_file: Path,
    run_dir: Path,
    attempt: int,
) -> Tuple[bool, str, subprocess.CompletedProcess[str]]:
    if review_file.exists():
        review_file.unlink()

    codex_cmd = [
        *codex_base_cmd,
        "exec",
        "-C",
        str(repo),
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--ephemeral",
        "--output-last-message",
        str(review_file),
    ]
    if model:
        codex_cmd.extend(["--model", model])
    codex_cmd.append("-")

    completed = subprocess.run(
        codex_cmd,
        cwd=repo,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    stdout_log = run_dir / f"codex-attempt-{attempt}-stdout.txt"
    stderr_log = run_dir / f"codex-attempt-{attempt}-stderr.txt"
    write_file(stdout_log, completed.stdout)
    write_file(stderr_log, completed.stderr)

    review_ok = review_file_has_content(review_file)
    if completed.returncode == 0 and review_ok:
        return True, "ok", completed

    if review_file.exists():
        attempt_review = run_dir / f"review-attempt-{attempt}.md"
        write_file(attempt_review, read_text_if_present(review_file))

    if completed.returncode != 0:
        return False, f"codex-exit-{completed.returncode}", completed
    if not review_ok:
        return False, "missing-or-empty-review", completed
    return False, "unknown-review-failure", completed


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    skill_dir = script_path.parent.parent / "skills" / "bug-hunting-code-review"
    repair_script = script_path.parent / "propose_review_repairs.py"
    pre_pr = load_pre_pr_module(skill_dir)

    repo = pre_pr.repo_root(Path(args.repo).resolve())
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = repo / args.output_dir / timestamp

    prepared = pre_pr.prepare_review_artifacts(
        skill_dir,
        repo,
        base=args.base,
        pr=None,
        mode=args.mode,
        depth=args.depth,
        quality_comparison=args.quality_comparison,
    )

    write_file(run_dir / "diff.patch", prepared["diff"])
    write_file(run_dir / "review-metadata.json", prepared["metadata"])
    write_file(run_dir / "surface-scan.txt", prepared["scan"])
    write_file(run_dir / "review-prompt.txt", prepared["prompt"])
    if prepared["calibration_section"]:
        write_file(
            run_dir / "miss-calibration.txt", prepared["calibration_section"] + "\n"
        )

    if args.prepare_only:
        print(f"Prepared review artifacts in {run_dir}")
        return 0

    codex_base_cmd = resolve_codex_base_command()
    review_file = run_dir / "review.md"
    stdout_log = run_dir / "codex-stdout.txt"
    stderr_log = run_dir / "codex-stderr.txt"
    repair_summary = run_dir / "repair-summary.txt"

    max_attempts = 2
    pass_reviews: list[tuple[str, str]] = []
    pass_stdout_texts: list[str] = []
    pass_stderr_texts: list[str] = []
    overall_notes: list[str] = []
    pass_prompts = build_pass_prompts(prepared["prompt"], args.depth)

    for pass_index, (pass_name, pass_prompt) in enumerate(pass_prompts, start=1):
        final_completed = None
        repair_notes: list[str] = []
        reason_before_retry: str | None = None
        success = False
        pass_review_file = run_dir / f"{pass_name}-review.md"

        for attempt in range(1, max_attempts + 1):
            attempt_success, reason, completed = run_codex_attempt(
                codex_base_cmd=codex_base_cmd,
                model=args.model,
                repo=repo,
                prompt=pass_prompt,
                review_file=pass_review_file,
                run_dir=run_dir,
                attempt=pass_index * 10 + attempt,
            )
            final_completed = completed

            if attempt_success:
                if attempt > 1:
                    repair_notes.append(
                        f"{pass_name}: recovered after one automatic read-only retry. "
                        f"First attempt failed with: {reason_before_retry or 'unknown mechanical failure'}."
                    )
                success = True
                break

            if attempt == max_attempts:
                raise RuntimeError(
                    "Codex review generation failed after one automatic read-only retry. "
                    f"Pass {pass_name!r} final failure: {reason}."
                )

            reason_before_retry = reason
            repair_notes.append(
                f"{pass_name}: first Codex review attempt failed mechanically "
                f"({reason}). Retrying once in the same read-only sandbox."
            )

        assert final_completed is not None
        write_file(run_dir / f"{pass_name}-codex-stdout.txt", final_completed.stdout)
        write_file(run_dir / f"{pass_name}-codex-stderr.txt", final_completed.stderr)
        pass_stdout_texts.append(final_completed.stdout)
        pass_stderr_texts.append(final_completed.stderr)
        if repair_notes:
            overall_notes.extend(repair_notes)
        if success:
            pass_reviews.append((pass_name, read_text_if_present(pass_review_file)))

    combined_review = combine_pass_reviews(pass_reviews)
    write_file(review_file, combined_review)
    write_file(stdout_log, "\n\n".join(pass_stdout_texts))
    write_file(stderr_log, "\n\n".join(pass_stderr_texts))
    if overall_notes:
        write_file(repair_summary, "\n".join(overall_notes) + "\n")

    print(f"Artifacts: {run_dir}")
    print(f"Review: {review_file}")
    print(f"Codex command: {' '.join(codex_base_cmd)}")
    print(f"Review mode: {args.mode}")
    print(f"Review depth: {args.depth}")
    if len(pass_prompts) > 1:
        print(
            f"Review strategy: multi-pass ({', '.join(name for name, _ in pass_prompts)})"
        )
    if overall_notes:
        print("Self-repair: recovered after one or more automatic read-only retries.")

    repair_output = run_repair_plan(repair_script, review_file, run_dir, repo)
    print(repair_output.strip())

    should_skip_benchmark = args.no_benchmark or args.depth == "quick"
    if should_skip_benchmark:
        return 0

    benchmark_output = pre_pr.run_benchmarks(skill_dir, review_file, repo)
    benchmark_json = run_json_benchmarks(skill_dir, review_file, repo)
    write_file(run_dir / "benchmark-summary.txt", benchmark_output)
    write_file(
        run_dir / "benchmark-summary.json", json.dumps(benchmark_json, indent=2) + "\n"
    )

    print()
    print(benchmark_output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
