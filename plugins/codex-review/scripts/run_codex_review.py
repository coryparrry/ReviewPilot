import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

JsonDict = dict[str, Any]
DEFAULT_PASS_TIMEOUT_SECONDS = 420
DEFAULT_MAX_DEEP_PASSES = 3
REVIEW_RUN_SUMMARY_SCHEMA_VERSION = "codex-review.review-run-summary.v1"
DEEP_PASS_ORDER = [
    "changed-hunks",
    "concurrency-state",
    "validation-contract",
    "workflow-lifecycle",
    "async-helpers",
]

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
    parser.add_argument(
        "--pass-timeout-seconds",
        type=int,
        default=int(os.environ.get("CODEX_REVIEW_PASS_TIMEOUT_SECONDS", "420")),
        help=(
            "Maximum seconds per Codex review pass before the pass is treated as stalled. "
            "Defaults to CODEX_REVIEW_PASS_TIMEOUT_SECONDS or 420."
        ),
    )
    parser.add_argument(
        "--max-deep-passes",
        type=int,
        default=int(os.environ.get("CODEX_REVIEW_MAX_DEEP_PASSES", "3")),
        help=(
            "Maximum number of deep-review passes to run after adaptive pass selection. "
            "Defaults to CODEX_REVIEW_MAX_DEEP_PASSES or 3."
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reuse of a prior completed review run for the same repo head and settings.",
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


def current_head_sha(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout.strip()


def coerce_completed_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def review_cache_key(args: argparse.Namespace, head_sha: str) -> JsonDict:
    return {
        "head_sha": head_sha,
        "base": args.base,
        "mode": args.mode,
        "depth": args.depth,
        "model": args.model,
        "quality_comparison": str(args.quality_comparison or ""),
        "max_deep_passes": args.max_deep_passes,
        "pass_timeout_seconds": args.pass_timeout_seconds,
        "benchmark_enabled": not args.no_benchmark and args.depth != "quick",
    }


def write_cache_key(path: Path, payload: JsonDict) -> None:
    write_file(path, json.dumps(payload, indent=2) + "\n")


def load_cache_key(path: Path) -> JsonDict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def find_reusable_review_run(review_root: Path, cache_key: JsonDict) -> Path | None:
    if not review_root.is_dir():
        return None
    candidates = sorted(
        (child for child in review_root.iterdir() if child.is_dir()),
        key=lambda item: item.name,
        reverse=True,
    )
    for candidate in candidates:
        if not (candidate / "review.md").is_file():
            continue
        existing_key = load_cache_key(candidate / "review-cache-key.json")
        if existing_key == cache_key:
            return candidate
    return None


def finding_priority(item: str) -> tuple[int, int]:
    lowered = item.lower()
    score = 0
    if any(
        token in lowered
        for token in ("security", "auth", "permission", "secret", "token")
    ):
        score += 6
    if any(
        token in lowered
        for token in ("race", "queue", "concurrency", "duplicate", "claim")
    ):
        score += 5
    if any(
        token in lowered
        for token in ("state", "stale", "rollback", "reset", "workflow", "lifecycle")
    ):
        score += 4
    if any(
        token in lowered
        for token in ("contract", "validation", "null", "bounds", "cleanup")
    ):
        score += 3
    return score, -len(item)


def summarize_review_findings(review_text: str) -> JsonDict:
    findings = extract_findings_items(review_text)
    titles = [item.splitlines()[0].strip() for item in findings if item.strip()]
    return {
        "count": len(findings),
        "titles": titles,
        "has_findings": bool(findings),
    }


def build_review_run_summary(
    *,
    run_dir: Path,
    repo: Path,
    head_sha: str,
    args: argparse.Namespace,
    cache_hit: bool,
    cache_source: str | None,
    selected_passes: list[str],
    skipped_passes: list[JsonDict],
    pass_results: list[JsonDict],
    review_file: Path,
    benchmark_enabled: bool,
    benchmark_json: JsonDict | None,
    stop_reason: str | None,
    overall_notes: list[str],
) -> JsonDict:
    review_text = read_text_if_present(review_file)
    findings_summary = summarize_review_findings(review_text)
    benchmark_summary: JsonDict = {
        "enabled": benchmark_enabled,
        "completed": benchmark_json is not None,
    }
    if benchmark_json is not None:
        benchmark_summary["results"] = benchmark_json

    if args.depth == "deep":
        effective_strategy = (
            "multi-pass" if len(selected_passes) > 1 else "single-pass-deep"
        )
    else:
        effective_strategy = "single-pass-quick"

    return {
        "schema_version": REVIEW_RUN_SUMMARY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "repo": str(repo),
        "base": args.base,
        "head_sha": head_sha,
        "mode": args.mode,
        "model": args.model,
        "requested_depth": args.depth,
        "effective_strategy": effective_strategy,
        "quality_comparison_file": str(args.quality_comparison or ""),
        "cache": {
            "hit": cache_hit,
            "source": cache_source or "",
        },
        "pass_strategy": {
            "selected_passes": selected_passes,
            "skipped_passes": skipped_passes,
            "stop_reason": stop_reason or "",
            "completed_passes": [
                result["name"]
                for result in pass_results
                if result.get("status") == "success"
            ],
        },
        "pass_results": pass_results,
        "findings_summary": findings_summary,
        "benchmark": benchmark_summary,
        "notes": overall_notes,
        "artifacts": {
            "review_file": str(review_file),
            "repair_plan_json": str(run_dir / "repair-plan.json"),
            "repair_plan_markdown": str(run_dir / "repair-plan.md"),
            "inline_findings": str(run_dir / "inline-findings.json"),
            "inline_comments": str(run_dir / "codex-inline-comments.txt"),
            "benchmark_json": str(run_dir / "benchmark-summary.json"),
            "benchmark_text": str(run_dir / "benchmark-summary.txt"),
        },
    }


def build_review_run_summary_markdown(summary: JsonDict) -> str:
    cache_value = summary.get("cache")
    cache: JsonDict = cache_value if isinstance(cache_value, dict) else {}
    pass_strategy_value = summary.get("pass_strategy")
    pass_strategy: JsonDict = (
        pass_strategy_value if isinstance(pass_strategy_value, dict) else {}
    )
    findings_value = summary.get("findings_summary")
    findings_summary: JsonDict = (
        findings_value if isinstance(findings_value, dict) else {}
    )
    benchmark_value = summary.get("benchmark")
    benchmark: JsonDict = benchmark_value if isinstance(benchmark_value, dict) else {}
    lines = [
        "# Review Run Summary",
        "",
        f"- Requested depth: {summary.get('requested_depth', 'unknown')}",
        f"- Effective strategy: {summary.get('effective_strategy', 'unknown')}",
        f"- Cache reuse: {'yes' if cache.get('hit') else 'no'}",
        f"- Selected passes: {', '.join(pass_strategy.get('selected_passes') or ['none'])}",
        f"- Findings surfaced: {findings_summary.get('count', 0)}",
        f"- Benchmark completed: {'yes' if benchmark.get('completed') else 'no'}",
    ]
    if summary.get("quality_comparison_file"):
        lines.append(
            f"- Linked quality comparison: {summary.get('quality_comparison_file')}"
        )
    warning = str(summary.get("summary_warning") or "").strip()
    if warning:
        lines.append(f"- Summary warning: {warning}")
    skipped = pass_strategy.get("skipped_passes")
    if isinstance(skipped, list) and skipped:
        lines.extend(["", "## Skipped Passes", ""])
        for item in skipped:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('name', 'unknown')}: {item.get('reason', 'no reason recorded')}"
            )
    results = summary.get("pass_results")
    if isinstance(results, list) and results:
        lines.extend(["", "## Pass Results", ""])
        for item in results:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('name', 'unknown')}: {item.get('status', 'unknown')}"
            )
    notes = summary.get("notes")
    if isinstance(notes, list) and notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes if str(note).strip())
    return "\n".join(lines) + "\n"


