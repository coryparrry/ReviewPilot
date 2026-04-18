import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GRAPHQL_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    owner {
      login
    }
    name
    pullRequest(number: $number) {
      number
      reviewThreads(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          path
          line
          startLine
          comments(first: 100) {
            pageInfo {
              hasNextPage
              endCursor
            }
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

GRAPHQL_THREAD_COMMENTS_QUERY = """
query($threadId: ID!, $cursor: String) {
  node(id: $threadId) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
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
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing raw review artifacts outside the repo's ignored artifacts/github-intake tree.",
    )
    return parser.parse_args()


def run_cmd(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, capture_output=True, check=True)
    return completed.stdout.decode("utf-8", errors="replace")


def split_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError(f"Repo must be in owner/name form, got: {repo}")
    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise ValueError(f"Repo must be in owner/name form, got: {repo}")
    for segment in (owner, name):
        if not all(ch.isalnum() or ch in "._-" for ch in segment):
            raise ValueError(f"Repo must contain only GitHub-safe owner/name characters, got: {repo}")
    return owner, name


def ensure_gh_auth() -> None:
    subprocess.run(["gh", "auth", "status"], capture_output=True, check=True)


def gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if isinstance(value, int):
            cmd.extend(["-F", f"{key}={value}"])
        elif value is None:
            continue
        else:
            cmd.extend(["-f", f"{key}={value}"])
    return json.loads(run_cmd(cmd))


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


def fetch_thread_comments(thread_id: str, after: str | None = None) -> dict[str, Any]:
    payload = gh_graphql(GRAPHQL_THREAD_COMMENTS_QUERY, {"threadId": thread_id, "cursor": after})
    comments = payload["data"]["node"]["comments"]
    return comments


def fetch_graphql_threads(repo: str, pr_number: int) -> dict[str, Any]:
    owner, name = split_repo(repo)
    cursor: str | None = None
    aggregated_nodes: list[dict[str, Any]] = []
    repository_meta: dict[str, Any] | None = None
    pull_request_meta: dict[str, Any] | None = None

    while True:
        payload = gh_graphql(
            GRAPHQL_THREADS_QUERY,
            {"owner": owner, "name": name, "number": pr_number, "cursor": cursor},
        )
        repository = payload["data"]["repository"]
        pull_request = repository["pullRequest"]
        review_threads = pull_request["reviewThreads"]

        if repository_meta is None:
            repository_meta = {
                "owner": repository["owner"],
                "name": repository["name"],
            }
        if pull_request_meta is None:
            pull_request_meta = {"number": pull_request["number"]}

        for thread in review_threads["nodes"]:
            comments = thread["comments"]
            all_comments = list(comments["nodes"])
            comment_cursor = comments["pageInfo"]["endCursor"]

            while comments["pageInfo"]["hasNextPage"]:
                comments = fetch_thread_comments(thread["id"], comment_cursor)
                all_comments.extend(comments["nodes"])
                comment_cursor = comments["pageInfo"]["endCursor"]

            aggregated_nodes.append(
                {
                    "id": thread["id"],
                    "path": thread.get("path"),
                    "line": thread.get("line"),
                    "startLine": thread.get("startLine"),
                    "comments": {
                        "nodes": all_comments,
                    },
                }
            )

        if not review_threads["pageInfo"]["hasNextPage"]:
            break
        cursor = review_threads["pageInfo"]["endCursor"]

    return {
        "source": "github-graphql-review-threads",
        "data": {
            "repository": {
                **(repository_meta or {}),
                "pullRequest": {
                    **(pull_request_meta or {}),
                    "reviewThreads": {
                        "nodes": aggregated_nodes,
                    },
                },
            }
        },
    }


def default_output_dir(repo_root: Path, repo: str, pr_number: int) -> Path:
    safe_repo = repo.replace("/", "-")
    return repo_root / "artifacts" / "github-intake" / "fetches" / f"{safe_repo}-pr-{pr_number}"


def resolve_output_dir(repo_root: Path, output_dir: str | None, allow_outside_artifacts: bool) -> Path:
    artifacts_root = (repo_root / "artifacts" / "github-intake").resolve()
    candidate = Path(output_dir).resolve() if output_dir else default_output_dir(repo_root, repo="", pr_number=0)
    if output_dir is None:
        return artifacts_root / "fetches" / candidate.name
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write raw GitHub review artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    out_dir = (
        resolve_output_dir(repo_root, args.output_dir, args.allow_outside_artifacts)
        if args.output_dir
        else default_output_dir(repo_root, args.repo, args.pr)
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    split_repo(args.repo)
    ensure_gh_auth()

    rest_payload = fetch_rest_comments(args.repo, args.pr)
    rest_path = out_dir / f"{timestamp}-rest-review-comments.json"
    write_json(rest_path, rest_payload)

    normalize_script = script_path.parent / "ingest_github_review_feedback.py"
    print(f"Wrote raw REST review comments: {rest_path}")

    try:
        graphql_payload = fetch_graphql_threads(args.repo, args.pr)
    except subprocess.CalledProcessError:
        print("GraphQL review-thread fetch failed after REST artifact was saved.", file=sys.stderr)
        print()
        print("Next normalization command:")
        print(f'{sys.executable} "{normalize_script}" --input "{rest_path}"')
        return 1

    graphql_path = out_dir / f"{timestamp}-graphql-review-threads.json"
    write_json(graphql_path, graphql_payload)

    print(f"Wrote raw GraphQL review threads: {graphql_path}")
    print()
    print("Next normalization commands:")
    print(f'{sys.executable} "{normalize_script}" --input "{rest_path}"')
    print(f'{sys.executable} "{normalize_script}" --input "{graphql_path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
