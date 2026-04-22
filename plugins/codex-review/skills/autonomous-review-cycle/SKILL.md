---
name: autonomous-review-cycle
description: Orchestrate ReviewPilot workflows by routing Codex to the right entrypoint for local review, bounded repair handoff, GitHub miss intake, probationary learning, public comparison, or hardening.
---

# Autonomous Review Cycle

Use this skill when Codex should run ReviewPilot as a workflow, not just a one-off review.

This skill is the router.
The review standard still comes from `$bug-hunting-code-review`.

## Router

Choose the smallest entrypoint that matches the task.

### 1. Full Local Automation

Use when Codex should run the normal end-to-end loop for the repo.

Route to:
- `references/automation-entrypoints.md`

Preferred entrypoint:
- `run_automation_cycle.py`

### 2. GitHub Intake And Learning

Use when the task is about:
- captured GitHub review feedback
- comparison against review artifacts
- probationary learning

Route to:
- `references/automation-entrypoints.md`

Preferred entrypoint:
- `run_github_intake_pipeline.py`

### 3. Public PR Comparison

Use when the task is:
- compare a public PR’s review comments against a local review artifact
- optionally auto-learn only the safe misses

Route to:
- `references/automation-entrypoints.md`

Preferred entrypoint:
- `run_public_pr_quality_cycle.py`

### 4. Bounded Repair Handoff

Use when the task is:
- take one review finding
- prepare the next repair step safely

Preferred entrypoint:
- `run_review_fix.py`

### 5. Hardening Only

Use when the task is:
- external benchmark pressure
- Hugging Face or SWE-bench style hardening

Preferred entrypoint:
- `run_hf_hardening_cycle.py`

## Safety Rules

- Keep GitHub access read-only.
- Default to repair handoff, not automatic repo edits.
- Default GitHub learning into the probationary lane only.
- Do not auto-promote into the primary corpus by default.
- Treat Hugging Face as benchmark pressure, not direct corpus-writing automation.

## Entry Points

For script selection and command examples, read:

- `references/automation-entrypoints.md`

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
