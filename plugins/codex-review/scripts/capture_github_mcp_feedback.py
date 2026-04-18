import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture GitHub MCP connector output into a repo-local raw artifact for the review-intake pipeline. "
            "Intended for Codex-side MCP tool output, not direct GitHub access."
        )
    )
    parser.add_argument("--repo", required=True, help="GitHub repo in owner/name form.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
    parser.add_argument(
        "--kind",
        required=True,
        choices=["pr_comments", "review_threads"],
        help="Which GitHub MCP payload is being captured.",
    )
    parser.add_argument(
        "--input",
        help="Optional JSON input file. If omitted, the script reads JSON from stdin.",
    )
    parser.add_argument(
        "--output",
        help=(
            "Optional raw artifact path. Defaults to "
            "artifacts/github-intake/mcp/<repo>-pr-<number>/<timestamp>-mcp-<kind>.json."
        ),
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing raw artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def default_output_path(repo_root: Path, repo: str, pr_number: int, kind: str) -> Path:
    safe_repo = repo.replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "pr-comments" if kind == "pr_comments" else "review-threads"
    return (
        repo_root
        / "artifacts"
        / "github-intake"
        / "mcp"
        / f"{safe_repo}-pr-{pr_number}"
        / f"{timestamp}-mcp-{suffix}.json"
    )


def resolve_output_path(
    repo_root: Path,
    repo: str,
    pr_number: int,
    kind: str,
    output_path: str | None,
    allow_outside_artifacts: bool,
) -> Path:
    artifacts_root = (repo_root / "artifacts" / "github-intake").resolve()
    if output_path is None:
        return default_output_path(repo_root, repo, pr_number, kind)

    candidate = Path(output_path).resolve()
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write MCP capture artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def load_payload(input_path: str | None) -> Any:
    if input_path:
        return json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    return json.loads(sys.stdin.read())


def validate_payload(kind: str, payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("GitHub MCP capture payload must be a JSON object.")

    if kind == "pr_comments":
        comments = payload.get("comments")
        if not isinstance(comments, list):
            raise ValueError("PR comments capture must contain a top-level comments array.")
        return

    threads = payload.get("review_threads")
    if not isinstance(threads, list):
        raise ValueError("Review-thread capture must contain a top-level review_threads array.")


def build_enriched_payload(repo: str, pr_number: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    display_url = payload.get("display_url") or payload.get("url") or f"https://github.com/{repo}/pull/{pr_number}"
    if kind == "pr_comments":
        return {
            "source": "github-mcp-pr-comments",
            "repo": repo,
            "pr_number": pr_number,
            "url": payload.get("url") or display_url,
            "display_url": display_url,
            "title": payload.get("title") or f"{repo} PR #{pr_number} comments",
            "display_title": payload.get("display_title") or payload.get("title") or f"{repo} PR #{pr_number} comments",
            "comments": payload.get("comments", []),
        }

    return {
        "source": "github-mcp-review-threads",
        "repo": repo,
        "pr_number": pr_number,
        "url": payload.get("url") or display_url,
        "display_url": display_url,
        "title": payload.get("title") or f"{repo} PR #{pr_number} review threads",
        "display_title": payload.get("display_title")
        or payload.get("title")
        or f"{repo} PR #{pr_number} review threads",
        "review_threads": payload.get("review_threads", []),
    }


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_root = repo_root_from_script()
    output_path = resolve_output_path(
        repo_root,
        args.repo,
        args.pr,
        args.kind,
        args.output,
        args.allow_outside_artifacts,
    )

    payload = load_payload(args.input)
    validate_payload(args.kind, payload)
    enriched_payload = build_enriched_payload(args.repo, args.pr, args.kind, payload)
    write_output(output_path, enriched_payload)

    raw_format = "github_mcp_pr_comments" if args.kind == "pr_comments" else "github_mcp_review_threads"
    print(f"Wrote MCP capture artifact: {output_path}")
    print()
    print("Next pipeline command:")
    print(
        f'{sys.executable} ".\\plugins\\codex-review\\scripts\\run_github_intake_pipeline.py" '
        f'--repo {args.repo} --pr {args.pr} --raw-input "{output_path}" --raw-format {raw_format} --apply-mode review'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
