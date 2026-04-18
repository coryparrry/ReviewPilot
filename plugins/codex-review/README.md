# Codex Review Plugin

This plugin is the primary container for the review system in this repo.

## Current Contents

- `.codex-plugin/plugin.json`
  Plugin manifest and user-facing metadata
- `skills/bug-hunting-code-review`
  The bundled CodeRabbit-style review skill
- `.mcp.json`
  Placeholder MCP config for future structured integrations such as GitHub-safe review ingestion
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

The first read-only live GitHub fetch script lives at:

- `plugins/codex-review/scripts/fetch_github_review_feedback.py`

The wrapper entrypoint for the full live intake flow now lives at:

- `plugins/codex-review/scripts/run_github_intake_pipeline.py`

Safety notes for the live fetch step:

- raw fetched review artifacts may contain private review content for private repos
- GitHub access is read-only: the fetch path issues comment/thread reads only and does not perform GitHub writes
- the default output path stays under ignored `artifacts/github-intake/`
- the fetch script refuses to write outside that tree unless explicitly overridden for local output
- the proposal normalizer follows the same default output boundary
- `--allow-outside-artifacts` is an unsafe local-write escape hatch only; it does not enable any GitHub write behavior
- when `--review-run-dir` points outside the ignored artifacts tree, that same local-write override must be passed explicitly; the wrapper no longer weakens this boundary implicitly

The non-destructive review-mapping script lives at:

- `plugins/codex-review/scripts/propose_corpus_updates.py`

The reviewed promotion script now lives at:

- `plugins/codex-review/scripts/promote_corpus_candidates.py`

That script exists to turn selected reviewed candidates into auto-eligible candidates without weakening the default intake heuristics.

The corpus apply script now lives at:

- `plugins/codex-review/scripts/apply_corpus_updates.py`

Recommended entrypoint for normal use:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py --repo owner/name --pr 123 --apply-mode review
```

That wrapper runs:

- fetch
- ingest
- propose
- optional promote
- apply

To compare a real review output against the corpus before and after apply in the same run:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --apply-mode review `
  --score-review-file .\draft-review.md
```

That writes before, after, and delta benchmark artifacts into the same pipeline run directory.

If the review was prepared through the bundled pre-PR helper, the wrapper can consume the prepared artifact directory directly:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
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
  --review-run-dir .\.codex-review\20260418-120000 `
  --allow-outside-artifacts `
  --resume `
  --score-review-artifacts .\.codex-review\20260418-120000
```

The `--resume` path reuses existing fetch, proposal, candidate, and promoted-candidate artifacts when present, then continues from the next missing stage.

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
