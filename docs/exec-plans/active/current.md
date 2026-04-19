# Current Execution Plan

## Active Batch

- keep the plugin-owned review and learning loop aligned with the current repo state
- harden the helper scripts where CodeRabbit surfaced real correctness gaps
- keep the default path safe, conservative, and measurable

## Execution Path Changes

- implement the [GitHub Intake Plan](../../github-intake-plan.md) as the first plugin-owned workflow
- keep live GitHub fetch read-only while the self-improvement loop hardens
- make `auto` the default corpus-apply mode, with `review` as the explicit no-write option
- wire before/after benchmark comparison into the wrapper when a real review output is available
- let the wrapper consume prepared `.codex-review` artifact directories directly so Codex-authored reviews can flow into scoring without manual file extraction
- let the wrapper reuse a prepared review run directory and stop after proposal generation so the full authoring loop can stay in one folder
- let the wrapper resume from existing shared-run artifacts instead of repeating the early read-only stages
- make MCP-shaped GitHub raw artifacts a first-class wrapper input and keep `gh` fetch as an explicit fallback only
- define the normalized schema and apply safety checks before broader automation
- gate GitHub-derived candidates into a probationary corpus before they can influence the primary GitHub corpus
- use the curated SWE-bench lane as external hardening pressure so the skill can improve without relying only on your own buggy PRs
- keep strict benchmark scoring separate from softer probationary admission evidence so learning stays safer than raw regex matching alone
- expose one plugin-owned review runner so the review brain can actually author `review.md` and benchmark it in one command
- let the review runner self-repair only obvious review-output failures with one automatic read-only retry, not broad auto-editing
- emit a structured repair plan from each completed review run so later code-fix automation has a safe intermediate artifact
- add a one-finding repair executor that prepares a bounded fix handoff by default and only runs an edit pass on explicit apply
- automate the external Hugging Face hardening lane so curated SWE-bench cases can be fetched, reviewed blindly, and scored in one run
- add a plugin-owned automation entrypoint so Codex automations can invoke the skill-centered review, learning, repair-handoff, and hardening loop end to end
- make probationary-to-primary promotion evidence-based so the durable corpus only grows when repeated review artifacts support the same case
- wire that durable-promotion step into the wrapper as an explicit opt-in so the whole learning loop can run from one entrypoint

## Current Next Step

- stabilize the helper scripts and release/install path so the early-beta public workflow is consistent and safe

## Blockers

- no hard blocker right now
- remaining decisions are mostly policy or product-shape questions, not broken-path issues
