import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch review feedback from a public GitHub PR, normalize it through the existing intake pipeline, "
            "and optionally compare it against a local review artifact. This defaults to comparison-only and "
            "does not write to the corpus lanes."
        )
    )
    parser.add_argument(
        "--repo", required=True, help="Public GitHub repo in owner/name form."
    )
    parser.add_argument(
        "--pr", required=True, type=int, help="Public pull request number."
    )
    parser.add_argument(
        "--source",
        default="rest",
        choices=["rest", "graphql"],
        help="Which legacy gh fetch surface to normalize. Defaults to rest.",
    )
    parser.add_argument(
        "--review-file",
        help="Optional local review artifact to compare against the public PR feedback.",
    )
    parser.add_argument(
        "--review-artifacts",
        help=(
            "Optional prepared review-artifact directory. Accepts either a run directory containing review.md "
            "or a parent .codex-review directory, in which case the newest child run with review.md is used."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to artifacts/public-pr-quality/<repo>-pr-<number>-<timestamp>.",
    )
    parser.add_argument(
        "--auto-learn-probationary",
        action="store_true",
        help="Run the gated probationary auto-learning path on public comparison misses after quality comparison.",
    )
    parser.add_argument(
        "--quality-apply-mode",
        default="auto",
        choices=["auto", "review", "force"],
        help="Apply mode for gated probationary auto-learning. Defaults to auto.",
    )
    return parser.parse_args()


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


def completed_to_dict(completed: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def repo_root(cwd: Path) -> Path:
    completed = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(completed.stdout.strip())


def default_output_dir(repo: Path, github_repo: str, pr_number: int) -> Path:
    safe_repo = github_repo.replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        repo
        / "artifacts"
        / "public-pr-quality"
        / f"{safe_repo}-pr-{pr_number}-{timestamp}"
    )


def default_intake_dir(repo: Path, github_repo: str, pr_number: int) -> Path:
    safe_repo = github_repo.replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        repo
        / "artifacts"
        / "github-intake"
        / "pipeline"
        / f"public-{safe_repo}-pr-{pr_number}-{timestamp}"
    )


