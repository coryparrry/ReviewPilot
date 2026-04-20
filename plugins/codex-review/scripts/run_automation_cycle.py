import argparse
import json
import subprocess
import sys
import traceback
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
    parser.add_argument(
        "--model",
        default="gpt-5.4-mini",
        help="Codex model override passed through where supported. Defaults to gpt-5.4-mini.",
    )
    parser.add_argument(
        "--lessons-source",
        help=(
            "Optional path to a lessons markdown file. When set, the automation cycle refreshes "
            "the repo-local lessons snapshot before the review runs."
        ),
    )
    parser.add_argument(
        "--lessons-limit",
        type=int,
        default=40,
        help="Maximum number of most-recent lessons to stage when --lessons-source is used.",
    )

    parser.add_argument("--skip-review", action="store_true", help="Skip the local review run.")
    parser.add_argument(
        "--review-quality-comparison",
        help="Optional quality-comparison JSON artifact to feed into the local review prompt.",
    )
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
        "--github-apply-mode",
        default="auto",
        choices=["auto", "review", "force"],
        help="Apply mode passed into the GitHub intake pipeline. Defaults to auto.",
    )
    parser.add_argument(
        "--github-apply-target",
        default="probationary",
        choices=["probationary", "primary"],
        help="Corpus lane for GitHub intake apply. Defaults to probationary.",
    )
    parser.add_argument(
        "--github-promote-probationary-id",
        action="append",
        default=[],
        help=(
            "Optional probationary case id to promote during the same automation run. "
            "Repeat the flag to promote more than one case."
        ),
    )
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
        "--skip-github-quality-comparison",
        action="store_true",
        help="Skip the post-intake review-vs-GitHub quality comparison step.",
    )
    parser.add_argument(
        "--skip-github-auto-learn",
        action="store_true",
        help="Skip automatic probationary learning from quality-comparison corpus-gap misses.",
    )
    parser.add_argument(
        "--github-quality-apply-mode",
        default="auto",
        choices=["auto", "review", "force"],
        help="Apply mode for comparison-approved probationary candidates. Defaults to auto.",
    )

    parser.add_argument(
        "--skip-hardening",
        action="store_true",
        help="Skip the Hugging Face hardening batch.",
    )
    parser.add_argument(
        "--skip-coderabbit-calibration",
        action="store_true",
        help="Skip the supervised CodeRabbit calibration summary step.",
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


def find_latest_quality_comparison(repo: Path) -> Path | None:
    quality_root = repo / "artifacts" / "review-quality"
    if not quality_root.is_dir():
        return None

    latest_file: Path | None = None
    latest_mtime = -1.0
    for candidate in quality_root.glob("*/quality-comparison.json"):
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_file = candidate
            latest_mtime = mtime
    return latest_file


def resolve_review_quality_comparison(repo: Path, configured_path: str | None) -> dict:
    if configured_path:
        resolved = Path(configured_path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Configured quality comparison file not found: {resolved}")
        return {"path": str(resolved), "source": "argument"}

    latest = find_latest_quality_comparison(repo)
    if latest is None:
        return {"path": None, "source": "none"}
    return {"path": str(latest.resolve()), "source": "latest_artifact"}


def run_review(repo: Path, run_dir: Path, base: str, model: str | None, quality_comparison: str | None) -> dict:
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
    if quality_comparison:
        cmd.extend(["--quality-comparison", quality_comparison])
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
    apply_mode: str,
    apply_target: str,
    promote_probationary_ids: list[str],
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
        apply_target,
        "--apply-mode",
        apply_mode,
        "--output-dir",
        str(output_dir),
    ]
    if promote_probationary_ids:
        cmd.extend(["--stop-after", "promote-primary"])
        cmd.append("--promote-probationary-ids")
        cmd.extend(promote_probationary_ids)
    completed = run_cmd(cmd, repo)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(output_dir),
    }


def artifact_prefix_for_raw_format(raw_format: str) -> str:
    if raw_format in {"github_graphql_review_threads", "github_mcp_review_threads"}:
        return "graphql"
    if raw_format in {"github_rest_review_comments", "github_mcp_pr_comments"}:
        return "rest"
    return "input"


