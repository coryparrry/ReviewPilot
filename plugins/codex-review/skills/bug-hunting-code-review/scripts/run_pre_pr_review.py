#!/usr/bin/env python3
"""Prepare, run, and score a bug-hunting pre-PR review."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path) -> str:
    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return completed.stdout


def repo_root(cwd: Path) -> Path:
    return Path(run_cmd(["git", "rev-parse", "--show-toplevel"], cwd).strip())


def current_branch(cwd: Path) -> str:
    return run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


def load_default_prompt(skill_dir: Path) -> str:
    config_path = skill_dir / "agents" / "openai.yaml"
    text = config_path.read_text(encoding="utf-8")
    marker = 'default_prompt: "'
    start = text.find(marker)
    if start == -1:
        raise ValueError(f"Could not find default_prompt in {config_path}")
    start += len(marker)
    end = text.find('"', start)
    if end == -1:
        raise ValueError(f"Could not parse default_prompt in {config_path}")
    return text[start:end]


def get_diff(repo: Path, base: str | None, pr: str | None) -> tuple[str, str]:
    if pr:
        diff = run_cmd(["gh", "pr", "diff", pr, "--patch"], repo)
        try:
            meta = run_cmd(
                ["gh", "pr", "view", pr, "--json", "number,title,baseRefName,headRefName,url"],
                repo,
            )
            return diff, meta
        except subprocess.CalledProcessError:
            return diff, ""

    if base is None:
        base = "origin/main"
    diff = run_cmd(["git", "diff", f"{base}...HEAD"], repo)
    metadata = json.dumps(
        {
            "mode": "local-branch",
            "base": base,
            "head": current_branch(repo),
        },
        indent=2,
    )
    return diff, metadata


def run_surface_scan(skill_dir: Path, repo: Path, base: str | None) -> str:
    scan_script = skill_dir / "scripts" / "review_surface_scan.py"
    cmd = [sys.executable, str(scan_script), "--repo", str(repo)]
    if base:
        cmd.extend(["--base", base])
    completed = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=True)
    return completed.stdout


def build_prompt(
    default_prompt: str,
    metadata: str,
    scan: str,
    diff: str,
) -> str:
    return textwrap.dedent(
        f"""\
        {default_prompt}

        Produce a release-blocking code review.
        Findings first. Prioritize correctness, security, AI-slop drift, stale state, broken paths, broken tests, and missing negative-path handling.
        Use the scan hints, but verify them from the diff and surrounding behavior.
        If there are no findings, say so explicitly and mention residual risk or test gaps briefly.

        Review context:
        {metadata}

        Surface scan:
        {scan}

        Diff:
        {diff}
        """
    )


def call_openai(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    payload = {
        "model": model,
        "input": prompt,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API request failed: {exc.code} {detail}") from exc

    output = body.get("output_text")
    if output:
        return output

    pieces: list[str] = []
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                pieces.append(text)
    if pieces:
        return "\n".join(pieces)
    raise RuntimeError("OpenAI response did not contain output text.")


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_benchmarks(skill_dir: Path, review_file: Path, repo: Path) -> str:
    runner = skill_dir / "scripts" / "run_review_benchmarks.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--review-file", str(review_file)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and score a pre-PR bug-hunting review.")
    parser.add_argument("--repo", default=".", help="Repository path. Defaults to the current directory.")
    parser.add_argument("--base", help="Base branch for local diff mode. Defaults to origin/main.")
    parser.add_argument("--pr", help="PR number, URL, or branch to review via gh.")
    parser.add_argument(
        "--model",
        default=os.environ.get("CODEX_REVIEW_MODEL", "gpt-5.1"),
        help="OpenAI model to use. Defaults to CODEX_REVIEW_MODEL or gpt-5.1.",
    )
    parser.add_argument(
        "--output-dir",
        default=".codex-review",
        help="Directory under the repo root for saved artifacts.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare diff, prompt, and scan artifacts without calling the OpenAI API.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_dir = Path(__file__).resolve().parent.parent
    repo = repo_root(Path(args.repo).resolve())
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = repo / args.output_dir / timestamp

    default_prompt = load_default_prompt(skill_dir)
    diff, metadata = get_diff(repo, args.base, args.pr)
    scan = run_surface_scan(skill_dir, repo, args.base if not args.pr else None)
    prompt = build_prompt(default_prompt, metadata, scan, diff)

    write_file(out_dir / "diff.patch", diff)
    write_file(out_dir / "review-metadata.json", metadata)
    write_file(out_dir / "surface-scan.txt", scan)
    write_file(out_dir / "review-prompt.txt", prompt)

    if args.prepare_only:
        print(f"Prepared review artifacts in {out_dir}")
        return 0

    review_text = call_openai(prompt, args.model)
    review_file = out_dir / "review.md"
    write_file(review_file, review_text)
    benchmark_output = run_benchmarks(skill_dir, review_file, repo)
    write_file(out_dir / "benchmark-summary.txt", benchmark_output)

    print(f"Artifacts: {out_dir}")
    print()
    print(benchmark_output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