def write_review_run_summary(run_dir: Path, summary: JsonDict) -> None:
    write_file(
        run_dir / "review-run-summary.json", json.dumps(summary, indent=2) + "\n"
    )
    write_file(
        run_dir / "review-run-summary.md", build_review_run_summary_markdown(summary)
    )


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


PASS_FOCUS_SUFFIXES: dict[str, str] = {
    "changed-hunks": (
        "\n\nFocus pass:\n"
        "- Report only bugs directly caused by changed files, changed hunks, or the state transitions those hunks now control.\n"
        "- Ignore unrelated pre-existing issues elsewhere unless the diff clearly routes through them.\n"
    ),
    "concurrency-state": (
        "\n\nFocus pass:\n"
        "- Prioritize race conditions, TOCTOU bugs, rollback-on-throw gaps, stale status after reset, and source-of-truth drift.\n"
        "- Re-check shared async helpers for state that is only updated after await, fetch, retry, delay, throttle, or detached-process dispatch.\n"
        "- Re-check optimistic UI or workflow state for paths where thrown exceptions bypass rollback while returned error objects do not.\n"
        "- Prefer findings in the touched functions and their immediate callers/callees.\n"
    ),
    "validation-contract": (
        "\n\nFocus pass:\n"
        "- Prioritize missing input validation, NULL or bounds guards, return-value handling, cleanup failures, and changed contract mismatches.\n"
        "- Re-scan sibling touched functions for the same low-level guard pattern once one missing NULL, parameter, bounds, or return-value check is found.\n"
        "- Prefer mismatches where the write path stores one source of truth but the read path still uses a live default or fallback value.\n"
        "- Prefer findings in the touched functions and their immediate callers/callees.\n"
    ),
    "boundary-fidelity": (
        "\n\nFocus pass:\n"
        "- Prioritize connector/workflow boundary drift: dropped non-2xx failure payloads, malformed JSON escaping as 500s, wrapped payload/test mismatches, connector fallback drift, timeoutless external awaits, explicit-cleared-state fallback overwrites, and wake/claim races.\n"
        "- Trace both sides of each boundary: transport response -> normalized error, connector adapter -> canonical runtime source, workflow claim -> current-run status, and wrapped payload -> test assertion.\n"
        "- Prefer findings where the caller loses failure detail, waits forever, reads a global pending state instead of the current run, or tests assert the wrapper instead of the real payload.\n"
        "- Prefer findings in touched boundary code and immediate call sites that depend on the preserved shape, timeout, or state source.\n"
    ),
    "workflow-lifecycle": (
        "\n\nFocus pass:\n"
        "- Prioritize reset, cleanup, teardown, retry, process-launch, timeout, and refresh behavior.\n"
        "- Check whether the first successful or failing request leaves behind durable state that the next request still interprets correctly.\n"
        "- Check shell or external-process paths for verification-after-dispatch gaps, missing timeouts, or cleanup steps that depend on unrelated metadata.\n"
        "- Prefer findings in the touched functions and their immediate callers/callees.\n"
    ),
    "async-helpers": (
        "\n\nFocus pass:\n"
        "- Prioritize shared async helpers such as throttle, retry, backoff, queue, cache, and client wrappers.\n"
        "- Check whether coordination state is read before await and only written after await, which lets concurrent callers bypass the intended guard.\n"
        "- Check whether helper fallbacks, retries, and Retry-After handling preserve the intended delay semantics when headers or metadata are absent.\n"
        "- Prefer findings in the touched helper and the immediate call site that depends on its coordination behavior.\n"
    ),
}


