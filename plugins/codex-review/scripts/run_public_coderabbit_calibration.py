import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SET_PATH = Path("plugins/codex-review/references/public-coderabbit-calibration-set.json")


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
    raw = str(entry.get("label") or f"{entry['repo'].replace('/', '-')}-pr-{entry['pr']}")
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
        ["gh", "pr", "view", str(pr_number), "--repo", github_repo, "--json", "baseRefName,title,url"],
        repo_dir,
    )
    return json.loads(completed.stdout)


def checkout_pr(repo_dir: Path, pr_number: int) -> None:
    local_branch = f"pr-{pr_number}"
    run_cmd(["git", "fetch", "--force", "origin", f"pull/{pr_number}/head"], repo_dir)
    run_cmd(["git", "checkout", "--force", "-B", local_branch, "FETCH_HEAD"], repo_dir)


def newest_child_dir(path: Path) -> Path:
    children = sorted((child for child in path.iterdir() if child.is_dir()), key=lambda item: item.name, reverse=True)
    if not children:
        raise FileNotFoundError(f"No child directories found under {path}")
    return children[0]


def review_run_is_complete(path: Path) -> bool:
    review_file = path / "review.md"
    return review_file.is_file() and bool(review_file.read_text(encoding="utf-8", errors="replace").strip())


def run_review(repo_root_dir: Path, target_repo: Path, base_ref: str, output_dir: Path, model: str) -> Path:
    cmd = [
        sys.executable,
        str(repo_root_dir / "plugins" / "codex-review" / "scripts" / "run_codex_review.py"),
        "--repo",
        str(target_repo),
        "--mode",
        "changes",
        "--depth",
        "deep",
        "--base",
        base_ref,
        "--model",
        model,
        "--output-dir",
        str(output_dir),
    ]
    run_cmd(cmd, repo_root_dir)
    return newest_child_dir(output_dir)


def run_public_compare(repo_root_dir: Path, github_repo: str, pr_number: int, source: str, review_file: Path, output_dir: Path) -> Path:
    cmd = [
        sys.executable,
        str(repo_root_dir / "plugins" / "codex-review" / "scripts" / "run_public_pr_quality_cycle.py"),
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
            category_counter[str(finding.get("normalized_category") or "uncategorized")] += 1
            severity_counter[str(finding.get("severity") or "unknown")] += 1
            title_counter[str(finding.get("candidate_title") or "untitled")] += 1
            for phrase in finding.get("suggested_signal_phrases") or []:
                cleaned = " ".join(str(phrase).split())
                if cleaned:
                    anchor_counter[cleaned] += 1

    return {
        "missed_count": len(missed_findings),
        "top_categories": [{"category": key, "count": count} for key, count in category_counter.most_common(10)],
        "top_severities": [{"severity": key, "count": count} for key, count in severity_counter.most_common(10)],
        "repeated_titles": [{"title": key, "count": count} for key, count in title_counter.most_common(10)],
        "repeated_signal_phrases": [{"phrase": key, "count": count} for key, count in anchor_counter.most_common(20)],
    }


def main() -> int:
    args = parse_args()
    root = repo_root(Path.cwd())
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(root)
    output_dir.mkdir(parents=True, exist_ok=True)

    calibration_set = load_json((root / args.calibration_set).resolve() if not Path(args.calibration_set).is_absolute() else Path(args.calibration_set))
    if not isinstance(calibration_set, list):
        raise ValueError("Calibration set must be a JSON list.")
    entries = calibration_set[: args.limit] if args.limit else calibration_set

    clones_root = output_dir / "repos"
    reviews_root = output_dir / "reviews"
    comparisons_root = output_dir / "comparisons"

    results: list[dict[str, Any]] = []
    comparison_files: list[Path] = []

    for entry in entries:
        github_repo = str(entry["repo"])
        pr_number = int(entry["pr"])
        source = str(entry.get("source") or "rest")
        label = safe_label(entry)

        repo_dir = ensure_repo_clone(clones_root, github_repo)
        metadata = pr_metadata(repo_dir, github_repo, pr_number)
        checkout_pr(repo_dir, pr_number)
        base_ref = f"origin/{metadata['baseRefName']}"

        review_parent = reviews_root / label
        existing_review_run = None
        if args.resume and review_parent.is_dir():
            try:
                existing_review_run = newest_child_dir(review_parent)
                if not review_run_is_complete(existing_review_run):
                    existing_review_run = None
            except FileNotFoundError:
                existing_review_run = None
        review_run_dir = existing_review_run or run_review(root, repo_dir, base_ref, review_parent, args.model)
        review_file = review_run_dir / "review.md"

        comparison_parent = comparisons_root / label
        comparison_file = comparison_parent / "quality-comparison" / "quality-comparison.json"
        if not (args.resume and comparison_file.is_file()):
            comparison_file = run_public_compare(root, github_repo, pr_number, source, review_file, comparison_parent)
        comparison_files.append(comparison_file)
        comparison_payload = load_json(comparison_file)

        results.append(
            {
                "label": label,
                "repo": github_repo,
                "pr": pr_number,
                "base_ref": base_ref,
                "review_run_dir": str(review_run_dir),
                "review_file": str(review_file),
                "comparison_file": str(comparison_file),
                "summary": comparison_payload.get("summary") or {},
            }
        )

    aggregate = {
        "schema_version": "codex-review.public-coderabbit-calibration.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "results": results,
        "miss_clusters": cluster_misses(comparison_files),
    }
    write_json(output_dir / "aggregate-summary.json", aggregate)
    print(f"Public CodeRabbit calibration run: {output_dir}")
    print(f"Aggregate summary: {output_dir / 'aggregate-summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
