import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the plugin-owned automation cycle: local review, optional GitHub learning intake, "
            "bounded repair handoff, and optional Hugging Face hardening."
        )
    )
    parser.add_argument("--repo", default=".", help="Repository path. Defaults to current directory.")
    parser.add_argument("--base", default="origin/main", help="Base branch for the local review diff.")
    parser.add_argument("--output-dir", help="Optional automation run directory.")
    parser.add_argument("--model", help="Optional Codex model override passed through where supported.")

    parser.add_argument("--skip-review", action="store_true", help="Skip the local review run.")
    parser.add_argument(
        "--skip-repair-handoff",
        action="store_true",
        help="Skip the bounded repair-plan handoff step.",
    )
    parser.add_argument(
        "--repair-finding-index",
        type=int,
        default=1,
        help="1-based repair finding index for the bounded fix handoff. Defaults to 1.",
    )

    parser.add_argument("--github-repo", help="GitHub repo in owner/name form for intake.")
    parser.add_argument("--github-pr", type=int, help="PR number for intake.")
    parser.add_argument("--github-raw-input", help="Captured GitHub raw artifact for the intake pipeline.")
    parser.add_argument(
        "--github-raw-format",
        default="auto",
        choices=[
            "auto",
            "custom_review_bundle",
            "github_rest_review_comments",
            "github_graphql_review_threads",
            "github_mcp_pr_comments",
            "github_mcp_review_threads",
        ],
        help="Format for --github-raw-input. Defaults to auto.",
    )
    parser.add_argument(
        "--skip-github-intake",
        action="store_true",
        help="Skip the GitHub intake/self-learning path.",
    )

    parser.add_argument(
        "--skip-hardening",
        action="store_true",
        help="Skip the Hugging Face hardening batch.",
    )
    parser.add_argument(
        "--hardening-offset",
        type=int,
        default=0,
        help="Hugging Face hardening offset. Defaults to 0.",
    )
    parser.add_argument(
        "--hardening-length",
        type=int,
        default=3,
        help="Number of Hugging Face rows to fetch. Defaults to 3.",
    )
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def newest_child_dir(path: Path) -> Path:
    children = sorted((child for child in path.iterdir() if child.is_dir()), key=lambda item: item.name, reverse=True)
    if not children:
        raise FileNotFoundError(f"No child directories found under {path}")
    return children[0]


def repo_root(cwd: Path) -> Path:
    completed = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(completed.stdout.strip())


def default_run_dir(repo: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo / "artifacts" / "automation-runs" / timestamp


def run_review(repo: Path, run_dir: Path, base: str, model: str | None) -> dict:
    review_root = run_dir / "review"
    cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "run_codex_review.py"),
        "--repo",
        str(repo),
        "--base",
        base,
        "--output-dir",
        str(review_root),
    ]
    if model:
        cmd.extend(["--model", model])
    completed = run_cmd(cmd, repo)
    review_run_dir = newest_child_dir(review_root)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "review_run_dir": str(review_run_dir),
        "review_file": str(review_run_dir / "review.md"),
        "repair_plan": str(review_run_dir / "repair-plan.json"),
    }


def run_repair_handoff(repo: Path, run_dir: Path, repair_plan: Path, finding_index: int, model: str | None) -> dict:
    output_dir = run_dir / "repair-handoff"
    cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "run_review_fix.py"),
        "--repo",
        str(repo),
        "--repair-plan",
        str(repair_plan),
        "--finding-index",
        str(finding_index),
        "--output-dir",
        str(output_dir),
    ]
    if model:
        cmd.extend(["--model", model])
    completed = run_cmd(cmd, repo)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(output_dir),
        "fix_prompt": str(output_dir / "fix-prompt.txt"),
        "selected_repair": str(output_dir / "selected-repair.json"),
    }


def run_github_intake(
    repo: Path,
    run_dir: Path,
    github_repo: str,
    github_pr: int,
    raw_input: Path,
    raw_format: str,
    review_run_dir: Path,
    model: str | None,
) -> dict:
    output_dir = run_dir / "github-intake"
    cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "run_github_intake_pipeline.py"),
        "--repo",
        github_repo,
        "--pr",
        str(github_pr),
        "--raw-input",
        str(raw_input),
        "--raw-format",
        raw_format,
        "--score-review-artifacts",
        str(review_run_dir),
        "--gate-candidates",
        "--apply-target",
        "probationary",
        "--apply-mode",
        "auto",
        "--output-dir",
        str(output_dir),
    ]
    if model:
        cmd.extend(["--model", model])
    completed = run_cmd(cmd, repo)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(output_dir),
    }


def run_hf_hardening(repo: Path, run_dir: Path, offset: int, length: int, model: str | None) -> dict:
    output_dir = run_dir / "hf-hardening"
    cmd = [
        sys.executable,
        str(
            repo
            / "plugins"
            / "codex-review"
            / "skills"
            / "bug-hunting-code-review"
            / "scripts"
            / "run_hf_hardening_cycle.py"
        ),
        "--repo",
        str(repo),
        "--offset",
        str(offset),
        "--length",
        str(length),
        "--output-dir",
        str(output_dir),
    ]
    if model:
        cmd.extend(["--model", model])
    completed = run_cmd(cmd, repo)
    hardening_run_dir = newest_child_dir(output_dir)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(hardening_run_dir),
        "summary_file": str(hardening_run_dir / "summary.json"),
    }


def main() -> int:
    args = parse_args()
    repo = repo_root(Path(args.repo).resolve())
    run_dir = Path(args.output_dir).resolve() if args.output_dir else default_run_dir(repo)
    run_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "schema_version": "codex-review.automation-cycle.v1",
        "repo": str(repo),
        "run_dir": str(run_dir),
        "steps": {},
    }

    review_run_dir: Path | None = None
    repair_plan: Path | None = None

    if not args.skip_review:
        review_result = run_review(repo, run_dir, args.base, args.model)
        summary["steps"]["review"] = review_result
        review_run_dir = Path(review_result["review_run_dir"])
        repair_plan = Path(review_result["repair_plan"])

    if not args.skip_repair_handoff and repair_plan is not None:
        repair_plan_payload = read_json(repair_plan)
        if not repair_plan_payload.get("findings"):
            summary["steps"]["repair_handoff"] = {
                "skipped": True,
                "reason": "Repair plan did not contain any parsed findings.",
                "repair_plan": str(repair_plan),
            }
        else:
            summary["steps"]["repair_handoff"] = run_repair_handoff(
                repo,
                run_dir,
                repair_plan,
                args.repair_finding_index,
                args.model,
            )

    if not args.skip_github_intake:
        if not (args.github_repo and args.github_pr and args.github_raw_input and review_run_dir):
            summary["steps"]["github_intake"] = {
                "skipped": True,
                "reason": "GitHub intake needs --github-repo, --github-pr, --github-raw-input, and a completed review run.",
            }
        else:
            summary["steps"]["github_intake"] = run_github_intake(
                repo,
                run_dir,
                args.github_repo,
                args.github_pr,
                Path(args.github_raw_input).resolve(),
                args.github_raw_format,
                review_run_dir,
                args.model,
            )

    if not args.skip_hardening:
        summary["steps"]["hf_hardening"] = run_hf_hardening(
            repo,
            run_dir,
            args.hardening_offset,
            args.hardening_length,
            args.model,
        )

    write_json(run_dir / "automation-summary.json", summary)
    print(f"Automation run: {run_dir}")
    print(f"Summary: {run_dir / 'automation-summary.json'}")
    print(f"Completed steps: {', '.join(summary['steps'].keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
