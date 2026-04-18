import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CATEGORY_RULES = [
    {
        "category": "fixture-masking",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"feature.?gate", r"full object", r"overwrite", r"fixture", r"helper"],
    },
    {
        "category": "registry-drift",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"allowlist", r"classifier", r"registry", r"exact-key", r"connector family"],
    },
    {
        "category": "state-symmetry",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"approval", r"pending", r"queue", r"summary", r"status", r"clear"],
    },
    {
        "category": "migration-backfill",
        "severity": "critical",
        "confidence": "medium",
        "patterns": [r"migration", r"backfill", r"required field", r"legacy record"],
    },
    {
        "category": "error-shaping",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"500", r"4xx", r"422", r"typed error", r"plain error", r"error mapping"],
    },
    {
        "category": "request-contract",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"request", r"patch", r"payload", r"schema", r"validation", r"role-only"],
    },
    {
        "category": "fail-open-synthesis",
        "severity": "critical",
        "confidence": "medium",
        "patterns": [r"fallback owner", r"synthetic", r"borrow", r"inherit", r"copy another"],
    },
    {
        "category": "source-of-truth-drift",
        "severity": "critical",
        "confidence": "medium",
        "patterns": [r"canonical", r"shared resolver", r"drift", r"parity", r"source of truth", r"preview"],
    },
    {
        "category": "migration-cleared-state",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"explicit null", r"cleared state", r"\?\?", r"nullish", r"fallback"],
    },
    {
        "category": "concurrency-queue-claim",
        "severity": "critical",
        "confidence": "medium",
        "patterns": [r"claim", r"duplicate", r"second poll", r"queue", r"heartbeat", r"wake"],
    },
    {
        "category": "test-realism",
        "severity": "medium",
        "confidence": "medium",
        "patterns": [r"seed order", r"named run", r"index 0", r"test should target"],
    },
    {
        "category": "legacy-fallback-source",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"runtimeAdapterType", r"adapterType", r"legacy fallback", r"wrong source field"],
    },
    {
        "category": "response-contract",
        "severity": "medium",
        "confidence": "medium",
        "patterns": [r"wrapped payload", r"response shape", r"payload shape", r"assert the real"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize GitHub PR review feedback into proposal-only corpus-update artifacts."
    )
    parser.add_argument("--input", required=True, help="Path to a GitHub review feedback JSON file.")
    parser.add_argument(
        "--output",
        help="Path to the proposal artifact. Defaults to artifacts/github-intake/<timestamp>-proposal.json",
    )
    return parser.parse_args()


def load_input(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_comments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []

    for comment in payload.get("comments", []):
        comments.append(comment)

    for review in payload.get("reviews", []):
        review_id = review.get("review_id") or review.get("id")
        for comment in review.get("comments", []):
            enriched = dict(comment)
            enriched.setdefault("review_id", review_id)
            comments.append(enriched)

    return comments


def classify_comment(body: str) -> tuple[str, str, str]:
    lowered = body.lower()
    best_match: tuple[int, dict[str, Any] | None] = (0, None)

    for rule in CATEGORY_RULES:
        score = 0
        for pattern in rule["patterns"]:
            if re.search(pattern, lowered):
                score += 1
        if score > best_match[0]:
            best_match = (score, rule)

    if best_match[1] is None or best_match[0] == 0:
        return ("uncategorized", "unknown", "low")

    rule = best_match[1]
    confidence = rule["confidence"]
    if best_match[0] >= 3:
        confidence = "high"

    return (rule["category"], rule["severity"], confidence)


def build_expectations(body: str) -> list[str]:
    fragments = re.split(r"[.;\n]", body)
    expectations: list[str] = []
    for fragment in fragments:
        text = " ".join(fragment.strip().split())
        if len(text) < 8:
            continue
        expectations.append(text[:120])
        if len(expectations) == 3:
            break
    return expectations


def normalize_record(payload: dict[str, Any], comment: dict[str, Any]) -> dict[str, Any]:
    body = str(comment.get("body", "")).strip()
    category, severity, confidence = classify_comment(body)
    return {
        "source": payload.get("source", "unknown"),
        "repo": payload.get("repo", "unknown"),
        "pr_number": payload.get("pr_number"),
        "review_id": comment.get("review_id"),
        "comment_id": comment.get("comment_id") or comment.get("id"),
        "source_type": comment.get("source_type", "github_review_comment"),
        "file_path": comment.get("file_path"),
        "line": comment.get("line"),
        "body": body,
        "normalized_category": category,
        "severity": severity,
        "confidence": confidence,
        "needs_human_review": True,
        "candidate_expectations": build_expectations(body),
        "notes": "Heuristic classification from proposal-only intake.",
    }


def default_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-proposal.json"


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    payload = load_input(input_path)
    comments = iter_comments(payload)

    proposal = {
        "schema_version": "codex-review.github-intake.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(input_path),
        "records": [normalize_record(payload, comment) for comment in comments],
    }

    output_path = Path(args.output).resolve() if args.output else default_output_path(repo_root)
    write_output(output_path, proposal)
    print(f"Wrote proposal artifact: {output_path}")
    print(f"Records: {len(proposal['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
