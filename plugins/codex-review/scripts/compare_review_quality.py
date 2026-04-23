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
DEFAULT_CALIBRATION_INPUT = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/coderabbit-comment-calibration.json"
)


@dataclass
class CandidateMatch:
    strict_match: bool
    title_overlap: float
    expectation_overlap: float

    @property
    def matched(self) -> bool:
        return (
            self.strict_match
            or self.title_overlap >= 0.6
            or self.expectation_overlap >= 0.45
            or (self.title_overlap >= 0.35 and self.expectation_overlap >= 0.3)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a review artifact against normalized GitHub intake findings and classify caught vs missed issues."
        )
    )
    parser.add_argument(
        "--review-file", required=True, help="Path to a review markdown artifact."
    )
    parser.add_argument(
        "--proposal",
        required=True,
        help="Path to a normalized GitHub intake proposal artifact.",
    )
    parser.add_argument(
        "--candidates",
        help="Optional corpus-candidate artifact generated from the same proposal. Used for stable ids when available.",
    )
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
        "--calibration-input",
        default=str(DEFAULT_CALIBRATION_INPUT),
        help="Path to the accepted/rejected CodeRabbit calibration file.",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to artifacts/review-quality/<timestamp>-<name>.",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing comparison artifacts outside the repo's ignored artifacts tree.",
    )
    parser.add_argument(
        "--bugs-only",
        action="store_true",
        help="Filter obvious typo/comment nit picks and deduplicate near-identical live findings before scoring.",
    )
    return parser.parse_args()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_path(repo_root: Path, requested: str) -> Path:
    candidate = Path(requested)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (repo_root / candidate).resolve()
    )


def default_output_dir(repo_root: Path, proposal_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        repo_root / "artifacts" / "review-quality" / f"{timestamp}-{proposal_path.stem}"
    )


def resolve_output_dir(
    repo_root: Path,
    requested: str | None,
    proposal_path: Path,
    allow_outside_artifacts: bool,
) -> Path:
    artifacts_root = (repo_root / "artifacts").resolve()
    if requested is None:
        return default_output_dir(repo_root, proposal_path)

    candidate = resolve_path(repo_root, requested)
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write review-quality artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def title_tokens(value: str) -> set[str]:
    return set(normalize_title(value).split())


def expectation_tokens(expected_groups: list[list[str]]) -> set[str]:
    tokens: set[str] = set()
    for group in expected_groups:
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


def derive_expected_groups(record: dict[str, Any]) -> list[list[str]]:
    expectations = record.get("candidate_expectations") or []
    group: list[str] = []
    for expectation in expectations[:3]:
        cleaned = " ".join(str(expectation).split())
        if not cleaned:
            continue
        group.append(re.escape(cleaned))
    return [group] if group else []


def compact_expectation_signals(record: dict[str, Any], limit: int = 3) -> list[str]:
    expectations = record.get("candidate_expectations") or []
    if not isinstance(expectations, list):
        return []
    signals: list[str] = []
    for expectation in expectations:
        cleaned = " ".join(str(expectation).split())
        if not cleaned:
            continue
        signals.append(cleaned[:220])
        if len(signals) == limit:
            break
    return signals


def record_text(record: dict[str, Any]) -> str:
    parts: list[str] = [
        str(record.get("candidate_title") or ""),
        str(record.get("candidate_summary") or ""),
    ]
    for expectation in record.get("candidate_expectations") or []:
        parts.append(str(expectation))
    return " ".join(part for part in parts if part)


def similarity_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9_]{4,}", value.lower())}


def is_bug_worthy_record(record: dict[str, Any]) -> bool:
    if bool(record.get("is_low_signal_bug_comment")):
        return False
    combined = record_text(record).lower()
    if not combined.strip():
        return False
    low_signal_markers = [
        "fix typo",
        "minor typos",
        "spelling error",
        "wording",
        "comment contains",
        "grammar",
    ]
    return not any(marker in combined for marker in low_signal_markers)


def records_are_near_duplicates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_file = str(left.get("file_path") or "")
    right_file = str(right.get("file_path") or "")
    left_line = int(left.get("line") or 0)
    right_line = int(right.get("line") or 0)
    same_file = bool(left_file and right_file and left_file == right_file)
    nearby_lines = (
        same_file and left_line and right_line and abs(left_line - right_line) <= 35
    )

    left_tokens = similarity_tokens(record_text(left))
    right_tokens = similarity_tokens(record_text(right))
    overlap = token_overlap(left_tokens, right_tokens)
    title_similarity = SequenceMatcher(
        None,
        normalize_title(str(left.get("candidate_title") or "")),
        normalize_title(str(right.get("candidate_title") or "")),
    ).ratio()

    if nearby_lines and (overlap >= 0.42 or title_similarity >= 0.7):
        return True

    same_category = str(left.get("normalized_category") or "") == str(
        right.get("normalized_category") or ""
    )
    if same_category and overlap >= 0.72:
        return True

    return False


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for record in records:
        if any(records_are_near_duplicates(record, existing) for existing in deduped):
            continue
        deduped.append(record)
    return deduped


