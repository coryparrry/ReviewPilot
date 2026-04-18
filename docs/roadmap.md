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
- run the first live `ReviewPilot` PR through the wrapper pipeline command over fetch, ingest, propose, and apply
- keep live GitHub fetch read-only while the self-improvement loop hardens
- make `auto` the default corpus-apply mode, with `review` as the explicit no-write option
- wire before/after benchmark comparison into the wrapper when a real review output is available
- let the wrapper consume prepared `.codex-review` artifact directories directly so Codex-authored reviews can flow into scoring without manual file extraction
- let the wrapper reuse a prepared review run directory and stop after proposal generation so the full authoring loop can stay in one folder
- define the normalized schema and apply safety checks before broader automation

## Phase 4

- optionally add CI or packaging only after the local workflow is stable
- optionally add GitHub-facing automation only after the local review and scoring loop is stable
- add plugin install/runtime documentation once the local plugin shape is stable