def select_deep_pass_names(
    scan_report: JsonDict, max_deep_passes: int = DEFAULT_MAX_DEEP_PASSES
) -> list[str]:
    selected = ["changed-hunks"]
    risk_keys: set[str] = set()
    risk_hits = scan_report.get("risk_hits")
    if isinstance(risk_hits, list):
        for hit in risk_hits:
            if not isinstance(hit, dict):
                continue
            key = str(hit.get("key") or "").strip()
            if key:
                risk_keys.add(key)

    layers = scan_report.get("layers")
    layer_names = set(layers.keys()) if isinstance(layers, dict) else set()

    if risk_keys & {
        "state-machine",
        "parity-drift",
        "explicit-null-drift",
        "queue-claim",
    }:
        selected.append("concurrency-state")
    if risk_keys & {
        "request-contract",
        "error-shaping",
        "connector-workflow-boundary",
        "security-boundary",
        "path-reachability",
    } or layer_names & {"route-controller", "contracts-types"}:
        selected.append("validation-contract")
    if risk_keys & {
        "connector-workflow-boundary",
        "registry-drift",
        "parity-drift",
        "explicit-null-drift",
        "queue-claim",
    }:
        selected.append("boundary-fidelity")
    if (
        risk_keys
        & {"state-machine", "queue-claim", "fail-open-fallback", "connector-workflow-boundary"}
        or "workflow-runtime" in layer_names
    ):
        selected.append("workflow-lifecycle")
    if risk_keys & {"queue-claim"}:
        selected.append("async-helpers")

    deduped: list[str] = []
    for pass_name in selected:
        if pass_name not in deduped:
            deduped.append(pass_name)
    return deduped[: max(1, max_deep_passes)]


