# Codex Review Plugin

This plugin is the primary container for the review system in this repo.

## Current Contents

- `.codex-plugin/plugin.json`
  Plugin manifest and user-facing metadata
- `skills/bug-hunting-code-review`
  The bundled CodeRabbit-style review skill
- `.mcp.json`
  Plugin-owned MCP config. GitHub is now declared there as a read-only remote MCP boundary for live PR intake.
- `scripts/`
  Reserved for plugin-owned helper workflows as repo scripts migrate behind plugin boundaries

## Current Boundary

Today, the plugin contains the maintained skill source, but the live runtime path is still the installed direct skill under:

- `~/.codex/skills/bug-hunting-code-review`

That direct skill runtime is currently updated with `scripts/sync_skill_to_codex.ps1`.

## Intended Direction

The plugin should become the clean integration boundary for:

- GitHub PR review intake
- corpus and benchmark scoring workflows
- post-sync verification
- future MCP-backed or app-backed review operations

The bundled skill remains the review brain inside that plugin.

The current next-step implementation plan is documented at:

- `docs/github-intake-plan.md`

The normalized proposal schema for the first GitHub intake workflow is documented at:

- `docs/github-intake-schema.md`

The first proposal-only intake script lives at:

- `plugins/codex-review/scripts/ingest_github_review_feedback.py`

The Codex-side MCP capture helper lives at:

- `plugins/codex-review/scripts/capture_github_mcp_feedback.py`

The legacy `gh`-based live GitHub fetch script lives at:

- `plugins/codex-review/scripts/fetch_github_review_feedback.py`

The wrapper entrypoint for the full live intake flow now lives at:

- `plugins/codex-review/scripts/run_github_intake_pipeline.py`

The plugin-owned review runner now lives at:

- `plugins/codex-review/scripts/run_codex_review.py`

Safety notes for the live fetch step:

- raw fetched review artifacts may contain private review content for private repos
- the preferred live GitHub path is the plugin MCP boundary in `.mcp.json`, not ambient `gh` auth
- `.mcp.json` pins GitHub to remote MCP, read-only mode, and the `pull_requests` toolset only
- GitHub access is read-only in both supported live paths: the MCP boundary is configured read-only, and the legacy `gh` path issues comment/thread reads only
- the default output path stays under ignored `artifacts/github-intake/`
- the fetch script refuses to write outside that tree unless explicitly overridden for local output
- the proposal normalizer follows the same default output boundary
- `--allow-outside-artifacts` is an unsafe local-write escape hatch only; it does not enable any GitHub write behavior
- when `--review-run-dir` points outside the ignored artifacts tree, that same local-write override must be passed explicitly; the wrapper no longer weakens this boundary implicitly
- the wrapper no longer defaults to the `gh` fetch path; `gh` is now an explicit legacy fallback behind `--use-gh-legacy-fetch`

The non-destructive review-mapping script lives at:

- `plugins/codex-review/scripts/propose_corpus_updates.py`

The candidate-quality gate now lives at:

- `plugins/codex-review/scripts/score_candidate_quality.py`

The reviewed promotion script now lives at:

- `plugins/codex-review/scripts/promote_corpus_candidates.py`

That script exists to turn selected reviewed candidates into auto-eligible candidates without weakening the default intake heuristics.

The probationary-to-primary promotion gate now lives at:

- `plugins/codex-review/scripts/promote_probationary_cases.py`

That script exists to promote cases out of the probationary lane only when repeated review artifacts support the same case strongly enough to treat it as durable primary-corpus knowledge.

The corpus apply script now lives at:

- `plugins/codex-review/scripts/apply_corpus_updates.py`

The current learning policy is intentionally two-lane:

- gate-approved GitHub-derived cases can auto-apply into the probationary corpus
- the primary GitHub corpus should stay harder to change and should not be treated as the raw output lane for fresh PR feedback

The current durable-promotion rule is also intentionally evidence-based:

- probationary cases should move into the primary corpus only after repeated review artifacts hit the same case
- exact duplicates and conflicting IDs fail closed
- near-duplicate primary matches stay out of `auto` and require explicit force if you really want them

The wrapper now defaults `--apply-target` to `probationary` so the safer lane is the default behavior, not an extra flag the caller has to remember.

The external SWE-bench lane is the hardening lane for broader review pressure. It helps the review brain improve without depending only on your own buggy PRs, but it should not auto-write directly into the GitHub-derived corpus lanes.