def run_github_quality_comparison(
    repo: Path,
    run_dir: Path,
    review_file: Path,
    intake_output_dir: Path,
    raw_format: str,
) -> dict:
    output_dir = run_dir / "github-quality-comparison"
    prefix = artifact_prefix_for_raw_format(raw_format)
    proposal_file = intake_output_dir / f"{prefix}-proposal.json"
    candidates_file = intake_output_dir / f"{prefix}-candidates.json"
    cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "compare_review_quality.py"),
        "--review-file",
        str(review_file),
        "--proposal",
        str(proposal_file),
        "--candidates",
        str(candidates_file),
        "--output-dir",
        str(output_dir),
    ]
    completed = run_cmd(cmd, repo)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(output_dir),
        "comparison_file": str(output_dir / "quality-comparison.json"),
        "comparison_markdown": str(output_dir / "quality-comparison.md"),
    }


def run_github_auto_learn(
    repo: Path,
    run_dir: Path,
    intake_output_dir: Path,
    comparison_file: Path,
    raw_format: str,
    apply_mode: str,
) -> dict:
    output_dir = run_dir / "github-quality-learning"
    prefix = artifact_prefix_for_raw_format(raw_format)
    candidates_file = intake_output_dir / f"{prefix}-candidates.json"
    approved_candidates_file = output_dir / "quality-learning-candidates.json"
    apply_result_file = output_dir / "quality-learning-apply-result.json"
    probationary_corpus = (
        repo
        / "plugins"
        / "codex-review"
        / "skills"
        / "bug-hunting-code-review"
        / "references"
        / "probationary-review-cases.json"
    )

    approval_cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "approve_quality_learning_candidates.py"),
        "--candidates",
        str(candidates_file),
        "--comparison",
        str(comparison_file),
        "--output",
        str(approved_candidates_file),
    ]
    approval = run_cmd(approval_cmd, repo)
    approved_payload = read_json(approved_candidates_file)
    approved_ids = approved_payload.get("approved_ids") or []
    if not approved_ids:
        return {
            "stdout": approval.stdout,
            "stderr": approval.stderr,
            "skipped": True,
            "reason": "Quality comparison did not approve any corpus-gap misses for probationary learning.",
            "approved_candidates_file": str(approved_candidates_file),
        }

    apply_cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "apply_corpus_updates.py"),
        "--input",
        str(approved_candidates_file),
        "--mode",
        apply_mode,
        "--corpus",
        str(probationary_corpus),
        "--result-output",
        str(apply_result_file),
    ]
    apply_completed = run_cmd(apply_cmd, repo)
    return {
        "stdout": approval.stdout + apply_completed.stdout,
        "stderr": approval.stderr + apply_completed.stderr,
        "approved_candidates_file": str(approved_candidates_file),
        "apply_result_file": str(apply_result_file),
        "approved_ids": approved_ids,
    }


def refresh_lessons_snapshot(repo: Path, run_dir: Path, source: Path, limit: int) -> dict:
    output_path = run_dir / "lessons" / "knowledge-hub-codex-lessons.md"
    cmd = [
        sys.executable,
        str(
            repo
            / "plugins"
            / "codex-review"
            / "skills"
            / "bug-hunting-code-review"
            / "scripts"
            / "refresh_lessons_reference.py"
        ),
        "--source",
        str(source),
        "--output",
        str(output_path),
        "--limit",
        str(limit),
    ]
    completed = run_cmd(cmd, repo)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "source": str(source),
        "output_file": str(output_path),
        "limit": limit,
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


def run_coderabbit_calibration(repo: Path, run_dir: Path) -> dict:
    output_dir = run_dir / "coderabbit-calibration"
    summary_file = output_dir / "summary.json"
    cmd = [
        sys.executable,
        str(repo / "plugins" / "codex-review" / "scripts" / "score_coderabbit_calibration.py"),
        "--output",
        str(summary_file),
        "--allow-outside-artifacts",
    ]
    completed = run_cmd(cmd, repo)
    summary = read_json(summary_file)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": str(output_dir),
        "summary_file": str(summary_file),
        "total_comments": summary.get("total_comments", 0),
        "verdict_counts": summary.get("verdict_counts", {}),
    }


