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
DEFAULT_PROBATIONARY_CORPUS_PATH = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/probationary-review-cases.json"
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
        "--raw-input",
        help=(
            "Optional raw review-feedback JSON file. This is the preferred MCP-native path and skips live fetch. "
            "The file can be a GitHub export, an MCP tool output snapshot, or an existing fetch artifact."
        ),
    )
    parser.add_argument(
        "--raw-format",
        default="auto",
        choices=[
            "auto",
            "custom_review_bundle",
            "github_rest_review_comments",
            "github_graphql_review_threads",
            "github_mcp_pr_comments",
            "github_mcp_review_threads",
        ],
        help="Format for --raw-input. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--source",
        default="rest",
        choices=["rest", "graphql"],
        help="Which fetched legacy-gh source artifact to normalize. Defaults to rest.",
    )
    parser.add_argument(
        "--use-gh-legacy-fetch",
        action="store_true",
        help=(
            "Opt into the legacy gh-based live GitHub fetch path. The preferred path is to provide --raw-input "
            "from the plugin's MCP-backed GitHub connector."
        ),
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
        "--apply-target",
        default="primary",
        choices=["primary", "probationary"],
        help="Target corpus lane for apply. Defaults to primary.",
    )
    parser.add_argument(
        "--gate-candidates",
        action="store_true",
        help=(
            "Run candidate-quality gating before apply. Requires a review artifact or review text and is intended "
            "for safer self-learning into the probationary lane."
        ),
    )
    parser.add_argument(
        "--score-review-file",
        help="Optional review output file to benchmark before and after apply.",
    )
    parser.add_argument(
        "--score-review-artifacts",
        help=(
            "Optional prepared review-artifact directory. Accepts either a specific run directory "
            "containing review.md or a parent .codex-review directory, in which case the newest "
            "child run with review.md is used."
        ),
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
        "--review-run-dir",
        help=(
            "Optional prepared review run directory to reuse as the pipeline working directory. "
            "This allows prepare -> write review -> benchmark/apply to happen in one shared run folder."
        ),
    )
    parser.add_argument(
        "--stop-after",
        default="apply",
        choices=["fetch", "ingest", "propose", "promote", "apply"],
        help="Stop after the named stage. Defaults to apply.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing artifacts in the run directory instead of rerunning completed earlier stages.",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help=(
            "Unsafe local-write override: allow pipeline artifacts to be written outside the repo's "
            "ignored artifacts/github-intake tree. This does not change GitHub access, which remains read-only."
        ),
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


def find_optional_single_artifact(fetch_dir: Path, pattern: str) -> Path | None:
    matches = sorted(fetch_dir.glob(pattern))
    if not matches:
        return None
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected at most one artifact matching {pattern} under {fetch_dir}, found {len(matches)}."
        )
    return matches[0]


def print_summary(
    output_dir: Path,
    selected_raw: Path,
    proposal_path: Path,
    candidates_path: Path,
    apply_input_path: Path,
    apply_result_path: Path | None,
    benchmark_delta_path: Path | None,
) -> None:
    print(f"Pipeline run directory: {output_dir}")
    print(f"Selected raw input: {selected_raw}")
    print(f"Proposal artifact: {proposal_path}")
    print(f"Candidate artifact: {candidates_path}")
    if apply_input_path != candidates_path:
        print(f"Apply input artifact: {apply_input_path}")
    if apply_result_path is not None:
        print(f"Apply result artifact: {apply_result_path}")
    if benchmark_delta_path is not None:
        print(f"Benchmark delta artifact: {benchmark_delta_path}")


def resolve_corpus_path(repo_root: Path, requested_path: str | None, apply_target: str) -> Path:
    if requested_path:
        return Path(requested_path).resolve()
    default_corpus = DEFAULT_CORPUS_PATH if apply_target == "primary" else DEFAULT_PROBATIONARY_CORPUS_PATH
    return (repo_root / default_corpus).resolve()


