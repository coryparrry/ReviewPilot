---
name: autonomous-review-cycle
description: Run the ReviewPilot automation loop for this repo: local review, bounded repair handoff, optional GitHub miss intake, and small hardening batches.
---

# Autonomous Review Cycle

Use this skill when Codex should run ReviewPilot as an automation workflow instead of a one-off review.

This skill is the orchestration layer.
The review standard still comes from `$bug-hunting-code-review`.

## What This Skill Does

Use it when Codex should:

1. run a local review
2. prepare a bounded repair handoff
3. ingest GitHub review misses through the plugin's read-only boundary
4. learn safely into the probationary lane
5. run a small external hardening batch
6. leave a compact automation summary

## Safety Rules

- Keep GitHub access read-only.
- Default to repair handoff, not automatic repo edits.
- Default GitHub learning into the probationary lane only.
- Do not auto-promote into the primary corpus by default.
- Do not widen the review standard here; reuse `$bug-hunting-code-review`.
- Treat Hugging Face as benchmark pressure, not direct corpus-writing automation.

## Preferred Entry Point

Use the wrapper when possible:

```sh
python "./plugins/codex-review/scripts/run_automation_cycle.py" --repo .
```

That wrapper can:
- run the local review
- prepare the bounded repair handoff
- optionally run GitHub intake
- optionally compare against live GitHub misses
- optionally auto-learn approved probationary cases
- run a small Hugging Face hardening batch
- write `automation-summary.json`

## Default Automation Sequence

When you need the steps explicitly, use this order:

1. Local review

```sh
python "./plugins/codex-review/scripts/run_codex_review.py" --repo . --base origin/main
```

2. Bounded repair handoff

```sh
python "./plugins/codex-review/scripts/run_review_fix.py" --repo . --repair-plan "<repair-plan.json>" --finding-index 1
```

3. Capture GitHub MCP feedback when PR context exists

```sh
python "./plugins/codex-review/scripts/capture_github_mcp_feedback.py" --repo owner/name --pr 123 --kind review_threads --input "<tool-output.json>"
```

4. Run intake and gated learning

```sh
python "./plugins/codex-review/scripts/run_github_intake_pipeline.py" --repo owner/name --pr 123 --raw-input "<captured-artifact.json>" --raw-format github_mcp_review_threads --score-review-artifacts "<review-run-dir>" --gate-candidates --apply-target probationary --apply-mode auto
```

5. Run a small hardening batch

```sh
python "./plugins/codex-review/skills/bug-hunting-code-review/scripts/run_hf_hardening_cycle.py" --repo . --offset 0 --length 3
```

## User-Facing Language

Prefer skill names and wrapper entrypoints, not long script lists.

Use:
- `$bug-hunting-code-review` for one-off reviews
- `$autonomous-review-cycle` for recurring review and learning workflows

If a user wants a recurring automation, describe it in plain language:

- inspect recent PR review comments
- compare them against ReviewPilot review artifacts
- auto-learn only gated probationary misses
- summarize what was learned and what still needs human review

## Non-Goals

- do not auto-apply multi-finding repair passes by default
- do not make GitHub writes part of the normal automation path
- do not treat this skill as a replacement for the review posture itself
