# Roadmap

## Phase 1

- create dedicated repo
- document project boundary
- document relationship to installed skill
- copy the installed skill into the repo under a clean source layout

## Phase 2

- define canonical source-of-truth rules
- add sync workflow between the repo copy and the installed runtime copy
- add lightweight validation commands
- scaffold the plugin container that will own the skill long-term

## Current Phase 2 Status

- repo copy is the maintained edit location
- plugin scaffold now exists at `plugins/codex-review`
- one-way repo-to-installed sync now lives at `scripts/sync_skill_to_codex.ps1`
- destination deletes remain intentionally manual for now
- next sync hardening should add verification before any mirror-delete mode

## Phase 3

- formalize benchmark workflows
- add regression gates for critical and high misses
- document how Codex should invoke bundled scripts during review
- make the GitHub PR review lane a first-class input to skill improvement
- document how this repo should ingest future missed-review cases from linked GitHub repos
- start moving GitHub-facing workflows behind plugin-owned interfaces instead of loose repo scripts

## Next Execution Plan

- implement the [GitHub Intake Plan](github-intake-plan.md) as the first plugin-owned workflow
- keep v1 proposal-only and non-destructive
- define the normalized schema before adding direct GitHub-backed writes

## Phase 4

- optionally add CI or packaging only after the local workflow is stable
- optionally add GitHub-facing automation only after the local review and scoring loop is stable
- add plugin install/runtime documentation once the local plugin shape is stable