Recommended entrypoint for normal use:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --apply-mode review
```

That wrapper runs:

- normalize imported raw input
- ingest
- propose
- optional candidate-quality gate
- optional promote
- apply
- optional probationary-to-primary promotion when you ask for it explicitly

For the actual review-authoring path, use:

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py `
  --repo . `
  --base origin/main
```

That command:

- prepares the review prompt, diff, metadata, and surface scan
- invokes Codex non-interactively in read-only mode
- writes `review.md`
- writes Codex stdout and stderr logs for inspection
- benchmarks the resulting review against the configured lanes
- automatically retries once in the same read-only sandbox if review generation fails mechanically or produces a missing or empty `review.md`

For MCP-native live intake, use the plugin's GitHub connector to capture one of these raw payload shapes first:

- PR comments timeline output compatible with `github_mcp_pr_comments`
- review-thread output compatible with `github_mcp_review_threads`

The intended Codex-side flow is:

1. use the GitHub connector to fetch either PR comments or review threads
2. write that tool output into a local raw artifact with `capture_github_mcp_feedback.py`
3. feed the captured artifact into `--raw-input`

Example capture step for PR comments:

```powershell
python .\plugins\codex-review\scripts\capture_github_mcp_feedback.py `
  --repo owner/name `
  --pr 123 `
  --kind pr_comments `
  --input .\artifacts\github-intake\mcp-tool-output.json
```

In Codex usage, the tool output file can be created by the agent automatically after the GitHub MCP call, so the user does not need to save connector output by hand.

To compare a real review output against the corpus before and after apply in the same run:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --apply-mode review `
  --score-review-file .\draft-review.md
```

That writes before, after, and delta benchmark artifacts into the same pipeline run directory.

To run the safer self-learning path into the probationary corpus:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --apply-target probationary `
  --gate-candidates `
  --score-review-file .\draft-review.md `
  --apply-mode auto
```

That path:

- gates candidates against duplicate checks and review-artifact evidence
- auto-applies only the gate-approved subset
- targets the probationary lane rather than the durable primary corpus

To promote a probationary case into the durable primary corpus:

```powershell
python .\plugins\codex-review\scripts\promote_probationary_cases.py `
  --ids feature-gates-preserve-existing `
  --review-file .\artifacts\review-a.md `
  --review-file .\artifacts\review-b.md
```

That path:

- requires repeated review-artifact evidence by default
- requires at least one strict expected-group match by default
- removes promoted cases from the probationary corpus
- appends them into the primary corpus only when the promotion gate clears

The wrapper can now drive that same durable promotion step in the same run directory:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --score-review-artifacts .\.codex-review `
  --gate-candidates `
  --apply-mode auto `
  --promote-probationary-ids feature-gates-preserve-existing
```

That keeps the normal safe intake path unchanged by default, but lets one wrapper run:

- learn into the probationary lane
- then evaluate selected probationary cases for durable promotion
- write a separate promotion result artifact in the same run folder

If the review was prepared through the bundled pre-PR helper, the wrapper can consume the prepared artifact directory directly:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --apply-mode review `
  --score-review-artifacts .\.codex-review
```

That accepts either:

- a specific prepared run directory containing `review.md`
- the parent `.codex-review` directory, in which case the newest child run with `review.md` is used

To reuse a prepared review run directory directly and stop after proposal generation:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --review-run-dir .\.codex-review\20260418-120000 `
  --allow-outside-artifacts `
  --stop-after propose
```

That lets the same run directory hold:

- prepared diff and prompt artifacts
- intake proposal and candidate artifacts
- the eventual `review.md`
- later benchmark and apply artifacts after a follow-up wrapper run

To continue from existing artifacts in the same run directory instead of refetching and regenerating earlier stages:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --review-run-dir .\.codex-review\20260418-120000 `
  --allow-outside-artifacts `
  --resume `
  --score-review-artifacts .\.codex-review\20260418-120000
```

The `--resume` path reuses existing fetch, proposal, candidate, and promoted-candidate artifacts when present, then continues from the next missing stage.

If you intentionally need the old CLI-backed fetch for comparison or migration work, opt into it explicitly:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --source rest `
  --use-gh-legacy-fetch `
  --apply-mode review
```

Apply modes:

- `auto`
  Default mode. Apply candidates that pass hard validation and do not carry soft warnings.
- `review`
  No-write mode for previewing what would be applied or held back.
- `force`
  Apply candidates that pass hard validation even if soft warnings remain.

Current apply safety rules:

- exact existing matches are treated as already present and do not append duplicates
- conflicting IDs block instead of overwriting existing corpus entries
- malformed candidates fail closed
