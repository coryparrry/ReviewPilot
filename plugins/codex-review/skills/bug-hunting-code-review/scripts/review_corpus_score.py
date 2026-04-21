#!/usr/bin/env python3
"""Score a review output against the bug-hunting review corpus."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEVERITY_WEIGHTS = {
    "critical": 5,
    "high": 3,
    "medium": 2,
    "low": 1,
}


@dataclass
class CaseResult:
    case_id: str
    title: str
    severity: str
    category: str
    matched: bool
    matched_group: list[str] | None
    missing_groups: list[list[str]]
    weight: int
    source: str


def load_corpus(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Corpus file must contain a JSON array.")
    return data


def read_review_text(args: argparse.Namespace) -> str:
    if args.review_file:
        return Path(args.review_file).read_text(encoding="utf-8")
    if args.review_text is not None:
        return args.review_text
    return sys.stdin.read()


def match_group(text: str, group: list[str]) -> bool:
    return all(
        re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        for pattern in group
    )


def score_case(text: str, case: dict[str, Any]) -> CaseResult:
    groups = case.get("expected_groups", [])
    matched_group: list[str] | None = None
    missing_groups: list[list[str]] = []
    for group in groups:
        group = list(group)
        if match_group(text, group):
            matched_group = group
            break
        missing_groups.append(group)

    severity = str(case.get("severity", "medium")).lower()
    weight = SEVERITY_WEIGHTS.get(severity, 1)
    return CaseResult(
        case_id=str(case["id"]),
        title=str(case["title"]),
        severity=severity,
        category=str(case.get("category", "uncategorized")),
        matched=matched_group is not None,
        matched_group=matched_group,
        missing_groups=missing_groups,
        weight=weight,
        source=str(case.get("source", "")),
    )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    total_weight = sum(item.weight for item in results)
    matched_weight = sum(item.weight for item in results if item.matched)
    recall = 0.0 if total_weight == 0 else matched_weight / total_weight

    by_severity: dict[str, dict[str, int]] = {}
    by_category: dict[str, dict[str, int]] = {}

    for item in results:
        sev_bucket = by_severity.setdefault(item.severity, {"matched": 0, "total": 0})
        sev_bucket["total"] += 1
        if item.matched:
            sev_bucket["matched"] += 1

        cat_bucket = by_category.setdefault(item.category, {"matched": 0, "total": 0})
        cat_bucket["total"] += 1
        if item.matched:
            cat_bucket["matched"] += 1

    return {
        "total_cases": len(results),
        "matched_cases": sum(1 for item in results if item.matched),
        "total_weight": total_weight,
        "matched_weight": matched_weight,
        "weighted_recall": recall,
        "by_severity": by_severity,
        "by_category": by_category,
        "critical_or_high_misses": [
            item.case_id
            for item in results
            if not item.matched and item.severity in {"critical", "high"}
        ],
    }


def print_text(
    summary: dict[str, Any], results: list[CaseResult], show_all: bool
) -> None:
    print("Review corpus score")
    print()
    print(f"Cases matched: {summary['matched_cases']}/{summary['total_cases']}")
    print(
        f"Weighted recall: {summary['matched_weight']}/{summary['total_weight']} ({summary['weighted_recall']:.1%})"
    )
    print()
    print("By severity:")
    for severity in ("critical", "high", "medium", "low"):
        if severity not in summary["by_severity"]:
            continue
        bucket = summary["by_severity"][severity]
        print(f"- {severity}: {bucket['matched']}/{bucket['total']}")
    print()
    print("By category:")
    for category in sorted(summary["by_category"]):
        bucket = summary["by_category"][category]
        print(f"- {category}: {bucket['matched']}/{bucket['total']}")

    misses = [item for item in results if not item.matched]
    if misses:
        print()
        print("Missed cases:")
        for item in misses:
            print(f"- [{item.severity}] {item.case_id}: {item.title}")
            print(f"  Source: {item.source}")
            if item.missing_groups:
                example = " AND ".join(item.missing_groups[0])
                print(f"  Expected signal pattern: {example}")

    if show_all:
        print()
        print("All cases:")
        for item in results:
            state = "matched" if item.matched else "missed"
            print(f"- [{item.severity}] {item.case_id}: {state}")


def parse_args() -> argparse.Namespace:
    skill_dir = Path(__file__).resolve().parent.parent
    default_corpus = skill_dir / "references" / "review-corpus-cases.json"

    parser = argparse.ArgumentParser(
        description="Score a review output against the bug-hunting review corpus."
    )
    parser.add_argument(
        "--review-file",
        help="Path to a markdown or text file containing the review output.",
    )
    parser.add_argument("--review-text", help="Inline review text to score.")
    parser.add_argument(
        "--corpus", default=str(default_corpus), help="Path to the corpus JSON file."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--show-all", action="store_true", help="Include matched cases in text output."
    )
    parser.add_argument(
        "--list-cases", action="store_true", help="List corpus cases and exit."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    corpus = load_corpus(Path(args.corpus))

    if args.list_cases:
        for case in corpus:
            print(f"{case['id']}: [{case.get('severity', 'medium')}] {case['title']}")
        return 0

    review_text = read_review_text(args)
    results = [score_case(review_text, case) for case in corpus]
    summary = summarize(results)

    if args.json:
        payload = {
            "summary": summary,
            "results": [item.__dict__ for item in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        print_text(summary, results, args.show_all)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
