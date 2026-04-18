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

## Current Phase 2 Status

- repo copy is the maintained edit location
- one-way repo-to-installed sync now lives at `scripts/sync_skill_to_codex.ps1`
- destination deletes remain intentionally manual for now
- next sync hardening should add verification before any mirror-delete mode

## Phase 3

- formalize benchmark workflows
- add regression gates for critical and high misses
- document how Codex should invoke bundled scripts during review
- make the GitHub PR review lane a first-class input to skill improvement
- document how this repo should ingest future missed-review cases from linked GitHub repos

## Phase 4

- optionally add CI or packaging only after the local workflow is stable
- optionally add GitHub-facing automation only after the local review and scoring loop is stable
