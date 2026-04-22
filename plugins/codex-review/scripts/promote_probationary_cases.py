import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DEFAULT_PRIMARY_CORPUS = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/review-corpus-cases.json"
)
DEFAULT_PROBATIONARY_CORPUS = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/probationary-review-cases.json"
)


@dataclass
class EvidenceMatch:
    file: str
    strict_match: bool
    title_overlap: float
    expectation_overlap: float

    @property
    def matched(self) -> bool:
        return (
            self.strict_match
            or self.title_overlap >= 0.6
            or self.expectation_overlap >= 0.45
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Promote probationary review cases into the durable primary corpus only when repeated "
            "review-artifact evidence supports the move."
        )
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        default=[],
        help="Probationary case ids to evaluate. Omit only when using --all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every case in the probationary corpus.",
    )
    parser.add_argument(
        "--review-file",
        action="append",
        default=[],
        help="Path to a review artifact file. Repeat for multiple review artifacts.",
    )
    parser.add_argument(
        "--review-artifacts",
        action="append",
        default=[],
        help=(
            "Prepared review run directory or parent .codex-review directory. Repeat for multiple "
            "artifact roots. If a parent directory is given, all child runs containing review.md are used."
        ),
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "review", "force"],
        help="Promotion mode. Defaults to auto.",
    )
    parser.add_argument(
        "--min-matches",
        type=int,
        default=2,
        help="Minimum number of distinct review artifacts that must hit the case. Defaults to 2.",
    )
    parser.add_argument(
        "--min-strict-matches",
        type=int,
        default=1,
        help="Minimum number of strict expected-group matches required. Defaults to 1.",
    )
    parser.add_argument(
        "--primary-corpus",
        default=str(DEFAULT_PRIMARY_CORPUS),
        help="Path to the durable primary corpus.",
    )
    parser.add_argument(
        "--probationary-corpus",
        default=str(DEFAULT_PROBATIONARY_CORPUS),
        help="Path to the probationary corpus.",
    )
    parser.add_argument(
        "--result-output",
        help="Path to the promotion result artifact. Defaults to artifacts/github-intake/<timestamp>-promotion-result.json",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing promotion artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_path(repo_root: Path, requested: str) -> Path:
    candidate = Path(requested)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (repo_root / candidate).resolve()
    )


def default_result_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        repo_root / "artifacts" / "github-intake" / f"{timestamp}-promotion-result.json"
    )


def resolve_result_output_path(
    repo_root: Path, output_path: str | None, allow_outside_artifacts: bool
) -> Path:
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
            f"Refusing to write promotion artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def require_corpus_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Corpus file must contain a JSON array.")
    return [entry for entry in payload if isinstance(entry, dict)]


def normalize_expected_groups(expected_groups: Any) -> list[list[str]]:
    normalized: list[list[str]] = []
    if not isinstance(expected_groups, list):
        return normalized
    for group in expected_groups:
        if not isinstance(group, list):
            continue
        cleaned = [
            token.strip() for token in group if isinstance(token, str) and token.strip()
        ]
        if cleaned:
            normalized.append(cleaned)
    return normalized


def corpus_fingerprint(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        entry.get("title"),
        entry.get("severity"),
        entry.get("category"),
        tuple(
            tuple(group)
            for group in normalize_expected_groups(entry.get("expected_groups"))
        ),
    )


def normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def title_tokens(title: str) -> set[str]:
    return set(normalize_title(title).split())


