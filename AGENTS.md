# Agent Rules

Inspect before editing.

## Scope

- This repo is for the Codex review-skill project itself.
- Keep changes tightly scoped to the skill, its scripts, benchmarks, and docs.
- Do not treat the installed skill under `.codex/skills/` as automatically editable from this repo unless the task explicitly requires sync or migration work.

## Working Rules

- Prefer the minimum correct practical change.
- Preserve existing conventions unless there is a clear reason to improve them.
- Keep docs aligned with the current project state.
- If the repo and the installed skill diverge, note the divergence explicitly instead of silently assuming one is canonical.

## Context Use

Be conscious of context-window usage. When reading long documents, large generated skills, or doing review-heavy analysis across many files, prefer subagents so the main thread stays compact.

## Subagent Use

For non-trivial engineering work, use `$agent-team-orchestrator` from the local Codex skill runtime to decide when and how to delegate.

Apply these rules:
- Keep the main agent on the critical path. The main agent owns user communication, synthesis, final decisions, and any immediate blocking step.
- Use subagents for bounded sidecar tasks only when delegation improves parallelism, context isolation, or independent verification.
- Always spawn subagents with `model: "gpt-5.4-mini"`.
- Do not fork or pass the full thread by default.
- Prefer `fork_context: false` and pass only the minimum context needed: a short task summary plus the exact files, diffs, paths, symbols, commands, or artifacts required for the task.
- Use full-thread context only when a shorter context would materially risk correctness.
- Keep subagents read-only unless edits are specifically needed.
- Do not delegate work that is too ambiguous, too broad, or too context-heavy for `gpt-5.4-mini`; keep that work on the main agent.
- Prefer several small, well-scoped subagents over one vague general-purpose subagent.
- Do not delegate trivial single-file work or urgent blocking work that the main agent can complete faster directly.

Use these roles:
- `Explore scout`: read-only repo digging, dependency tracing, and source-of-truth discovery.
- `Planner`: decomposition only.
- `Reviewer`: correctness, architecture drift, security smell, duplicated-logic drift, and missing-test review.
- `Validator`: focused lint, typecheck, test, build, repro, or browser verification.
- `Handoff summariser`: compress subagent outputs into a compact parent-ready handoff.

Subagent prompts should be short, explicit, and bounded. Each subagent task should specify scope, allowed actions, deliverable, and stop condition.

## Validation

- Run relevant script validation for any touched Python helper.
- Run repo-local checks when they exist.
- State clearly what was validated and what was not validated.

## Project Boundary

- Bundled scripts are part of the skill project when they make the skill repeatable.
- Avoid unnecessary external dependencies.
- Keep Codex-native usage as the default path; do not require separate API automation unless the task explicitly asks for external orchestration.
