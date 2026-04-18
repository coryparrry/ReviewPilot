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

- For this workstream, subagents should always use `gpt-5.4-mini`.

Use subagents for non-trivial work that benefits from parallelism, context isolation, or independent verification. Prefer them when the task has multiple independent questions, needs read-only repo exploration, would benefit from a separate review or validation pass, or would otherwise flood the main agent's context with noisy intermediate output.

Keep the main agent on the critical path. It should own user communication, final decisions, synthesis, and any immediate blocking step. Delegate bounded sidecar tasks with clear deliverables and stop conditions.

Default role split:

- Explore scout: read-only codebase digging and source-of-truth discovery.
- Planner: decomposition only for large or ambiguous tasks.
- Reviewer: correctness, architecture drift, security smell, and test-gap review.
- Validator: focused lint, test, build, or browser verification.
- Handoff summariser: compresses subagent output into a compact parent-ready summary.

Do not use subagents for trivial single-file work, tasks that are faster to do than explain, or urgent blocking work the main agent can complete directly. Prefer several small, well-scoped subagents over one vague general-purpose delegate.

## Validation

- Run relevant script validation for any touched Python helper.
- Run repo-local checks when they exist.
- State clearly what was validated and what was not validated.

## Project Boundary

- Bundled scripts are part of the skill project when they make the skill repeatable.
- Avoid unnecessary external dependencies.
- Keep Codex-native usage as the default path; do not require separate API automation unless the task explicitly asks for external orchestration.