def build_pass_prompts(
    prompt: str,
    depth: str,
    scan_report: JsonDict,
    max_deep_passes: int = DEFAULT_MAX_DEEP_PASSES,
) -> list[tuple[str, str]]:
    if depth != "deep":
        return [("single", prompt)]

    pass_names = select_deep_pass_names(scan_report, max_deep_passes)
    return [
        (pass_name, prompt + PASS_FOCUS_SUFFIXES[pass_name]) for pass_name in pass_names
    ]


def should_continue_after_pass(
    *,
    pass_name: str,
    review_text: str,
    scan_report: JsonDict,
) -> bool:
    if pass_name != "changed-hunks":
        return False

    findings = extract_findings_items(review_text)
    if not findings:
        return True

    risk_hits = scan_report.get("risk_hits")
    high_risk_keys: set[str] = set()
    high_risk_count = 0
    if isinstance(risk_hits, list):
        for hit in risk_hits:
            if not isinstance(hit, dict):
                continue
            if str(hit.get("severity") or "") != "high":
                continue
            high_risk_count += 1
            key = str(hit.get("key") or "").strip()
            if key:
                high_risk_keys.add(key)

    if len(findings) >= 2:
        return False
    if high_risk_count >= 2:
        return True
    if high_risk_keys & {"security-boundary", "queue-claim", "state-machine"}:
        return True
    return False


