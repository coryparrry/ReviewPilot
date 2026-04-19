import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a bug-hunting review run, invoke Codex non-interactively, and benchmark the resulting review."
        )
    )
    parser.add_argument("--repo", default=".", help="Repository path. Defaults to the current directory.")
    parser.add_argument("--base", default="origin/main", help="Base branch for the review diff. Defaults to origin/main.")
    parser.add_argument(
        "--output-dir",
        default=".codex-review",
        help="Directory under the repo root for saved review artifacts.",
    )
    parser.add_argument("--model", help="Optional Codex model override.")
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


def load_pre_pr_module(skill_dir: Path):
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
    raise FileNotFoundError("Could not find a working Codex transport. Neither codex nor npx.cmd was usable.")


def run_json_benchmarks(skill_dir: Path, review_file: Path, repo: Path) -> dict:
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
    return json.loads(completed.stdout)


def review_file_has_content(review_file: Path) -> bool:
    return review_file.is_file() and bool(read_text_if_present(review_file).strip())


def run_codex_attempt(
    codex_cmd: list[str],
    repo: Path,
    prompt: str,
    review_file: Path,
    run_dir: Path,
    attempt: int,
) -> Tuple[bool, str, subprocess.CompletedProcess[str]]:
    if review_file.exists():
        review_file.unlink()

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
    pre_pr = load_pre_pr_module(skill_dir)

    repo = pre_pr.repo_root(Path(args.repo).resolve())
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = repo / args.output_dir / timestamp

    default_prompt = pre_pr.load_default_prompt(skill_dir)
    diff, metadata = pre_pr.get_diff(repo, args.base, None)
    scan = pre_pr.run_surface_scan(skill_dir, repo, args.base)
    prompt = pre_pr.build_prompt(default_prompt, metadata, scan, diff)

    write_file(run_dir / "diff.patch", diff)
    write_file(run_dir / "review-metadata.json", metadata)
    write_file(run_dir / "surface-scan.txt", scan)
    write_file(run_dir / "review-prompt.txt", prompt)

    if args.prepare_only:
        print(f"Prepared review artifacts in {run_dir}")
        return 0

    codex_base_cmd = resolve_codex_base_command()
    review_file = run_dir / "review.md"
    stdout_log = run_dir / "codex-stdout.txt"
    stderr_log = run_dir / "codex-stderr.txt"
    repair_summary = run_dir / "repair-summary.txt"

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
    if args.model:
        codex_cmd.extend(["--model", args.model])
    codex_cmd.append("-")

    max_attempts = 2
    final_completed = None
    repair_notes: list[str] = []
    success = False

    for attempt in range(1, max_attempts + 1):
        attempt_success, reason, completed = run_codex_attempt(
            codex_cmd=codex_cmd,
            repo=repo,
            prompt=prompt,
            review_file=review_file,
            run_dir=run_dir,
            attempt=attempt,
        )
        final_completed = completed

        if attempt_success:
            if attempt > 1:
                repair_notes.append(
                    f"Recovered after one automatic read-only retry. First attempt failed with: {reason_before_retry}."
                )
            success = True
            break

        if attempt == max_attempts:
            raise RuntimeError(
                "Codex review generation failed after one automatic read-only retry. "
                f"Final failure: {reason}."
            )

        reason_before_retry = reason
        repair_notes.append(
            "First Codex review attempt failed mechanically "
            f"({reason}). Retrying once in the same read-only sandbox."
        )

    assert final_completed is not None
    write_file(stdout_log, final_completed.stdout)
    write_file(stderr_log, final_completed.stderr)
    if repair_notes:
        write_file(repair_summary, "\n".join(repair_notes) + "\n")

    print(f"Artifacts: {run_dir}")
    print(f"Review: {review_file}")
    print(f"Codex command: {' '.join(codex_base_cmd)}")
    if success and repair_notes:
        print("Self-repair: recovered after one automatic read-only retry.")

    if args.no_benchmark:
        return 0

    benchmark_output = pre_pr.run_benchmarks(skill_dir, review_file, repo)
    benchmark_json = run_json_benchmarks(skill_dir, review_file, repo)
    write_file(run_dir / "benchmark-summary.txt", benchmark_output)
    write_file(run_dir / "benchmark-summary.json", json.dumps(benchmark_json, indent=2) + "\n")

    print()
    print(benchmark_output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
