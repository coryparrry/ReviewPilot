import argparse
import json
import re
from pathlib import Path


SECTION_HEADING_RE = re.compile(r"^\*\*(.+?)\*\*$")
NUMBERED_ITEM_RE = re.compile(r"^\d+\.\s+", re.MULTILINE)
SEVERITY_RE = re.compile(r"^\[(?P<severity>[^\]]+)\]\s+(?P<title>.+)$")
LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Turn a Codex review artifact into a structured repair-plan artifact."
    )
    parser.add_argument("--review-file", required=True, help="Path to review.md or another review artifact.")
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to the review file directory.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_name = "body"
    sections[current_name] = []

    for line in text.splitlines():
        match = SECTION_HEADING_RE.match(line.strip())
        if match:
            current_name = match.group(1).strip().lower()
            sections.setdefault(current_name, [])
            continue
        sections.setdefault(current_name, []).append(line)

    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def split_numbered_items(block: str) -> list[str]:
    if not block.strip():
        return []

    matches = list(NUMBERED_ITEM_RE.finditer(block))
    if not matches:
        return [block.strip()]

    items: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        item = block[start:end].strip()
        if item:
            items.append(item)
    return items


def extract_file_references(text: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for match in LINK_RE.finditer(text):
        refs.append(
            {
                "label": match.group("label"),
                "target": match.group("target"),
            }
        )
    return refs


def build_validation_hints(title: str, refs: list[dict[str, str]]) -> list[str]:
    hints = ["re-run the review after the fix and confirm this finding disappears"]
    if refs:
        hints.append("add or update a focused test near the touched file path")
    lowered = title.lower()
    if "state" in lowered or "active" in lowered or "retry" in lowered:
        hints.append("exercise the retry and state-transition path so the invariant holds after repeated calls")
    if "bootstrap" in lowered or "auth" in lowered or "owner" in lowered:
        hints.append("verify the default local identity still works when stored records start inactive")
    return hints


def parse_finding(item: str, ordinal: int) -> dict:
    lines = [line.rstrip() for line in item.splitlines()]
    header = lines[0].strip() if lines else ""
    body = "\n".join(line for line in lines[1:]).strip()

    severity = "unknown"
    title = header
    severity_match = SEVERITY_RE.match(header)
    if severity_match:
        severity = severity_match.group("severity").strip().lower()
        title = severity_match.group("title").strip()

    file_refs = extract_file_references(item)
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()

    evidence = body or item.strip()
    return {
        "id": f"repair-{ordinal}",
        "title": title,
        "severity": severity,
        "file_references": file_refs,
        "evidence": evidence,
        "repair_goal": f"Fix the issue described as: {title}",
        "validation_hints": build_validation_hints(title, file_refs),
    }


def build_plan(review_file: Path) -> dict:
    text = read_text(review_file)
    sections = split_sections(text)
    findings_block = sections.get("findings", "")
    findings = [parse_finding(item, index + 1) for index, item in enumerate(split_numbered_items(findings_block))]

    return {
        "schema_version": "codex-review.repair-plan.v1",
        "review_file": review_file.name,
        "sections": sections,
        "findings": findings,
    }


def render_markdown(plan: dict) -> str:
    lines = ["# Repair Plan", ""]
    lines.append(f"Source review: `{plan['review_file']}`")
    lines.append("")

    findings = plan["findings"]
    if not findings:
        lines.append("No parsed findings were available.")
        return "\n".join(lines) + "\n"

    for finding in findings:
        lines.append(f"## {finding['title']}")
        lines.append("")
        lines.append(f"- Severity: `{finding['severity']}`")
        if finding["file_references"]:
            joined_refs = ", ".join(f"`{ref['target']}`" for ref in finding["file_references"])
            lines.append(f"- File references: {joined_refs}")
        lines.append(f"- Repair goal: {finding['repair_goal']}")
        lines.append(f"- Evidence: {finding['evidence'].replace(chr(10), ' ')}")
        lines.append("- Validation:")
        for hint in finding["validation_hints"]:
            lines.append(f"  - {hint}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    review_file = Path(args.review_file).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else review_file.parent

    plan = build_plan(review_file)
    json_path = output_dir / "repair-plan.json"
    md_path = output_dir / "repair-plan.md"

    write_text(json_path, json.dumps(plan, indent=2) + "\n")
    write_text(md_path, render_markdown(plan))

    print(f"Repair plan JSON: {json_path}")
    print(f"Repair plan Markdown: {md_path}")
    print(f"Parsed findings: {len(plan['findings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
