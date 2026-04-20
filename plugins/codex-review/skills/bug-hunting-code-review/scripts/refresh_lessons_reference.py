import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "references" / "local-lessons-snapshot.md"

ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
FIELD_RE = re.compile(
    r"^- (Context|Mistake or correction|What changed|Prevention for next time):\s*(.*)$",
    re.MULTILINE,
)


@dataclass
class LessonEntry:
    date: str
    context: str
    correction: str
    changed: str
    prevention: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a repo-local lessons snapshot so maintainers can refresh "
            "review prompts from a local notes file without copying the full source into the repo."
        )
    )
    parser.add_argument("--source", required=True, help="Path to the source codex-lessons.md file.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output markdown path. Defaults to the bundled references folder.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum number of most-recent lessons to include. Defaults to 40.",
    )
    return parser.parse_args()


def parse_entries(text: str) -> list[LessonEntry]:
    matches = list(ENTRY_RE.finditer(text))
    entries: list[LessonEntry] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        fields = {field: value.strip() for field, value in FIELD_RE.findall(block)}
        if not fields:
            continue
        entries.append(
            LessonEntry(
                date=match.group(1),
                context=fields.get("Context", ""),
                correction=fields.get("Mistake or correction", ""),
                changed=fields.get("What changed", ""),
                prevention=fields.get("Prevention for next time", ""),
            )
        )

    return entries


def render_output(entries: list[LessonEntry], source: Path) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# Local Lessons Snapshot",
        "",
        "This file is generated from a local lessons log.",
        "",
        "Use it as review-training input when refreshing the bundled review prompts.",
        "Do not treat it as the durable public source of truth for the skill.",
        "Promote repeated, review-relevant patterns into `bug-patterns-from-lessons.md` deliberately.",
        "",
        f"- Source file: `{source}`",
        f"- Generated at: `{generated_at}`",
        f"- Entries included: `{len(entries)}`",
        "",
        "## How To Use",
        "",
        "- Read this before updating `bug-patterns-from-lessons.md`.",
        "- Keep operational environment mistakes out of the public bug-pattern list unless they change review behavior in a durable way.",
        "- Prefer repeated product-review misses, boundary mistakes, stale-state bugs, and test-modeling mistakes over one-off setup incidents.",
        "",
        "## Included Lessons",
        "",
    ]

    for entry in entries:
        lines.extend(
            [
                f"### {entry.date}",
                f"- Context: {entry.context or 'Not provided.'}",
                f"- Mistake or correction: {entry.correction or 'Not provided.'}",
                f"- What changed: {entry.changed or 'Not provided.'}",
                f"- Prevention for next time: {entry.prevention or 'Not provided.'}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0.")
    if not source.is_file():
        raise SystemExit(f"Lessons file not found: {source}")

    text = source.read_text(encoding="utf-8", errors="replace")
    entries = parse_entries(text)
    if not entries:
        raise SystemExit(f"No lessons entries found in {source}")

    selected_entries = sorted(entries, key=lambda item: item.date, reverse=True)[: args.limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_output(selected_entries, source), encoding="utf-8")

    print(f"Wrote lessons snapshot: {output}")
    print(f"Entries included: {len(selected_entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
