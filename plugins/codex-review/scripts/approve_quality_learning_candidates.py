import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Approve comparison-identified corpus-gap misses for probationary auto-learning by annotating the"
            " matching candidate rows with a tight learning gate."
        )
    )
    parser.add_argument("--candidates", required=True, help="Path to a corpus-candidate artifact.")
    parser.add_argument("--comparison", required=True, help="Path to a quality-comparison JSON artifact.")
    parser.add_argument(
        "--output",
        help="Optional output path. Defaults to artifacts/github-intake/<timestamp>-quality-learning-candidates.json",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing outside the repo's ignored artifacts tree.",
    )
    return parser.parse_args()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_path(repo_root: Path, requested: str) -> Path:
    candidate = Path(requested)
    return candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()


def default_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-quality-learning-candidates.json"


def resolve_output_path(repo_root: Path, requested: str | None, allow_outside_artifacts: bool) -> Path:
    artifacts_root = (repo_root / "artifacts").resolve()
    if requested is None:
        return default_output_path(repo_root)

    candidate = Path(requested).resolve()
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write quality-learning artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_root = repo_root_from_script()
    candidates_path = resolve_path(repo_root, args.candidates)
    comparison_path = resolve_path(repo_root, args.comparison)
    output_path = resolve_output_path(repo_root, args.output, args.allow_outside_artifacts)

    candidate_payload = load_json(candidates_path)
    comparison_payload = load_json(comparison_path)

    candidates = candidate_payload.get("candidates")
    findings = comparison_payload.get("findings")
    approved_ids = set(comparison_payload.get("recommended_probationary_candidates") or [])

    if not isinstance(candidates, list):
        raise ValueError("Candidate artifact must contain a top-level candidates list.")
    if not isinstance(findings, list):
        raise ValueError("Quality comparison artifact must contain a top-level findings list.")

    finding_by_id = {
        str(finding.get("candidate_id")): finding
        for finding in findings
        if isinstance(finding, dict) and finding.get("candidate_id")
    }

    approved_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("id") or "")
        if candidate_id not in approved_ids:
            continue
        finding = finding_by_id.get(candidate_id)
        if not isinstance(finding, dict):
            continue
        if finding.get("gap_classification") != "corpus-gap":
            continue
        if finding.get("represented_in_corpus") is not False:
            continue
        if finding.get("represented_in_calibration") is not False:
            continue

        review_match = finding.get("review_match") or {}
        if review_match.get("matched") is not False:
            continue
        expectation_overlap = float(review_match.get("expectation_overlap") or 0.0)
        title_overlap = float(review_match.get("title_overlap") or 0.0)
        if expectation_overlap >= 0.35 or title_overlap >= 0.35:
            continue

        severity = str(candidate.get("severity") or "").lower()
        if severity not in {"critical", "high", "medium"}:
            continue

        updated = dict(candidate)
        review_notes = dict(candidate.get("review_notes") or {})
        review_notes["needs_human_review"] = False
        review_notes["confidence"] = "high"
        review_notes["approved_for_auto"] = True
        review_notes["learning_gate"] = {
            "type": "quality-comparison-corpus-gap",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "comparison_file": str(comparison_path),
            "comment_id": finding.get("comment_id"),
            "gap_classification": finding.get("gap_classification"),
            "review_match": finding.get("review_match"),
        }
        updated["review_notes"] = review_notes
        approved_candidates.append(updated)

    output = {
        "schema_version": "codex-review.quality-learning-candidates.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_candidates_file": str(candidates_path),
        "source_comparison_file": str(comparison_path),
        "approved_ids": [candidate.get("id") for candidate in approved_candidates],
        "candidates": approved_candidates,
    }
    write_json(output_path, output)

    print(f"Quality learning candidates: {output_path}")
    print(f"Approved candidates: {len(approved_candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
