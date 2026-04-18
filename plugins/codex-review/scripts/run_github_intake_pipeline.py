import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the GitHub review-intake pipeline end-to-end: fetch, ingest, propose, "
            "optional promote, and apply."
        )
    )
    parser.add_argument("--repo", required=True, help="GitHub repo in owner/name form.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
    parser.add_argument(
        "--source",
        default="rest",
        choices=["rest", "graphql"],
        help="Which fetched source artifact to normalize. Defaults to rest.",
    )
    parser.add_argument(
        "--apply-mode",
        default="auto",
        choices=["auto", "review", "force"],
        help="Apply mode for the final corpus-apply step. Defaults to auto.",
    )
    parser.add_argument(
        "--promote-ids",
        nargs="*",
        default=[],
        help="Candidate ids to promote before apply.",
    )
    parser.add_argument(
        "--promote-all",
        action="store_true",
        help="Promote all generated candidates before apply.",
    )
    parser.add_argument(
        "--reviewer",
        default="local-review",
        help="Reviewer label for promotion metadata. Defaults to local-review.",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional promotion note recorded in promoted candidate metadata.",
    )
    parser.add_argument(
        "--corpus",
        help="Optional path to the target review corpus JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Optional pipeline run directory. Defaults to "
            "artifacts/github-intake/pipeline/<repo>-pr-<number>-<timestamp>."
        ),
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def default_output_dir(repo_root: Path, repo: str, pr_number: int) -> Path:
    safe_repo = repo.replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / "pipeline" / f"{safe_repo}-pr-{pr_number}-{timestamp}"


def resolve_output_dir(
    repo_root: Path,
    repo: str,
    pr_number: int,
    output_dir: str | None,
    allow_outside_artifacts: bool,
) -> Path:
    artifacts_root = (repo_root / "artifacts" / "github-intake").resolve()
    if output_dir is None:
        return default_output_dir(repo_root, repo, pr_number)

    candidate = Path(output_dir).resolve()
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write pipeline artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def run_step(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def find_single_artifact(fetch_dir: Path, pattern: str) -> Path:
    matches = sorted(fetch_dir.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one artifact matching {pattern} under {fetch_dir}, found {len(matches)}."
        )
    return matches[0]


def print_summary(
    output_dir: Path,
    selected_raw: Path,
    proposal_path: Path,
    candidates_path: Path,
    apply_input_path: Path,
    apply_result_path: Path,
) -> None:
    print(f"Pipeline run directory: {output_dir}")
    print(f"Selected raw input: {selected_raw}")
    print(f"Proposal artifact: {proposal_path}")
    print(f"Candidate artifact: {candidates_path}")
    if apply_input_path != candidates_path:
        print(f"Apply input artifact: {apply_input_path}")
    print(f"Apply result artifact: {apply_result_path}")


def main() -> int:
    args = parse_args()
    if args.promote_all and args.promote_ids:
        raise ValueError("Use either --promote-all or --promote-ids, not both.")

    script_path = Path(__file__).resolve()
    repo_root = repo_root_from_script()
    output_dir = resolve_output_dir(repo_root, args.repo, args.pr, args.output_dir, args.allow_outside_artifacts)
    fetch_dir = output_dir / "fetches"
    selected_prefix = args.source

    fetch_script = script_path.parent / "fetch_github_review_feedback.py"
    ingest_script = script_path.parent / "ingest_github_review_feedback.py"
    propose_script = script_path.parent / "propose_corpus_updates.py"
    promote_script = script_path.parent / "promote_corpus_candidates.py"
    apply_script = script_path.parent / "apply_corpus_updates.py"

    proposal_path = output_dir / f"{selected_prefix}-proposal.json"
    candidates_path = output_dir / f"{selected_prefix}-candidates.json"
    promoted_candidates_path = output_dir / f"{selected_prefix}-promoted-candidates.json"
    apply_result_path = output_dir / f"{selected_prefix}-apply-result.json"

    fetch_cmd = [
        sys.executable,
        str(fetch_script),
        "--repo",
        args.repo,
        "--pr",
        str(args.pr),
        "--output-dir",
        str(fetch_dir),
    ]
    if args.allow_outside_artifacts:
        fetch_cmd.append("--allow-outside-artifacts")
    run_step(fetch_cmd)

    rest_raw_path = find_single_artifact(fetch_dir, "*-rest-review-comments.json")
    graphql_raw_path = find_single_artifact(fetch_dir, "*-graphql-review-threads.json")
    selected_raw_path = rest_raw_path if args.source == "rest" else graphql_raw_path

    ingest_cmd = [
        sys.executable,
        str(ingest_script),
        "--input",
        str(selected_raw_path),
        "--output",
        str(proposal_path),
    ]
    if args.allow_outside_artifacts:
        ingest_cmd.append("--allow-outside-artifacts")
    run_step(ingest_cmd)

    propose_cmd = [
        sys.executable,
        str(propose_script),
        "--input",
        str(proposal_path),
        "--output",
        str(candidates_path),
    ]
    if args.allow_outside_artifacts:
        propose_cmd.append("--allow-outside-artifacts")
    run_step(propose_cmd)

    apply_input_path = candidates_path
    if args.promote_all or args.promote_ids:
        promote_cmd = [
            sys.executable,
            str(promote_script),
            "--input",
            str(candidates_path),
            "--output",
            str(promoted_candidates_path),
            "--reviewer",
            args.reviewer,
            "--note",
            args.note,
        ]
        if args.promote_all:
            promote_cmd.append("--all")
        else:
            promote_cmd.append("--ids")
            promote_cmd.extend(args.promote_ids)
        if args.allow_outside_artifacts:
            promote_cmd.append("--allow-outside-artifacts")
        run_step(promote_cmd)
        apply_input_path = promoted_candidates_path

    apply_cmd = [
        sys.executable,
        str(apply_script),
        "--input",
        str(apply_input_path),
        "--mode",
        args.apply_mode,
        "--result-output",
        str(apply_result_path),
    ]
    if args.corpus:
        apply_cmd.extend(["--corpus", args.corpus])
    if args.allow_outside_artifacts:
        apply_cmd.append("--allow-outside-artifacts")
    run_step(apply_cmd)

    print_summary(
        output_dir=output_dir,
        selected_raw=selected_raw_path,
        proposal_path=proposal_path,
        candidates_path=candidates_path,
        apply_input_path=apply_input_path,
        apply_result_path=apply_result_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