def write_json(path: Path, payload: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def resolve_review_file(candidate: str | None, artifacts: str | None) -> Path | None:
    if candidate and artifacts:
        raise ValueError("Use either --review-file or --review-artifacts, not both.")
    if candidate:
        review_file = Path(candidate).resolve()
        if not review_file.is_file():
            raise FileNotFoundError(f"Review file not found: {review_file}")
        return review_file
    if not artifacts:
        return None

    artifact_root = Path(artifacts).resolve()
    if artifact_root.is_file():
        return artifact_root
    if not artifact_root.is_dir():
        raise FileNotFoundError(f"Review artifact path not found: {artifact_root}")

    direct_review = artifact_root / "review.md"
    if direct_review.is_file():
        return direct_review

    child_runs = sorted(
        (
            child
            for child in artifact_root.iterdir()
            if child.is_dir() and (child / "review.md").is_file()
        ),
        key=lambda child: child.name,
        reverse=True,
    )
    if child_runs:
        return child_runs[0] / "review.md"

    raise FileNotFoundError(f"Could not find review.md under {artifact_root}")


def artifact_prefix_for_source(source: str) -> str:
    return "rest" if source == "rest" else "graphql"


def read_json(path: Path) -> JsonDict:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def main() -> int:
    args = parse_args()
    repo = repo_root(Path.cwd())
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else default_output_dir(repo, args.repo, args.pr)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    review_file = resolve_review_file(args.review_file, args.review_artifacts)
    if args.auto_learn_probationary and review_file is None:
        raise ValueError(
            "--auto-learn-probationary requires --review-file or --review-artifacts."
        )
    intake_dir = default_intake_dir(repo, args.repo, args.pr)
    comparison_dir = output_dir / "quality-comparison"

    pipeline_cmd = [
        sys.executable,
        str(
            repo
            / "plugins"
            / "codex-review"
            / "scripts"
            / "run_github_intake_pipeline.py"
        ),
        "--repo",
        args.repo,
        "--pr",
        str(args.pr),
        "--use-gh-legacy-fetch",
        "--source",
        args.source,
        "--output-dir",
        str(intake_dir),
        "--stop-after",
        "propose",
    ]
    pipeline = run_cmd(pipeline_cmd, repo)

    steps: JsonDict = {
        "github_intake": {
            "stdout": pipeline.stdout,
            "stderr": pipeline.stderr,
        }
    }
    summary: JsonDict = {
        "schema_version": "codex-review.public-pr-quality-cycle.v1",
        "repo": args.repo,
        "pr": args.pr,
        "output_dir": str(output_dir),
        "intake_dir": str(intake_dir),
        "review_file": str(review_file) if review_file else None,
        "steps": steps,
    }

    if review_file is not None:
        prefix = artifact_prefix_for_source(args.source)
        compare_cmd = [
            sys.executable,
            str(
                repo
                / "plugins"
                / "codex-review"
                / "scripts"
                / "compare_review_quality.py"
            ),
            "--review-file",
            str(review_file),
            "--proposal",
            str(intake_dir / f"{prefix}-proposal.json"),
            "--candidates",
            str(intake_dir / f"{prefix}-candidates.json"),
            "--output-dir",
            str(comparison_dir),
            "--bugs-only",
        ]
        comparison = run_cmd(compare_cmd, repo)
        steps["quality_comparison"] = {
            "stdout": comparison.stdout,
            "stderr": comparison.stderr,
            "comparison_file": str(comparison_dir / "quality-comparison.json"),
            "comparison_markdown": str(comparison_dir / "quality-comparison.md"),
        }

        if args.auto_learn_probationary:
            learning_dir = output_dir / "quality-learning"
            approved_candidates_file = learning_dir / "quality-learning-candidates.json"
            apply_result_file = learning_dir / "quality-learning-apply-result.json"
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
                str(
                    repo
                    / "plugins"
                    / "codex-review"
                    / "scripts"
                    / "approve_quality_learning_candidates.py"
                ),
                "--candidates",
                str(intake_dir / f"{prefix}-candidates.json"),
                "--comparison",
                str(comparison_dir / "quality-comparison.json"),
                "--output",
                str(approved_candidates_file),
            ]
            approval = run_cmd(approval_cmd, repo)
            approved_payload = read_json(approved_candidates_file)
            approved_ids = approved_payload.get("approved_ids") or []
            if approved_ids:
                apply_cmd = [
                    sys.executable,
                    str(
                        repo
                        / "plugins"
                        / "codex-review"
                        / "scripts"
                        / "apply_corpus_updates.py"
                    ),
                    "--input",
                    str(approved_candidates_file),
                    "--mode",
                    args.quality_apply_mode,
                    "--corpus",
                    str(probationary_corpus),
                    "--result-output",
                    str(apply_result_file),
                    "--allow-outside-artifacts",
                ]
                try:
                    apply_completed = run_cmd(apply_cmd, repo)
                    steps["quality_learning"] = {
                        "stdout": approval.stdout + apply_completed.stdout,
                        "stderr": approval.stderr + apply_completed.stderr,
                        "approved_candidates_file": str(approved_candidates_file),
                        "apply_result_file": str(apply_result_file),
                        "approved_ids": approved_ids,
                    }
                except subprocess.CalledProcessError as exc:
                    steps["quality_learning"] = {
                        "stdout": approval.stdout + exc.stdout,
                        "stderr": approval.stderr + exc.stderr,
                        "approved_candidates_file": str(approved_candidates_file),
                        "apply_result_file": str(apply_result_file),
                        "approved_ids": approved_ids,
                        "apply_failed": True,
                        "reason": "apply_corpus_updates.py rejected the approved public candidate batch.",
                    }
            else:
                steps["quality_learning"] = {
                    "stdout": approval.stdout,
                    "stderr": approval.stderr,
                    "approved_candidates_file": str(approved_candidates_file),
                    "approved_ids": [],
                    "skipped": True,
                    "reason": "Quality comparison did not approve any corpus-gap misses for probationary learning.",
                }

    summary_path = output_dir / "public-pr-quality-summary.json"
    write_json(summary_path, summary)
    print(f"Public PR quality run: {output_dir}")
    print(f"Summary: {summary_path}")
    if review_file is not None:
        print(f"Comparison: {comparison_dir / 'quality-comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