def run_benchmarks(
    benchmark_script: Path,
    primary_corpus: Path,
    probationary_corpus: Path,
    review_file: str | None,
    review_text: str | None,
) -> dict:
    cmd = [
        sys.executable,
        str(benchmark_script),
        "--json",
        "--primary-corpus",
        str(primary_corpus),
        "--probationary-corpus",
        str(probationary_corpus),
    ]
    if review_file:
        cmd.extend(["--review-file", review_file])
    elif review_text is not None:
        cmd.extend(["--review-text", review_text])
    else:
        raise ValueError("Scoring requires --score-review-file or --score-review-text.")
    return run_json_cmd(cmd)


def resolve_review_artifact_file(review_artifacts: str) -> Path:
    candidate = Path(review_artifacts).resolve()
    if candidate.is_file():
        return candidate
    if not candidate.is_dir():
        raise FileNotFoundError(f"Review artifact path does not exist: {candidate}")

    direct_review = candidate / "review.md"
    if direct_review.is_file():
        return direct_review

    child_runs = sorted(
        (child for child in candidate.iterdir() if child.is_dir() and (child / "review.md").is_file()),
        key=lambda child: child.name,
        reverse=True,
    )
    if child_runs:
        return child_runs[0] / "review.md"

    raise FileNotFoundError(
        f"Could not find review.md under {candidate}. "
        "Pass a run directory containing review.md or a parent .codex-review directory with scored runs."
    )


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

    return {lane_name: lane_delta(before[lane_name], after[lane_name]) for lane_name in before if lane_name in after}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def artifact_prefix_for_raw_format(raw_format: str) -> str:
    if raw_format in {"github_graphql_review_threads", "github_mcp_review_threads"}:
        return "graphql"
    if raw_format in {"github_rest_review_comments", "github_mcp_pr_comments"}:
        return "rest"
    return "input"