def main() -> int:
    args = parse_args()
    repo = repo_root(Path(args.repo).resolve())
    run_dir = Path(args.output_dir).resolve() if args.output_dir else default_run_dir(repo)
    run_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "schema_version": "codex-review.automation-cycle.v2",
        "repo": str(repo),
        "run_dir": str(run_dir),
        "steps": {},
    }

    review_run_dir: Path | None = None
    repair_plan: Path | None = None
    exit_code = 0
    current_step = "automation_cycle"

    def record_failure(step_name: str, exc: Exception) -> None:
        failure: dict[str, object] = {
            "failed": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if isinstance(exc, subprocess.CalledProcessError):
            failure["returncode"] = exc.returncode
            failure["cmd"] = exc.cmd
            failure["stdout"] = exc.stdout
            failure["stderr"] = exc.stderr
        summary["steps"][step_name] = failure
        summary["failure"] = {
            "step": step_name,
            **failure,
            "traceback": traceback.format_exc(),
        }

    try:
        if args.lessons_source:
            current_step = "lessons_refresh"
            summary["steps"]["lessons_refresh"] = refresh_lessons_snapshot(
                repo,
                run_dir,
                Path(args.lessons_source).resolve(),
                args.lessons_limit,
            )

        if not args.skip_review:
            current_step = "review"
            review_quality = resolve_review_quality_comparison(repo, args.review_quality_comparison)
            review_result = run_review(repo, run_dir, args.base, args.model, review_quality["path"])
            review_result["quality_comparison"] = review_quality
            summary["steps"]["review"] = review_result
            review_run_dir = Path(review_result["review_run_dir"])
            repair_plan = Path(review_result["repair_plan"])

        if not args.skip_repair_handoff and repair_plan is not None:
            current_step = "repair_handoff"
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

        intake_output_dir: Path | None = None
        if not args.skip_github_intake:
            current_step = "github_intake"
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
                    args.github_apply_mode,
                    args.github_apply_target,
                    args.github_promote_probationary_id,
                )
                intake_output_dir = Path(summary["steps"]["github_intake"]["output_dir"])

        if not args.skip_github_quality_comparison:
            current_step = "github_quality_comparison"
            if not (review_run_dir and intake_output_dir):
                summary["steps"]["github_quality_comparison"] = {
                    "skipped": True,
                    "reason": "GitHub quality comparison needs a completed review run and GitHub intake output.",
                }
            else:
                summary["steps"]["github_quality_comparison"] = run_github_quality_comparison(
                    repo,
                    run_dir,
                    review_run_dir / "review.md",
                    intake_output_dir,
                    args.github_raw_format,
                )

        if not args.skip_github_auto_learn:
            current_step = "github_auto_learn"
            comparison_step = summary["steps"].get("github_quality_comparison")
            comparison_file = (
                Path(comparison_step["comparison_file"])
                if isinstance(comparison_step, dict) and comparison_step.get("comparison_file")
                else None
            )
            if not (intake_output_dir and comparison_file):
                summary["steps"]["github_auto_learn"] = {
                    "skipped": True,
                    "reason": "GitHub auto-learn needs both quality comparison output and GitHub intake output.",
                }
            else:
                summary["steps"]["github_auto_learn"] = run_github_auto_learn(
                    repo,
                    run_dir,
                    intake_output_dir,
                    comparison_file,
                    args.github_raw_format,
                    args.github_quality_apply_mode,
                )

        if not args.skip_coderabbit_calibration:
            current_step = "coderabbit_calibration"
            summary["steps"]["coderabbit_calibration"] = run_coderabbit_calibration(repo, run_dir)

        if not args.skip_hardening:
            current_step = "hf_hardening"
            summary["steps"]["hf_hardening"] = run_hf_hardening(
                repo,
                run_dir,
                args.hardening_offset,
                args.hardening_length,
                args.model,
            )
    except Exception as exc:
        exit_code = exc.returncode if isinstance(exc, subprocess.CalledProcessError) and exc.returncode else 1
        record_failure(current_step, exc)
    finally:
        write_json(run_dir / "automation-summary.json", summary)

    print(f"Automation run: {run_dir}")
    print(f"Summary: {run_dir / 'automation-summary.json'}")
    print(f"Completed steps: {', '.join(summary['steps'].keys())}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
