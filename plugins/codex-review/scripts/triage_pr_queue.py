#!/usr/bin/env python3
"""Cheap GitHub PR triage for deciding which reviews deserve full Codex budget."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

JsonDict = dict[str, Any]
TRIAGE_SCHEMA_VERSION = "codex-review.pr-triage.v2"

PR_SPEC_RE = re.compile(r"^(?P<repo>[^/\s]+/[^#\s]+)#(?P<pr>\d+)$")
PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<repo>[^/]+/[^/]+)/pull/(?P<pr>\d+)/?$", re.I
)
HIGH_SIGNAL_PATH_TAGS: tuple[tuple[re.Pattern[str], str, int], ...] = (
    (re.compile(r"(auth|session|permission|policy|token|secret)", re.I), "auth", 4),
    (
        re.compile(r"(workflow|scheduler|queue|heartbeat|wake|automation|job)", re.I),
        "workflow",
        4,
    ),
    (
        re.compile(r"(migration|persist|store|repository|adapter|bootstrap)", re.I),
        "persistence",
        3,
    ),
    (
        re.compile(r"(route|controller|schema|contract|request|response|api)", re.I),
        "api-contract",
        3,
    ),
    (re.compile(r"(component|page|dialog|modal|form|tsx|jsx)", re.I), "ui", 1),
    (re.compile(r"(test|spec)", re.I), "tests", 0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a queue of GitHub PRs through gh, score them cheaply for review "
            "risk, and rank which ones deserve deep Codex review first."
        )
    )
    parser.add_argument(
        "--pr",
        action="append",
        default=[],
        help="PR spec in owner/name#123 or full GitHub pull URL form. Repeatable.",
    )
    parser.add_argument(
        "--input",
        help=(
            "Optional JSON file containing either a top-level list of PR specs/objects "
            "or an object with a top-level prs list."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Optional output directory. Defaults to artifacts/pr-triage/<timestamp> "
            "under this repo."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="How many highest-risk PRs to flag as immediate deep-review targets.",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=40000,
        help="Maximum diff characters to scan per PR. Keeps triage cheap.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reuse of earlier triage results for unchanged PR head SHAs.",
    )
    return parser.parse_args()


def run_cmd(
    cmd: list[str], cwd: Path, timeout: float | None = 120.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=timeout,
    )


def repo_root(cwd: Path) -> Path:
    completed = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(completed.stdout.strip())


def default_output_dir(repo: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo / "artifacts" / "pr-triage" / timestamp


def triage_root(repo: Path) -> Path:
    return repo / "artifacts" / "pr-triage"


def write_json(path: Path, payload: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_pr_spec(raw: str) -> tuple[str, int]:
    text = raw.strip()
    match = PR_SPEC_RE.match(text)
    if match:
        return match.group("repo"), int(match.group("pr"))
    url_match = PR_URL_RE.match(text)
    if url_match:
        return url_match.group("repo"), int(url_match.group("pr"))
    raise ValueError(f"Unsupported PR spec: {raw!r}")


def normalize_pr_entry(entry: object) -> tuple[str, int]:
    if isinstance(entry, str):
        return parse_pr_spec(entry)
    if isinstance(entry, dict):
        repo = str(entry.get("repo") or "").strip()
        pr_value = entry.get("pr")
        if repo and isinstance(pr_value, int):
            return repo, pr_value
        if repo and isinstance(pr_value, str) and pr_value.isdigit():
            return repo, int(pr_value)
    raise ValueError(f"Unsupported PR queue entry: {entry!r}")


def load_pr_queue(
    raw_specs: list[str], input_path: str | None
) -> list[tuple[str, int]]:
    queue: list[tuple[str, int]] = [parse_pr_spec(spec) for spec in raw_specs]
    if input_path is not None:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        entries_obj: object = payload
        if isinstance(payload, dict):
            entries_obj = payload.get("prs", [])
        if not isinstance(entries_obj, list):
            raise ValueError("Queue input must be a list or an object with a prs list.")
        for entry in entries_obj:
            queue.append(normalize_pr_entry(entry))
    if not queue:
        raise ValueError("Pass at least one --pr or --input queue file.")

    deduped: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in queue:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def load_surface_scan_module(repo: Path) -> types.ModuleType:
    script_path = (
        repo
        / "plugins"
        / "codex-review"
        / "skills"
        / "bug-hunting-code-review"
        / "scripts"
        / "review_surface_scan.py"
    )
    spec = importlib.util.spec_from_file_location(
        "review_surface_scan_triage", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load surface-scan module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_surface_scan_triage"] = module
    spec.loader.exec_module(module)
    return module


def fetch_pr_view(repo_name: str, pr_number: int, cwd: Path) -> JsonDict:
    completed = run_cmd(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo_name,
            "--json",
            ",".join(
                [
                    "number",
                    "title",
                    "url",
                    "changedFiles",
                    "additions",
                    "deletions",
                    "files",
                    "isDraft",
                    "baseRefName",
                    "headRefName",
                    "headRefOid",
                ]
            ),
        ],
        cwd,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("gh pr view returned a non-object payload.")
    return cast(JsonDict, payload)


def fetch_pr_diff(repo_name: str, pr_number: int, cwd: Path) -> str:
    completed = run_cmd(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo_name, "--patch"],
        cwd,
    )
    return completed.stdout


def classify_changed_layers(
    file_paths: list[str], scan_module: types.ModuleType
) -> dict[str, int]:
    classify_layer = cast(Any, getattr(scan_module, "classify_layer"))
    counts: dict[str, int] = {}
    for file_path in file_paths:
        layer = str(classify_layer(Path(file_path)))
        counts[layer] = counts.get(layer, 0) + 1
    return counts


def path_tags(file_paths: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for file_path in file_paths:
        for pattern, tag, _points in HIGH_SIGNAL_PATH_TAGS:
            if tag in seen:
                continue
            if pattern.search(file_path):
                tags.append(tag)
                seen.add(tag)
    return tags


def layer_score(layer_counts: dict[str, int]) -> int:
    score = 0
    if layer_counts.get("workflow-runtime", 0):
        score += 4
    if layer_counts.get("persistence-migration", 0):
        score += 4
    if layer_counts.get("route-controller", 0):
        score += 3
    if layer_counts.get("contracts-types", 0):
        score += 2
    if layer_counts.get("service", 0):
        score += 2
    if layer_counts.get("ui", 0):
        score += 1
    return score


def build_recommendation_signals(
    *,
    total_score: int,
    risk_hits: list[JsonDict],
    layer_counts: dict[str, int],
    code_files_changed: int,
) -> dict[str, Any]:
    high_risk_count = sum(
        1 for hit in risk_hits if str(hit.get("severity") or "") == "high"
    )
    medium_risk_count = sum(
        1 for hit in risk_hits if str(hit.get("severity") or "") == "medium"
    )
    docs_only = code_files_changed == 0 and set(layer_counts).issubset(
        {"docs", "config"}
    )
    touches_workflow = layer_counts.get("workflow-runtime", 0) > 0
    touches_persistence = layer_counts.get("persistence-migration", 0) > 0
    touches_contracts = (
        layer_counts.get("route-controller", 0) > 0
        or layer_counts.get("contracts-types", 0) > 0
    )
    return {
        "docs_only": docs_only,
        "touches_workflow": touches_workflow,
        "touches_persistence": touches_persistence,
        "touches_contracts": touches_contracts,
        "code_files_changed": code_files_changed,
        "high_risk_count": high_risk_count,
        "medium_risk_count": medium_risk_count,
        "total_score": total_score,
    }


def recommend_review_depth(
    *,
    total_score: int,
    risk_hits: list[JsonDict],
    layer_counts: dict[str, int],
    code_files_changed: int,
) -> str:
    signals = build_recommendation_signals(
        total_score=total_score,
        risk_hits=risk_hits,
        layer_counts=layer_counts,
        code_files_changed=code_files_changed,
    )
    if signals["docs_only"] and total_score < 4:
        return "skip"
    if (
        total_score >= 16
        or signals["high_risk_count"] >= 2
        or signals["touches_workflow"]
        or (
            signals["high_risk_count"] >= 1
            and (signals["touches_persistence"] or signals["touches_contracts"])
        )
    ):
        return "deep"
    if (
        total_score >= 5
        or signals["medium_risk_count"] >= 1
        or signals["high_risk_count"] >= 1
        or signals["touches_persistence"]
        or signals["touches_contracts"]
        or code_files_changed >= 3
    ):
        return "quick"
    return "skip"


def recommend_review_settings(recommended_depth: str, triage_score: int) -> JsonDict:
    if recommended_depth == "deep":
        return {
            "depth": "deep",
            "max_deep_passes": 2 if triage_score < 20 else 3,
            "pass_timeout_seconds": 180,
        }
    if recommended_depth == "quick":
        return {
            "depth": "quick",
            "max_deep_passes": 1,
            "pass_timeout_seconds": 120,
        }
    return {
        "depth": "quick",
        "max_deep_passes": 1,
        "pass_timeout_seconds": 90,
    }


def recommendation_summary(
    *,
    recommended_depth: str,
    total_score: int,
    risk_hits: list[JsonDict],
    layer_counts: dict[str, int],
    code_files_changed: int,
) -> JsonDict:
    signals = build_recommendation_signals(
        total_score=total_score,
        risk_hits=risk_hits,
        layer_counts=layer_counts,
        code_files_changed=code_files_changed,
    )
    if recommended_depth == "skip":
        if signals["docs_only"]:
            primary_reason = "docs-or-config-only low-risk change"
            reason_codes = ["docs-only-low-risk"]
        else:
            primary_reason = "low-risk change did not justify review spend"
            reason_codes = ["below-review-threshold"]
    elif recommended_depth == "deep":
        reason_codes = []
        if signals["touches_workflow"]:
            reason_codes.append("workflow-runtime")
        if signals["high_risk_count"] >= 2:
            reason_codes.append("multiple-high-risk-signals")
        if signals["high_risk_count"] >= 1 and (
            signals["touches_persistence"] or signals["touches_contracts"]
        ):
            reason_codes.append("high-risk-plus-critical-layer")
        if total_score >= 16:
            reason_codes.append("high-total-score")
        primary_reason = (
            "deep review justified by risky code paths or strong risk signals"
        )
    else:
        reason_codes = []
        if signals["high_risk_count"] >= 1 or signals["medium_risk_count"] >= 1:
            reason_codes.append("risk-signal-present")
        if signals["touches_persistence"]:
            reason_codes.append("persistence-change")
        if signals["touches_contracts"]:
            reason_codes.append("contract-change")
        if code_files_changed >= 3:
            reason_codes.append("multi-file-code-change")
        if total_score >= 5:
            reason_codes.append("moderate-total-score")
        primary_reason = (
            "quick review is enough unless later evidence shows missed risk"
        )

    return {
        "recommended_depth": recommended_depth,
        "primary_reason": primary_reason,
        "reason_codes": reason_codes,
        "signals": signals,
    }


def analyze_pr(
    repo_name: str,
    pr_number: int,
    *,
    cwd: Path,
    scan_module: types.ModuleType,
    max_diff_chars: int,
    view: JsonDict | None = None,
) -> JsonDict:
    if view is None:
        view = fetch_pr_view(repo_name, pr_number, cwd)
    diff = fetch_pr_diff(repo_name, pr_number, cwd)
    scan_risks = cast(Any, getattr(scan_module, "scan_risks"))

    raw_files = view.get("files")
    file_paths: list[str] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            path_value = str(item.get("path") or "").strip()
            if path_value:
                file_paths.append(path_value)

    layer_counts = classify_changed_layers(file_paths, scan_module)
    code_files_changed = sum(
        count
        for layer, count in layer_counts.items()
        if layer not in {"docs", "config", "tests"}
    )
    diff_sample = diff[:max_diff_chars]
    risk_hits = cast(
        list[JsonDict],
        scan_risks(diff_sample, code_like_change_present=code_files_changed > 0),
    )
    tags = path_tags(file_paths)

    score = 0
    score += layer_score(layer_counts)
    score += min(int(view.get("changedFiles") or 0), 12)
    churn = int(view.get("additions") or 0) + int(view.get("deletions") or 0)
    if churn >= 800:
        score += 5
    elif churn >= 300:
        score += 3
    elif churn >= 120:
        score += 1
    for pattern, tag, points in HIGH_SIGNAL_PATH_TAGS:
        if tag in tags:
            score += points
    for hit in risk_hits:
        severity = str(hit.get("severity") or "")
        if severity == "high":
            score += 5
        elif severity == "medium":
            score += 2
    if bool(view.get("isDraft")):
        score = max(score - 2, 0)

    depth = recommend_review_depth(
        total_score=score,
        risk_hits=risk_hits,
        layer_counts=layer_counts,
        code_files_changed=code_files_changed,
    )
    review_settings = recommend_review_settings(depth, score)
    recommendation = recommendation_summary(
        recommended_depth=depth,
        total_score=score,
        risk_hits=risk_hits,
        layer_counts=layer_counts,
        code_files_changed=code_files_changed,
    )

    reasons: list[str] = []
    if risk_hits:
        reasons.append(
            ", ".join(
                str(hit.get("title") or "").strip()
                for hit in risk_hits[:3]
                if str(hit.get("title") or "").strip()
            )
        )
    if tags:
        reasons.append("high-signal paths: " + ", ".join(tags[:4]))
    if churn:
        reasons.append(
            f"churn {int(view.get('additions') or 0)}+/{int(view.get('deletions') or 0)}- across {int(view.get('changedFiles') or 0)} files"
        )

    return {
        "repo": repo_name,
        "pr": pr_number,
        "title": str(view.get("title") or ""),
        "url": str(view.get("url") or ""),
        "is_draft": bool(view.get("isDraft")),
        "base_ref": str(view.get("baseRefName") or ""),
        "head_ref": str(view.get("headRefName") or ""),
        "head_oid": str(view.get("headRefOid") or ""),
        "changed_files": int(view.get("changedFiles") or 0),
        "additions": int(view.get("additions") or 0),
        "deletions": int(view.get("deletions") or 0),
        "layer_counts": layer_counts,
        "path_tags": tags,
        "risk_hits": risk_hits,
        "triage_score": score,
        "recommended_depth": depth,
        "recommended_review_settings": review_settings,
        "recommendation_summary": recommendation,
        "reasons": reasons,
        "checkout_hint": f"gh pr checkout {pr_number} --repo {repo_name}",
        "recommended_review_command": (
            'python "./plugins/codex-review/scripts/run_codex_review.py" '
            '--repo "<checked-out-repo>" '
            "--base "
            f'{str(view.get("baseRefName") or "origin/main")} '
            f'--depth {review_settings["depth"]} '
            f'--max-deep-passes {review_settings["max_deep_passes"]} '
            f'--pass-timeout-seconds {review_settings["pass_timeout_seconds"]}'
        ),
        "public_compare_hint": (
            'python "./plugins/codex-review/scripts/run_public_pr_quality_cycle.py" '
            f'--repo {repo_name} --pr {pr_number} --review-artifacts "<review-run-dir>"'
        ),
    }


def load_cached_triage_result(
    repo: Path, repo_name: str, pr_number: int, head_oid: str
) -> JsonDict | None:
    if not head_oid:
        return None
    root = triage_root(repo)
    if not root.is_dir():
        return None
    summaries = sorted(root.glob("*/triage-summary.json"), reverse=True)
    for summary_path in summaries:
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("schema_version") or "") != TRIAGE_SCHEMA_VERSION:
            continue
        prs = payload.get("prs")
        if not isinstance(prs, list):
            continue
        for item in prs:
            if not isinstance(item, dict):
                continue
            try:
                cached_pr = int(item.get("pr") or 0)
            except (TypeError, ValueError):
                continue
            if (
                str(item.get("repo") or "") == repo_name
                and cached_pr == pr_number
                and str(item.get("head_oid") or "") == head_oid
            ):
                cached = dict(item)
                cached["cache_hit"] = True
                cached["cache_source"] = str(summary_path)
                return cached
    return None


def build_markdown(queue: list[JsonDict], top_n: int) -> str:
    lines = ["# PR Review Triage", ""]
    deep_targets = [item for item in queue if item["recommended_depth"] == "deep"][
        :top_n
    ]
    quick_targets = [item for item in queue if item["recommended_depth"] == "quick"][
        :top_n
    ]

    lines.append("## Immediate Deep Reviews")
    if deep_targets:
        for item in deep_targets:
            lines.append(
                f"- `{item['repo']}#{item['pr']}` ({item['triage_score']}) - {item['title']}"
            )
            lines.append(f"  Reasons: {'; '.join(item['reasons'][:2])}")
            summary = item.get("recommendation_summary") or {}
            if isinstance(summary, dict) and summary.get("primary_reason"):
                lines.append(f"  Decision: {summary['primary_reason']}")
    else:
        lines.append("- None.")
    lines.append("")

    lines.append("## Quick Reviews")
    if quick_targets:
        for item in quick_targets:
            lines.append(
                f"- `{item['repo']}#{item['pr']}` ({item['triage_score']}) - {item['title']}"
            )
            lines.append(f"  Reasons: {'; '.join(item['reasons'][:2])}")
            summary = item.get("recommendation_summary") or {}
            if isinstance(summary, dict) and summary.get("primary_reason"):
                lines.append(f"  Decision: {summary['primary_reason']}")
    else:
        lines.append("- None.")
    lines.append("")

    lines.append("## Full Queue")
    for item in queue:
        lines.append(
            f"- `{item['repo']}#{item['pr']}`: {item['recommended_depth']} "
            f"(score {item['triage_score']})"
        )
        if item["reasons"]:
            lines.append(f"  Reasons: {'; '.join(item['reasons'][:3])}")
        summary = item.get("recommendation_summary") or {}
        if isinstance(summary, dict):
            primary_reason = str(summary.get("primary_reason") or "").strip()
            if primary_reason:
                lines.append(f"  Decision: {primary_reason}")
            reason_codes = summary.get("reason_codes")
            if isinstance(reason_codes, list) and reason_codes:
                lines.append(
                    f"  Decision codes: {', '.join(str(code) for code in reason_codes)}"
                )
        lines.append(f"  Checkout: `{item['checkout_hint']}`")
        lines.append(f"  Review: `{item['recommended_review_command']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo = repo_root(Path.cwd())
    queue_specs = load_pr_queue(cast(list[str], args.pr), args.input)
    out_dir = (
        Path(args.output_dir).resolve() if args.output_dir else default_output_dir(repo)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    scan_module = load_surface_scan_module(repo)
    analyzed: list[JsonDict] = []
    for repo_name, pr_number in queue_specs:
        view = fetch_pr_view(repo_name, pr_number, repo)
        head_oid = str(view.get("headRefOid") or "")
        cached = None
        if not args.no_cache:
            cached = load_cached_triage_result(repo, repo_name, pr_number, head_oid)
        if cached is not None:
            analyzed.append(cached)
            continue
        analyzed.append(
            analyze_pr(
                repo_name,
                pr_number,
                cwd=repo,
                scan_module=scan_module,
                max_diff_chars=args.max_diff_chars,
                view=view,
            )
        )
    analyzed.sort(
        key=lambda item: (
            -int(item["triage_score"]),
            str(item["repo"]),
            int(item["pr"]),
        )
    )

    summary: JsonDict = {
        "schema_version": TRIAGE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(out_dir),
        "queue_size": len(analyzed),
        "top_n": args.top,
        "prs": analyzed,
    }
    write_json(out_dir / "triage-summary.json", summary)
    write_text(out_dir / "triage-summary.md", build_markdown(analyzed, args.top))

    print(f"PR triage run: {out_dir}")
    print(f"Summary: {out_dir / 'triage-summary.json'}")
    if analyzed:
        top = analyzed[0]
        print(
            f"Top target: {top['repo']}#{top['pr']} -> {top['recommended_depth']} review "
            f"(score {top['triage_score']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
