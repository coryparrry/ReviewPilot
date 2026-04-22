from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name: str, relative_path: str) -> ModuleType:
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {module_path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


approve_quality_learning_candidates = load_module(
    "approve_quality_learning_candidates_test",
    "plugins/codex-review/scripts/approve_quality_learning_candidates.py",
)
propose_review_repairs = load_module(
    "propose_review_repairs_test",
    "plugins/codex-review/scripts/propose_review_repairs.py",
)


def test_finding_is_auto_approvable_skips_non_dict_review_match() -> None:
    finding_is_auto_approvable = cast(
        Callable[[dict[str, Any]], bool],
        getattr(
            approve_quality_learning_candidates, "finding_is_auto_approvable"
        ),
    )
    finding: dict[str, Any] = {
        "gap_classification": "corpus-gap",
        "represented_in_corpus": False,
        "represented_in_calibration": False,
        "review_match": "bad-shape",
    }

    assert finding_is_auto_approvable(finding) is False


def test_finding_is_auto_approvable_skips_malformed_overlap_values() -> None:
    finding_is_auto_approvable = cast(
        Callable[[dict[str, Any]], bool],
        getattr(
            approve_quality_learning_candidates, "finding_is_auto_approvable"
        ),
    )
    finding: dict[str, Any] = {
        "gap_classification": "corpus-gap",
        "represented_in_corpus": False,
        "represented_in_calibration": False,
        "review_match": {
            "matched": False,
            "expectation_overlap": "not-a-number",
            "title_overlap": 0.1,
        },
    }

    assert finding_is_auto_approvable(finding) is False


def test_parse_link_target_accepts_angle_bracket_paths_with_spaces() -> None:
    parse_link_target = cast(
        Callable[[str], dict[str, Any] | None],
        getattr(propose_review_repairs, "parse_link_target"),
    )

    parsed = parse_link_target("</tmp/Some Dir/file.py:12>")

    assert parsed == {
        "file": "/tmp/Some Dir/file.py",
        "start": 12,
        "end": 12,
    }
