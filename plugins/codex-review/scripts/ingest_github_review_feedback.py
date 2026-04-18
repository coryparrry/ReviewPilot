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
        "patterns": [r"feature.?gate", r"full object", r"overwrite", r"fixture", r"helper", r"rewrites? the whole"],
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
        "patterns": [
            r"approvalrequired",
            r"pending approval",
            r"paused for review",
            r"companion",
            r"summary becomes incorrect",
            r"status.*summary",
            r"objecttype",
            r"wrong object type",
        ],
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
        "patterns": [r"500", r"4xx", r"422", r"typed error", r"plain error", r"error mapping", r"malformed json"],
    },
    {
        "category": "request-contract",
        "severity": "high",
        "confidence": "medium",
        "patterns": [r"request", r"patch", r"payload", r"schema", r"validation", r"role-only", r"objecttype"],
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
        "patterns": [r"explicit null", r"cleared state", r"\?\?", r"nullish", r"fallback", r"nullable", r"null"],
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
        "patterns": [
            r"seed order",
            r"named run",
            r"index 0",
            r"test should target",
            r"hardcoded .*expiresat",
            r"expiry drift",
            r"flaky fail",
            r"eventually cause flaky failures",
            r"date\.now",
        ],
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

GENERIC_TITLE_PATTERNS = [
    re.compile(r"^_?⚠️?\s*potential issue", re.IGNORECASE),
    re.compile(r"^potential issue", re.IGNORECASE),
    re.compile(r"^major$", re.IGNORECASE),
    re.compile(r"^minor$", re.IGNORECASE),
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
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing proposal artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def load_input(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def detect_format(payload: Any) -> str:
    if isinstance(payload, list):
        if payload and all(
            isinstance(item, dict)
            and ("pull_request_review_id" in item or "path" in item or "diff_hunk" in item)
            for item in payload
        ):
            return "github_rest_review_comments"
        raise ValueError(
            "Top-level JSON arrays must look like GitHub REST review comment exports. "
            "Pass --format explicitly only when the input shape is known."
        )

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


def normalize_markdown_text(text: str) -> str:
    value = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"_([^_]+)_", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def strip_review_boilerplate(body: str) -> str:
    trimmed = body.strip()
    for marker in ["\n\n<details>", "\n\n<!--", "\n\nUseful? React with"]:
        if marker in trimmed:
            trimmed = trimmed.split(marker, 1)[0].strip()
    return trimmed


def extract_comment_summary(body: str) -> tuple[str, str]:
    trimmed = strip_review_boilerplate(body)
    paragraphs = [normalize_markdown_text(chunk) for chunk in re.split(r"\n\s*\n", trimmed) if chunk.strip()]
    cleaned_paragraphs: list[str] = []

    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if lowered.startswith("useful? react with"):
            continue
        if "auto-generated comment by coderabbit" in lowered:
            continue
        cleaned_paragraphs.append(paragraph)

    if not cleaned_paragraphs:
        return ("", "")

    title = ""
    details: list[str] = []
    for paragraph in cleaned_paragraphs:
        if any(pattern.search(paragraph) for pattern in GENERIC_TITLE_PATTERNS):
            continue
        if not title:
            title = paragraph.rstrip(".")
            continue
        details.append(paragraph)

    if not title:
        title = cleaned_paragraphs[0].rstrip(".")
        details = cleaned_paragraphs[1:]

    if details:
        summary = " ".join(details)
    else:
        summary = title

    return (title[:160], summary[:1000])


def classify_comment(body: str, file_path: str | None = None) -> tuple[str, str, str]:
    lowered = body.lower()
    best_match: tuple[int, dict[str, Any] | None] = (0, None)

    for rule in CATEGORY_RULES:
        score = 0
        for pattern in rule["patterns"]:
            if re.search(pattern, lowered):
                score += 1
        if rule["category"] == "test-realism" and file_path and "/test/" in file_path.replace("\\", "/"):
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
    title, summary = extract_comment_summary(body)
    body_for_classification = "\n".join(part for part in [title, summary] if part)
    category, severity, confidence = classify_comment(body_for_classification or body, comment.get("file_path"))
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
        "candidate_title": title,
        "candidate_summary": summary,
        "normalized_category": category,
        "severity": severity,
        "confidence": confidence,
        "needs_human_review": True,
        "candidate_expectations": build_expectations(summary or title or body),
        "notes": build_notes(comment, category),
    }


def default_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "github-intake" / f"{timestamp}-proposal.json"


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
            f"Refusing to write proposal artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


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
        "source_file": input_path.name,
        "source_format": format_name,
        "records": [normalize_record(context, comment) for comment in comments],
    }

    output_path = resolve_output_path(repo_root, args.output, args.allow_outside_artifacts)
    write_output(output_path, proposal)
    print(f"Wrote proposal artifact: {output_path}")
    print(f"Format: {format_name}")
    print(f"Records: {len(proposal['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
