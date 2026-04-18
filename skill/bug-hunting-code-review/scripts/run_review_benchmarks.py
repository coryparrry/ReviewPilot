#!/usr/bin/env python3
"""Run the bug-hunting review benchmarks across all configured lanes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_score(
    scorer: Path,
    corpus: Path,
    review_file: Path | None,
    review_text: str | None,
) -> dict[str, Any]:
    cmd = [sys.executable, str(scorer), "--corpus", str(corpus), "--json"]
    if review_file is not None:
        cmd.extend(["--review-file", str(review_file)])
    elif review_text is not None:
        cmd.extend(["--review-text", review_text])
    else:
        raise ValueError("Either review_file or review_text must be provided.")

    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def print_lane(name: str, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    print(f"{name}:")
    print(
        f"- Cases matched: {summary['matched_cases']}/{summary['total_cases']}"
    )
    print(
        f"- Weighted recall: {summary['matched_weight']}/{summary['total_weight']} "
        f"({summary['weighted_recall']:.1%})"
    )
    misses = summary.get("critical_or_high_misses") or []
    if misses:
        print(f"- Critical/high misses: {', '.join(misses)}")
    else:
        print("- Critical/high misses: none")


def parse_args() -> argparse.Namespace:
    skill_dir = Path(__file__).resolve().parent.parent
    references_dir = skill_dir / "references"

    parser = argparse.ArgumentParser(
        description="Run all configured review benchmark lanes for bug-hunting-code-review."
    )
    parser.add_argument("--review-file", help="Path to a markdown or text file containing the review output.")
    parser.add_argument("--review-text", help="Inline review text to score.")
    parser.add_argument("--json", action="store_true", help="Emit combined JSON.")
    parser.add_argument(
        "--primary-corpus",
        default=str(references_dir / "review-corpus-cases.json"),
        help="Path to the primary GitHub review corpus.",
    )
    parser.add_argument(
        "--external-corpus",
        default=str(references_dir / "swebench-verified-review-cases.json"),
        help="Path to the external benchmark corpus.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.review_file and args.review_text is None:
        raise SystemExit("Pass --review-file or --review-text.")

    skill_dir = Path(__file__).resolve().parent.parent
    scorer = skill_dir / "scripts" / "review_corpus_score.py"

    review_file = Path(args.review_file) if args.review_file else None
    review_text = args.review_text

    primary = run_score(scorer, Path(args.primary_corpus), review_file, review_text)
    external = run_score(scorer, Path(args.external_corpus), review_file, review_text)

    combined = {
        "primary_github_corpus": primary,
        "external_swebench_verified": external,
    }

    if args.json:
        print(json.dumps(combined, indent=2))
        return 0

    print("Review benchmark summary")
    print()
    print_lane("Primary GitHub corpus", primary)
    print()
    print_lane("External SWE-bench Verified lane", external)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
