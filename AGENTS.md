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

## Validation

- Run relevant script validation for any touched Python helper.
- Run repo-local checks when they exist.
- State clearly what was validated and what was not validated.

## Project Boundary

- Bundled scripts are part of the skill project when they make the skill repeatable.
- Avoid unnecessary external dependencies.
- Keep Codex-native usage as the default path; do not require separate API automation unless the task explicitly asks for external orchestration.
