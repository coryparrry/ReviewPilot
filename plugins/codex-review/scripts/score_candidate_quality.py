import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


SKILL_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "bug-hunting-code-review" / "scripts"
if str(SKILL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

from review_corpus_score import SEVERITY_WEIGHTS, score_case, summarize


DEFAULT_PRIMARY_CORPUS = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/review-corpus-cases.json"
)
DEFAULT_PROBATIONARY_CORPUS = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/probationary-review-cases.json"
)
DEFAULT_EXTERNAL_CORPUS = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/swebench-verified-review-cases.json"
)


@dataclass
class NearDuplicate:
    corpus: str
    existing_id: str
    title_similarity: float
    token_overlap: float


@dataclass
class AdmissionMatch:
    matched: bool
    strict_match: bool
    title_overlap: float
    expectation_overlap: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score GitHub-derived corpus candidates for probationary admission using duplicate checks "
            "and review-artifact benchmark evidence."
        )
    )
    parser.add_argument("--input", required=True, help="Path to a corpus-candidate JSON file.")
    parser.add_argument("--review-file", help="Path to a review output file.")
    parser.add_argument("--review-text", help="Inline review text.")
    parser.add_argument(
        "--primary-corpus",
        default=str(DEFAULT_PRIMARY_CORPUS),
        help="Path to the primary GitHub review corpus.",
    )
    parser.add_argument(
        "--probationary-corpus",
        default=str(DEFAULT_PROBATIONARY_CORPUS),
        help="Path to the probationary GitHub review corpus.",
    )
    parser.add_argument(
        "--external-corpus",
        default=str(DEFAULT_EXTERNAL_CORPUS),
        help="Path to the external SWE-bench review corpus.",
    )
    parser.add_argument(
        "--output",
        help="Path to the quality-gate result artifact. Defaults to artifacts/github-intake/<timestamp>-candidate-quality.json",
    )
    parser.add_argument(
        "--filtered-output",
        help="Optional path to a filtered candidate artifact containing only gate-approved probationary candidates.",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing gate artifacts outside the repo's ignored artifacts/github-intake tree.",
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
    return candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()


def default_output_path(repo_root: Path, suffix: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-{suffix}.json"


def resolve_output_path(repo_root: Path, output_path: str | None, suffix: str, allow_outside_artifacts: bool) -> Path:
    artifacts_root = (repo_root / "artifacts" / "github-intake").resolve()
    if output_path is None:
        return default_output_path(repo_root, suffix)

    candidate = Path(output_path).resolve()
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write candidate-quality artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def read_review_text(args: argparse.Namespace) -> str:
    if args.review_file:
        return Path(args.review_file).read_text(encoding="utf-8")
    if args.review_text is not None:
        return args.review_text
    raise ValueError("Pass --review-file or --review-text.")


def require_candidate_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Corpus-candidate artifact must contain a top-level 'candidates' list.")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"Candidate at index {index} is not a JSON object.")
    return candidates


def require_corpus_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Corpus file must contain a JSON array.")
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ValueError(f"Corpus entry at index {index} is not a JSON object.")
    return payload


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
        tuple(tuple(group) for group in normalize_expected_groups(entry.get("expected_groups"))),
    )


def normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def expectation_tokens(entry: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for group in normalize_expected_groups(entry.get("expected_groups")):
        for pattern in group:
            for token in re.findall(r"[a-zA-Z0-9]{4,}", pattern.lower()):
                tokens.add(token)
    return tokens


def token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def review_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{4,}", text.lower())}


def title_tokens(title: str) -> set[str]:
    return set(normalize_title(title).split())


def admission_match(review_text: str, candidate_entry: dict[str, Any]) -> AdmissionMatch:
    strict_result = score_case(review_text, candidate_entry)
    candidate_title_tokens = title_tokens(str(candidate_entry.get("title", "")))
    candidate_expectation_tokens = expectation_tokens(candidate_entry)
    review_token_set = review_tokens(review_text)
    title_overlap = token_overlap(candidate_title_tokens, review_token_set)
    expectation_overlap = token_overlap(candidate_expectation_tokens, review_token_set)
    matched = strict_result.matched or title_overlap >= 0.6 or expectation_overlap >= 0.45
    return AdmissionMatch(
        matched=matched,
        strict_match=strict_result.matched,
        title_overlap=round(title_overlap, 3),
        expectation_overlap=round(expectation_overlap, 3),
    )


def admission_summary(review_text: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    total_weight = 0
    matched_weight = 0
    matched_cases = 0
    for case in cases:
        severity = str(case.get("severity", "medium")).lower()
        weight = SEVERITY_WEIGHTS.get(severity, 1)
        total_weight += weight
        if admission_match(review_text, case).matched:
            matched_cases += 1
            matched_weight += weight

    return {
        "total_cases": len(cases),
        "matched_cases": matched_cases,
        "total_weight": total_weight,
        "matched_weight": matched_weight,
        "weighted_recall": 0.0 if total_weight == 0 else matched_weight / total_weight,
    }


def near_duplicates(candidate_entry: dict[str, Any], corpus_name: str, corpus: list[dict[str, Any]]) -> list[NearDuplicate]:
    duplicates: list[NearDuplicate] = []
    candidate_title = normalize_title(str(candidate_entry.get("title", "")))
    candidate_tokens = expectation_tokens(candidate_entry)
    candidate_category = candidate_entry.get("category")

    for entry in corpus:
        if entry.get("category") != candidate_category:
            continue
        title_similarity = SequenceMatcher(None, candidate_title, normalize_title(str(entry.get("title", "")))).ratio()
        overlap = token_overlap(candidate_tokens, expectation_tokens(entry))
        if title_similarity >= 0.88 or overlap >= 0.75:
            duplicates.append(
                NearDuplicate(
                    corpus=corpus_name,
                    existing_id=str(entry.get("id", "")),
                    title_similarity=round(title_similarity, 3),
                    token_overlap=round(overlap, 3),
                )
            )
    return duplicates


def to_corpus_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    required = ("id", "title", "severity", "category", "source", "expected_groups")
    missing = [key for key in required if key not in candidate]
    if missing:
        raise ValueError(f"Candidate missing required fields: {missing}")
    return {
        "id": candidate["id"],
        "title": candidate["title"],
        "severity": candidate["severity"],
        "category": candidate["category"],
        "source": candidate["source"],
        "expected_groups": candidate["expected_groups"],
    }


def append_gate_metadata(candidate: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    updated = dict(candidate)
    review_notes = dict(candidate.get("review_notes") or {})
    review_notes["needs_human_review"] = False
    review_notes["confidence"] = "high"
    review_notes["approved_for_auto"] = True
    review_notes["learning_gate"] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "recommendation": evaluation["recommendation"],
        "reasons": evaluation["reasons"],
        "benchmark_delta": evaluation["benchmark_delta"],
        "duplicate_matches": evaluation["duplicate_matches"],
    }
    updated["review_notes"] = review_notes
    return updated


def main() -> int:
    args = parse_args()
    repo_root = repo_root_from_script()
    review_text = read_review_text(args)

    input_path = Path(args.input).resolve()
    output_path = resolve_output_path(repo_root, args.output, "candidate-quality", args.allow_outside_artifacts)
    filtered_output_path = (
        resolve_output_path(repo_root, args.filtered_output, "gate-approved-candidates", args.allow_outside_artifacts)
        if args.filtered_output or args.output is not None
        else default_output_path(repo_root, "gate-approved-candidates")
    )

    candidate_payload = load_json(input_path)
    candidates = require_candidate_list(candidate_payload)

    primary_corpus = require_corpus_list(load_json(resolve_path(repo_root, args.primary_corpus)))
    probationary_corpus = require_corpus_list(load_json(resolve_path(repo_root, args.probationary_corpus)))
    external_corpus = require_corpus_list(load_json(resolve_path(repo_root, args.external_corpus)))

    baseline_combined = summarize([score_case(review_text, case) for case in [*primary_corpus, *probationary_corpus]])
    baseline_admission = admission_summary(review_text, [*primary_corpus, *probationary_corpus])
    baseline_external = summarize([score_case(review_text, case) for case in external_corpus])

    existing_fingerprints = {
        *(corpus_fingerprint(entry) for entry in primary_corpus),
        *(corpus_fingerprint(entry) for entry in probationary_corpus),
    }
    approved_candidates: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []

    for candidate in candidates:
        reasons: list[str] = []
        candidate_entry = to_corpus_entry(candidate)
        fingerprint = corpus_fingerprint(candidate_entry)

        exact_duplicate = fingerprint in existing_fingerprints
        if exact_duplicate:
            reasons.append("exact-duplicate")

        duplicate_matches = [
            *near_duplicates(candidate_entry, "primary", primary_corpus),
            *near_duplicates(candidate_entry, "probationary", probationary_corpus),
        ]
        if duplicate_matches:
            reasons.append("near-duplicate")

        review_notes = candidate.get("review_notes") or {}
        body = str(review_notes.get("body", ""))
        if "addressed in commit" in body.lower():
            reasons.append("already-addressed-upstream")

        strict_candidate_result = score_case(review_text, candidate_entry)
        admission_candidate_result = admission_match(review_text, candidate_entry)
        if not admission_candidate_result.matched:
            reasons.append("review-artifact-does-not-hit-candidate")

        combined_after = summarize(
            [score_case(review_text, case) for case in [*primary_corpus, *probationary_corpus, candidate_entry]]
        )
        admission_after = admission_summary(review_text, [*primary_corpus, *probationary_corpus, candidate_entry])
        benchmark_delta = {
            "strict": {
                "matched_cases_delta": combined_after["matched_cases"] - baseline_combined["matched_cases"],
                "matched_weight_delta": combined_after["matched_weight"] - baseline_combined["matched_weight"],
                "weighted_recall_delta": combined_after["weighted_recall"] - baseline_combined["weighted_recall"],
            },
            "admission": {
                "matched_cases_delta": admission_after["matched_cases"] - baseline_admission["matched_cases"],
                "matched_weight_delta": admission_after["matched_weight"] - baseline_admission["matched_weight"],
                "weighted_recall_delta": admission_after["weighted_recall"] - baseline_admission["weighted_recall"],
            },
        }
        if benchmark_delta["admission"]["matched_cases_delta"] <= 0:
            reasons.append("no-benchmark-improvement")

        recommendation = "probationary" if not reasons else "hold"
        evaluation = {
            "id": candidate.get("id"),
            "title": candidate.get("title"),
            "recommendation": recommendation,
            "reasons": reasons,
            "matched_group": strict_candidate_result.matched_group,
            "admission_match": admission_candidate_result.__dict__,
            "benchmark_delta": benchmark_delta,
            "duplicate_matches": [duplicate.__dict__ for duplicate in duplicate_matches],
        }
        evaluations.append(evaluation)

        if recommendation == "probationary":
            approved_candidates.append(append_gate_metadata(candidate, evaluation))

    output = {
        "schema_version": "codex-review.candidate-quality.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_file": input_path.name,
        "baseline": {
            "combined_primary_and_probationary": baseline_combined,
            "admission_combined_primary_and_probationary": baseline_admission,
            "external_swebench_verified": baseline_external,
        },
        "approved_ids": [candidate.get("id") for candidate in approved_candidates],
        "held_ids": [evaluation["id"] for evaluation in evaluations if evaluation["recommendation"] != "probationary"],
        "evaluations": evaluations,
    }
    write_json(output_path, output)

    filtered_payload = dict(candidate_payload)
    filtered_payload["candidates"] = approved_candidates
    filtered_payload["quality_gate"] = {
        "result_file": output_path.name,
        "approved_ids": output["approved_ids"],
        "held_ids": output["held_ids"],
    }
    write_json(filtered_output_path, filtered_payload)

    print(f"Wrote candidate quality result: {output_path}")
    print(f"Approved for probationary corpus: {len(approved_candidates)}")
    print(f"Held back: {len(output['held_ids'])}")
    print(f"Wrote filtered candidates: {filtered_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