def expectation_tokens(entry: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for group in normalize_expected_groups(entry.get("expected_groups")):
        for pattern in group:
            for token in re.findall(r"[a-zA-Z0-9]{4,}", pattern.lower()):
                tokens.add(token)
    return tokens


def review_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{4,}", text.lower())}


def token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def match_group(text: str, group: list[str]) -> bool:
    return all(
        re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        for pattern in group
    )


def strict_match(text: str, case: dict[str, Any]) -> bool:
    return any(
        match_group(text, group)
        for group in normalize_expected_groups(case.get("expected_groups"))
    )


def has_near_duplicate(
    candidate: dict[str, Any], primary_corpus: list[dict[str, Any]]
) -> bool:
    candidate_title = normalize_title(str(candidate.get("title", "")))
    candidate_tokens = expectation_tokens(candidate)
    candidate_category = candidate.get("category")

    for entry in primary_corpus:
        if entry.get("category") != candidate_category:
            continue
        title_similarity = SequenceMatcher(
            None, candidate_title, normalize_title(str(entry.get("title", "")))
        ).ratio()
        overlap = token_overlap(candidate_tokens, expectation_tokens(entry))
        if title_similarity >= 0.88 or overlap >= 0.75:
            return True
    return False


def collect_review_files(
    review_files: list[str], review_artifacts: list[str]
) -> list[Path]:
    collected: dict[str, Path] = {}
    for review_file in review_files:
        path = Path(review_file).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Review artifact file does not exist: {path}")
        collected[str(path)] = path

    for artifact_root in review_artifacts:
        path = Path(artifact_root).resolve()
        if path.is_file():
            collected[str(path)] = path
            continue
        if not path.is_dir():
            raise FileNotFoundError(f"Review artifact path does not exist: {path}")
        direct_review = path / "review.md"
        if direct_review.is_file():
            collected[str(direct_review)] = direct_review
            continue
        for child in sorted(path.iterdir()):
            review_md = child / "review.md"
            if child.is_dir() and review_md.is_file():
                collected[str(review_md.resolve())] = review_md.resolve()

    if not collected:
        raise ValueError("Pass at least one --review-file or --review-artifacts path.")
    return list(collected.values())


def evaluate_case_against_reviews(
    case: dict[str, Any], review_files: list[Path]
) -> list[EvidenceMatch]:
    matches: list[EvidenceMatch] = []
    case_title_tokens = title_tokens(str(case.get("title", "")))
    case_expectation_tokens = expectation_tokens(case)
    for review_file in review_files:
        text = review_file.read_text(encoding="utf-8")
        review_token_set = review_tokens(text)
        title_overlap = round(token_overlap(case_title_tokens, review_token_set), 3)
        expectation_overlap = round(
            token_overlap(case_expectation_tokens, review_token_set), 3
        )
        matches.append(
            EvidenceMatch(
                file=review_file.name,
                strict_match=strict_match(text, case),
                title_overlap=title_overlap,
                expectation_overlap=expectation_overlap,
            )
        )
    return matches


def build_result(
    mode: str,
    primary_corpus: Path,
    probationary_corpus: Path,
    promoted: list[dict[str, Any]],
    pending_review: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "codex-review.probationary-promotion-result.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "primary_corpus_file": primary_corpus.name,
        "probationary_corpus_file": probationary_corpus.name,
        "promoted": promoted,
        "pending_review": pending_review,
        "blocked": blocked,
    }


def main() -> int:
    args = parse_args()
    if not args.all and not args.ids:
        raise ValueError("Pass --all or at least one probationary case id via --ids.")

    repo_root = repo_root_from_script()
    primary_corpus_path = resolve_path(repo_root, args.primary_corpus)
    probationary_corpus_path = resolve_path(repo_root, args.probationary_corpus)
    result_output_path = resolve_result_output_path(
        repo_root, args.result_output, args.allow_outside_artifacts
    )
    review_files = collect_review_files(args.review_file, args.review_artifacts)

    primary_corpus = require_corpus_list(load_json(primary_corpus_path))
    probationary_corpus = require_corpus_list(load_json(probationary_corpus_path))

    probationary_by_id = {
        entry["id"]: entry
        for entry in probationary_corpus
        if isinstance(entry.get("id"), str)
    }
    primary_by_id = {
        entry["id"]: entry
        for entry in primary_corpus
        if isinstance(entry.get("id"), str)
    }
    primary_fingerprints = {corpus_fingerprint(entry) for entry in primary_corpus}

    selected_ids = (
        sorted(probationary_by_id)
        if args.all
        else [case_id for case_id in args.ids if case_id.strip()]
    )

    promoted: list[dict[str, Any]] = []
    pending_review: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    promoted_ids: list[str] = []

    for case_id in selected_ids:
        case = probationary_by_id.get(case_id)
        summary = {"id": case_id, "warnings": [], "evidence": []}
        if case is None:
            blocked.append({**summary, "reasons": ["missing-from-probationary-corpus"]})
            continue

        fingerprint = corpus_fingerprint(case)
        existing_primary = primary_by_id.get(case_id)
        if existing_primary is not None:
            if corpus_fingerprint(existing_primary) == fingerprint:
                blocked.append({**summary, "reasons": ["already-present-in-primary"]})
            else:
                blocked.append({**summary, "reasons": ["conflicting-id-in-primary"]})
            continue

        if fingerprint in primary_fingerprints:
            blocked.append({**summary, "reasons": ["exact-duplicate-in-primary"]})
            continue

        evidence = evaluate_case_against_reviews(case, review_files)
        strict_matches = sum(1 for item in evidence if item.strict_match)
        matched_reviews = sum(1 for item in evidence if item.matched)
        summary["evidence"] = [
            item.__dict__ | {"matched": item.matched} for item in evidence
        ]

        warnings: list[str] = []
        if matched_reviews < args.min_matches:
            warnings.append("insufficient-evidence-matches")
        if strict_matches < args.min_strict_matches:
            warnings.append("insufficient-strict-matches")
        if has_near_duplicate(case, primary_corpus):
            warnings.append("near-duplicate-primary-match")

        summary["warnings"] = warnings

        if args.mode == "review":
            pending_review.append({**summary, "reasons": ["review-requested"]})
            continue

        if args.mode == "auto" and warnings:
            pending_review.append({**summary, "reasons": warnings})
            continue

        promoted.append(
            {
                **summary,
                "title": case.get("title"),
                "severity": case.get("severity"),
                "category": case.get("category"),
                "reasons": ["promotion-approved"] if not warnings else warnings,
            }
        )
        promoted_ids.append(case_id)

    if args.mode != "review" and promoted_ids:
        remaining_probationary = [
            entry
            for entry in probationary_corpus
            if str(entry.get("id", "")) not in set(promoted_ids)
        ]
        promoted_entries = [probationary_by_id[case_id] for case_id in promoted_ids]
        primary_corpus.extend(promoted_entries)
        write_json(primary_corpus_path, primary_corpus)
        write_json(probationary_corpus_path, remaining_probationary)

    result = build_result(
        mode=args.mode,
        primary_corpus=primary_corpus_path,
        probationary_corpus=probationary_corpus_path,
        promoted=promoted,
        pending_review=pending_review,
        blocked=blocked,
    )
    write_json(result_output_path, result)

    print(f"Mode: {args.mode}")
    print(f"Primary corpus: {primary_corpus_path}")
    print(f"Probationary corpus: {probationary_corpus_path}")
    print(f"Promoted: {len(promoted)}")
    print(f"Pending review: {len(pending_review)}")
    print(f"Blocked: {len(blocked)}")
    print(f"Wrote promotion result: {result_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
