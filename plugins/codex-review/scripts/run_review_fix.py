import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA = "codex-review.repair-plan.v1"
LINE_SUFFIX_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+)$")
JsonDict = dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Select one finding from a repair plan and prepare or execute a bounded Codex fix pass."
        )
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository path. Defaults to the current directory.",
    )
    parser.add_argument(
        "--repair-plan", required=True, help="Path to repair-plan.json."
    )
    parser.add_argument("--finding-id", help="Repair finding id to execute.")
    parser.add_argument(
        "--finding-index", type=int, help="1-based repair finding index to execute."
    )
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to the repair plan directory.",
    )
    parser.add_argument("--model", help="Optional Codex model override.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Invoke Codex in workspace-write mode to attempt the selected fix. Defaults to prepare-only.",
    )
    return parser.parse_args()


def read_json(path: Path) -> JsonDict:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}.")
    return payload


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: JsonDict) -> None:
    write_text(path, json.dumps(payload, indent=2) + "\n")


def resolve_codex_base_command() -> list[str]:
    direct = shutil.which("codex")
    if direct:
        return [direct]
    npx_cmd = shutil.which("npx.cmd") or shutil.which("npx")
    if npx_cmd:
        return [npx_cmd, "-y", "@openai/codex"]
    raise FileNotFoundError(
        "Could not find a working Codex transport. Neither codex nor npx.cmd was usable."
    )


def select_finding(
    plan: JsonDict, finding_id: str | None, finding_index: int | None
) -> tuple[JsonDict, int]:
    findings_raw = plan.get("findings", [])
    if not isinstance(findings_raw, list):
        raise ValueError("The repair plan does not contain a valid findings list.")

    findings: list[JsonDict] = []
    for index, finding in enumerate(findings_raw, start=1):
        if not isinstance(finding, dict):
            raise ValueError(f"Repair finding {index} is not a JSON object.")
        findings.append(finding)

    if not findings:
        raise ValueError("The repair plan does not contain any findings.")

    if finding_id and finding_index is not None:
        raise ValueError("Use either --finding-id or --finding-index, not both.")

    if finding_id:
        for index, finding in enumerate(findings, start=1):
            if finding.get("id") == finding_id:
                return finding, index
        raise ValueError(f"Could not find repair id {finding_id!r}.")

    if finding_index is not None:
        if finding_index < 1 or finding_index > len(findings):
            raise ValueError(f"--finding-index must be between 1 and {len(findings)}.")
        return findings[finding_index - 1], finding_index

    return findings[0], 1


def validate_plan(plan: JsonDict) -> None:
    schema_version = plan.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA:
        raise ValueError(
            f"Unsupported repair plan schema {schema_version!r}. Expected {SUPPORTED_SCHEMA!r}."
        )
    findings = plan.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Repair plan is missing a valid findings list.")


def collect_repo_targets(repo: Path, finding: JsonDict) -> list[Path]:
    refs = finding.get("file_references", [])
    if not isinstance(refs, list):
        return []
    targets: list[Path] = []
    seen: set[str] = set()

    for ref in refs:
        if not isinstance(ref, dict):
            continue
        raw_target = str(ref.get("target", "")).strip()
        if not raw_target:
            continue
        normalized_target = raw_target
        if normalized_target.startswith("<") and normalized_target.endswith(">"):
            normalized_target = normalized_target[1:-1]
        line_match = LINE_SUFFIX_RE.match(normalized_target)
        path_part = line_match.group("path") if line_match else normalized_target
        candidate = Path(path_part)
        if not candidate.is_absolute():
            candidate = (repo / candidate).resolve()
        else:
            candidate = candidate.resolve()

        try:
            candidate.relative_to(repo)
        except ValueError as exc:
            raise ValueError(
                f"Repair target {candidate} is outside the repo and cannot be used."
            ) from exc

        key = str(candidate)
        if key not in seen:
            seen.add(key)
            targets.append(candidate)

    return targets


def build_fix_prompt(finding: JsonDict, repo_targets: list[Path], repo: Path) -> str:
    evidence = finding.get("evidence")
    evidence_text = (
        evidence.strip() if isinstance(evidence, str) else str(evidence or "")
    )
    lines = [
        "You are fixing exactly one review finding.",
        "",
        "Constraints:",
        "- Touch only the minimum files needed for this one finding.",
        "- Do not address unrelated review findings.",
        "- Preserve existing conventions.",
        "- Add or update focused validation only if it directly supports this fix.",
        "- At the end, summarize what changed, what was validated, and any residual risk.",
        "",
        f"Finding id: {finding.get('id', '')}",
        f"Severity: {finding.get('severity', 'unknown')}",
        f"Title: {finding.get('title', '')}",
        f"Repair goal: {finding.get('repair_goal', '')}",
        "",
        "Evidence:",
        evidence_text.strip(),
        "",
    ]

    if repo_targets:
        lines.append("Allowed file targets:")
        for target in repo_targets:
            lines.append(f"- {target.relative_to(repo)}")
        lines.append("")

    hints = finding.get("validation_hints", [])
    if hints:
        lines.append("Validation hints:")
        for hint in hints:
            if isinstance(hint, str):
                lines.append(f"- {hint}")
        lines.append("")

    lines.append("Fix this single finding now.")
    return "\n".join(lines).strip() + "\n"


def run_codex_fix(
    repo: Path,
    prompt: str,
    output_dir: Path,
    model: str | None,
) -> None:
    codex_base_cmd = resolve_codex_base_command()
    result_file = output_dir / "fix-result.md"
    stdout_log = output_dir / "fix-codex-stdout.txt"
    stderr_log = output_dir / "fix-codex-stderr.txt"

    cmd = [
        *codex_base_cmd,
        "exec",
        "-C",
        str(repo),
        "--sandbox",
        "workspace-write",
        "--color",
        "never",
        "--ephemeral",
        "--output-last-message",
        str(result_file),
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
    write_text(stdout_log, completed.stdout)
    write_text(stderr_log, completed.stderr)


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    repair_plan = Path(args.repair_plan).resolve()
    output_dir = (
        Path(args.output_dir).resolve() if args.output_dir else repair_plan.parent
    )

    plan = read_json(repair_plan)
    validate_plan(plan)
    finding, ordinal = select_finding(plan, args.finding_id, args.finding_index)
    repo_targets = collect_repo_targets(repo, finding)
    prompt = build_fix_prompt(finding, repo_targets, repo)

    write_json(output_dir / "selected-repair.json", finding)
    write_text(output_dir / "fix-prompt.txt", prompt)
    write_text(
        output_dir / "fix-targets.txt",
        "\n".join(str(target.relative_to(repo)) for target in repo_targets)
        + ("\n" if repo_targets else ""),
    )

    print(f"Selected finding: {finding.get('id', f'index-{ordinal}')}")
    print(f"Fix prompt: {output_dir / 'fix-prompt.txt'}")
    print(f"Selected repair JSON: {output_dir / 'selected-repair.json'}")
    print(f"Fix targets: {output_dir / 'fix-targets.txt'}")

    if not args.apply:
        print("Mode: prepare-only")
        return 0

    if not repo_targets:
        raise ValueError(
            "Refusing to apply a fix without at least one repo-local file target."
        )

    raise ValueError(
        "Refusing --apply because Codex workspace-write cannot enforce the selected file-target boundary yet. "
        "Use the prepare-only output for a supervised fix pass until a real path-scoped execution boundary exists."
    )


if __name__ == "__main__":
    raise SystemExit(main())
