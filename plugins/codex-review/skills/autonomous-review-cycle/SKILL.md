---
name: autonomous-review-cycle
description: Run the full Codex Review automation loop for this repo: local review, repair handoff, optional GitHub miss intake, and external hardening. Use when Codex automation should drive the plugin end to end rather than invoking each script manually.
---

# Autonomous Review Cycle

Use this skill when Codex should run the plugin as an automation workflow, not just as a one-off review helper.

The review standard still comes from `$bug-hunting-code-review`.
This skill is the execution layer that wires the plugin-owned scripts together in a safe order.

## Purpose

This skill exists so a Codex automation can:

1. review the current repo changes
2. generate a structured repair handoff
3. ingest real GitHub review misses through the plugin's read-only MCP boundary
4. learn safely into the probationary lane
5. run a small external hardening batch from Hugging Face
6. leave a compact summary artifact for follow-up

## Safety Boundary

- The review standard stays in `$bug-hunting-code-review`.
- This skill should orchestrate existing scripts. It should not replace the review posture with a new prompt.
- GitHub access must stay read-only.
- Repair execution must stay bounded to one finding at a time unless the user explicitly asks for broader edits.
- Default to a repair handoff, not automatic code edits.
- Default GitHub learning into the probationary lane only.
- Treat the Hugging Face lane as benchmark pressure, not direct corpus-writing automation.

## Default Automation Path

When used in a Codex automation, prefer this sequence:

1. Run the local review:

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py --repo . --base origin/main
```

2. Prepare the bounded fix handoff from the generated `repair-plan.json`:

```powershell
python .\plugins\codex-review\scripts\run_review_fix.py --repo . --repair-plan "<repair-plan.json>" --finding-index 1
```

3. If the automation has GitHub PR context, use the plugin's GitHub MCP connector in read-only mode to fetch PR comments or review threads, capture them with:

```powershell
python .\plugins\codex-review\scripts\capture_github_mcp_feedback.py --repo owner/name --pr 123 --kind review_threads --input "<tool-output.json>"
```

4. Feed the captured artifact into the intake pipeline with the review artifacts from step 1:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py --repo owner/name --pr 123 --raw-input "<captured-artifact.json>" --raw-format github_mcp_review_threads --score-review-artifacts "<review-run-dir>" --gate-candidates --apply-target probationary --apply-mode auto
```

5. Run a small external hardening batch:

```powershell
python .\plugins\codex-review\skills\bug-hunting-code-review\scripts\run_hf_hardening_cycle.py --repo . --offset 0 --length 3
```

## Unified Wrapper

If you want the local shell-side orchestration in one command, use:

```powershell
python .\plugins\codex-review\scripts\run_automation_cycle.py --repo .
```

That wrapper:

- runs the local review
- prepares the bounded repair handoff
- can run GitHub intake if `--github-repo`, `--github-pr`, and `--github-raw-input` are provided
- runs a small Hugging Face hardening batch unless you skip it
- writes `automation-summary.json` under `artifacts/automation-runs/`

## For Codex Automations

When creating a Codex automation prompt, tell Codex to:

- load `$autonomous-review-cycle`
- use `$bug-hunting-code-review` as the review standard
- use the plugin's GitHub MCP boundary only in read-only mode
- write outputs into repo-local artifact directories
- summarize:
  - review findings
  - repair handoff path
  - GitHub learning result
  - hardening recall result
  - what should be improved next

## Non-Goals

- do not auto-promote probationary cases into the primary corpus by default
- do not auto-apply multi-finding code fixes by default
- do not let automation widen GitHub access beyond read-only
