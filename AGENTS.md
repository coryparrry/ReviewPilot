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

For non-trivial engineering work, use `$agent-team-orchestrator` at `C:\Users\coryp\.codex\skills\agent-team-orchestrator` to decide when and how to delegate.

Apply these rules:
- Keep the main agent on the critical path. The main agent owns user communication, synthesis, final decisions, and any immediate blocking step.
- Use subagents only for bounded sidecar tasks where delegation improves parallelism, context isolation, independent review, or focused validation.
- Default to `model: "gpt-5.4-mini"` for subagents unless the selected support agent intentionally uses another approved model.
- Do not fork or pass the full thread by default.
- Prefer `fork_context: false` and pass only the minimum context needed: a short task summary plus the exact files, diffs, paths, symbols, commands, or artifacts required for the task.
- Use full-thread context only when a shorter context would materially risk correctness.
- Keep subagents read-only unless edits are specifically needed.
- Do not delegate work that is too broad, ambiguous, or context-heavy for the selected subagent model; keep that work on the main agent.
- Prefer several small, well-scoped subagents over one vague general-purpose subagent.
- Do not delegate trivial work or urgent blocking work that the main agent can complete faster directly.
- Avoid overlapping write ownership across concurrent subagents.
- Define the integration point before spawning a subagent: what result is needed back, how it will be used, and what happens if the result is uncertain.
- If spawning fails, fall back locally in the same role mode, mention it once, and stop opportunistic spawn retries for that turn unless the failure reason materially changes.

Core role modes:
- `Explore scout`: read-only repo digging, dependency tracing, source-of-truth discovery, and evidence gathering.
- `Planner`: decomposition only.
- `Reviewer`: correctness, architecture drift, security smell, duplicated-logic drift, and missing-test review.
- `Validator`: focused lint, typecheck, test, build, repro, or browser verification.
- `Handoff summariser`: compress subagent outputs into a compact parent-ready handoff.

Available support agents:
- `context-manager`: builds compact context packets
- `code-mapper`: traces real code paths and ownership boundaries
- `knowledge-synthesizer`: merges overlapping delegate outputs
- `docs-researcher`: verifies docs-backed API and framework behavior
- `build-engineer`: isolates build, bundler, compiler, and CI issues
- `test-automator`: adds focused regression coverage
- `documentation-engineer`: updates docs to match real code and workflows
- `ai-engineer`: handles model-backed feature and orchestration work
- `backend-developer`: bounded backend implementation on `gpt-5.4-mini`
- `frontend-developer`: bounded frontend implementation on `gpt-5.4-mini`
- `fullstack-developer`: bounded end-to-end implementation, intentionally on `gpt-5.4`
- `reviewer`: stronger independent review pass, intentionally on `gpt-5.4`
- `debugger`: root-cause isolation for subtle bugs, intentionally on `gpt-5.4`

Subagent prompts should be short, explicit, and bounded. Each subagent task should specify:
- role
- task
- scope
- relevant context
- deliverable
- stop condition

## Validation

- Run relevant script validation for any touched Python helper.
- Run repo-local checks when they exist.
- State clearly what was validated and what was not validated.

## Project Boundary

- Bundled scripts are part of the skill project when they make the skill repeatable.
- Avoid unnecessary external dependencies.
- Keep Codex-native usage as the default path; do not require separate API automation unless the task explicitly asks for external orchestration.
