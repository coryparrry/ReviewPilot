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
- make the plugin MCP boundary, not ambient `gh`, the primary live GitHub access path
- add a Codex-side capture helper so GitHub connector output becomes a pipeline artifact without manual save steps

## Next Execution Plan

- implement the [GitHub Intake Plan](github-intake-plan.md) as the first plugin-owned workflow
- run the first live `ReviewPilot` PR through the wrapper pipeline command over fetch, ingest, propose, and apply
- keep live GitHub fetch read-only while the self-improvement loop hardens
- make `auto` the default corpus-apply mode, with `review` as the explicit no-write option
- wire before/after benchmark comparison into the wrapper when a real review output is available
- let the wrapper consume prepared `.codex-review` artifact directories directly so Codex-authored reviews can flow into scoring without manual file extraction
- let the wrapper reuse a prepared review run directory and stop after proposal generation so the full authoring loop can stay in one folder
- let the wrapper resume from existing shared-run artifacts instead of repeating the early read-only stages
- make MCP-shaped GitHub raw artifacts a first-class wrapper input and keep `gh` fetch as an explicit fallback only
- define the normalized schema and apply safety checks before broader automation
- gate GitHub-derived candidates into a probationary corpus before they can influence the primary GitHub corpus
- use the curated SWE-bench lane as external hardening pressure so the skill can improve without relying only on one team's historical PR misses
- keep strict benchmark scoring separate from softer probationary admission evidence so learning stays safer than raw regex matching alone
- expose one plugin-owned review runner so the review brain can actually author `review.md` and benchmark it in one command
- let the review runner self-repair only obvious review-output failures with one automatic read-only retry, not broad auto-editing
- emit a structured repair plan from each completed review run so later code-fix automation has a safe intermediate artifact
- add a one-finding repair executor that prepares a bounded fix handoff by default and only runs an edit pass on explicit apply
- automate the external Hugging Face hardening lane so curated SWE-bench cases can be fetched, reviewed blindly, and scored in one run
- add a plugin-owned automation entrypoint so Codex automations can invoke the skill-centered review, learning, repair-handoff, and hardening loop end to end
- make probationary-to-primary promotion evidence-based so the durable corpus only grows when repeated review artifacts support the same case
- wire that durable-promotion step into the wrapper as an explicit opt-in so the whole learning loop can run from one entrypoint

## Phase 4

- optionally add CI or packaging only after the local workflow is stable
- optionally add GitHub-facing automation only after the local review and scoring loop is stable
- add plugin install/runtime documentation once the local plugin shape is stable
