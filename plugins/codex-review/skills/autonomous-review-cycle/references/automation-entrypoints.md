# Automation Entrypoints

Use this file when the task is operational and you need the correct ReviewPilot workflow entrypoint.

## Full Local Automation

Use when you want the normal local review, repair handoff, optional GitHub intake, and hardening loop.

```sh
python "./plugins/codex-review/scripts/run_automation_cycle.py" --repo .
```

## Local Review Only

Use when you want the plugin-owned local review runner.

```sh
python "./plugins/codex-review/scripts/run_codex_review.py" --repo . --base origin/main
```

## Bounded Repair Handoff

Use when you want the next safe step from a single repair finding.

```sh
python "./plugins/codex-review/scripts/run_review_fix.py" --repo . --repair-plan "<repair-plan.json>" --finding-index 1
```

## GitHub MCP Capture

Use when PR review feedback has already been read through the GitHub MCP boundary and needs to be turned into a pipeline artifact.

```sh
python "./plugins/codex-review/scripts/capture_github_mcp_feedback.py" --repo owner/name --pr 123 --kind review_threads --input "<tool-output.json>"
```

## GitHub Intake And Gated Learning

Use when you want ingest, propose, compare, gate, and probationary apply behavior from a captured artifact.

```sh
python "./plugins/codex-review/scripts/run_github_intake_pipeline.py" --repo owner/name --pr 123 --raw-input "<captured-artifact.json>" --raw-format github_mcp_review_threads --score-review-artifacts "<review-run-dir>" --gate-candidates --apply-target probationary --apply-mode auto
```

## Public PR Comparison

Use when you want comparison-only behavior against a public PR, with optional probationary learning.

```sh
python "./plugins/codex-review/scripts/run_public_pr_quality_cycle.py" --repo owner/name --pr 123 --review-artifacts ".codex-review"
```

## Batch PR Triage

Use when you have many PRs and want a cheap ranked queue before spending Codex review budget.

```sh
python "./plugins/codex-review/scripts/triage_pr_queue.py" --pr owner/name#123 --pr owner/name#124
```

## Hardening Batch

Use when you want a small external hardening batch only.

```sh
python "./plugins/codex-review/skills/bug-hunting-code-review/scripts/run_hf_hardening_cycle.py" --repo . --offset 0 --length 3
```