def main() -> int:
    args = parse_args()
    if args.promote_all and args.promote_ids:
        raise ValueError("Use either --promote-all or --promote-ids, not both.")
    if args.score_review_artifacts and args.score_review_file:
        raise ValueError("Use either --score-review-artifacts or --score-review-file, not both.")
    resolved_review_file: str | None = None
    if args.score_review_artifacts:
        resolved_review_file = str(resolve_review_artifact_file(args.score_review_artifacts))
    if args.score_review_file and args.score_review_text is not None:
        raise ValueError("Use either --score-review-file or --score-review-text, not both.")
    if args.score_review_artifacts and args.score_review_text is not None:
        raise ValueError("Use either --score-review-artifacts or --score-review-text, not both.")
    if resolved_review_file is None:
        resolved_review_file = args.score_review_file

    script_path = Path(__file__).resolve()
    repo_root = repo_root_from_script()
    if args.review_run_dir and args.output_dir:
        raise ValueError("Use either --review-run-dir or --output-dir, not both.")
    resolved_output_dir = args.review_run_dir or args.output_dir
    allow_outside_artifacts = args.allow_outside_artifacts
    output_dir = resolve_output_dir(repo_root, args.repo, args.pr, resolved_output_dir, allow_outside_artifacts)
    fetch_dir = output_dir / "fetches"
    selected_prefix = artifact_prefix_for_raw_format(args.raw_format) if args.raw_input else args.source

    fetch_script = script_path.parent / "fetch_github_review_feedback.py"
    ingest_script = script_path.parent / "ingest_github_review_feedback.py"
    propose_script = script_path.parent / "propose_corpus_updates.py"
    promote_script = script_path.parent / "promote_corpus_candidates.py"
    quality_gate_script = script_path.parent / "score_candidate_quality.py"
    apply_script = script_path.parent / "apply_corpus_updates.py"
    benchmark_script = (
        script_path.parent.parent / "skills" / "bug-hunting-code-review" / "scripts" / "run_review_benchmarks.py"
    )
    corpus_path = resolve_corpus_path(repo_root, args.corpus, args.apply_target)

    proposal_path = output_dir / f"{selected_prefix}-proposal.json"
    candidates_path = output_dir / f"{selected_prefix}-candidates.json"
    promoted_candidates_path = output_dir / f"{selected_prefix}-promoted-candidates.json"
    quality_result_path = output_dir / f"{selected_prefix}-candidate-quality.json"
    gated_candidates_path = output_dir / f"{selected_prefix}-gate-approved-candidates.json"
    apply_result_path = output_dir / f"{selected_prefix}-apply-result.json"
    benchmark_before_path = output_dir / f"{selected_prefix}-benchmarks-before.json"
    benchmark_after_path = output_dir / f"{selected_prefix}-benchmarks-after.json"
    benchmark_delta_path = output_dir / f"{selected_prefix}-benchmark-delta.json"
    benchmark_before_primary_snapshot = output_dir / f"{selected_prefix}-primary-corpus-before.json"
    benchmark_before_probationary_snapshot = output_dir / f"{selected_prefix}-probationary-corpus-before.json"
    primary_corpus_path = (repo_root / DEFAULT_CORPUS_PATH).resolve()
    probationary_corpus_path = (repo_root / DEFAULT_PROBATIONARY_CORPUS_PATH).resolve()
    raw_format_for_ingest = args.raw_format
    if args.raw_input:
        selected_raw_path = Path(args.raw_input).resolve()
        if not selected_raw_path.is_file():
            raise FileNotFoundError(f"Raw input file does not exist: {selected_raw_path}")
    else:
        if not args.use_gh_legacy_fetch:
            raise ValueError(
                "Live GitHub fetch now expects MCP-backed raw input by default. "
                "Provide --raw-input from the plugin GitHub MCP path, or pass --use-gh-legacy-fetch to opt into "
                "the legacy gh-based fetch script."
            )

        rest_raw_path = find_optional_single_artifact(fetch_dir, "*-rest-review-comments.json")
        graphql_raw_path = find_optional_single_artifact(fetch_dir, "*-graphql-review-threads.json")
        need_fetch = not (
            args.resume and rest_raw_path is not None and (args.source == "rest" or graphql_raw_path is not None)
        )

        if need_fetch:
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
            if allow_outside_artifacts:
                fetch_cmd.append("--allow-outside-artifacts")
            fetch_result = run_cmd_with_result(fetch_cmd)
            if fetch_result.stdout:
                print(fetch_result.stdout, end="")
            if fetch_result.stderr:
                print(fetch_result.stderr, end="", file=sys.stderr)

            rest_raw_path = find_single_artifact(fetch_dir, "*-rest-review-comments.json")
            graphql_raw_path = find_optional_single_artifact(fetch_dir, "*-graphql-review-threads.json")

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
        else:
            print(f"Reusing existing fetch artifacts in {fetch_dir}")

        if rest_raw_path is None:
            raise FileNotFoundError(f"No REST review artifact was found under {fetch_dir}.")

        if args.source == "rest":
            selected_raw_path = rest_raw_path
            raw_format_for_ingest = "github_rest_review_comments"
        else:
            if graphql_raw_path is None:
                raise FileNotFoundError(
                    f"GraphQL source was requested but no GraphQL artifact was written under {fetch_dir}."
                )
            selected_raw_path = graphql_raw_path
            raw_format_for_ingest = "github_graphql_review_threads"

    if args.stop_after == "fetch":
        print_summary(
            output_dir=output_dir,
            selected_raw=selected_raw_path,
            proposal_path=proposal_path,
            candidates_path=candidates_path,
            apply_input_path=candidates_path,
            apply_result_path=None,
            benchmark_delta_path=None,
        )
        return 0

    if not (args.resume and proposal_path.is_file()):
        ingest_cmd = [
            sys.executable,
            str(ingest_script),
            "--input",
            str(selected_raw_path),
            "--output",
            str(proposal_path),
        ]
        if raw_format_for_ingest != "auto":
            ingest_cmd.extend(["--format", raw_format_for_ingest])
        if allow_outside_artifacts:
            ingest_cmd.append("--allow-outside-artifacts")
        run_step(ingest_cmd)
    else:
        print(f"Reusing existing proposal artifact: {proposal_path}")

    if args.stop_after == "ingest":
        print_summary(
            output_dir=output_dir,
            selected_raw=selected_raw_path,
            proposal_path=proposal_path,
            candidates_path=candidates_path,
            apply_input_path=candidates_path,
            apply_result_path=None,
            benchmark_delta_path=None,
        )
        return 0

    if not (args.resume and candidates_path.is_file()):
        propose_cmd = [
            sys.executable,
            str(propose_script),
            "--input",
            str(proposal_path),
            "--output",
            str(candidates_path),
        ]
        if allow_outside_artifacts:
            propose_cmd.append("--allow-outside-artifacts")
        run_step(propose_cmd)
    else:
        print(f"Reusing existing candidate artifact: {candidates_path}")

    apply_input_path = candidates_path
    if args.stop_after == "propose":
        print_summary(
            output_dir=output_dir,
            selected_raw=selected_raw_path,
            proposal_path=proposal_path,
            candidates_path=candidates_path,
            apply_input_path=apply_input_path,
            apply_result_path=None,
            benchmark_delta_path=None,
        )
        return 0

    if args.promote_all or args.promote_ids:
        if not (args.resume and promoted_candidates_path.is_file()):
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
            if allow_outside_artifacts:
                promote_cmd.append("--allow-outside-artifacts")
            run_step(promote_cmd)
        else:
            print(f"Reusing existing promoted candidate artifact: {promoted_candidates_path}")
        apply_input_path = promoted_candidates_path

    if args.stop_after == "promote":
        print_summary(
            output_dir=output_dir,
            selected_raw=selected_raw_path,
            proposal_path=proposal_path,
            candidates_path=candidates_path,
            apply_input_path=apply_input_path,
            apply_result_path=None,
            benchmark_delta_path=None,
        )
        return 0

    scoring_enabled = bool(resolved_review_file or args.score_review_text is not None)
    if args.gate_candidates:
        if not scoring_enabled:
            raise ValueError(
                "--gate-candidates requires --score-review-file, --score-review-artifacts, or --score-review-text."
            )
        quality_cmd = [
            sys.executable,
            str(quality_gate_script),
            "--input",
            str(apply_input_path),
            "--primary-corpus",
            str((repo_root / DEFAULT_CORPUS_PATH).resolve()),
            "--probationary-corpus",
            str((repo_root / DEFAULT_PROBATIONARY_CORPUS_PATH).resolve()),
            "--output",
            str(quality_result_path),
            "--filtered-output",
            str(gated_candidates_path),
        ]
        if resolved_review_file:
            quality_cmd.extend(["--review-file", resolved_review_file])
        else:
            quality_cmd.extend(["--review-text", args.score_review_text])
        if allow_outside_artifacts:
            quality_cmd.append("--allow-outside-artifacts")
        run_step(quality_cmd)
        apply_input_path = gated_candidates_path

    if scoring_enabled:
        before_primary_corpus = primary_corpus_path
        before_probationary_corpus = probationary_corpus_path
        if args.apply_target == "primary":
            shutil.copyfile(corpus_path, benchmark_before_primary_snapshot)
            before_primary_corpus = benchmark_before_primary_snapshot
        else:
            shutil.copyfile(corpus_path, benchmark_before_probationary_snapshot)
            before_probationary_corpus = benchmark_before_probationary_snapshot
        before_benchmarks = run_benchmarks(
            benchmark_script,
            before_primary_corpus,
            before_probationary_corpus,
            resolved_review_file,
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
        "--corpus",
        str(corpus_path),
        "--result-output",
        str(apply_result_path),
    ]
    if allow_outside_artifacts:
        apply_cmd.append("--allow-outside-artifacts")
    run_step(apply_cmd)

    printed_benchmark_delta_path: Path | None = None
    if scoring_enabled:
        after_primary_corpus = corpus_path if args.apply_target == "primary" else primary_corpus_path
        after_probationary_corpus = corpus_path if args.apply_target == "probationary" else probationary_corpus_path
        after_benchmarks = run_benchmarks(
            benchmark_script,
            after_primary_corpus,
            after_probationary_corpus,
            resolved_review_file,
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
