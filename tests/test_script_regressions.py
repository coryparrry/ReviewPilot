from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import pytest  # type: ignore[import-not-found,unused-ignore]

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
run_codex_review = load_module(
    "run_codex_review_test",
    "plugins/codex-review/scripts/run_codex_review.py",
)
triage_pr_queue = load_module(
    "triage_pr_queue_test",
    "plugins/codex-review/scripts/triage_pr_queue.py",
)
run_public_coderabbit_calibration = load_module(
    "run_public_coderabbit_calibration_test",
    "plugins/codex-review/scripts/run_public_coderabbit_calibration.py",
)
ingest_github_review_feedback = load_module(
    "ingest_github_review_feedback_test",
    "plugins/codex-review/scripts/ingest_github_review_feedback.py",
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
        Callable[[dict[str, Any], str], str], run_pre_pr_review.render_surface_scan
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


def test_run_surface_scan_invokes_expected_json_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    skill_dir = tmp_path / "skill"
    repo = tmp_path / "repo"
    (skill_dir / "scripts").mkdir(parents=True)
    repo.mkdir()

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout='{"risk_hits": []}')

    monkeypatch.setattr(run_pre_pr_review.subprocess, "run", fake_run)

    payload = run_pre_pr_review.run_surface_scan(
        skill_dir, repo, "origin/main", "changes"
    )

    assert payload == {"risk_hits": []}
    assert len(calls) == 1
    assert calls[0]["cmd"] == [
        sys.executable,
        str(skill_dir / "scripts" / "review_surface_scan.py"),
        "--repo",
        str(repo),
        "--mode",
        "changes",
        "--json",
        "--base",
        "origin/main",
    ]
    assert calls[0]["cwd"] == repo
    assert calls[0]["check"] is True


def test_render_miss_calibration_section_is_compact_without_live_focus() -> None:
    render_miss_calibration_section = cast(
        Callable[[Path, Path | None], str],
        run_pre_pr_review.render_miss_calibration_section,
    )
    skill_dir = (
        REPO_ROOT / "plugins" / "codex-review" / "skills" / "bug-hunting-code-review"
    )

    rendered = render_miss_calibration_section(skill_dir, None)

    assert "Durable miss patterns worth preserving:" in rendered
    assert "Accepted CodeRabbit comment patterns worth preserving:" not in rendered
    assert "Public CodeRabbit miss patterns worth preserving:" not in rendered


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


def test_scan_risks_flags_optimistic_rollback_gap() -> None:
    scan_risks = cast(
        Callable[..., list[dict[str, str]]],
        getattr(review_surface_scan, "scan_risks"),
    )
    text = """
    const prev = slides;
    setSlides(reordered);
    const result = await reorderHeroSlides(reordered.map((s) => s.id));
    if (result?.error) {
      setSlides(prev);
      setActionError(result.error);
    }
    """

    risks = scan_risks(text, code_like_change_present=True)
    keys = {risk["key"] for risk in risks}

    assert "optimistic-rollback" in keys


def test_ingest_classifies_optimistic_rollback_comment() -> None:
    classify_comment = cast(
        Callable[[str, str | None], tuple[str, str, str]],
        ingest_github_review_feedback.classify_comment,
    )

    category, severity, confidence = classify_comment(
        "Rollback is only triggered when the action returns { error }. "
        "If reorderHeroSlides throws, optimistic state is kept. "
        "Catch exceptions and restore prev too.",
        "components/admin/hero-slide-list.tsx",
    )

    assert (category, severity, confidence) == (
        "optimistic-state",
        "high",
        "high",
    )


def test_ingest_does_not_classify_transaction_comment_as_optimistic() -> None:
    classify_comment = cast(
        Callable[[str, str | None], tuple[str, str, str]],
        ingest_github_review_feedback.classify_comment,
    )

    category, _, _ = classify_comment(
        "Two concurrent activations can both pass the count check. "
        "Run the count check inside the same transaction as the insert/update write. "
        "Ensure the transaction rolls back on error.",
        "lib/actions/admin-hero.ts",
    )

    assert category != "optimistic-state"


