import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_SEVERITIES = {"critical", "high", "medium", "low"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Turn normalized GitHub intake proposal records into reviewed corpus-candidate output."
    )
    parser.add_argument("--input", required=True, help="Path to a normalized proposal artifact JSON file.")
    parser.add_argument(
        "--output",
        help="Path to candidate output. Defaults to artifacts/github-intake/<timestamp>-corpus-candidates.json",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing corpus-candidate artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def load_input(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def default_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-corpus-candidates.json"


def resolve_output_path(repo_root: Path, output_path: str | None, allow_outside_artifacts: bool) -> Path:
    artifacts_root = (repo_root / "artifacts" / "github-intake").resolve()
    if output_path is None:
        return default_output_path(repo_root)

    candidate = Path(output_path).resolve()
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write candidate artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or "candidate"


def derive_title(record: dict[str, Any]) -> str:
    expectations = record.get("candidate_expectations") or []
    if expectations:
        first = str(expectations[0]).strip()
        return first[:100]
    body = str(record.get("body", "")).strip()
    return body[:100] if body else "Review feedback candidate"


def derive_expected_groups(record: dict[str, Any]) -> list[list[str]]:
    expectations = record.get("candidate_expectations") or []
    if not expectations:
        body = str(record.get("body", "")).strip()
        if not body:
            return []
        expectations = [body[:120]]

    group: list[str] = []
    for expectation in expectations[:3]:
        cleaned = " ".join(str(expectation).split())
        if len(cleaned) < 4:
            continue
        group.append(re.escape(cleaned))

    return [group] if group else []


def build_source_ref(proposal: dict[str, Any], record: dict[str, Any]) -> str:
    repo = record.get("repo") or "unknown"
    pr_number = record.get("pr_number")
    review_id = record.get("review_id")
    comment_id = record.get("comment_id")
    source_file = proposal.get("source_file") or "unknown"
    return (
        f"{repo}#PR{pr_number}/review-{review_id}/comment-{comment_id}"
        if pr_number and review_id and comment_id
        else f"{repo}:{source_file}"
    )


def should_skip(record: dict[str, Any]) -> str | None:
    if record.get("normalized_category") == "uncategorized":
        return "uncategorized"
    if record.get("severity") not in ALLOWED_SEVERITIES:
        return "unknown-severity"
    if not record.get("candidate_expectations"):
        return "missing-expectations"
    return None


def build_candidate(proposal: dict[str, Any], record: dict[str, Any], index: int) -> dict[str, Any]:
    title = derive_title(record)
    category = str(record["normalized_category"])
    severity = str(record["severity"])
    candidate_id = f"{category}-{slugify(title)}-{index + 1}"
    return {
        "id": candidate_id,
        "title": title,
        "severity": severity,
        "category": category,
        "source": build_source_ref(proposal, record),
        "expected_groups": derive_expected_groups(record),
        "review_notes": {
            "needs_human_review": record.get("needs_human_review", True),
            "confidence": record.get("confidence"),
            "file_path": record.get("file_path"),
            "line": record.get("line"),
            "body": record.get("body"),
            "notes": record.get("notes"),
        },
    }


def build_output(proposal: dict[str, Any]) -> dict[str, Any]:
    records = proposal.get("records", [])
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        reason = should_skip(record)
        if reason:
            skipped.append(
                {
                    "reason": reason,
                    "record": {
                        "repo": record.get("repo"),
                        "pr_number": record.get("pr_number"),
                        "review_id": record.get("review_id"),
                        "comment_id": record.get("comment_id"),
                        "normalized_category": record.get("normalized_category"),
                        "severity": record.get("severity"),
                        "body": record.get("body"),
                    },
                }
            )
            continue
        candidates.append(build_candidate(proposal, record, len(candidates)))

    return {
        "schema_version": "codex-review.github-corpus-candidates.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposal_source_file": proposal.get("source_file"),
        "proposal_source_format": proposal.get("source_format"),
        "candidates": candidates,
        "skipped": skipped,
    }


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    input_path = Path(args.input).resolve()
    proposal = load_input(input_path)
    output = build_output(proposal)
    output_path = resolve_output_path(repo_root, args.output, args.allow_outside_artifacts)
    write_output(output_path, output)
    print(f"Wrote corpus candidates: {output_path}")
    print(f"Candidates: {len(output['candidates'])}")
    print(f"Skipped: {len(output['skipped'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
