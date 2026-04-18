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
        "--format",
        default="auto",
        choices=[
            "auto",
            "custom_review_bundle",
            "github_rest_review_comments",
            "github_graphql_review_threads",
        ],
        help="Input format. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--output",
        help="Path to the proposal artifact. Defaults to artifacts/github-intake/<timestamp>-proposal.json",
    )
    return parser.parse_args()


def load_input(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def detect_format(payload: Any) -> str:
    if isinstance(payload, list):
        return "github_rest_review_comments"

    if not isinstance(payload, dict):
        raise ValueError("Unsupported input payload. Expected a JSON object or array.")

    if nested_get(payload, "data", "repository", "pullRequest", "reviewThreads", "nodes") is not None:
        return "github_graphql_review_threads"

    if nested_get(payload, "repository", "pullRequest", "reviewThreads", "nodes") is not None:
        return "github_graphql_review_threads"

    if payload.get("source") == "github-rest-review-comments":
        return "github_rest_review_comments"

    if payload.get("source") == "github-graphql-review-threads":
        return "github_graphql_review_threads"

    raw_comments = payload.get("comments")
    if isinstance(raw_comments, list):
        if not raw_comments and "repo" in payload and "pr_number" in payload:
            return "github_rest_review_comments"
        if raw_comments:
            first_comment = raw_comments[0]
            if isinstance(first_comment, dict) and (
                "pull_request_review_id" in first_comment or "path" in first_comment or "diff_hunk" in first_comment
            ):
                return "github_rest_review_comments"

    if "pull_request_review_id" in payload or "pullRequestReview" in payload:
        return "github_rest_review_comments"

    if "comments" in payload or "reviews" in payload:
        return "custom_review_bundle"

    raise ValueError("Could not auto-detect input format.")


def extract_repo_context(payload: Any, format_name: str) -> dict[str, Any]:
    if format_name == "custom_review_bundle":
        assert isinstance(payload, dict)
        return {
            "source": payload.get("source", "unknown"),
            "repo": payload.get("repo", "unknown"),
            "pr_number": payload.get("pr_number"),
        }

    if format_name == "github_rest_review_comments":
        if isinstance(payload, dict):
            return {
                "source": payload.get("source", "github-rest-review-comments"),
                "repo": payload.get("repo", "unknown"),
                "pr_number": payload.get("pr_number"),
            }
        return {
            "source": "github-rest-review-comments",
            "repo": "unknown",
            "pr_number": None,
        }

    root = payload.get("data", payload) if isinstance(payload, dict) else {}
    repository = nested_get(root, "repository") or {}
    pull_request = nested_get(repository, "pullRequest") or {}
    owner = nested_get(repository, "owner", "login")
    name = repository.get("name")
    repo = f"{owner}/{name}" if owner and name else "unknown"
    return {
        "source": payload.get("source", "github-graphql-review-threads") if isinstance(payload, dict) else "github-graphql-review-threads",
        "repo": repo,
        "pr_number": pull_request.get("number"),
    }


def iter_custom_review_bundle(payload: dict[str, Any]) -> list[dict[str, Any]]:
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


def iter_github_rest_review_comments(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_comments = payload.get("comments", [])
    else:
        raw_comments = payload

    comments: list[dict[str, Any]] = []
    for comment in raw_comments:
        comments.append(
            {
                "review_id": comment.get("pull_request_review_id") or comment.get("review_id"),
                "comment_id": comment.get("id") or comment.get("comment_id"),
                "source_type": "github_review_comment",
                "file_path": comment.get("path") or comment.get("file_path"),
                "line": comment.get("line") or comment.get("original_line") or comment.get("position"),
                "body": comment.get("body", ""),
            }
        )
    return comments


def iter_github_graphql_review_threads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("data", payload)
    thread_nodes = nested_get(root, "repository", "pullRequest", "reviewThreads", "nodes") or []
    comments: list[dict[str, Any]] = []

    for thread in thread_nodes:
        thread_path = thread.get("path")
        thread_line = thread.get("line") or thread.get("startLine")
        for comment in nested_get(thread, "comments", "nodes") or []:
            review = comment.get("pullRequestReview") or {}
            comments.append(
                {
                    "review_id": review.get("databaseId") or review.get("id"),
                    "comment_id": comment.get("databaseId") or comment.get("id"),
                    "source_type": "github_review_comment",
                    "file_path": comment.get("path") or thread_path,
                    "line": comment.get("line") or thread_line,
                    "body": comment.get("body", ""),
                }
            )

    return comments


def iter_comments(payload: Any, format_name: str) -> list[dict[str, Any]]:
    if format_name == "custom_review_bundle":
        assert isinstance(payload, dict)
        return iter_custom_review_bundle(payload)

    if format_name == "github_rest_review_comments":
        return iter_github_rest_review_comments(payload)

    if format_name == "github_graphql_review_threads":
        assert isinstance(payload, dict)
        return iter_github_graphql_review_threads(payload)

    raise ValueError(f"Unsupported format: {format_name}")


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


def build_notes(comment: dict[str, Any], category: str) -> str:
    notes: list[str] = ["Heuristic classification from proposal-only intake."]
    if category == "uncategorized":
        notes.append("No existing corpus category matched confidently.")
    if not comment.get("file_path"):
        notes.append("Source comment did not include a file path.")
    if not comment.get("line"):
        notes.append("Source comment did not include a stable line reference.")
    return " ".join(notes)


def normalize_record(context: dict[str, Any], comment: dict[str, Any]) -> dict[str, Any]:
    body = str(comment.get("body", "")).strip()
    category, severity, confidence = classify_comment(body)
    return {
        "source": context.get("source", "unknown"),
        "repo": context.get("repo", "unknown"),
        "pr_number": context.get("pr_number"),
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
        "notes": build_notes(comment, category),
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
    format_name = detect_format(payload) if args.format == "auto" else args.format
    context = extract_repo_context(payload, format_name)
    comments = iter_comments(payload, format_name)

    proposal = {
        "schema_version": "codex-review.github-intake.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(input_path),
        "source_format": format_name,
        "records": [normalize_record(context, comment) for comment in comments],
    }

    output_path = Path(args.output).resolve() if args.output else default_output_path(repo_root)
    write_output(output_path, proposal)
    print(f"Wrote proposal artifact: {output_path}")
    print(f"Format: {format_name}")
    print(f"Records: {len(proposal['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