def test_ingest_classifies_toctou_transaction_comment() -> None:
    classify_comment = cast(
        Callable[[str, str | None], tuple[str, str, str]],
        ingest_github_review_feedback.classify_comment,
    )

    category, severity, confidence = classify_comment(
        "These are TOCTOU checks right now. Two concurrent activations can both "
        "pass the count check and end up with more than 5 active slides. "
        "Run the count check inside the same transaction as the write.",
        "lib/actions/admin-hero.ts",
    )

    assert (category, severity, confidence) == (
        "concurrency-atomicity",
        "high",
        "high",
    )


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


def test_recommend_review_depth_prefers_quick_for_medium_risk_contract_change() -> None:
    recommend_review_depth = cast(
        Callable[..., str],
        getattr(triage_pr_queue, "recommend_review_depth"),
    )

    depth = recommend_review_depth(
        total_score=4,
        risk_hits=[{"severity": "medium"}],
        layer_counts={"contracts-types": 1},
        code_files_changed=1,
    )

    assert depth == "quick"


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


def test_recommendation_summary_records_decision_codes() -> None:
    recommendation_summary = cast(
        Callable[..., dict[str, Any]],
        getattr(triage_pr_queue, "recommendation_summary"),
    )

    summary = recommendation_summary(
        recommended_depth="deep",
        total_score=18,
        risk_hits=[{"severity": "high"}],
        layer_counts={"workflow-runtime": 1, "contracts-types": 1},
        code_files_changed=2,
    )

    assert summary["primary_reason"]
    assert "workflow-runtime" in summary["reason_codes"]
    assert "high-risk-plus-critical-layer" in summary["reason_codes"]


def test_recommend_review_settings_match_depth_and_score() -> None:
    recommend_review_settings = cast(
        Callable[[str, int], dict[str, Any]],
        getattr(triage_pr_queue, "recommend_review_settings"),
    )

    assert recommend_review_settings("deep", 18) == {
        "depth": "deep",
        "max_deep_passes": 2,
        "pass_timeout_seconds": 180,
    }
    assert recommend_review_settings("deep", 25) == {
        "depth": "deep",
        "max_deep_passes": 3,
        "pass_timeout_seconds": 180,
    }
    assert recommend_review_settings("quick", 8) == {
        "depth": "quick",
        "max_deep_passes": 1,
        "pass_timeout_seconds": 120,
    }


