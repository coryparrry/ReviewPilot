import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render ReviewPilot inline findings as Codex ::code-comment directives."
        )
    )
    parser.add_argument(
        "--input",
        help="Path to inline-findings.json. Defaults to <review-dir>/inline-findings.json when --review-dir is used.",
    )
    parser.add_argument(
        "--review-dir",
        help="Optional review run directory that contains inline-findings.json.",
    )
    return parser.parse_args()


def resolve_input(args: argparse.Namespace) -> Path:
    if args.input and args.review_dir:
        raise ValueError("Use either --input or --review-dir, not both.")
    if args.input:
        path = Path(args.input).resolve()
    elif args.review_dir:
        path = Path(args.review_dir).resolve() / "inline-findings.json"
    else:
        raise ValueError("Pass either --input or --review-dir.")

    if not path.is_file():
        raise FileNotFoundError(f"Inline findings file not found: {path}")
    return path


def load_findings(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("Inline findings payload must be a JSON array.")
    findings: list[dict[str, Any]] = []
    for row in payload:
        if isinstance(row, dict):
            findings.append(row)
    return findings


def escape_attr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def to_directive(finding: dict[str, Any]) -> str:
    title = escape_attr(str(finding.get("title") or "Review finding"))
    body = escape_attr(str(finding.get("body") or ""))
    file_path = escape_attr(str(finding.get("file") or ""))
    start = int(finding.get("start") or 1)
    end = int(finding.get("end") or start)
    priority = int(finding.get("priority") or 2)
    confidence = float(finding.get("confidence") or 0.6)
    return (
        f'::code-comment{{title="{title}" body="{body}" file="{file_path}" '
        f"start={start} end={end} priority={priority} confidence={confidence:.2f}}}"
    )


def main() -> int:
    args = parse_args()
    input_path = resolve_input(args)
    findings = load_findings(input_path)
    for finding in findings:
        print(to_directive(finding))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
