import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CORPUS_PATH = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/review-corpus-cases.json"
)


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
        "--score-review-file",
        help="Optional review output file to benchmark before and after apply.",
    )
    parser.add_argument(
        "--score-review-text",
        help="Optional inline review text to benchmark before and after apply.",
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


def run_cmd_with_result(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def run_json_cmd(cmd: list[str]) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


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
    benchmark_delta_path: Path | None,
) -> None:
    print(f"Pipeline run directory: {output_dir}")
    print(f"Selected raw input: {selected_raw}")
    print(f"Proposal artifact: {proposal_path}")
    print(f"Candidate artifact: {candidates_path}")
    if apply_input_path != candidates_path:
        print(f"Apply input artifact: {apply_input_path}")
    print(f"Apply result artifact: {apply_result_path}")
    if benchmark_delta_path is not None:
        print(f"Benchmark delta artifact: {benchmark_delta_path}")


def resolve_corpus_path(repo_root: Path, requested_path: str | None) -> Path:
    if requested_path:
        return Path(requested_path).resolve()
    return (repo_root / DEFAULT_CORPUS_PATH).resolve()


def run_benchmarks(
    benchmark_script: Path,
    primary_corpus: Path,
    review_file: str | None,
    review_text: str | None,
) -> dict:
    cmd = [
        sys.executable,
        str(benchmark_script),
        "--json",
        "--primary-corpus",
        str(primary_corpus),
    ]
    if review_file:
        cmd.extend(["--review-file", review_file])
    elif review_text is not None:
        cmd.extend(["--review-text", review_text])
    else:
        raise ValueError("Scoring requires --score-review-file or --score-review-text.")
    return run_json_cmd(cmd)


def build_benchmark_delta(before: dict, after: dict) -> dict:
    def lane_delta(before_lane: dict, after_lane: dict) -> dict:
        before_summary = before_lane["summary"]
        after_summary = after_lane["summary"]
        return {
            "matched_cases_before": before_summary["matched_cases"],
            "matched_cases_after": after_summary["matched_cases"],
            "matched_cases_delta": after_summary["matched_cases"] - before_summary["matched_cases"],
            "weighted_recall_before": before_summary["weighted_recall"],
            "weighted_recall_after": after_summary["weighted_recall"],
            "weighted_recall_delta": after_summary["weighted_recall"] - before_summary["weighted_recall"],
            "critical_or_high_misses_before": before_summary.get("critical_or_high_misses") or [],
            "critical_or_high_misses_after": after_summary.get("critical_or_high_misses") or [],
        }

    return {
        "primary_github_corpus": lane_delta(before["primary_github_corpus"], after["primary_github_corpus"]),
        "external_swebench_verified": lane_delta(
            before["external_swebench_verified"], after["external_swebench_verified"]
        ),
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.promote_all and args.promote_ids:
        raise ValueError("Use either --promote-all or --promote-ids, not both.")
    if args.score_review_file and args.score_review_text is not None:
        raise ValueError("Use either --score-review-file or --score-review-text, not both.")

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
    benchmark_script = (
        script_path.parent.parent / "skills" / "bug-hunting-code-review" / "scripts" / "run_review_benchmarks.py"
    )
    corpus_path = resolve_corpus_path(repo_root, args.corpus)

    proposal_path = output_dir / f"{selected_prefix}-proposal.json"
    candidates_path = output_dir / f"{selected_prefix}-candidates.json"
    promoted_candidates_path = output_dir / f"{selected_prefix}-promoted-candidates.json"
    apply_result_path = output_dir / f"{selected_prefix}-apply-result.json"
    benchmark_before_path = output_dir / f"{selected_prefix}-benchmarks-before.json"
    benchmark_after_path = output_dir / f"{selected_prefix}-benchmarks-after.json"
    benchmark_delta_path = output_dir / f"{selected_prefix}-benchmark-delta.json"
    benchmark_before_corpus_snapshot = output_dir / f"{selected_prefix}-primary-corpus-before.json"

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
    fetch_result = run_cmd_with_result(fetch_cmd)
    if fetch_result.stdout:
        print(fetch_result.stdout, end="")
    if fetch_result.stderr:
        print(fetch_result.stderr, end="", file=sys.stderr)

    rest_raw_path = find_single_artifact(fetch_dir, "*-rest-review-comments.json")
    graphql_raw_path: Path | None = None
    graphql_matches = sorted(fetch_dir.glob("*-graphql-review-threads.json"))
    if graphql_matches:
        if len(graphql_matches) != 1:
            raise FileNotFoundError(
                f"Expected exactly one GraphQL artifact under {fetch_dir}, found {len(graphql_matches)}."
            )
        graphql_raw_path = graphql_matches[0]

    if fetch_result.returncode != 0:
        if args.source == "rest" and graphql_raw_path is None:
            print(
                "Continuing with REST artifact after GraphQL fetch failure because --source rest was selected.",
                file=sys.stderr,
            )
        else:
            raise subprocess.CalledProcessError(
                fetch_result.returncode,
                fetch_cmd,
                output=fetch_result.stdout,
                stderr=fetch_result.stderr,
            )

    if args.source == "rest":
        selected_raw_path = rest_raw_path
    else:
        if graphql_raw_path is None:
            raise FileNotFoundError(f"GraphQL source was requested but no GraphQL artifact was written under {fetch_dir}.")
        selected_raw_path = graphql_raw_path

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

    scoring_enabled = bool(args.score_review_file or args.score_review_text is not None)
    if scoring_enabled:
        shutil.copyfile(corpus_path, benchmark_before_corpus_snapshot)
        before_benchmarks = run_benchmarks(
            benchmark_script,
            benchmark_before_corpus_snapshot,
            args.score_review_file,
            args.score_review_text,
        )
        write_json(benchmark_before_path, before_benchmarks)

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

    printed_benchmark_delta_path: Path | None = None
    if scoring_enabled:
        after_benchmarks = run_benchmarks(
            benchmark_script,
            corpus_path,
            args.score_review_file,
            args.score_review_text,
        )
        benchmark_delta = build_benchmark_delta(before_benchmarks, after_benchmarks)
        write_json(benchmark_after_path, after_benchmarks)
        write_json(benchmark_delta_path, benchmark_delta)
        printed_benchmark_delta_path = benchmark_delta_path

    print_summary(
        output_dir=output_dir,
        selected_raw=selected_raw_path,
        proposal_path=proposal_path,
        candidates_path=candidates_path,
        apply_input_path=apply_input_path,
        apply_result_path=apply_result_path,
        benchmark_delta_path=printed_benchmark_delta_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