def test_load_cached_triage_result_matches_head_oid(tmp_path: Path) -> None:
    load_cached_triage_result = cast(
        Callable[[Path, str, int, str], dict[str, Any] | None],
        triage_pr_queue.load_cached_triage_result,
    )
    summary_path = tmp_path / "artifacts" / "pr-triage" / "run" / "triage-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": triage_pr_queue.TRIAGE_SCHEMA_VERSION,
                "prs": [
                    {
                        "repo": "owner/name",
                        "pr": 123,
                        "head_oid": "abc123",
                        "recommended_depth": "quick",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cached = load_cached_triage_result(tmp_path, "owner/name", 123, "abc123")

    assert cached is not None
    assert cached["cache_hit"] is True
    assert str(cached["cache_source"]).endswith("triage-summary.json")


def test_load_cached_triage_result_skips_malformed_cached_pr(tmp_path: Path) -> None:
    summary_path = tmp_path / "artifacts" / "pr-triage" / "run" / "triage-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": triage_pr_queue.TRIAGE_SCHEMA_VERSION,
                "prs": [
                    {"repo": "owner/name", "pr": "not-a-number", "head_oid": "abc123"},
                    {
                        "repo": "owner/name",
                        "pr": 123,
                        "head_oid": "abc123",
                        "recommended_depth": "quick",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    cached = triage_pr_queue.load_cached_triage_result(
        tmp_path, "owner/name", 123, "abc123"
    )

    assert cached is not None
    assert cached["recommended_depth"] == "quick"


def test_load_cached_triage_result_skips_older_schema(tmp_path: Path) -> None:
    summary_path = tmp_path / "artifacts" / "pr-triage" / "run" / "triage-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": "codex-review.pr-triage.v1",
                "prs": [
                    {
                        "repo": "owner/name",
                        "pr": 123,
                        "head_oid": "abc123",
                        "recommended_depth": "quick",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cached = triage_pr_queue.load_cached_triage_result(
        tmp_path, "owner/name", 123, "abc123"
    )

    assert cached is None


def test_should_abort_remaining_passes_on_timeout_after_success() -> None:
    should_abort_remaining_passes = cast(
        Callable[..., bool],
        getattr(run_codex_review, "should_abort_remaining_passes"),
    )

    assert (
        should_abort_remaining_passes(
            successful_passes=1,
            reason="codex-timeout",
            attempt=1,
            max_attempts=2,
        )
        is True
    )


def test_should_not_abort_remaining_passes_before_any_success() -> None:
    should_abort_remaining_passes = cast(
        Callable[..., bool],
        getattr(run_codex_review, "should_abort_remaining_passes"),
    )

    assert (
        should_abort_remaining_passes(
            successful_passes=0,
            reason="codex-timeout",
            attempt=1,
            max_attempts=2,
        )
        is False
    )


def test_combine_pass_reviews_preserves_successful_first_pass() -> None:
    combine_pass_reviews = cast(
        Callable[[list[tuple[str, str]]], str],
        getattr(run_codex_review, "combine_pass_reviews"),
    )

    combined = combine_pass_reviews(
        [
            (
                "changed-hunks",
                """**Findings**

1. Title one
   Why this is a bug: Example.
   Evidence: Example.

**Open questions**

- None.
""",
            )
        ]
    )

    assert "**Findings**" in combined
    assert "Title one" in combined
    assert "Combined findings from: changed-hunks." in combined


def test_combine_pass_reviews_prioritizes_higher_signal_finding_titles() -> None:
    combine_pass_reviews = cast(
        Callable[[list[tuple[str, str]]], str],
        getattr(run_codex_review, "combine_pass_reviews"),
    )

    combined = combine_pass_reviews(
        [
            (
                "changed-hunks",
                """**Findings**

1. Minor cleanup issue
   Why this is a bug: Example.
   Evidence: Example.

2. Auth token can be reused after reset
   Why this is a bug: Example.
   Evidence: Example.
""",
            )
        ]
    )

    assert combined.index("Auth token can be reused after reset") < combined.index(
        "Minor cleanup issue"
    )


def test_build_review_run_summary_captures_selected_and_skipped_passes(
    tmp_path: Path,
) -> None:
    build_review_run_summary = cast(
        Callable[..., dict[str, Any]],
        getattr(run_codex_review, "build_review_run_summary"),
    )
    review_file = tmp_path / "review.md"
    review_file.write_text(
        """**Findings**

1. Queue claim can race
   Why this is a bug: Example.
   Evidence: Example.
""",
        encoding="utf-8",
    )
    args = Namespace(
        base="origin/main",
        mode="changes",
        depth="deep",
        model="gpt-5.4-mini",
        quality_comparison="artifacts/review-quality/run/quality-comparison.json",
    )

    summary = build_review_run_summary(
        run_dir=tmp_path,
        repo=tmp_path,
        head_sha="abc123",
        args=args,
        cache_hit=False,
        cache_source=None,
        selected_passes=["changed-hunks", "concurrency-state"],
        skipped_passes=[{"name": "async-helpers", "reason": "not prioritized"}],
        pass_results=[
            {
                "name": "changed-hunks",
                "status": "success",
                "attempts": 1,
                "final_reason": "ok",
                "review_file": str(review_file),
            },
            {
                "name": "concurrency-state",
                "status": "aborted-after-earlier-success",
                "attempts": 1,
                "final_reason": "codex-timeout",
                "review_file": str(tmp_path / "concurrency-state-review.md"),
            },
        ],
        review_file=review_file,
        benchmark_enabled=True,
        benchmark_json={"overall": {"score": 0.75}},
        stop_reason="codex-timeout",
        overall_notes=["preserved earlier successful pass"],
    )

    assert summary["pass_strategy"]["selected_passes"] == [
        "changed-hunks",
        "concurrency-state",
    ]
    assert summary["pass_strategy"]["skipped_passes"] == [
        {"name": "async-helpers", "reason": "not prioritized"}
    ]
    assert summary["cache"]["hit"] is False
    assert summary["benchmark"]["completed"] is True
    assert summary["findings_summary"]["count"] == 1


def test_build_review_run_summary_markdown_mentions_cache_and_skipped_passes() -> None:
    build_review_run_summary_markdown = cast(
        Callable[[dict[str, Any]], str],
        getattr(run_codex_review, "build_review_run_summary_markdown"),
    )

    rendered = build_review_run_summary_markdown(
        {
            "requested_depth": "deep",
            "effective_strategy": "multi-pass",
            "quality_comparison_file": "artifacts/run/quality-comparison.json",
            "cache": {"hit": True, "source": "/tmp/run"},
            "pass_strategy": {
                "selected_passes": ["changed-hunks"],
                "skipped_passes": [
                    {"name": "async-helpers", "reason": "not prioritized"}
                ],
            },
            "findings_summary": {"count": 2},
            "benchmark": {"completed": False},
            "pass_results": [{"name": "changed-hunks", "status": "success"}],
            "notes": ["reused prior run"],
        }
    )

    assert "- Cache reuse: yes" in rendered
    assert "async-helpers: not prioritized" in rendered
    assert "Linked quality comparison" in rendered


def test_build_review_run_summary_markdown_mentions_incomplete_legacy_summary() -> None:
    build_review_run_summary_markdown = cast(
        Callable[[dict[str, Any]], str],
        getattr(run_codex_review, "build_review_run_summary_markdown"),
    )

    rendered = build_review_run_summary_markdown(
        {
            "requested_depth": "deep",
            "effective_strategy": "single-pass-deep",
            "cache": {"hit": False, "source": ""},
            "pass_strategy": {"selected_passes": [], "skipped_passes": []},
            "findings_summary": {"count": 0},
            "benchmark": {"completed": False},
            "notes": [],
            "summary_warning": "legacy summary metadata was not trusted",
        }
    )

    assert "- Cache reuse: no" in rendered
    assert "Summary warning: legacy summary metadata was not trusted" in rendered


def test_select_deep_pass_names_prefers_relevant_subset() -> None:
    select_deep_pass_names = cast(
        Callable[[dict[str, Any], int], list[str]],
        getattr(run_codex_review, "select_deep_pass_names"),
    )

    selected = select_deep_pass_names(
        {
            "risk_hits": [
                {"key": "request-contract"},
                {"key": "explicit-null-drift"},
            ],
            "layers": {
                "config": {"count": 1, "files": ["package.json"]},
                "tests": {"count": 1, "files": ["test/foo.ts"]},
            },
        },
        3,
    )

    assert selected == ["changed-hunks", "concurrency-state", "validation-contract"]


def test_build_pass_prompts_limits_deep_pass_count() -> None:
    build_pass_prompts = cast(
        Callable[[str, str, dict[str, Any], int], list[tuple[str, str]]],
        getattr(run_codex_review, "build_pass_prompts"),
    )

    prompts = build_pass_prompts(
        "Base prompt",
        "deep",
        {
            "risk_hits": [
                {"key": "request-contract"},
                {"key": "explicit-null-drift"},
                {"key": "queue-claim"},
            ],
            "layers": {"workflow-runtime": {"count": 1, "files": ["src/workflow.ts"]}},
        },
        2,
    )

    assert [name for name, _prompt in prompts] == ["changed-hunks", "concurrency-state"]


def test_should_continue_after_changed_hunks_when_no_findings() -> None:
    should_continue_after_pass = cast(
        Callable[..., bool],
        getattr(run_codex_review, "should_continue_after_pass"),
    )

    assert (
        should_continue_after_pass(
            pass_name="changed-hunks",
            review_text="No findings.\n\nResidual risk:\n- None.\n",
            scan_report={"risk_hits": []},
        )
        is True
    )


def test_should_stop_after_strong_first_pass() -> None:
    should_continue_after_pass = cast(
        Callable[..., bool],
        getattr(run_codex_review, "should_continue_after_pass"),
    )
    review_text = """**Findings**

1. First issue
   Why this is a bug: Example.
   Evidence: Example.

2. Second issue
   Why this is a bug: Example.
   Evidence: Example.
"""

    assert (
        should_continue_after_pass(
            pass_name="changed-hunks",
            review_text=review_text,
            scan_report={
                "risk_hits": [{"key": "request-contract", "severity": "medium"}]
            },
        )
        is False
    )


def test_should_continue_after_single_finding_when_high_risk_remains() -> None:
    should_continue_after_pass = cast(
        Callable[..., bool],
        getattr(run_codex_review, "should_continue_after_pass"),
    )
    review_text = """**Findings**

1. One issue
   Why this is a bug: Example.
   Evidence: Example.
"""

    assert (
        should_continue_after_pass(
            pass_name="changed-hunks",
            review_text=review_text,
            scan_report={
                "risk_hits": [
                    {"key": "security-boundary", "severity": "high"},
                    {"key": "queue-claim", "severity": "high"},
                ]
            },
        )
        is True
    )


def test_build_evaluation_summary_distinguishes_known_vs_novel_misses() -> None:
    build_evaluation_summary = cast(
        Callable[[list[dict[str, Any]]], dict[str, Any]],
        getattr(compare_review_quality, "build_evaluation_summary"),
    )

    summary = build_evaluation_summary(
        [
            {"gap_classification": "caught", "severity": "low"},
            {"gap_classification": "prompt-gap", "severity": "high"},
            {"gap_classification": "corpus-gap", "severity": "medium"},
        ]
    )

    assert summary["review_sufficiency"] == "needs-deeper-follow-up"
    assert summary["deeper_review_likely_helpful"] is True
    assert summary["known_blind_spot_misses"] == 1
    assert summary["novel_gap_misses"] == 1


def test_build_markdown_report_includes_evaluation_breakdowns() -> None:
    build_markdown_report = cast(
        Callable[
            [dict[str, Any], list[dict[str, Any]], list[str], dict[str, Any]], str
        ],
        getattr(compare_review_quality, "build_markdown_report"),
    )

    rendered = build_markdown_report(
        {
            "accepted_live_findings": 3,
            "caught": 1,
            "missed": 2,
            "prompt_gaps": 1,
            "corpus_gaps": 1,
            "corpus_and_calibration_gaps": 0,
            "severity_counts": {"critical": 0, "high": 1, "medium": 1, "low": 1},
            "gap_class_counts": {
                "caught": 1,
                "prompt-gap": 1,
                "corpus-gap": 1,
                "corpus-and-calibration-gap": 0,
            },
        },
        [
            {
                "gap_classification": "prompt-gap",
                "candidate_title": "Missed auth reset gap",
                "file_path": "src/auth.ts",
            }
        ],
        ["Missed auth reset gap in src/auth.ts: example"],
        {
            "review_sufficiency": "needs-deeper-follow-up",
            "deeper_review_likely_helpful": True,
        },
    )

    assert "Review sufficiency: needs-deeper-follow-up" in rendered
    assert "## Severity Breakdown" in rendered
    assert "## Gap Breakdown" in rendered


def test_triage_markdown_includes_review_command() -> None:
    build_markdown = cast(
        Callable[[list[dict[str, Any]], int], str],
        getattr(triage_pr_queue, "build_markdown"),
    )

    rendered = build_markdown(
        [
            {
                "repo": "owner/name",
                "pr": 123,
                "triage_score": 12,
                "title": "Example",
                "recommended_depth": "quick",
                "reasons": ["one", "two"],
                "checkout_hint": "gh pr checkout 123 --repo owner/name",
                "recommended_review_command": "python run_codex_review.py --depth quick",
            }
        ],
        5,
    )

    assert "Review: `python run_codex_review.py --depth quick`" in rendered


def test_triage_markdown_includes_decision_summary() -> None:
    build_markdown = cast(
        Callable[[list[dict[str, Any]], int], str],
        getattr(triage_pr_queue, "build_markdown"),
    )

    rendered = build_markdown(
        [
            {
                "repo": "owner/name",
                "pr": 123,
                "triage_score": 3,
                "title": "Docs tweak",
                "recommended_depth": "skip",
                "reasons": ["docs-only change"],
                "checkout_hint": "gh pr checkout 123 --repo owner/name",
                "recommended_review_command": "python run_codex_review.py --depth quick",
                "recommendation_summary": {
                    "primary_reason": "docs-or-config-only low-risk change",
                    "reason_codes": ["docs-only-low-risk"],
                },
            }
        ],
        5,
    )

    assert "Decision: docs-or-config-only low-risk change" in rendered
    assert "Decision codes: docs-only-low-risk" in rendered


def test_find_reusable_review_run_matches_cache_key(tmp_path: Path) -> None:
    find_reusable_review_run = cast(
        Callable[[Path, dict[str, Any]], Path | None],
        getattr(run_codex_review, "find_reusable_review_run"),
    )
    review_root = tmp_path / ".codex-review"
    run_dir = review_root / "20260422-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "review.md").write_text("review", encoding="utf-8")
    (run_dir / "review-cache-key.json").write_text(
        json.dumps({"head_sha": "abc123", "depth": "quick"}),
        encoding="utf-8",
    )

    reusable = find_reusable_review_run(
        review_root, {"head_sha": "abc123", "depth": "quick"}
    )

    assert reusable == run_dir


def test_review_cache_key_tracks_effective_benchmark_mode() -> None:
    args = Namespace(
        base="origin/main",
        mode="changes",
        depth="deep",
        model="gpt-5",
        quality_comparison=None,
        max_deep_passes=3,
        pass_timeout_seconds=180,
        no_benchmark=False,
    )

    enabled = run_codex_review.review_cache_key(args, "abc123")
    args.no_benchmark = True
    disabled = run_codex_review.review_cache_key(args, "abc123")

    assert enabled["benchmark_enabled"] is True
    assert disabled["benchmark_enabled"] is False


def test_public_coderabbit_calibration_parse_depths() -> None:
    parse_depths = cast(
        Callable[[str], list[str]],
        getattr(run_public_coderabbit_calibration, "parse_depths"),
    )

    assert parse_depths("quick, deep") == ["quick", "deep"]
    assert parse_depths("DEEP") == ["deep"]

    with pytest.raises(ValueError, match="Duplicate review depth"):
        parse_depths("quick,quick")
    with pytest.raises(ValueError, match="Invalid review depth"):
        parse_depths("quick,full")
    with pytest.raises(ValueError, match="at least one depth"):
        parse_depths(" , ")


def test_public_coderabbit_calibration_aggregate_tracks_depth_delta(
    tmp_path: Path,
) -> None:
    quick_comparison = tmp_path / "quick.json"
    deep_comparison = tmp_path / "deep.json"
    quick_comparison.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "candidate_id": "candidate-1",
                        "gap_classification": "missed",
                        "candidate_title": "Handle stale state",
                        "file_path": "src/app.py",
                        "line": 10,
                        "severity": "high",
                        "normalized_category": "state",
                        "suggested_signal_phrases": ["stale state"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    deep_comparison.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "candidate_id": "candidate-1",
                        "gap_classification": "caught",
                        "candidate_title": "Handle stale state",
                        "file_path": "src/app.py",
                        "line": 10,
                        "severity": "high",
                        "normalized_category": "state",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summarize_comparison_files = cast(
        Callable[[list[Path]], dict[str, Any]],
        run_public_coderabbit_calibration.summarize_comparison_files,
    )
    quick_vs_deep_delta = cast(
        Callable[[list[dict[str, Any]]], dict[str, Any]],
        run_public_coderabbit_calibration.quick_vs_deep_delta,
    )

    summary = summarize_comparison_files([quick_comparison])
    delta = quick_vs_deep_delta(
        [
            {
                "label": "sample",
                "repo": "owner/name",
                "pr": 123,
                "reviews": [
                    {"depth": "quick", "comparison_file": str(quick_comparison)},
                    {"depth": "deep", "comparison_file": str(deep_comparison)},
                ],
            }
        ]
    )

    assert summary["missed_count"] == 1
    assert summary["caught_count"] == 0
    assert summary["missed_by_severity"] == {"high": 1}
    assert delta["comparable_prs"] == 1
    assert delta["quick_missed_deep_caught_count"] == 1
    assert (
        delta["quick_missed_deep_caught"][0]["finding"]["candidate_id"]
        == "candidate-1"
    )


def test_public_coderabbit_calibration_resume_uses_depth_specific_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main = cast(Callable[[], int], getattr(run_public_coderabbit_calibration, "main"))
    output_dir = tmp_path / "out"
    calibration_set = tmp_path / "calibration.json"
    calibration_set.write_text(
        json.dumps([{"repo": "owner/name", "pr": 123, "label": "sample"}]),
        encoding="utf-8",
    )
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    for depth in ("quick", "deep"):
        review_run = output_dir / "reviews" / "sample" / depth / "20260422-000000"
        review_run.mkdir(parents=True)
        (review_run / "review.md").write_text(f"{depth} review", encoding="utf-8")
        (review_run / "review-cache-key.json").write_text(
            json.dumps({"head_sha": "reviewed-commit"}),
            encoding="utf-8",
        )
        comparison_dir = (
            output_dir / "comparisons" / "sample" / depth / "quality-comparison"
        )
        comparison_dir.mkdir(parents=True)
        (comparison_dir / "quality-comparison.json").write_text(
            json.dumps({"findings": [], "summary": {"depth": depth}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        run_public_coderabbit_calibration,
        "parse_args",
        lambda: Namespace(
            calibration_set=str(calibration_set),
            output_dir=str(output_dir),
            model="gpt-5.4-mini",
            depths="quick,deep",
            review_ref="comment-original",
            limit=None,
            resume=True,
        ),
    )
    monkeypatch.setattr(
        run_public_coderabbit_calibration, "repo_root", lambda _cwd: tmp_path
    )
    monkeypatch.setattr(
        run_public_coderabbit_calibration,
        "ensure_repo_clone",
        lambda _root, _github_repo: repo_dir,
    )
    monkeypatch.setattr(
        run_public_coderabbit_calibration,
        "pr_metadata",
        lambda _repo_dir, _github_repo, _pr_number: {"baseRefName": "main"},
    )
    monkeypatch.setattr(
        run_public_coderabbit_calibration,
        "checkout_pr",
        lambda _repo_dir, _pr_number: None,
    )
    monkeypatch.setattr(
        run_public_coderabbit_calibration,
        "checkout_review_ref",
        lambda _repo_dir, _github_repo, _pr_number, _review_ref: (
            "reviewed-commit",
            "comment-original",
        ),
    )

    def fail_run_review(*_args: Any, **_kwargs: Any) -> Path:
        raise AssertionError("resume should not run a new review")

    def fail_run_public_compare(*_args: Any, **_kwargs: Any) -> Path:
        raise AssertionError("resume should not run a new comparison")

    monkeypatch.setattr(run_public_coderabbit_calibration, "run_review", fail_run_review)
    monkeypatch.setattr(
        run_public_coderabbit_calibration, "run_public_compare", fail_run_public_compare
    )

    assert main() == 0

    aggregate = json.loads(
        (output_dir / "aggregate-summary.json").read_text(encoding="utf-8")
    )
    reviews = aggregate["results"][0]["reviews"]
    assert (
        aggregate["schema_version"]
        == "codex-review.public-coderabbit-calibration.v2"
    )
    assert [review["depth"] for review in reviews] == ["quick", "deep"]
    assert aggregate["results"][0]["review_head_sha"] == "reviewed-commit"
    assert "sample/quick" in reviews[0]["review_run_dir"]
    assert "sample/deep" in reviews[1]["review_run_dir"]


def test_public_coderabbit_calibration_prefers_original_comment_commit() -> None:
    choose_original_comment_commit = cast(
        Callable[[list[dict[str, Any]]], str | None],
        run_public_coderabbit_calibration.choose_original_comment_commit,
    )

    commit = choose_original_comment_commit(
        [
            {"original_commit_id": "old-a", "commit_id": "new-a"},
            {"original_commit_id": "old-b", "commit_id": "new-b"},
            {"original_commit_id": "old-a", "commit_id": "new-c"},
        ]
    )

    assert commit == "old-a"
