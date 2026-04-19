import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote reviewed corpus candidates into auto-eligible candidates."
    )
    parser.add_argument("--input", required=True, help="Path to a corpus-candidate JSON file.")
    parser.add_argument(
        "--output",
        help="Path to promoted candidate output. Defaults to artifacts/github-intake/<timestamp>-promoted-candidates.json",
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        default=[],
        help="Candidate ids to promote. Omit only when using --all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Promote all candidates in the input artifact.",
    )
    parser.add_argument(
        "--reviewer",
        default="local-review",
        help="Reviewer label to stamp into promotion metadata.",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional short promotion note.",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing promoted candidate artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def default_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-promoted-candidates.json"


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
            f"Refusing to write promoted candidate artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def require_candidate_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Corpus-candidate artifact must contain a top-level 'candidates' list.")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"Candidate at index {index} is not a JSON object.")
    return candidates


def promote_candidate(candidate: dict[str, Any], reviewer: str, note: str) -> dict[str, Any]:
    promoted = dict(candidate)
    review_notes = dict(candidate.get("review_notes") or {})
    review_notes["needs_human_review"] = False
    review_notes["confidence"] = "high"
    review_notes["approved_for_auto"] = True
    review_notes["promotion"] = {
        "reviewed_by": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    promoted["review_notes"] = review_notes
    return promoted


def main() -> int:
    args = parse_args()
    if not args.all and not args.ids:
        raise ValueError("Pass --all or at least one candidate id via --ids.")

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    input_path = Path(args.input).resolve()
    output_path = resolve_output_path(repo_root, args.output, args.allow_outside_artifacts)

    payload = load_json(input_path)
    candidates = require_candidate_list(payload)
    selected_ids = {candidate_id.strip() for candidate_id in args.ids if candidate_id.strip()}

    promoted_candidates: list[dict[str, Any]] = []
    promoted_ids: list[str] = []
    untouched_ids: list[str] = []

    for candidate in candidates:
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, str):
            untouched_ids.append("<missing-id>")
            promoted_candidates.append(candidate)
            continue

        if args.all or candidate_id in selected_ids:
            promoted_candidates.append(promote_candidate(candidate, args.reviewer, args.note))
            promoted_ids.append(candidate_id)
        else:
            promoted_candidates.append(candidate)
            untouched_ids.append(candidate_id)

    output = dict(payload)
    output["schema_version"] = "codex-review.github-corpus-candidates.v1"
    output["promotion_metadata"] = {
        "reviewed_by": args.reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "note": args.note,
        "promoted_ids": promoted_ids,
        "untouched_ids": untouched_ids,
    }
    output["candidates"] = promoted_candidates

    write_json(output_path, output)
    print(f"Wrote promoted candidates: {output_path}")
    print(f"Promoted: {len(promoted_ids)}")
    print(f"Untouched: {len(untouched_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
