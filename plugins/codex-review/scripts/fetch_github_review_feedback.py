import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    owner {
      login
    }
    name
    pullRequest(number: $number) {
      number
      reviewThreads(first: 100) {
        nodes {
          path
          line
          startLine
          comments(first: 100) {
            nodes {
              id
              databaseId
              body
              path
              line
              pullRequestReview {
                id
                databaseId
              }
            }
          }
        }
      }
    }
  }
}
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch GitHub PR review feedback into raw artifacts for proposal-only normalization."
    )
    parser.add_argument("--repo", required=True, help="GitHub repo in owner/name form.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
    parser.add_argument(
        "--output-dir",
        help="Output directory for raw artifacts. Defaults to artifacts/github-intake/fetches/<repo>-pr-<number>.",
    )
    return parser.parse_args()


def run_cmd(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, capture_output=True, check=True)
    return completed.stdout.decode("utf-8")


def split_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError(f"Repo must be in owner/name form, got: {repo}")
    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise ValueError(f"Repo must be in owner/name form, got: {repo}")
    return owner, name


def fetch_rest_comments(repo: str, pr_number: int) -> dict[str, Any]:
    output = run_cmd(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{pr_number}/comments",
            "--paginate",
        ]
    )
    comments = json.loads(output)
    return {
        "source": "github-rest-review-comments",
        "repo": repo,
        "pr_number": pr_number,
        "comments": comments,
    }


def fetch_graphql_threads(repo: str, pr_number: int) -> dict[str, Any]:
    owner, name = split_repo(repo)
    output = run_cmd(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={pr_number}",
            "-f",
            f"query={GRAPHQL_QUERY}",
        ]
    )
    payload = json.loads(output)
    payload["source"] = "github-graphql-review-threads"
    return payload


def default_output_dir(repo_root: Path, repo: str, pr_number: int) -> Path:
    safe_repo = repo.replace("/", "-")
    return repo_root / "artifacts" / "github-intake" / "fetches" / f"{safe_repo}-pr-{pr_number}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    out_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(repo_root, args.repo, args.pr)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    rest_payload = fetch_rest_comments(args.repo, args.pr)
    graphql_payload = fetch_graphql_threads(args.repo, args.pr)

    rest_path = out_dir / f"{timestamp}-rest-review-comments.json"
    graphql_path = out_dir / f"{timestamp}-graphql-review-threads.json"

    write_json(rest_path, rest_payload)
    write_json(graphql_path, graphql_payload)

    normalize_script = script_path.parent / "ingest_github_review_feedback.py"

    print(f"Wrote raw REST review comments: {rest_path}")
    print(f"Wrote raw GraphQL review threads: {graphql_path}")
    print()
    print("Next normalization commands:")
    print(f'{sys.executable} "{normalize_script}" --input "{rest_path}"')
    print(f'{sys.executable} "{normalize_script}" --input "{graphql_path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
