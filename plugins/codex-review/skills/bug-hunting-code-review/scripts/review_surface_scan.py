#!/usr/bin/env python3
"""Build a change map and risk prompts for deep code review.

This script is intentionally heuristic. It does not try to prove bugs; it
summarizes the review surface and highlights recurring miss classes so the agent
knows where to dig next.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FULL_REPO_SCAN_LIMIT = 20
UNTRACKED_TEXT_LIMIT = 8000


@dataclass(frozen=True)
class RiskRule:
    key: str
    title: str
    severity: str
    patterns: tuple[re.Pattern[str], ...]
    why: str
    check: str
    allow_docs_only: bool = False


RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        key="state-machine",
        title="State-machine or companion-state drift risk",
        severity="high",
        patterns=(
            re.compile(
                r"\b(status|state|phase|paused|running|completed|failed)\b", re.I
            ),
            re.compile(
                r"\b(approvalRequired|pendingApproval|queue|artifact|finishedAt|summary)\b",
                re.I,
            ),
        ),
        why="Transitions that touch headline state often leave approval flags, queue summaries, or artifacts stale.",
        check="List every companion surface that should change with the transition and verify each one.",
    ),
    RiskRule(
        key="registry-drift",
        title="Central registry or allowlist drift risk",
        severity="high",
        patterns=(
            re.compile(
                r"\b(allowlist|registry|capabilityFamil(?:y|ies)|runtimeFamil(?:y|ies)|connector(?:Type|Key)?)\b",
                re.I,
            ),
            re.compile(r"\b(enum|family|kind|adapterType)\b", re.I),
        ),
        why="New families or kinds often require updates in central classifiers; missing one silently misclassifies runtime behavior.",
        check="Search for exact-key helpers and central maps that must stay in sync with this change.",
    ),
    RiskRule(
        key="parity-drift",
        title="Duplicated-context parity risk",
        severity="high",
        patterns=(
            re.compile(
                r"\b(runtime|binder|executionPackage|preview|readiness|metadata)\b",
                re.I,
            ),
            re.compile(
                r"\b(trustLevel|capabilityFamilies|runtimeFamily|connectorType)\b", re.I
            ),
        ),
        why="Duplicated runtime or preview context often validates one field but lets other mismatches leak deeper.",
        check="Compare every duplicated field that downstream execution or UI reads, not just the headline ones.",
    ),
    RiskRule(
        key="fixture-widening",
        title="Over-broad test fixture risk",
        severity="high",
        patterns=(
            re.compile(
                r"\b(featureGates|toolPolicy|policy|capabilityFamilies|permissions)\b",
                re.I,
            ),
            re.compile(r"=\s*\{", re.I),
        ),
        why="Tests can keep passing by replacing an entire policy object instead of flipping only the needed gate.",
        check="Verify fixture helpers merge narrow overrides on top of persisted state instead of rewriting the world.",
    ),
    RiskRule(
        key="request-contract",
        title="Request or response contract drift risk",
        severity="medium",
        patterns=(
            re.compile(
                r"\b(schema|contract|dto|mapper|response|request|parse)\b", re.I
            ),
            re.compile(r"\b(create|patch|update)\b", re.I),
        ),
        why="Generated-looking API code often reuses response or persisted shapes as input validation.",
        check="Make sure create and patch validation reflects the real request contract, not a response DTO or display model.",
    ),
    RiskRule(
        key="error-shaping",
        title="Typed error or parser-shaping risk",
        severity="medium",
        patterns=(
            re.compile(
                r"\b(validate|parse|cron|timezone|throw new Error|jsonError|status)\b",
                re.I,
            ),
        ),
        why="User faults often leak as 500s when helpers throw plain errors or parser semantics drift.",
        check="Trace validation and parse failures to the route boundary and confirm they still map to the intended 4xx response.",
    ),
    RiskRule(
        key="security-boundary",
        title="Security or trust-boundary risk",
        severity="high",
        patterns=(
            re.compile(
                r"\b(auth|token|secret|permission|authorize|html|sql|exec|shell|path|redirect|gateway)\b",
                re.I,
            ),
        ),
        why="These surfaces need an explicit security pass; diff-local review is not enough.",
        check="Trace attacker-controlled input to sinks, confirm allowlists or authorization, and inspect sibling write paths.",
    ),
    RiskRule(
        key="ui-affordance",
        title="UI affordance or reachability risk",
        severity="medium",
        patterns=(
            re.compile(
                r"\b(disabled|readOnly|aria-|focus|navigate|tab|dialog|modal|selected)\b",
                re.I,
            ),
        ),
        why="UI refactors often keep the surface looking plausible while losing accessibility, saveability, or reachability.",
        check="Verify editability, accessible naming, focus state, navigation reachability, and stale-selection clearing.",
    ),
    RiskRule(
        key="path-reachability",
        title="Import, path, or validation-claim reachability risk",
        severity="medium",
        patterns=(
            re.compile(
                r"\b(import|from|require|README|AGENTS\.md|docs/|scripts/|npm run|typecheck|lint|build)\b",
                re.I,
            ),
        ),
        why="AI-written changes often advertise a path, command, or docs move that no longer resolves.",
        check="Confirm imports, example paths, docs references, and claimed validation commands still resolve in the repo.",
        allow_docs_only=True,
    ),
)


def run_git(repo: Path, *args: str, allow_failure: bool = False) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 and not allow_failure:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root(path: Path) -> Path:
    out = run_git(path, "rev-parse", "--show-toplevel")
    return Path(out.strip())


def git_untracked_files(repo: Path) -> list[Path]:
    output = run_git(repo, "ls-files", "--others", "--exclude-standard")
    return [repo / line.strip() for line in output.splitlines() if line.strip()]


def is_probably_text_file(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:2048]
    except OSError:
        return False
    return b"\x00" not in sample


def render_untracked_snapshot(repo: Path) -> str:
    sections: list[str] = []
    for path in git_untracked_files(repo)[:8]:
        rel = path.relative_to(repo).as_posix()
        if not path.is_file() or not is_probably_text_file(path):
            sections.append(
                f"Untracked file: {rel}\n(Binary or unreadable file omitted)"
            )
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = "[Could not read file contents]"
        sections.append(f"Untracked file: {rel}\n{body[:UNTRACKED_TEXT_LIMIT]}")
    return "\n\n".join(sections)


def changed_files(
    repo: Path, base: str | None, head: str | None, mode: str
) -> list[Path]:
    if mode == "dirty":
        name_out = run_git(repo, "diff", "--name-only", "HEAD")
        untracked = run_git(repo, "ls-files", "--others", "--exclude-standard")
        name_out = "\n".join([name_out.strip(), untracked.strip()]).strip()
    elif base:
        spec = f"{base}...{head or 'HEAD'}"
        name_out = run_git(repo, "diff", "--name-only", spec)
    else:
        name_out = run_git(repo, "diff", "--name-only", "HEAD")
        untracked = run_git(repo, "ls-files", "--others", "--exclude-standard")
        name_out = "\n".join([name_out.strip(), untracked.strip()]).strip()

    files: list[Path] = []
    seen: set[str] = set()
    for line in name_out.splitlines():
        value = line.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        files.append(repo / value)
    return files


def diff_text(repo: Path, base: str | None, head: str | None, mode: str) -> str:
    if mode == "dirty":
        tracked = run_git(repo, "diff", "-U0", "HEAD")
        untracked = render_untracked_snapshot(repo)
        return "\n\n".join(
            chunk for chunk in [tracked.strip(), untracked.strip()] if chunk
        )
    if base:
        spec = f"{base}...{head or 'HEAD'}"
        return run_git(repo, "diff", "-U0", spec)
    return run_git(repo, "diff", "-U0", "HEAD")


def classify_layer(path: Path) -> str:
    value = str(path).replace("\\", "/").lower()
    parts = value.split("/")
    name = path.name.lower()
    stem = path.stem.lower()
    if any(part in {"test", "tests", "__tests__"} for part in parts) or name.endswith(
        (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
    ):
        return "tests"
    if any(part in {"routes", "controllers"} for part in parts) or stem in {
        "route",
        "routes",
        "controller",
        "controllers",
    }:
        return "route-controller"
    if any(part in {"service", "services"} for part in parts) or stem in {
        "service",
        "services",
    }:
        return "service"
    if any(part in {"mappers", "mapper"} for part in parts) or stem in {
        "mapper",
        "mappers",
    }:
        return "mapping"
    if any(part in {"types", "contracts", "schemas"} for part in parts) or stem in {
        "types",
        "type",
        "contracts",
        "contract",
        "schema",
        "schemas",
    }:
        return "contracts-types"
    if any(
        part in {"migration", "migrations", "seed", "workspace"} for part in parts
    ) or stem in {"migration", "migrations", "seed", "workspace"}:
        return "persistence-migration"
    if any(
        part
        in {"runtime-connectors", "connectors", "scheduler", "workflow", "automations"}
        for part in parts
    ) or stem in {
        "scheduler",
        "workflow",
        "automations",
        "executor",
        "runtime-connectors",
        "connectors",
    }:
        return "workflow-runtime"
    if any(part in {"pages", "components", "ui"} for part in parts) or name.endswith(
        (".tsx", ".jsx")
    ):
        return "ui"
    if any(part in {"docs"} for part in parts) or name.endswith(".md"):
        return "docs"
    if name.endswith((".json", ".yaml", ".yml", ".toml")):
        return "config"
    return "other"


def scan_risks(text: str, *, code_like_change_present: bool) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    for rule in RISK_RULES:
        if not code_like_change_present and not rule.allow_docs_only:
            continue
        if all(pattern.search(text) for pattern in rule.patterns):
            risks.append(
                {
                    "key": rule.key,
                    "title": rule.title,
                    "severity": rule.severity,
                    "why": rule.why,
                    "check": rule.check,
                }
            )
    return risks


def find_adjacent(repo: Path, changed: Iterable[Path]) -> list[str]:
    suggestions: set[str] = set()
    changed_set = {path.resolve() for path in changed if path.exists()}
    for path in changed:
        rel = path.relative_to(repo).as_posix()
        parts = rel.split("/")
        stem = path.stem.replace(".test", "").replace(".spec", "")
        layer = classify_layer(path)

        if layer == "route-controller":
            parent = "/".join(parts[:-2])
            for hint in (
                "contracts",
                "mappers",
                "service",
                "services",
                "test",
                "tests",
            ):
                if parent:
                    suggestions.add(f"{parent}/{hint}/")
        elif layer == "mapping":
            parent = "/".join(parts[:-2])
            for hint in ("contracts", "types", "service", "services", "test", "tests"):
                if parent:
                    suggestions.add(f"{parent}/{hint}/")
        elif layer == "service":
            parent = "/".join(parts[:-2])
            for hint in (
                "routes",
                "controllers",
                "types",
                "contracts",
                "test",
                "tests",
            ):
                if parent:
                    suggestions.add(f"{parent}/{hint}/")
        elif layer == "workflow-runtime":
            parent = "/".join(parts[:-2])
            for hint in ("routes", "service", "services", "types", "test", "tests"):
                if parent:
                    suggestions.add(f"{parent}/{hint}/")
        elif layer == "ui":
            parent = "/".join(parts[:-2])
            for hint in ("lib", "hooks", "test", "tests"):
                if parent:
                    suggestions.add(f"{parent}/{hint}/")

        for root, _, filenames in os.walk(repo):
            root_path = Path(root)
            if ".git" in root_path.parts:
                continue
            for filename in filenames:
                candidate = root_path / filename
                if candidate.resolve() in changed_set:
                    continue
                candidate_name = candidate.name.lower()
                if (
                    stem
                    and stem in candidate_name
                    and (
                        candidate_name.endswith(
                            (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx")
                        )
                        or "/test/" in candidate.as_posix().lower()
                        or "/tests/" in candidate.as_posix().lower()
                    )
                ):
                    suggestions.add(candidate.relative_to(repo).as_posix())
    return sorted(suggestions)[:20]


def repo_hotspots(
    repo: Path, limit: int = FULL_REPO_SCAN_LIMIT
) -> list[dict[str, object]]:
    hotspot_patterns = (
        (
            re.compile(r"(auth|session|permission|policy|secret|token)", re.I),
            "auth-session",
        ),
        (
            re.compile(
                r"(workflow|automation|scheduler|queue|wake|review|benchmark)", re.I
            ),
            "workflow-review",
        ),
        (re.compile(r"(migrat|store|persist|adapter|repository)", re.I), "persistence"),
        (
            re.compile(r"(install|publish|release|smoke|validate)", re.I),
            "release-install",
        ),
        (re.compile(r"(test|spec)", re.I), "tests"),
    )
    tracked = run_git(repo, "ls-files")
    scored: list[tuple[int, str, list[str]]] = []
    for line in tracked.splitlines():
        rel = line.strip()
        if not rel:
            continue
        score = 0
        tags: list[str] = []
        for pattern, tag in hotspot_patterns:
            if pattern.search(rel):
                score += 1
                tags.append(tag)
        if rel.endswith((".py", ".ts", ".tsx", ".js")):
            score += 1
        if score:
            scored.append((score, rel, tags))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"path": rel, "score": score, "tags": tags}
        for score, rel, tags in scored[:limit]
    ]


def build_report(
    repo: Path, base: str | None, head: str | None, mode: str
) -> dict[str, object]:
    files = changed_files(repo, base, head, mode)
    patch = diff_text(repo, base, head, mode)
    layer_counts: dict[str, int] = defaultdict(int)
    grouped_files: dict[str, list[str]] = defaultdict(list)
    for file_path in files:
        layer = classify_layer(file_path)
        layer_counts[layer] += 1
        grouped_files[layer].append(file_path.relative_to(repo).as_posix())

    code_like_change_present = any(
        layer not in {"docs", "config"} for layer in grouped_files
    )
    risk_hits = scan_risks(patch, code_like_change_present=code_like_change_present)
    report = {
        "repo_root": str(repo),
        "mode": mode,
        "diff_basis": (
            "HEAD vs working tree"
            if mode == "dirty"
            else (f"{base}...{head or 'HEAD'}" if base else "working-tree-vs-HEAD")
        ),
        "changed_file_count": len(files),
        "layers": {
            key: {"count": layer_counts[key], "files": sorted(grouped_files[key])}
            for key in sorted(grouped_files)
        },
        "risk_hits": risk_hits,
        "adjacent_paths_to_inspect": find_adjacent(repo, files),
        "repo_hotspots": repo_hotspots(repo) if mode == "full" else [],
        "required_questions": [
            "What invariant must remain true after this patch?",
            "Which companion state surfaces must stay aligned with the primary state change?",
            "Which central registry, allowlist, or classifier must stay in sync with this patch?",
            "Which mirrored create/update/delete or sibling write paths could bypass the same invariant?",
            "Could any test helper or fixture be broadening permissions or feature gates so the regression would still pass?",
            "Does the real route or UI contract match the shape the tests currently assert?",
            "Which negative path, retry path, and stale-state path did I actually trace?",
            "What proof do I have that imports, docs paths, and claimed validation commands still resolve?",
        ],
    }
    return report


def print_text_report(report: dict[str, object]) -> None:
    print(f"Repo root: {report['repo_root']}")
    print(f"Mode: {report['mode']}")
    print(f"Diff basis: {report['diff_basis']}")
    print(f"Changed files: {report['changed_file_count']}")
    print()
    print("Layers:")
    for layer, payload in report["layers"].items():
        assert isinstance(payload, dict)
        print(f"- {layer} ({payload['count']})")
        for file_name in payload["files"][:8]:
            print(f"  - {file_name}")
    if report["repo_hotspots"]:
        print()
        print("Repo hotspots:")
        for hotspot in report["repo_hotspots"]:
            assert isinstance(hotspot, dict)
            tags = ", ".join(str(tag) for tag in hotspot["tags"])
            print(f"- {hotspot['path']} [{tags}]")
    print()
    print("Risk prompts:")
    risk_hits = report["risk_hits"]
    if risk_hits:
        for risk in risk_hits:
            assert isinstance(risk, dict)
            print(f"- [{risk['severity']}] {risk['title']}")
            print(f"  Why: {risk['why']}")
            print(f"  Check: {risk['check']}")
    else:
        print(
            "- No heuristic risk hits. Do not treat this as proof the patch is clean."
        )
    print()
    print("Adjacent paths to inspect:")
    paths = report["adjacent_paths_to_inspect"]
    if paths:
        for path in paths:
            print(f"- {path}")
    else:
        print("- No adjacency hints found.")
    print()
    print("Required questions:")
    for question in report["required_questions"]:
        print(f"- {question}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize change surface and deep-review prompts."
    )
    parser.add_argument(
        "--repo", default=".", help="Path inside the git repo to inspect."
    )
    parser.add_argument(
        "--base", help="Optional merge-base or branch ref for PR-style reviews."
    )
    parser.add_argument(
        "--head", help="Optional head ref when --base is used. Defaults to HEAD."
    )
    parser.add_argument(
        "--mode",
        default="changes",
        choices=["changes", "dirty", "full"],
        help="Review surface mode. changes=base...HEAD, dirty=working tree, full=broader repo scan.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of text."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = repo_root(Path(args.repo).resolve())
    report = build_report(repo, args.base, args.head, args.mode)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
