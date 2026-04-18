import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


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

    completed = subprocess.run(
        codex_cmd,
        cwd=repo,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    write_file(stdout_log, completed.stdout)
    write_file(stderr_log, completed.stderr)

    print(f"Artifacts: {run_dir}")
    print(f"Review: {review_file}")
    print(f"Codex command: {' '.join(codex_base_cmd)}")

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
