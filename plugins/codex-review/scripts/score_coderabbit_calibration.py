import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CALIBRATION_INPUT = Path(
    "plugins/codex-review/skills/bug-hunting-code-review/references/coderabbit-comment-calibration.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize the supervised CodeRabbit calibration set so automation runs can track "
            "what kinds of comments should be accepted, rejected, or treated as policy calls."
        )
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_CALIBRATION_INPUT),
        help="Path to the CodeRabbit calibration JSON file.",
    )
    parser.add_argument(
        "--output",
        help="Optional output path. Defaults to artifacts/coderabbit-calibration/<timestamp>-summary.json",
    )
    parser.add_argument(
        "--allow-outside-artifacts",
        action="store_true",
        help="Allow writing the output outside the repo's ignored artifacts tree.",
    )
    return parser.parse_args()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_path(repo_root: Path, requested: str) -> Path:
    candidate = Path(requested)
    return candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()


def default_output_path(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "artifacts" / "coderabbit-calibration" / f"{timestamp}-summary.json"


def resolve_output_path(repo_root: Path, requested: str | None, allow_outside_artifacts: bool) -> Path:
    artifacts_root = (repo_root / "artifacts").resolve()
    if requested is None:
        return default_output_path(repo_root)

    candidate = resolve_path(repo_root, requested)
    if allow_outside_artifacts:
        return candidate

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to write CodeRabbit calibration artifacts outside {artifacts_root}. "
            "Use --allow-outside-artifacts only when you intentionally need that."
        ) from exc
    return candidate


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def require_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("CodeRabbit calibration input must be a JSON array.")

    allowed_verdicts = {"accept", "reject", "policy"}
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ValueError(f"Calibration entry at index {index} is not a JSON object.")
        verdict = entry.get("verdict")
        if verdict not in allowed_verdicts:
            raise ValueError(
                f"Calibration entry at index {index} has invalid verdict {verdict!r}. "
                f"Expected one of {sorted(allowed_verdicts)}."
            )
        for field in ("id", "file", "summary", "severity", "reason", "use"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"Calibration entry at index {index} is missing a non-empty '{field}' field.")
        entries.append(entry)
    return entries


def top_counts(counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def compact_entries(entries: list[dict[str, Any]], verdict: str) -> list[dict[str, str]]:
    filtered = [entry for entry in entries if entry.get("verdict") == verdict]
    return [
        {
            "id": str(entry["id"]),
            "file": str(entry["file"]),
            "summary": str(entry["summary"]),
            "use": str(entry["use"]),
        }
        for entry in filtered
    ]


def build_summary(source_path: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    verdict_counts = Counter(str(entry["verdict"]) for entry in entries)
    severity_counts = Counter(str(entry["severity"]) for entry in entries)
    accepted_use_counts = Counter(str(entry["use"]) for entry in entries if entry["verdict"] == "accept")
    accepted_file_counts = Counter(str(entry["file"]) for entry in entries if entry["verdict"] == "accept")

    return {
        "schema_version": "codex-review.coderabbit-calibration.v1",
        "source_file": str(source_path),
        "total_comments": len(entries),
        "verdict_counts": dict(verdict_counts),
        "severity_counts": dict(severity_counts),
        "accepted_use_counts": dict(accepted_use_counts),
        "top_accepted_uses": top_counts(accepted_use_counts),
        "top_accepted_files": top_counts(accepted_file_counts),
        "accepted_comments": compact_entries(entries, "accept"),
        "rejected_comments": compact_entries(entries, "reject"),
        "policy_comments": compact_entries(entries, "policy"),
        "guidance": {
            "accepted_comments": (
                "These are validated implementation or workflow issues that can inform prompt tuning, "
                "triage calibration, or future evidence-backed corpus work."
            ),
            "rejected_comments": (
                "These comments should not be treated as real bugs without stronger proof."
            ),
            "policy_comments": (
                "These comments reflect workflow or learning-policy choices and should stay outside the main bug corpus."
            ),
        },
    }


def main() -> int:
    args = parse_args()
    repo_root = repo_root_from_script()
    input_path = resolve_path(repo_root, args.input)
    output_path = resolve_output_path(repo_root, args.output, args.allow_outside_artifacts)

    entries = require_entries(load_json(input_path))
    summary = build_summary(input_path, entries)
    write_json(output_path, summary)

    print(f"Calibration input: {input_path}")
    print(f"Calibration summary: {output_path}")
    print(
        "Accepted / rejected / policy counts: "
        f"{summary['verdict_counts'].get('accept', 0)} / "
        f"{summary['verdict_counts'].get('reject', 0)} / "
        f"{summary['verdict_counts'].get('policy', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
