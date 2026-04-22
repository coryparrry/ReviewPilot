from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import pytest  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name: str, relative_path: str) -> ModuleType:
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
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
compare_review_quality = load_module(
    "compare_review_quality_test",
    "plugins/codex-review/scripts/compare_review_quality.py",
)
run_pre_pr_review = load_module(
    "run_pre_pr_review_test",
    "plugins/codex-review/skills/bug-hunting-code-review/scripts/run_pre_pr_review.py",
)
review_surface_scan = load_module(
    "review_surface_scan_test",
    "plugins/codex-review/skills/bug-hunting-code-review/scripts/review_surface_scan.py",
)
run_public_pr_quality_cycle = load_module(
    "run_public_pr_quality_cycle_test",
    "plugins/codex-review/scripts/run_public_pr_quality_cycle.py",
)
triage_pr_queue = load_module(
    "triage_pr_queue_test",
    "plugins/codex-review/scripts/triage_pr_queue.py",
)


def test_finding_is_auto_approvable_skips_non_dict_review_match() -> None:
    finding_is_auto_approvable = cast(
        Callable[[dict[str, Any]], bool],
        getattr(approve_quality_learning_candidates, "finding_is_auto_approvable"),
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
        getattr(approve_quality_learning_candidates, "finding_is_auto_approvable"),
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


def test_parse_link_target_skips_url_style_colon_targets() -> None:
    parse_link_target = cast(
        Callable[[str], dict[str, Any] | None],
        getattr(propose_review_repairs, "parse_link_target"),
    )

    assert parse_link_target("http://localhost:3000") is None


def test_compare_review_quality_resolves_relative_output_dir_from_repo_root() -> None:
    resolve_output_dir = cast(
        Callable[[Path, str | None, Path, bool], Path],
        getattr(compare_review_quality, "resolve_output_dir"),
    )
    repo_root = REPO_ROOT
    proposal_path = repo_root / "artifacts" / "example-proposal.json"

    resolved = resolve_output_dir(
        repo_root, "artifacts/review-quality/custom-run", proposal_path, False
    )

    assert (
        resolved
        == (repo_root / "artifacts" / "review-quality" / "custom-run").resolve()
    )


def test_candidate_map_drops_ambiguous_file_and_title_pairs() -> None:
    candidate_map = cast(
        Callable[[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]],
        getattr(compare_review_quality, "candidate_map"),
    )
    payload: dict[str, Any] = {
        "candidates": [
            {
                "id": "cand-1",
                "title": "Same title",
                "review_notes": {"file_path": "src/app.py"},
            },
            {
                "id": "cand-2",
                "title": "Same title",
                "review_notes": {"file_path": "src/app.py"},
            },
        ]
    }

    assert candidate_map(payload) == {}


def test_record_key_matches_truncated_candidate_titles() -> None:
    record_key = cast(
        Callable[[dict[str, Any]], tuple[str, str]],
        getattr(compare_review_quality, "record_key"),
    )
    candidate_map = cast(
        Callable[[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]],
        getattr(compare_review_quality, "candidate_map"),
    )
    long_title = "X" * 120
    record = {"file_path": "src/app.py", "candidate_title": long_title}
    payload: dict[str, Any] = {
        "candidates": [
            {
                "id": "cand-1",
                "title": long_title[:100],
                "review_notes": {"file_path": "src/app.py"},
            }
        ]
    }

    assert candidate_map(payload)[record_key(record)]["id"] == "cand-1"


def test_calibration_matches_requires_semantic_overlap_not_same_file_alone() -> None:
    calibration_matches = cast(
        Callable[[dict[str, Any], list[dict[str, Any]]], bool],
        getattr(compare_review_quality, "calibration_matches"),
    )
    record: dict[str, Any] = {
        "file_path": "src/service.ts",
        "candidate_title": "Handle inactive owner records",
        "candidate_summary": "Bootstrap should reactivate the local owner account.",
    }
    calibration_entries = [
        {
            "verdict": "accept",
            "file": "src/service.ts",
            "summary": "Rename the helper for readability.",
        }
    ]

    assert calibration_matches(record, calibration_entries) is False


def test_run_pre_pr_review_resolves_quality_comparison_from_repo_root() -> None:
    resolve_repo_path = cast(
        Callable[[Path, str | None], Path | None],
        getattr(run_pre_pr_review, "resolve_repo_path"),
    )

    resolved = resolve_repo_path(
        REPO_ROOT, "artifacts/review-quality/run/quality-comparison.json"
    )

    assert (
        resolved
        == (
            REPO_ROOT
            / "artifacts"
            / "review-quality"
            / "run"
            / "quality-comparison.json"
        ).resolve()
    )


def test_render_surface_scan_highlights_risk_prompts_and_questions() -> None:
    render_surface_scan = cast(
        Callable[[dict[str, Any], str], str],
        getattr(run_pre_pr_review, "render_surface_scan"),
    )

    rendered = render_surface_scan(
        {
            "changed_file_count": 3,
            "layers": {
                "service": {"count": 1, "files": ["src/service.py"]},
                "tests": {"count": 2, "files": ["tests/test_service.py"]},
            },
            "risk_hits": [
                {
                    "severity": "high",
                    "title": "Queue-claim or duplicate-dispatch risk",
                    "check": "Verify the work item is claimed atomically before releasing control.",
                }
            ],
            "adjacent_paths_to_inspect": ["src/workflow/", "tests/"],
            "required_questions": [
                "Which fallback path could overwrite an explicit cleared value?"
            ],
        },
        "deep",
    )

    assert "Surface scan summary:" in rendered
    assert "Changed layers: service=1, tests=2" in rendered
    assert "[high] Queue-claim or duplicate-dispatch risk" in rendered
    assert "Adjacent paths worth opening:" in rendered
    assert "Questions to explicitly answer before you stop:" in rendered


def test_scan_risks_flags_fallback_null_and_queue_claim_patterns() -> None:
    scan_risks = cast(
        Callable[..., list[dict[str, str]]],
        getattr(review_surface_scan, "scan_risks"),
    )
    text = """
    const ownerAgent = fallbackOwner ?? null;
    const runtimeSession = currentSession ?? lastSession;
    if (queuedHeartbeat) {
      await processDueHeartbeats();
      enqueueWake(queueItem);
    }
    """

    risks = scan_risks(text, code_like_change_present=True)
    keys = {risk["key"] for risk in risks}

    assert "fail-open-fallback" in keys
    assert "explicit-null-drift" in keys
    assert "queue-claim" in keys


def test_public_pr_quality_cycle_requires_review_artifact_for_auto_learning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main = cast(Callable[[], int], getattr(run_public_pr_quality_cycle, "main"))

    monkeypatch.setattr(
        run_public_pr_quality_cycle,
        "parse_args",
        lambda: Namespace(
            repo="owner/name",
            pr=123,
            source="rest",
            review_file=None,
            review_artifacts=None,
            output_dir=str(tmp_path / "out"),
            auto_learn_probationary=True,
            quality_apply_mode="auto",
        ),
    )
    monkeypatch.setattr(run_public_pr_quality_cycle, "repo_root", lambda _cwd: tmp_path)

    with pytest.raises(
        ValueError,
        match="--auto-learn-probationary requires --review-file or --review-artifacts.",
    ):
        main()


def test_parse_pr_spec_accepts_repo_hash_number_and_url() -> None:
    parse_pr_spec = cast(
        Callable[[str], tuple[str, int]],
        getattr(triage_pr_queue, "parse_pr_spec"),
    )

    assert parse_pr_spec("owner/name#123") == ("owner/name", 123)
    assert parse_pr_spec("https://github.com/owner/name/pull/456") == (
        "owner/name",
        456,
    )


def test_load_pr_queue_accepts_json_entries_and_dedupes(tmp_path: Path) -> None:
    load_pr_queue = cast(
        Callable[[list[str], str | None], list[tuple[str, int]]],
        getattr(triage_pr_queue, "load_pr_queue"),
    )
    payload = {
        "prs": [
            {"repo": "owner/name", "pr": 10},
            "owner/name#10",
            "another/repo#12",
        ]
    }
    queue_path = tmp_path / "prs.json"
    queue_path.write_text(json.dumps(payload), encoding="utf-8")

    queue = load_pr_queue(["owner/name#10"], str(queue_path))

    assert queue == [("owner/name", 10), ("another/repo", 12)]


def test_recommend_review_depth_prefers_deep_for_high_signal_workflow_changes() -> None:
    recommend_review_depth = cast(
        Callable[..., str],
        getattr(triage_pr_queue, "recommend_review_depth"),
    )

    depth = recommend_review_depth(
        total_score=9,
        risk_hits=[{"severity": "high"}],
        layer_counts={"workflow-runtime": 1},
        code_files_changed=1,
    )

    assert depth == "deep"


def test_recommend_review_depth_skips_docs_only_low_score_changes() -> None:
    recommend_review_depth = cast(
        Callable[..., str],
        getattr(triage_pr_queue, "recommend_review_depth"),
    )

    depth = recommend_review_depth(
        total_score=2,
        risk_hits=[],
        layer_counts={"docs": 1},
        code_files_changed=0,
    )

    assert depth == "skip"