def combine_pass_reviews(
    pass_reviews: list[tuple[str, str]],
    *,
    overall_notes: list[str] | None = None,
) -> str:
    deduped_items: list[tuple[int, str]] = []
    seen: set[str] = set()

    for order, (_pass_name, review_text) in enumerate(pass_reviews):
        for item in extract_findings_items(review_text):
            first_line = item.splitlines()[0].strip().lower()
            key = re.sub(r"\s+", " ", first_line)
            if key in seen:
                continue
            seen.add(key)
            deduped_items.append((order, item))

    combined_items = [
        item
        for _order, item in sorted(
            deduped_items,
            key=lambda entry: (
                -finding_priority(entry[1])[0],
                entry[0],
                finding_priority(entry[1])[1],
            ),
        )
    ]
    pass_names = [name for name, _review in pass_reviews]

    if not combined_items:
        lines = [
            "No findings.",
            "",
            "**Open questions**",
            "",
            "- None.",
            "",
            "**Residual risk**",
            "",
            f"- Review covered {', '.join(pass_names)} but did not surface a concrete release-blocking bug.",
        ]
        if overall_notes:
            lines.extend(
                ["- Notes: " + "; ".join(note for note in overall_notes if note)]
            )
        return "\n".join(lines).rstrip() + "\n"

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
            f"- Combined findings from: {', '.join(pass_names)}.",
            "- Findings are ordered so the highest-signal bug reports appear first.",
            "",
        ]
    )
    if overall_notes:
        lines.extend(
            [
                "**Residual risk**",
                "",
                "- " + "; ".join(note for note in overall_notes if note),
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
    timeout_seconds: int,
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

    try:
        completed = subprocess.run(
            codex_cmd,
            cwd=repo,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            args=codex_cmd,
            returncode=124,
            stdout=coerce_completed_text(exc.stdout),
            stderr=coerce_completed_text(exc.stderr)
            + f"\nTimed out after {timeout_seconds} seconds.\n",
        )
        stdout_log = run_dir / f"codex-attempt-{attempt}-stdout.txt"
        stderr_log = run_dir / f"codex-attempt-{attempt}-stderr.txt"
        write_file(stdout_log, completed.stdout)
        write_file(stderr_log, completed.stderr)
        return False, "codex-timeout", completed

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


def should_abort_remaining_passes(
    *,
    successful_passes: int,
    reason: str,
    attempt: int,
    max_attempts: int,
) -> bool:
    if successful_passes <= 0:
        return False
    if reason == "codex-timeout":
        return True
    return attempt >= max_attempts


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    skill_dir = script_path.parent.parent / "skills" / "bug-hunting-code-review"
    repair_script = script_path.parent / "propose_review_repairs.py"
    pre_pr = load_pre_pr_module(skill_dir)

    repo = pre_pr.repo_root(Path(args.repo).resolve())
    head_sha = current_head_sha(repo)
    cache_key = review_cache_key(args, head_sha)
    review_root = repo / args.output_dir
    if not args.no_cache and args.mode != "dirty":
        reusable_run = find_reusable_review_run(review_root, cache_key)
        if reusable_run is not None:
            summary_path = reusable_run / "review-run-summary.json"
            loaded_summary = load_cache_key(summary_path)
            if (
                isinstance(loaded_summary, dict)
                and str(loaded_summary.get("schema_version") or "")
                == REVIEW_RUN_SUMMARY_SCHEMA_VERSION
            ):
                summary = dict(loaded_summary)
                cache_summary = summary.get("cache")
                if not isinstance(cache_summary, dict):
                    cache_summary = {}
                cache_summary["hit"] = True
                cache_summary["source"] = str(reusable_run)
                summary["cache"] = cache_summary
            else:
                summary = {
                    "schema_version": REVIEW_RUN_SUMMARY_SCHEMA_VERSION,
                    "incomplete": True,
                    "summary_warning": (
                        "Reused a cached review artifact without a compatible structured run summary. "
                        "Pass, benchmark, and strategy details were not trusted from legacy metadata."
                    ),
                    "cache": {
                        "hit": False,
                        "source": "",
                    },
                    "artifacts": {
                        "review_file": str(reusable_run / "review.md"),
                    },
                }
            summary["generated_at"] = datetime.now(timezone.utc).isoformat()
            summary["run_dir"] = str(reusable_run)
            summary["repo"] = str(repo)
            summary["base"] = args.base
            summary["head_sha"] = head_sha
            summary["mode"] = args.mode
            summary["model"] = args.model
            summary["requested_depth"] = args.depth
            write_review_run_summary(reusable_run, summary)
            print(f"Reused review artifacts: {reusable_run}")
            print(f"Review: {reusable_run / 'review.md'}")
            print(f"Run summary: {reusable_run / 'review-run-summary.json'}")
            return 0
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
    write_cache_key(run_dir / "review-cache-key.json", cache_key)
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
    scan_report = pre_pr.run_surface_scan(skill_dir, repo, args.base, args.mode)

    max_attempts = 2
    pass_reviews: list[tuple[str, str]] = []
    pass_stdout_texts: list[str] = []
    pass_stderr_texts: list[str] = []
    overall_notes: list[str] = []
    pass_results: list[JsonDict] = []
    pass_prompts = build_pass_prompts(
        prepared["prompt"],
        args.depth,
        scan_report,
        args.max_deep_passes,
    )
    selected_passes = [name for name, _prompt in pass_prompts]
    skipped_passes: list[JsonDict] = []
    if args.depth == "deep":
        for pass_name in DEEP_PASS_ORDER:
            if pass_name not in selected_passes:
                skipped_passes.append(
                    {
                        "name": pass_name,
                        "reason": "adaptive pass selection did not prioritize this risk lane",
                    }
                )
    stop_remaining_passes = False
    stop_reason: str | None = None

    for pass_index, (pass_name, pass_prompt) in enumerate(pass_prompts, start=1):
        final_completed = None
        repair_notes: list[str] = []
        reason_before_retry: str | None = None
        success = False
        pass_review_file = run_dir / f"{pass_name}-review.md"
        pass_status = "pending"
        final_reason = ""

        for attempt in range(1, max_attempts + 1):
            attempt_success, reason, completed = run_codex_attempt(
                codex_base_cmd=codex_base_cmd,
                model=args.model,
                repo=repo,
                prompt=pass_prompt,
                review_file=pass_review_file,
                run_dir=run_dir,
                attempt=pass_index * 10 + attempt,
                timeout_seconds=args.pass_timeout_seconds,
            )
            final_completed = completed
            final_reason = reason

            if attempt_success:
                if attempt > 1:
                    repair_notes.append(
                        f"{pass_name}: recovered after one automatic read-only retry. "
                        f"First attempt failed with: {reason_before_retry or 'unknown mechanical failure'}."
                    )
                success = True
                pass_status = "success"
                break

            if should_abort_remaining_passes(
                successful_passes=len(pass_reviews),
                reason=reason,
                attempt=attempt,
                max_attempts=max_attempts,
            ):
                overall_notes.append(
                    f"{pass_name}: stopping after {reason} once earlier passes already produced a usable review."
                )
                stop_remaining_passes = True
                stop_reason = reason
                pass_status = "aborted-after-earlier-success"
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
            pass_status = "retried"

        assert final_completed is not None
        write_file(run_dir / f"{pass_name}-codex-stdout.txt", final_completed.stdout)
        write_file(run_dir / f"{pass_name}-codex-stderr.txt", final_completed.stderr)
        pass_stdout_texts.append(final_completed.stdout)
        pass_stderr_texts.append(final_completed.stderr)
        if repair_notes:
            overall_notes.extend(repair_notes)
        if success:
            pass_review_text = read_text_if_present(pass_review_file)
            pass_reviews.append((pass_name, pass_review_text))
            if not should_continue_after_pass(
                pass_name=pass_name,
                review_text=pass_review_text,
                scan_report=scan_report,
            ):
                stop_remaining_passes = True
                stop_reason = "first-pass-strong-enough"
                if len(pass_prompts) > 1 and pass_name == "changed-hunks":
                    overall_notes.append(
                        "changed-hunks: first pass was strong enough, so deeper follow-up passes were skipped to save review budget."
                    )
        pass_results.append(
            {
                "name": pass_name,
                "status": pass_status,
                "attempts": attempt,
                "final_reason": final_reason,
                "review_file": str(pass_review_file),
            }
        )
        if stop_remaining_passes:
            for remaining_name, _remaining_prompt in pass_prompts[pass_index:]:
                skipped_passes.append(
                    {
                        "name": remaining_name,
                        "reason": (
                            "earlier pass was strong enough to stop deeper follow-up passes"
                            if stop_reason == "first-pass-strong-enough"
                            else "later pass stalled after earlier useful output was already preserved"
                        ),
                    }
                )
            break

    if not pass_reviews:
        raise RuntimeError(
            "Codex review generation did not produce any usable pass output."
        )

    combined_review = combine_pass_reviews(pass_reviews, overall_notes=overall_notes)
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
    if stop_remaining_passes:
        print(
            "Review hardening: stopped after a later pass stalled or failed, preserving earlier successful passes."
        )

    repair_output = run_repair_plan(repair_script, review_file, run_dir, repo)
    print(repair_output.strip())

    should_skip_benchmark = args.no_benchmark or args.depth == "quick"
    benchmark_json: JsonDict | None = None
    if should_skip_benchmark:
        summary = build_review_run_summary(
            run_dir=run_dir,
            repo=repo,
            head_sha=head_sha,
            args=args,
            cache_hit=False,
            cache_source=None,
            selected_passes=selected_passes,
            skipped_passes=skipped_passes,
            pass_results=pass_results,
            review_file=review_file,
            benchmark_enabled=False,
            benchmark_json=None,
            stop_reason=stop_reason,
            overall_notes=overall_notes,
        )
        write_review_run_summary(run_dir, summary)
        print(f"Run summary: {run_dir / 'review-run-summary.json'}")
        return 0

    benchmark_output = pre_pr.run_benchmarks(skill_dir, review_file, repo)
    benchmark_json = run_json_benchmarks(skill_dir, review_file, repo)
    write_file(run_dir / "benchmark-summary.txt", benchmark_output)
    write_file(
        run_dir / "benchmark-summary.json", json.dumps(benchmark_json, indent=2) + "\n"
    )

    print()
    print(benchmark_output.strip())
    summary = build_review_run_summary(
        run_dir=run_dir,
        repo=repo,
        head_sha=head_sha,
        args=args,
        cache_hit=False,
        cache_source=None,
        selected_passes=selected_passes,
        skipped_passes=skipped_passes,
        pass_results=pass_results,
        review_file=review_file,
        benchmark_enabled=True,
        benchmark_json=benchmark_json,
        stop_reason=stop_reason,
        overall_notes=overall_notes,
    )
    write_review_run_summary(run_dir, summary)
    print(f"Run summary: {run_dir / 'review-run-summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
