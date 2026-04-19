#!/usr/bin/env python3
"""Run a blind hardening pass against curated Hugging Face benchmark rows."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


DATASET_ROWS_URL = "https://datasets-server.huggingface.co/rows"


def parse_args() -> argparse.Namespace:
    skill_dir = Path(__file__).resolve().parent.parent
    references_dir = skill_dir / "references"

    parser = argparse.ArgumentParser(
        description=(
            "Fetch benchmark rows from Hugging Face, run blind review generation, "
            "and score the results against the external SWE-bench lane."
        )
    )
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Verified", help="Dataset repo id.")
    parser.add_argument("--config", default="default", help="Dataset config name.")
    parser.add_argument("--split", default="test", help="Dataset split.")
    parser.add_argument("--offset", type=int, default=0, help="0-based row offset.")
    parser.add_argument("--length", type=int, default=5, help="Number of rows to fetch.")
    parser.add_argument("--repo", default=".", help="Repo root used for Codex execution. Defaults to current dir.")
    parser.add_argument(
        "--output-dir",
        default="artifacts/hf-hardening",
        help="Directory for hardening run artifacts.",
    )
    parser.add_argument("--model", help="Optional Codex model override.")
    parser.add_argument(
        "--external-corpus",
        default=str(references_dir / "swebench-verified-review-cases.json"),
        help="Path to the curated external benchmark corpus.",
    )
    parser.add_argument(
        "--include-hints",
        action="store_true",
        help="Include dataset hints in the blind prompt. Defaults to false.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write prompts and metadata without invoking Codex.",
    )
    return parser.parse_args()


def fetch_rows(dataset: str, config: str, split: str, offset: int, length: int) -> dict[str, Any]:
    query = urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    with urlopen(f"{DATASET_ROWS_URL}?{query}") as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_codex_base_command() -> list[str]:
    direct = shutil.which("codex")
    if direct:
        try:
            completed = subprocess.run(
                [direct, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            if completed.stdout.strip():
                return [direct]
        except (OSError, subprocess.SubprocessError):
            pass
    npx_cmd = shutil.which("npx.cmd") or shutil.which("npx")
    if npx_cmd:
        return [npx_cmd, "-y", "@openai/codex"]
    raise FileNotFoundError("Could not find a working Codex transport. Neither codex nor npx.cmd was usable.")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2) + "\n")


def load_external_case_map(corpus_path: Path) -> dict[str, list[dict[str, Any]]]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    case_map: dict[str, list[dict[str, Any]]] = {}
    for case in corpus:
        source = case.get("source", "")
        instance_id = source.split(":")[-1].strip()
        if not instance_id:
            continue
        case_map.setdefault(instance_id, []).append(case)
    return case_map


def build_prompt(row: dict[str, Any], include_hints: bool) -> str:
    parts = [
        "You are acting as a release-blocking bug reviewer.",
        "You are given a benchmark bug report without the fix patch.",
        "Write concise findings that identify the real bug or risky invariant failure.",
        "Do not ask for the answer patch.",
        "Do not mention that this is a benchmark.",
        "",
        "Output format:",
        "- Start with **Findings**",
        "- Use a numbered list",
        "- Each finding should begin with [High] or [Medium] and a short title",
        "- Explain the bug clearly in plain English",
        "",
        f"Repository: {row.get('repo', '')}",
        f"Instance id: {row.get('instance_id', '')}",
        f"Difficulty: {row.get('difficulty', '')}",
        "",
        "Problem statement:",
        row.get("problem_statement", "").strip(),
    ]

    hints_text = row.get("hints_text", "").strip()
    if include_hints and hints_text:
        parts.extend(["", "Hints:", hints_text])

    return "\n".join(parts).strip() + "\n"


def run_codex_review(repo: Path, prompt: str, review_file: Path, model: str | None) -> str:
    codex_base_cmd = resolve_codex_base_command()
    cmd = [
        *codex_base_cmd,
        "exec",
        "-C",
        str(repo),
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--ephemeral",
        "--output-last-message",
        str(review_file),
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append("-")

    completed = subprocess.run(
        cmd,
        cwd=repo,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    write_text(review_file.parent / "codex-stdout.txt", completed.stdout)
    write_text(review_file.parent / "codex-stderr.txt", completed.stderr)
    return " ".join(codex_base_cmd)


def run_external_score(scorer: Path, corpus: Path, review_file: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(scorer), "--corpus", str(corpus), "--review-file", str(review_file), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(completed.stdout)


def evaluate_case(
    repo: Path,
    case_dir: Path,
    row: dict[str, Any],
    include_hints: bool,
    prepare_only: bool,
    scorer: Path,
    external_corpus: Path,
    model: str | None,
) -> dict[str, Any]:
    prompt = build_prompt(row, include_hints)
    prompt_file = case_dir / "prompt.txt"
    review_file = case_dir / "review.md"
    write_text(prompt_file, prompt)
    write_json(case_dir / "row.json", row)

    result: dict[str, Any] = {
        "instance_id": row.get("instance_id", ""),
        "repo": row.get("repo", ""),
        "review_file": str(review_file),
        "prompt_file": str(prompt_file),
        "mode": "prepare-only" if prepare_only else "executed",
    }

    if prepare_only:
        return result

    result["codex_command"] = run_codex_review(repo, prompt, review_file, model)
    score = run_external_score(scorer, external_corpus, review_file)
    write_json(case_dir / "external-score.json", score)
    result["score_summary"] = score.get("summary", {})
    return result


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    output_root = (repo / args.output_dir).resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = output_root / timestamp
    corpus_path = Path(args.external_corpus).resolve()
    scorer = Path(__file__).resolve().parent / "review_corpus_score.py"

    dataset_payload = fetch_rows(args.dataset, args.config, args.split, args.offset, args.length)
    write_json(run_dir / "fetched-rows.json", dataset_payload)

    case_map = load_external_case_map(corpus_path)
    selected_rows = [
        row_payload["row"]
        for row_payload in dataset_payload.get("rows", [])
        if row_payload.get("row", {}).get("instance_id", "") in case_map
    ]

    summary: dict[str, Any] = {
        "schema_version": "codex-review.hf-hardening-run.v1",
        "dataset": args.dataset,
        "config": args.config,
        "split": args.split,
        "offset": args.offset,
        "length": args.length,
        "run_dir": str(run_dir),
        "selected_case_count": len(selected_rows),
        "prepare_only": args.prepare_only,
        "cases": [],
    }

    for row in selected_rows:
        instance_id = row.get("instance_id", "unknown-case")
        case_dir = run_dir / instance_id
        case_result = evaluate_case(
            repo=repo,
            case_dir=case_dir,
            row=row,
            include_hints=args.include_hints,
            prepare_only=args.prepare_only,
            scorer=scorer,
            external_corpus=corpus_path,
            model=args.model,
        )
        summary["cases"].append(case_result)

    write_json(run_dir / "summary.json", summary)
    print(f"Hardening run: {run_dir}")
    print(f"Fetched rows: {len(dataset_payload.get('rows', []))}")
    print(f"Selected curated cases: {len(selected_rows)}")
    print(f"Mode: {'prepare-only' if args.prepare_only else 'executed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
