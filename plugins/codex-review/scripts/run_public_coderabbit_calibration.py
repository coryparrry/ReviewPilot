import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SET_PATH = Path(
    "plugins/codex-review/references/public-coderabbit-calibration-set.json"
)
ALLOWED_DEPTHS = {"quick", "deep"}
DEFAULT_DEPTHS = ["quick"]
DEFAULT_PASS_TIMEOUT_SECONDS = 420
DEFAULT_MAX_DEEP_PASSES = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a public CodeRabbit-only calibration batch: clone each public repo, review the PR diff with "
            "gpt-5.4-mini, compare the review against public CodeRabbit comments, and aggregate repeated misses."
        )
    )
    parser.add_argument(
        "--calibration-set",
        default=str(DEFAULT_SET_PATH),
        help="Path to the public calibration set JSON.",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to artifacts/public-coderabbit-calibration/<timestamp>.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.4-mini",
        help="Model passed to run_codex_review.py. Defaults to gpt-5.4-mini.",
    )
    parser.add_argument(
        "--depths",
        default=",".join(DEFAULT_DEPTHS),
        help=(
            "Comma-separated review depths to compare. Allowed values: quick,deep. "
            "Defaults to quick so calibration runs do not spend deep-review budget unless requested."
        ),
    )
    parser.add_argument(
        "--review-ref",
        default="comment-original",
        choices=["comment-original", "head"],
        help=(
            "Commit to review. comment-original reviews the commit that public review comments targeted; "
            "head reviews the final PR head. Defaults to comment-original for apples-to-apples calibration."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit on the number of calibration entries to run.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing review and comparison artifacts in the output directory when present.",
    )
    return parser.parse_args()


def parse_depths(raw: str) -> list[str]:
    depths = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not depths:
        raise ValueError("--depths must include at least one depth.")

    seen: set[str] = set()
    for depth in depths:
        if depth not in ALLOWED_DEPTHS:
            raise ValueError(
                f"Invalid review depth {depth!r}. Expected one of {sorted(ALLOWED_DEPTHS)}."
            )
        if depth in seen:
            raise ValueError(f"Duplicate review depth {depth!r} in --depths.")
        seen.add(depth)
    return depths


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def repo_root(cwd: Path) -> Path:
    completed = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(completed.stdout.strip())


def default_output_dir(repo: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo / "artifacts" / "public-coderabbit-calibration" / timestamp


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_label(entry: dict[str, Any]) -> str:
    raw = str(
        entry.get("label") or f"{entry['repo'].replace('/', '-')}-pr-{entry['pr']}"
    )
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    sanitized = sanitized.replace("..", "-")
    if sanitized:
        return sanitized[:120]
    fallback = f"{entry['repo'].replace('/', '-')}-pr-{entry['pr']}"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", fallback).strip(".-")[:120]


def ensure_repo_clone(root: Path, github_repo: str) -> Path:
    repo_dir = root / github_repo.replace("/", "__")
    if repo_dir.is_dir():
        run_cmd(["git", "fetch", "--all", "--prune"], repo_dir)
        return repo_dir
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["gh", "repo", "clone", github_repo, str(repo_dir)], root)
    return repo_dir


def pr_metadata(repo_dir: Path, github_repo: str, pr_number: int) -> dict[str, Any]:
    completed = run_cmd(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            github_repo,
            "--json",
            "baseRefName,title,url",
        ],
        repo_dir,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("gh pr view returned a non-object JSON payload.")
    return payload


def checkout_pr(repo_dir: Path, pr_number: int) -> None:
    local_branch = f"pr-{pr_number}"
    run_cmd(["git", "fetch", "--force", "origin", f"pull/{pr_number}/head"], repo_dir)
    run_cmd(["git", "checkout", "--force", "-B", local_branch, "FETCH_HEAD"], repo_dir)


def current_head_sha(repo_dir: Path) -> str:
    completed = run_cmd(["git", "rev-parse", "HEAD"], repo_dir)
    return completed.stdout.strip()


def fetch_pr_review_comments(
    repo_dir: Path, github_repo: str, pr_number: int
) -> list[dict[str, Any]]:
    completed = run_cmd(
        [
            "gh",
            "api",
            f"repos/{github_repo}/pulls/{pr_number}/comments",
            "--paginate",
            "--slurp",
        ],
        repo_dir,
    )
    payload = json.loads(completed.stdout)
    comments: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for page_or_item in payload:
            if isinstance(page_or_item, list):
                comments.extend(item for item in page_or_item if isinstance(item, dict))
            elif isinstance(page_or_item, dict):
                comments.append(page_or_item)
    return comments


def choose_original_comment_commit(comments: list[dict[str, Any]]) -> str | None:
    commit_counter: Counter[str] = Counter()
    commit_order: list[str] = []
    for comment in comments:
        commit = comment.get("original_commit_id") or comment.get("commit_id")
        if not isinstance(commit, str) or not commit.strip():
            continue
        commit = commit.strip()
        if commit not in commit_counter:
            commit_order.append(commit)
        commit_counter[commit] += 1
    if not commit_counter:
        return None
    return max(
        commit_order,
        key=lambda commit: (commit_counter[commit], -commit_order.index(commit)),
    )


def checkout_review_ref(
    repo_dir: Path, github_repo: str, pr_number: int, review_ref: str
) -> tuple[str, str]:
    if review_ref == "head":
        return current_head_sha(repo_dir), "head"

    comments = fetch_pr_review_comments(repo_dir, github_repo, pr_number)
    original_commit = choose_original_comment_commit(comments)
    if original_commit is None:
        return current_head_sha(repo_dir), "head-no-comments"

    run_cmd(["git", "checkout", "--force", original_commit], repo_dir)
    return current_head_sha(repo_dir), "comment-original"


def newest_child_dir(path: Path) -> Path:
    children = sorted(
        (child for child in path.iterdir() if child.is_dir()),
        key=lambda item: item.name,
        reverse=True,
    )
    if not children:
        raise FileNotFoundError(f"No child directories found under {path}")
    return children[0]


def expected_review_cache_key(
    *,
    head_sha: str,
    base_ref: str,
    depth: str,
    model: str,
) -> dict[str, Any]:
    return {
        "head_sha": head_sha,
        "base": base_ref,
        "mode": "changes",
        "depth": depth,
        "model": model,
        "quality_comparison": "",
        "max_deep_passes": DEFAULT_MAX_DEEP_PASSES,
        "pass_timeout_seconds": DEFAULT_PASS_TIMEOUT_SECONDS,
        "benchmark_enabled": depth != "quick",
    }


def review_run_is_complete(
    path: Path, expected_cache_key: dict[str, Any] | None = None
) -> bool:
    review_file = path / "review.md"
    if (
        not review_file.is_file()
        or not review_file.read_text(encoding="utf-8", errors="replace").strip()
    ):
        return False
    if expected_cache_key is None:
        return True
    cache_key_path = path / "review-cache-key.json"
    if not cache_key_path.is_file():
        return False
    try:
        cache_key = json.loads(
            cache_key_path.read_text(encoding="utf-8", errors="replace")
        )
    except json.JSONDecodeError:
        return False
    return isinstance(cache_key, dict) and cache_key == expected_cache_key


def newest_complete_review_run(
    path: Path, expected_cache_key: dict[str, Any]
) -> Path | None:
    if not path.is_dir():
        return None
    for candidate in sorted(
        (child for child in path.iterdir() if child.is_dir()),
        key=lambda item: item.name,
        reverse=True,
    ):
        if review_run_is_complete(candidate, expected_cache_key):
            return candidate
    return None


def comparison_cache_key(
    *,
    github_repo: str,
    pr_number: int,
    source: str,
    review_file: Path,
) -> dict[str, Any]:
    return {
        "github_repo": github_repo,
        "pr": pr_number,
        "source": source,
        "review_file": str(review_file.resolve()),
    }


def write_comparison_cache_key(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def comparison_file_is_current(
    comparison_file: Path, cache_key_file: Path, expected_cache_key: dict[str, Any]
) -> bool:
    if not comparison_file.is_file() or not cache_key_file.is_file():
        return False
    try:
        cache_key = json.loads(
            cache_key_file.read_text(encoding="utf-8", errors="replace")
        )
    except json.JSONDecodeError:
        return False
    return isinstance(cache_key, dict) and cache_key == expected_cache_key


def run_review(
    repo_root_dir: Path,
    target_repo: Path,
    base_ref: str,
    output_dir: Path,
    model: str,
    depth: str,
) -> Path:
    cmd = [
        sys.executable,
        str(
            repo_root_dir
            / "plugins"
            / "codex-review"
            / "scripts"
            / "run_codex_review.py"
        ),
        "--repo",
        str(target_repo),
        "--mode",
        "changes",
        "--depth",
        depth,
        "--base",
        base_ref,
        "--model",
        model,
        "--output-dir",
        str(output_dir),
    ]
    run_cmd(cmd, repo_root_dir)
    return newest_child_dir(output_dir)


def run_public_compare(
    repo_root_dir: Path,
    github_repo: str,
    pr_number: int,
    source: str,
    review_file: Path,
    output_dir: Path,
) -> Path:
    cmd = [
        sys.executable,
        str(
            repo_root_dir
            / "plugins"
            / "codex-review"
            / "scripts"
            / "run_public_pr_quality_cycle.py"
        ),
        "--repo",
        github_repo,
        "--pr",
        str(pr_number),
        "--source",
        source,
        "--review-file",
        str(review_file),
        "--output-dir",
        str(output_dir),
    ]
    run_cmd(cmd, repo_root_dir)
    return output_dir / "quality-comparison" / "quality-comparison.json"


def cluster_misses(comparison_files: list[Path]) -> dict[str, Any]:
    category_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    anchor_counter: Counter[str] = Counter()
    title_counter: Counter[str] = Counter()
    missed_findings: list[dict[str, Any]] = []

    for path in comparison_files:
        payload = load_json(path)
        for finding in payload.get("findings", []):
            if finding.get("gap_classification") == "caught":
                continue
            missed_findings.append(finding)
            category_counter[
                str(finding.get("normalized_category") or "uncategorized")
            ] += 1
            severity_counter[str(finding.get("severity") or "unknown")] += 1
            title_counter[str(finding.get("candidate_title") or "untitled")] += 1
            for phrase in finding.get("suggested_signal_phrases") or []:
                cleaned = " ".join(str(phrase).split())
                if cleaned:
                    anchor_counter[cleaned] += 1

    return {
        "missed_count": len(missed_findings),
        "top_categories": [
            {"category": key, "count": count}
            for key, count in category_counter.most_common(10)
        ],
        "top_severities": [
            {"severity": key, "count": count}
            for key, count in severity_counter.most_common(10)
        ],
        "repeated_titles": [
            {"title": key, "count": count}
            for key, count in title_counter.most_common(10)
        ],
        "repeated_signal_phrases": [
            {"phrase": key, "count": count}
            for key, count in anchor_counter.most_common(20)
        ],
    }


def finding_identity(finding: dict[str, Any]) -> str:
    candidate_id = finding.get("candidate_id")
    if isinstance(candidate_id, str) and candidate_id.strip():
        return f"id:{candidate_id.strip()}"
    return "|".join(
        [
            str(finding.get("file_path") or ""),
            str(finding.get("line") or ""),
            str(finding.get("candidate_title") or ""),
            str(finding.get("candidate_summary") or ""),
        ]
    )


def summarize_comparison_files(comparison_files: list[Path]) -> dict[str, Any]:
    severity_counter: Counter[str] = Counter()
    title_counter: Counter[str] = Counter()
    anchor_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    caught_count = 0
    missed_count = 0
    total_findings = 0

    for path in comparison_files:
        payload = load_json(path)
        for finding in payload.get("findings", []):
            total_findings += 1
            if finding.get("gap_classification") == "caught":
                caught_count += 1
                continue

            missed_count += 1
            severity_counter[str(finding.get("severity") or "unknown")] += 1
            title_counter[str(finding.get("candidate_title") or "untitled")] += 1
            category_counter[
                str(finding.get("normalized_category") or "uncategorized")
            ] += 1
            for phrase in finding.get("suggested_signal_phrases") or []:
                cleaned = " ".join(str(phrase).split())
                if cleaned:
                    anchor_counter[cleaned] += 1

    return {
        "total_findings": total_findings,
        "caught_count": caught_count,
        "missed_count": missed_count,
        "missed_by_severity": dict(severity_counter),
        "top_missed_categories": [
            {"category": key, "count": count}
            for key, count in category_counter.most_common(10)
        ],
        "repeated_missed_titles": [
            {"title": key, "count": count}
            for key, count in title_counter.most_common(10)
        ],
        "repeated_missed_signal_phrases": [
            {"phrase": key, "count": count}
            for key, count in anchor_counter.most_common(20)
        ],
    }


def finding_label(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": finding.get("candidate_id"),
        "candidate_title": finding.get("candidate_title"),
        "file_path": finding.get("file_path"),
        "line": finding.get("line"),
        "severity": finding.get("severity"),
        "normalized_category": finding.get("normalized_category"),
    }


def quick_vs_deep_delta(results: list[dict[str, Any]]) -> dict[str, Any]:
    improved_findings: list[dict[str, Any]] = []
    comparable_prs = 0

    for result in results:
        reviews_by_depth = {
            review["depth"]: review
            for review in result.get("reviews", [])
            if isinstance(review, dict)
        }
        quick_review = reviews_by_depth.get("quick")
        deep_review = reviews_by_depth.get("deep")
        if not quick_review or not deep_review:
            continue
        comparable_prs += 1

        quick_payload = load_json(Path(str(quick_review["comparison_file"])))
        deep_payload = load_json(Path(str(deep_review["comparison_file"])))
        quick_missed = {
            finding_identity(finding): finding
            for finding in quick_payload.get("findings", [])
            if finding.get("gap_classification") != "caught"
        }
        deep_caught = {
            finding_identity(finding): finding
            for finding in deep_payload.get("findings", [])
            if finding.get("gap_classification") == "caught"
        }

        for key in sorted(quick_missed.keys() & deep_caught.keys()):
            improved_findings.append(
                {
                    "label": result.get("label"),
                    "repo": result.get("repo"),
                    "pr": result.get("pr"),
                    "finding": finding_label(deep_caught[key]),
                }
            )

    return {
        "comparable_prs": comparable_prs,
        "quick_missed_deep_caught_count": len(improved_findings),
        "quick_missed_deep_caught": improved_findings,
    }


def main() -> int:
    args = parse_args()
    root = repo_root(Path.cwd())
    depths = parse_depths(args.depths)
    output_dir = (
        Path(args.output_dir).resolve() if args.output_dir else default_output_dir(root)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    calibration_set = load_json(
        (root / args.calibration_set).resolve()
        if not Path(args.calibration_set).is_absolute()
        else Path(args.calibration_set)
    )
    if not isinstance(calibration_set, list):
        raise ValueError("Calibration set must be a JSON list.")
    if args.limit is not None and args.limit < 0:
        raise ValueError("--limit must be >= 0.")
    entries = (
        calibration_set[: args.limit] if args.limit is not None else calibration_set
    )

    clones_root = output_dir / "repos"
    reviews_root = output_dir / "reviews"
    comparisons_root = output_dir / "comparisons"

    results: list[dict[str, Any]] = []
    comparison_files_by_depth: dict[str, list[Path]] = {depth: [] for depth in depths}
    all_comparison_files: list[Path] = []

    for entry in entries:
        github_repo = str(entry["repo"])
        pr_number = int(entry["pr"])
        source = str(entry.get("source") or "rest")
        label = safe_label(entry)

        repo_dir = ensure_repo_clone(clones_root, github_repo)
        metadata = pr_metadata(repo_dir, github_repo, pr_number)
        checkout_pr(repo_dir, pr_number)
        review_head_sha, effective_review_ref = checkout_review_ref(
            repo_dir, github_repo, pr_number, args.review_ref
        )
        base_ref = f"origin/{metadata['baseRefName']}"

        reviews: list[dict[str, Any]] = []
        for depth in depths:
            review_parent = reviews_root / label / depth
            review_cache_key = expected_review_cache_key(
                head_sha=review_head_sha,
                base_ref=base_ref,
                depth=depth,
                model=args.model,
            )
            existing_review_run = (
                newest_complete_review_run(review_parent, review_cache_key)
                if args.resume
                else None
            )
            review_run_dir = existing_review_run or run_review(
                root, repo_dir, base_ref, review_parent, args.model, depth
            )
            review_file = review_run_dir / "review.md"

            comparison_parent = comparisons_root / label / depth
            comparison_file = (
                comparison_parent / "quality-comparison" / "quality-comparison.json"
            )
            comparison_cache = comparison_cache_key(
                github_repo=github_repo,
                pr_number=pr_number,
                source=source,
                review_file=review_file,
            )
            comparison_cache_file = comparison_parent / "comparison-cache-key.json"
            if not (
                args.resume
                and comparison_file_is_current(
                    comparison_file, comparison_cache_file, comparison_cache
                )
            ):
                comparison_file = run_public_compare(
                    root,
                    github_repo,
                    pr_number,
                    source,
                    review_file,
                    comparison_parent,
                )
                write_comparison_cache_key(comparison_cache_file, comparison_cache)
            comparison_files_by_depth[depth].append(comparison_file)
            all_comparison_files.append(comparison_file)
            comparison_payload = load_json(comparison_file)
            reviews.append(
                {
                    "depth": depth,
                    "review_run_dir": str(review_run_dir),
                    "review_file": str(review_file),
                    "comparison_file": str(comparison_file),
                    "summary": comparison_payload.get("summary") or {},
                }
            )

        results.append(
            {
                "label": label,
                "repo": github_repo,
                "pr": pr_number,
                "base_ref": base_ref,
                "review_ref": effective_review_ref,
                "review_head_sha": review_head_sha,
                "reviews": reviews,
            }
        )

    aggregate = {
        "schema_version": "codex-review.public-coderabbit-calibration.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "depths": depths,
        "review_ref": args.review_ref,
        "results": results,
        "depth_summaries": {
            depth: summarize_comparison_files(files)
            for depth, files in comparison_files_by_depth.items()
        },
        "quick_vs_deep_delta": quick_vs_deep_delta(results),
        "miss_clusters": cluster_misses(all_comparison_files),
    }
    write_json(output_dir / "aggregate-summary.json", aggregate)
    print(f"Public CodeRabbit calibration run: {output_dir}")
    print(f"Aggregate summary: {output_dir / 'aggregate-summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