def stable_title_key(value: Any) -> str:
    return str(value or "").strip()[:100]


def record_key(record: dict[str, Any]) -> tuple[str, str]:
    return (
        str(record.get("file_path") or ""),
        stable_title_key(record.get("candidate_title")),
    )


def candidate_map(
    candidate_payload: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    mapped: dict[tuple[str, str], dict[str, Any]] = {}
    ambiguous: set[tuple[str, str]] = set()
    for candidate in candidate_payload.get("candidates", []):
        notes = candidate.get("review_notes") if isinstance(candidate, dict) else {}
        if not isinstance(notes, dict):
            notes = {}
        key = (
            str(notes.get("file_path") or ""),
            stable_title_key(candidate.get("title")),
        )
        if key in mapped:
            ambiguous.add(key)
            mapped.pop(key, None)
            continue
        if key not in ambiguous:
            mapped[key] = candidate
    return mapped


def compare_review_to_record(
    review_text: str, record: dict[str, Any]
) -> CandidateMatch:
    review_token_set = review_tokens(review_text)
    title_overlap = token_overlap(
        title_tokens(str(record.get("candidate_title", ""))), review_token_set
    )
    expected_overlap = token_overlap(
        expectation_tokens(derive_expected_groups(record)), review_token_set
    )
    strict_match = (
        all(
            re.search(pattern, review_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for pattern in derive_expected_groups(record)[0]
        )
        if derive_expected_groups(record)
        else False
    )
    return CandidateMatch(
        strict_match=strict_match,
        title_overlap=round(title_overlap, 3),
        expectation_overlap=round(expected_overlap, 3),
    )


def near_duplicate(record: dict[str, Any], corpus: list[dict[str, Any]]) -> bool:
    category = str(record.get("normalized_category", ""))
    record_title = normalize_title(str(record.get("candidate_title", "")))
    record_expectations = expectation_tokens(derive_expected_groups(record))
    for entry in corpus:
        if str(entry.get("category", "")) != category:
            continue
        title_similarity = SequenceMatcher(
            None, record_title, normalize_title(str(entry.get("title", "")))
        ).ratio()
        overlap = token_overlap(
            record_expectations, expectation_tokens(entry.get("expected_groups") or [])
        )
        if title_similarity >= 0.88 or overlap >= 0.75:
            return True
    return False


def calibration_matches(
    record: dict[str, Any], calibration_entries: list[dict[str, Any]]
) -> bool:
    record_title_tokens = title_tokens(str(record.get("candidate_title", "")))
    record_summary_tokens = title_tokens(str(record.get("candidate_summary", "")))
    for entry in calibration_entries:
        if str(entry.get("verdict")) != "accept":
            continue
        entry_tokens = title_tokens(str(entry.get("summary", "")))
        if token_overlap(record_title_tokens, entry_tokens) >= 0.6:
            return True
        if token_overlap(record_summary_tokens, entry_tokens) >= 0.6:
            return True
    return False


def classify_gap(
    record: dict[str, Any], matched: bool, corpus_match: bool, calibration_match: bool
) -> str:
    if matched:
        return "caught"
    if corpus_match or calibration_match:
        return "prompt-gap"
    if str(record.get("normalized_category", "")) == "uncategorized":
        return "corpus-and-calibration-gap"
    return "corpus-gap"


def build_prompt_focus(missed_records: list[dict[str, Any]]) -> list[str]:
    gap_rank = {
        "prompt-gap": 0,
        "corpus-and-calibration-gap": 1,
        "corpus-gap": 2,
        "caught": 3,
    }
    severity_rank = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    ordered_records = sorted(
        missed_records,
        key=lambda record: (
            gap_rank.get(str(record.get("gap_classification") or ""), 9),
            severity_rank.get(str(record.get("severity") or "").lower(), 9),
            str(record.get("candidate_title") or ""),
        ),
    )
    focus: list[str] = []
    for record in ordered_records[:6]:
        title = str(record.get("candidate_title") or "Untitled finding").strip()
        file_path = str(record.get("file_path") or "unknown-file").strip()
        summary = str(
            record.get("candidate_summary") or record.get("body") or ""
        ).strip()
        snippet = title
        if summary:
            snippet = (
                summary
                if len(summary) <= 240
                else summary[:237].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
            )
        signals = record.get("suggested_signal_phrases")
        if not isinstance(signals, list):
            signals = compact_expectation_signals(record)
        if signals:
            focus.append(
                f"{title} in {file_path}: {snippet}. Evidence anchors to mention if present: "
                + "; ".join(signals)
            )
        else:
            focus.append(f"{title} in {file_path}: {snippet}")
    return focus


def bucket_counts(
    findings: list[dict[str, Any]], field_name: str, buckets: list[str]
) -> dict[str, int]:
    counts = {bucket: 0 for bucket in buckets}
    for item in findings:
        value = str(item.get(field_name) or "").lower()
        if value in counts:
            counts[value] += 1
        else:
            counts.setdefault("other", 0)
            counts["other"] += 1
    return counts


def build_evaluation_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    missed = [item for item in findings if item["gap_classification"] != "caught"]
    high_severity_missed = [
        item
        for item in missed
        if str(item.get("severity") or "").lower() in {"critical", "high"}
    ]
    prompt_gap_misses = [
        item for item in missed if item["gap_classification"] == "prompt-gap"
    ]
    known_blind_spot_misses = [
        item
        for item in missed
        if item["gap_classification"] in {"prompt-gap", "corpus-and-calibration-gap"}
    ]
    novel_gap_misses = [
        item for item in missed if item["gap_classification"] == "corpus-gap"
    ]
    deeper_review_likely_helpful = bool(high_severity_missed or prompt_gap_misses)
    if not missed:
        review_sufficiency = "sufficient"
    elif deeper_review_likely_helpful:
        review_sufficiency = "needs-deeper-follow-up"
    else:
        review_sufficiency = "needs-prompt-or-corpus-tuning"
    return {
        "review_sufficiency": review_sufficiency,
        "deeper_review_likely_helpful": deeper_review_likely_helpful,
        "known_blind_spot_misses": len(known_blind_spot_misses),
        "novel_gap_misses": len(novel_gap_misses),
        "high_severity_missed": len(high_severity_missed),
    }


def build_markdown_report(
    summary: dict[str, Any],
    findings: list[dict[str, Any]],
    prompt_focus: list[str],
    evaluation_summary: dict[str, Any],
) -> str:
    severity_counts = summary.get("severity_counts") or {}
    gap_counts = summary.get("gap_class_counts") or {}
    lines = [
        "# Review Quality Comparison",
        "",
        "## Summary",
        "",
        f"- Accepted live GitHub findings: {summary['accepted_live_findings']}",
        f"- Caught by review: {summary['caught']}",
        f"- Missed: {summary['missed']}",
        f"- Prompt gaps: {summary['prompt_gaps']}",
        f"- Corpus gaps: {summary['corpus_gaps']}",
        f"- Corpus and calibration gaps: {summary['corpus_and_calibration_gaps']}",
        f"- Review sufficiency: {evaluation_summary['review_sufficiency']}",
        f"- Deeper review likely helpful: {'yes' if evaluation_summary['deeper_review_likely_helpful'] else 'no'}",
        "",
        "## Severity Breakdown",
        "",
        f"- Critical: {severity_counts.get('critical', 0)}",
        f"- High: {severity_counts.get('high', 0)}",
        f"- Medium: {severity_counts.get('medium', 0)}",
        f"- Low: {severity_counts.get('low', 0)}",
        "",
        "## Gap Breakdown",
        "",
        f"- Caught: {gap_counts.get('caught', 0)}",
        f"- Prompt gaps: {gap_counts.get('prompt-gap', 0)}",
        f"- Corpus gaps: {gap_counts.get('corpus-gap', 0)}",
        f"- Corpus and calibration gaps: {gap_counts.get('corpus-and-calibration-gap', 0)}",
        "",
        "## Findings",
        "",
    ]
    for finding in findings:
        lines.append(
            f"- [{finding['gap_classification']}] {finding['candidate_title']} - {finding['file_path']}"
        )
    if prompt_focus:
        lines.extend(["", "## Prompt Focus", ""])
        lines.extend(f"- {item}" for item in prompt_focus)
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    repo_root = repo_root_from_script()
    proposal_path = resolve_path(repo_root, args.proposal)
    review_path = resolve_path(repo_root, args.review_file)
    output_dir = resolve_output_dir(
        repo_root, args.output_dir, proposal_path, args.allow_outside_artifacts
    )
    review_text = review_path.read_text(encoding="utf-8")
    proposal = load_json(proposal_path)
    records = proposal.get("records") or []
    if not isinstance(records, list):
        raise ValueError("Proposal artifact must contain a top-level records list.")
    normalized_records = [record for record in records if isinstance(record, dict)]
    if args.bugs_only:
        normalized_records = [
            record for record in normalized_records if is_bug_worthy_record(record)
        ]
        normalized_records = dedupe_records(normalized_records)

    candidates_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if args.candidates:
        candidates_payload = load_json(resolve_path(repo_root, args.candidates))
        candidates_by_key = candidate_map(candidates_payload)

    primary_corpus = load_json(resolve_path(repo_root, args.primary_corpus))
    probationary_corpus = load_json(resolve_path(repo_root, args.probationary_corpus))
    calibration_entries = load_json(resolve_path(repo_root, args.calibration_input))
    combined_corpus = [*primary_corpus, *probationary_corpus]

    findings: list[dict[str, Any]] = []
    for record in normalized_records:
        review_match = compare_review_to_record(review_text, record)
        corpus_match = near_duplicate(record, combined_corpus)
        calibration_match = calibration_matches(record, calibration_entries)
        stable_candidate = candidates_by_key.get(record_key(record)) or {}
        gap = classify_gap(
            record, review_match.matched, corpus_match, calibration_match
        )
        findings.append(
            {
                "comment_id": record.get("comment_id"),
                "candidate_id": stable_candidate.get("id"),
                "candidate_title": record.get("candidate_title"),
                "candidate_summary": record.get("candidate_summary"),
                "file_path": record.get("file_path"),
                "line": record.get("line"),
                "normalized_category": record.get("normalized_category"),
                "severity": record.get("severity"),
                "candidate_expectations": record.get("candidate_expectations") or [],
                "suggested_signal_phrases": compact_expectation_signals(record),
                "review_match": {
                    "matched": review_match.matched,
                    "strict_match": review_match.strict_match,
                    "title_overlap": review_match.title_overlap,
                    "expectation_overlap": review_match.expectation_overlap,
                },
                "represented_in_corpus": corpus_match,
                "represented_in_calibration": calibration_match,
                "gap_classification": gap,
            }
        )

    missed = [item for item in findings if item["gap_classification"] != "caught"]
    prompt_focus = build_prompt_focus(missed)
    severity_counts = bucket_counts(
        findings, "severity", ["critical", "high", "medium", "low"]
    )
    gap_class_counts = bucket_counts(
        findings,
        "gap_classification",
        ["caught", "prompt-gap", "corpus-gap", "corpus-and-calibration-gap"],
    )
    evaluation_summary = build_evaluation_summary(findings)
    summary = {
        "accepted_live_findings": len(findings),
        "caught": sum(1 for item in findings if item["gap_classification"] == "caught"),
        "missed": len(missed),
        "prompt_gaps": sum(
            1 for item in findings if item["gap_classification"] == "prompt-gap"
        ),
        "corpus_gaps": sum(
            1 for item in findings if item["gap_classification"] == "corpus-gap"
        ),
        "corpus_and_calibration_gaps": sum(
            1
            for item in findings
            if item["gap_classification"] == "corpus-and-calibration-gap"
        ),
        "severity_counts": severity_counts,
        "gap_class_counts": gap_class_counts,
        "known_blind_spot_misses": evaluation_summary["known_blind_spot_misses"],
        "novel_gap_misses": evaluation_summary["novel_gap_misses"],
    }

    output = {
        "schema_version": "codex-review.quality-comparison.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_file": str(review_path),
        "proposal_file": str(proposal_path),
        "summary": summary,
        "evaluation_summary": evaluation_summary,
        "findings": findings,
        "prompt_focus": prompt_focus,
        "top_missed_findings": [
            {
                "candidate_title": item["candidate_title"],
                "file_path": item["file_path"],
                "severity": item["severity"],
                "gap_classification": item["gap_classification"],
            }
            for item in missed[:5]
        ],
        "recommended_probationary_candidates": [
            item["candidate_id"]
            for item in findings
            if item["gap_classification"] == "corpus-gap" and item["candidate_id"]
        ],
        "recommended_calibration_additions": [
            {
                "title": item["candidate_title"],
                "file_path": item["file_path"],
                "severity": item["severity"],
            }
            for item in findings
            if item["gap_classification"]
            in {"prompt-gap", "corpus-and-calibration-gap"}
        ],
    }

    json_path = output_dir / "quality-comparison.json"
    md_path = output_dir / "quality-comparison.md"
    write_json(json_path, output)
    write_text(
        md_path,
        build_markdown_report(summary, findings, prompt_focus, evaluation_summary),
    )

    print(f"Quality comparison JSON: {json_path}")
    print(f"Quality comparison Markdown: {md_path}")
    print(f"Caught vs missed: {summary['caught']} / {summary['missed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
