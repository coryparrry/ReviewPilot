import argparse
import json
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_SEVERITIES = {"critical", "high", "medium", "low"}
DEFAULT_CORPUS_PATH = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/review-corpus-cases.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply corpus-candidate artifacts into the curated review corpus."
    )
    parser.add_argument("--input", required=True, help="Path to a corpus-candidate JSON file.")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "review", "force"],
        help="Apply mode. Defaults to auto.",
    )
    parser.add_argument(
        "--corpus",
        help="Path to the target corpus JSON file. Defaults to the bundled review corpus.",
    )
    parser.add_argument(
        "--result-output",
        help="Path to the apply result artifact. Defaults to artifacts/github-intake/<timestamp>-apply-result.json",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing apply-result artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def default_result_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-apply-result.json"


def resolve_result_output_path(repo_root: Path, output_path: str | None, allow_outside_artifacts: bool) -> Path:
    artifacts_root = (repo_root / "artifacts" / "github-intake").resolve()
    if output_path is None:
        return default_result_output_path(repo_root)

    candidate = Path(output_path).resolve()
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write apply-result artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def resolve_corpus_path(repo_root: Path, requested_path: str | None) -> Path:
    if requested_path:
        return Path(requested_path).resolve()
    return (repo_root / DEFAULT_CORPUS_PATH).resolve()


def require_candidate_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Corpus-candidate artifact must contain a top-level 'candidates' list.")
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def require_corpus_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Target corpus must be a JSON array.")
    corpus: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("Target corpus entries must be JSON objects.")
        corpus.append(entry)
    return corpus


def validate_expected_groups(expected_groups: Any) -> bool:
    if not isinstance(expected_groups, list) or not expected_groups:
        return False
    cleaned_groups = 0
    for group in expected_groups:
        if not isinstance(group, list):
            return False
        cleaned = [token for token in group if isinstance(token, str) and token.strip()]
        if cleaned:
            cleaned_groups += 1
    return cleaned_groups > 0


def normalize_expected_groups(expected_groups: Any) -> list[list[str]]:
    normalized: list[list[str]] = []
    if not isinstance(expected_groups, list):
        return normalized
    for group in expected_groups:
        if not isinstance(group, list):
            continue
        cleaned = [token.strip() for token in group if isinstance(token, str) and token.strip()]
        if cleaned:
            normalized.append(cleaned)
    return normalized


def corpus_fingerprint(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        entry.get("title"),
        entry.get("severity"),
        entry.get("category"),
        entry.get("source"),
        tuple(tuple(group) for group in normalize_expected_groups(entry.get("expected_groups"))),
    )


def normalize_title(value: str) -> str:
    return " ".join(token for token in value.lower().split() if token)


def expectation_tokens(expected_groups: Any) -> set[str]:
    tokens: set[str] = set()
    if not isinstance(expected_groups, list):
        return tokens
    for group in expected_groups:
        if not isinstance(group, list):
            continue
        for token in group:
            if not isinstance(token, str):
                continue
            for word in "".join(ch if ch.isalnum() else " " for ch in token.lower()).split():
                if len(word) >= 4:
                    tokens.add(word)
    return tokens


def token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def has_near_duplicate(candidate: dict[str, Any], corpus: list[dict[str, Any]]) -> bool:
    candidate_category = candidate.get("category")
    candidate_title = normalize_title(str(candidate.get("title", "")))
    candidate_tokens = expectation_tokens(candidate.get("expected_groups"))

    for entry in corpus:
        if entry.get("category") != candidate_category:
            continue
        title_similarity = SequenceMatcher(
            None, candidate_title, normalize_title(str(entry.get("title", "")))
        ).ratio()
        overlap = token_overlap(candidate_tokens, expectation_tokens(entry.get("expected_groups")))
        if title_similarity >= 0.88 or overlap >= 0.75:
            return True
    return False


def soft_warnings(candidate: dict[str, Any], existing_title_keys: set[tuple[str, str]], corpus: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    review_notes = candidate.get("review_notes")
    approved_for_auto = False
    if isinstance(review_notes, dict):
        approved_for_auto = review_notes.get("approved_for_auto") is True
        if review_notes.get("needs_human_review") is not False and not approved_for_auto:
            warnings.append("needs-human-review")
        confidence = review_notes.get("confidence")
        if confidence != "high" and not approved_for_auto:
            warnings.append("non-high-confidence")
        file_path = review_notes.get("file_path")
        if isinstance(file_path, str):
            normalized_path = file_path.replace("\\", "/").lower()
            if (
                not approved_for_auto
                and (
                    normalized_path.endswith(".test.ts")
                    or normalized_path.endswith(".test.tsx")
                    or "/test/" in normalized_path
                )
            ):
                warnings.append("test-only-surface")
        body = review_notes.get("body")
        if isinstance(body, str) and "addressed in commit" in body.lower():
            warnings.append("already-addressed-upstream")

    if candidate.get("severity") != "critical" and not approved_for_auto:
        warnings.append("non-critical-severity")

    title = candidate.get("title")
    category = candidate.get("category")
    if isinstance(title, str) and isinstance(category, str):
        title_key = (category, title.strip().lower())
        if title_key in existing_title_keys:
            warnings.append("similar-title-category-exists")
    if has_near_duplicate(candidate, corpus):
        warnings.append("near-duplicate-corpus-match")

    return warnings


def hard_blockers(candidate: dict[str, Any], existing_ids: set[str], batch_ids: set[str]) -> list[str]:
    blockers: list[str] = []
    candidate_id = candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        blockers.append("missing-id")
    elif candidate_id in existing_ids:
        blockers.append("duplicate-id-in-corpus")
    elif candidate_id in batch_ids:
        blockers.append("duplicate-id-in-batch")

    if not isinstance(candidate.get("title"), str) or not candidate["title"].strip():
        blockers.append("missing-title")
    if candidate.get("severity") not in ALLOWED_SEVERITIES:
        blockers.append("invalid-severity")
    category = candidate.get("category")
    if not isinstance(category, str) or not category.strip() or category == "uncategorized":
        blockers.append("invalid-category")
    source = candidate.get("source")
    if not isinstance(source, str) or not source.strip():
        blockers.append("missing-source")
    if not validate_expected_groups(candidate.get("expected_groups")):
        blockers.append("invalid-expected-groups")
    return blockers


def to_corpus_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "title": candidate["title"],
        "severity": candidate["severity"],
        "category": candidate["category"],
        "source": candidate["source"],
        "expected_groups": candidate["expected_groups"],
    }


def build_result(
    input_path: Path,
    corpus_path: Path,
    mode: str,
    applied: list[dict[str, Any]],
    pending_review: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "codex-review.github-corpus-apply-result.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_file": input_path.name,
        "corpus_file": corpus_path.name,
        "mode": mode,
        "applied": applied,
        "pending_review": pending_review,
        "blocked": blocked,
    }


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    input_path = Path(args.input).resolve()
    corpus_path = resolve_corpus_path(repo_root, args.corpus)
    result_output_path = resolve_result_output_path(repo_root, args.result_output, args.allow_outside_artifacts)

    candidate_payload = load_json(input_path)
    candidates = require_candidate_list(candidate_payload)
    corpus = require_corpus_list(load_json(corpus_path))

    existing_ids = {entry.get("id") for entry in corpus if isinstance(entry.get("id"), str)}
    existing_by_id = {
        entry["id"]: entry for entry in corpus if isinstance(entry.get("id"), str)
    }
    existing_fingerprints = {corpus_fingerprint(entry) for entry in corpus}
    existing_title_keys = {
        (entry.get("category"), str(entry.get("title", "")).strip().lower())
        for entry in corpus
        if isinstance(entry.get("category"), str) and isinstance(entry.get("title"), str)
    }

    batch_ids: set[str] = set()
    new_entries: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    pending_review: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for candidate in candidates:
        candidate_entry = to_corpus_entry(candidate) if not hard_blockers(candidate, set(), set()) else None
        candidate_fingerprint = corpus_fingerprint(candidate_entry) if candidate_entry is not None else None
        summary = {
            "id": candidate.get("id"),
            "title": candidate.get("title"),
            "severity": candidate.get("severity"),
            "category": candidate.get("category"),
            "warnings": [],
        }

        if candidate_entry is not None and candidate_fingerprint in existing_fingerprints:
            pending_review.append({**summary, "reasons": ["already-present"]})
            continue

        blockers = hard_blockers(candidate, existing_ids, batch_ids)
        warnings = soft_warnings(candidate, existing_title_keys, corpus)
        candidate_id = candidate.get("id")
        existing_entry = existing_by_id.get(candidate_id) if isinstance(candidate_id, str) else None
        if existing_entry is not None:
            if corpus_fingerprint(existing_entry) == candidate_fingerprint:
                pending_review.append({**summary, "reasons": ["already-present"]})
                continue
            blockers = [reason for reason in blockers if reason != "duplicate-id-in-corpus"]
            blockers.append("conflicting-id-in-corpus")

        if isinstance(candidate_id, str) and candidate_id not in existing_ids:
            batch_ids.add(candidate_id)

        summary["warnings"] = warnings

        if blockers:
            blocked.append({**summary, "reasons": blockers})
            continue

        if args.mode == "review":
            pending_review.append({**summary, "reasons": ["review-requested"]})
            continue

        if args.mode == "auto" and warnings:
            pending_review.append({**summary, "reasons": warnings})
            continue

        new_entry = candidate_entry or to_corpus_entry(candidate)
        new_entries.append(new_entry)
        applied.append(summary)
        existing_ids.add(candidate["id"])
        existing_by_id[candidate["id"]] = new_entry
        existing_fingerprints.add(corpus_fingerprint(new_entry))
        existing_title_keys.add((candidate["category"], candidate["title"].strip().lower()))

    if args.mode != "review" and new_entries:
        corpus.extend(new_entries)
        write_json(corpus_path, corpus)

    result = build_result(input_path, corpus_path, args.mode, applied, pending_review, blocked)
    write_json(result_output_path, result)

    print(f"Mode: {args.mode}")
    print(f"Corpus: {corpus_path}")
    print(f"Applied: {len(applied)}")
    print(f"Pending review: {len(pending_review)}")
    print(f"Blocked: {len(blocked)}")
    print(f"Wrote apply result: {result_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
