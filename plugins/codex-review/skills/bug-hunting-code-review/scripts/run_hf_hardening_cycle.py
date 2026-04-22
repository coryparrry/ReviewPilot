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
from urllib.error import URLError
from urllib.request import urlopen

DATASET_ROWS_URL = "https://datasets-server.huggingface.co/rows"
JsonDict = dict[str, Any]


def parse_args() -> argparse.Namespace:
    skill_dir = Path(__file__).resolve().parent.parent
    references_dir = skill_dir / "references"

    parser = argparse.ArgumentParser(
        description=(
            "Fetch benchmark rows from Hugging Face, run blind review generation, "
            "and score the results against the external SWE-bench lane."
        )
    )
    parser.add_argument(
        "--dataset", default="SWE-bench/SWE-bench_Verified", help="Dataset repo id."
    )
    parser.add_argument("--config", default="default", help="Dataset config name.")
    parser.add_argument("--split", default="test", help="Dataset split.")
    parser.add_argument("--offset", type=int, default=0, help="0-based row offset.")
    parser.add_argument(
        "--length", type=int, default=5, help="Number of rows to fetch."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repo root used for Codex execution. Defaults to current dir.",
    )
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


def fetch_rows(
    dataset: str, config: str, split: str, offset: int, length: int
) -> JsonDict:
    query = urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    try:
        with urlopen(f"{DATASET_ROWS_URL}?{query}", timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise RuntimeError("Timed out fetching Hugging Face dataset rows.") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch Hugging Face dataset rows: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Dataset rows response must be a JSON object.")
    return payload


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
    raise FileNotFoundError(
        "Could not find a working Codex transport. Neither codex nor npx.cmd was usable."
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: JsonDict) -> None:
    write_text(path, json.dumps(payload, indent=2) + "\n")


def load_external_case_map(corpus_path: Path) -> dict[str, list[dict[str, Any]]]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8-sig"))
    case_map: dict[str, list[dict[str, Any]]] = {}
    for case in corpus:
        source = case.get("source", "")
        instance_id = source.split(":")[-1].strip()
        if not instance_id:
            continue
        case_map.setdefault(instance_id, []).append(case)
    return case_map


def summarize_target_case(
    score: dict[str, Any], expected_cases: list[dict[str, Any]]
) -> dict[str, Any]:
    results = {entry.get("case_id"): entry for entry in score.get("results", [])}
    target_results = []
    for case in expected_cases:
        case_id = case.get("id")
        if not case_id:
            continue
        result = results.get(case_id)
        target_results.append(
            {
                "case_id": case_id,
                "title": case.get("title", ""),
                "category": case.get("category", ""),
                "matched": bool(result and result.get("matched")),
                "severity": case.get("severity", ""),
            }
        )
    return {
        "target_case_count": len(target_results),
        "target_matches": sum(1 for item in target_results if item["matched"]),
        "target_results": target_results,
    }


def build_run_aggregate(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    target_match_count = sum(
        1
        for case in case_results
        if case.get("target_summary", {}).get("target_matches", 0) > 0
    )
    total_target_cases = 0
    matched_target_cases = 0
    missed_categories: dict[str, int] = {}

    for case in case_results:
        for target in case.get("target_summary", {}).get("target_results", []):
            total_target_cases += 1
            if target.get("matched"):
                matched_target_cases += 1
                continue
            category = target.get("category") or "unknown"
            missed_categories[category] = missed_categories.get(category, 0) + 1

    return {
        "executed_cases": total,
        "cases_with_target_match": target_match_count,
        "target_cases_total": total_target_cases,
        "target_cases_matched": matched_target_cases,
        "target_case_recall": (
            (matched_target_cases / total_target_cases) if total_target_cases else 0.0
        ),
        "missed_target_categories": missed_categories,
    }


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


def run_codex_review(
    repo: Path, prompt: str, review_file: Path, model: str | None
) -> str:
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


def run_external_score(scorer: Path, corpus: Path, review_file: Path) -> JsonDict:
    completed = subprocess.run(
        [
            sys.executable,
            str(scorer),
            "--corpus",
            str(corpus),
            "--review-file",
            str(review_file),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("External score runner must emit a JSON object.")
    return payload


def evaluate_case(
    repo: Path,
    case_dir: Path,
    row: dict[str, Any],
    include_hints: bool,
    prepare_only: bool,
    scorer: Path,
    external_corpus: Path,
    expected_cases: list[dict[str, Any]],
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
        result["target_summary"] = {
            "target_case_count": len(expected_cases),
            "target_matches": 0,
            "target_results": [
                {
                    "case_id": case.get("id", ""),
                    "title": case.get("title", ""),
                    "category": case.get("category", ""),
                    "matched": False,
                    "severity": case.get("severity", ""),
                }
                for case in expected_cases
            ],
        }
        return result

    result["codex_command"] = run_codex_review(repo, prompt, review_file, model)
    score = run_external_score(scorer, external_corpus, review_file)
    write_json(case_dir / "external-score.json", score)
    result["score_summary"] = score.get("summary", {})
    result["target_summary"] = summarize_target_case(score, expected_cases)
    return result


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    output_root = (repo / args.output_dir).resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = output_root / timestamp
    corpus_path = Path(args.external_corpus).resolve()
    scorer = Path(__file__).resolve().parent / "review_corpus_score.py"

    dataset_payload = fetch_rows(
        args.dataset, args.config, args.split, args.offset, args.length
    )
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
            expected_cases=case_map.get(instance_id, []),
            model=args.model,
        )
        summary["cases"].append(case_result)

    summary["aggregate"] = build_run_aggregate(summary["cases"])
    write_json(run_dir / "summary.json", summary)
    print(f"Hardening run: {run_dir}")
    print(f"Fetched rows: {len(dataset_payload.get('rows', []))}")
    print(f"Selected curated cases: {len(selected_rows)}")
    print(f"Mode: {'prepare-only' if args.prepare_only else 'executed'}")
    if selected_rows:
        aggregate = summary["aggregate"]
        print(
            "Target-case recall: "
            f"{aggregate['cases_with_target_match']}/{aggregate['executed_cases']} "
            f"({aggregate['target_case_recall']:.1%})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
