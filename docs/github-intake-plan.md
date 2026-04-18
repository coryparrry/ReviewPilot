# GitHub Intake Plan

## Purpose

This plan defines the first plugin-owned workflow for `codex-review`: safely ingesting GitHub PR review feedback and turning it into structured input for skill improvement.

The goal is to improve the CodeRabbit-style review system from real review outcomes without letting ad hoc scripts, manual corpus edits, or loose GitHub handling become the new source of drift.

## Problem

The repo already has:

- a strong bundled review skill
- a review corpus built from recurring misses
- benchmark scoring helpers
- a plugin container that should become the long-term integration boundary

What it does not yet have is a controlled workflow for taking real GitHub PR review feedback and turning that into reusable improvement input.

Without a defined workflow, the likely failure modes are:

- manual one-off corpus edits
- inconsistent categorization of misses
- overfitting to raw comment wording
- mixing source evidence, interpretation, and final corpus entries together
- unsafe or overly broad GitHub access patterns

## Outcome

The first plugin-owned GitHub workflow should:

1. read review feedback from GitHub or a GitHub-derived export
2. normalize that feedback into a stable local schema
3. produce a proposed corpus-update artifact
4. support a controlled corpus-apply step with safe defaults
5. gate new GitHub-derived cases into a probationary lane before they are treated as durable primary corpus cases

The first version should stay easy to validate, with raw fetch, normalization, proposal output, and apply behavior kept as separate explicit steps.

The repo can still expose a single wrapper command for normal use, but that wrapper should remain a thin orchestrator over the explicit underlying stages.

If the wrapper reports benchmark improvement, it should do so only by scoring a supplied review artifact before and after apply, not by inferring improvement from corpus growth alone.

GitHub-derived learning should still be policy-gated even when `auto` is the default mode:

- gate candidates first
- auto-apply only into the probationary lane
- require a later promotion step before a case is considered durable enough for the primary GitHub corpus

Prepared `.codex-review` run directories should count as valid review-artifact inputs so the benchmark path stays plugin-native end to end.

Prepared review run directories should also be reusable as the wrapper working directory so prepare, review authoring, and intake artifacts can live in one shared run folder.

That shared-run reuse should not silently weaken local output confinement: if the chosen run directory sits outside the ignored `artifacts/` tree, the caller must opt into that local write path explicitly.

## Scope

### In Scope For V1

- plugin-owned intake workflow design
- local normalized schema for review misses
- one plugin-owned script that reads input and emits a proposed normalized output
- support for GitHub-derived input files first, with direct GitHub integration as a follow-up layer
- support for MCP-derived input files directly so the plugin's GitHub connector can own the live access boundary
- repo docs that define the workflow and expected review of proposed updates

### Out of Scope For V1

- automatic edits to the durable lessons log
- auto-resolving severity or regex patterns without review
- plugin marketplace or runtime installation automation

## Design Principles

- Keep the skill as the review brain.
- Use the plugin as the integration and workflow boundary.
- Separate raw evidence from normalized interpretation from final curated corpus entries.
- Prefer proposal artifacts over direct mutation until the schema and categorization are trustworthy.
- Keep GitHub access narrow, auditable, and replaceable.
- Separate probationary admission from durable primary-corpus promotion.
- Use external benchmark data to pressure the review brain without auto-writing synthetic cases into the GitHub-derived corpus.
- Optimize for repeatability, not cleverness.

## Proposed Workflow

### Step 1. Collect Input

Accepted input should initially be one of:

- exported GitHub review comments
- manually curated JSON from a GitHub review thread
- repo-local fixtures that represent real review feedback

Initial supported shapes should include:

- repo-local custom review bundles
- exported GitHub REST review comment JSON
- exported GitHub GraphQL review-thread JSON
- GitHub MCP PR comment timeline JSON
- GitHub MCP review-thread JSON

V1 should not require live GitHub access to be useful.

### Step 2. Normalize Review Feedback

The plugin-owned intake script should transform raw comments into a local normalized record shape.

Each normalized record should preserve:

- source metadata
- original evidence text
- inferred miss category
- inferred severity
- confidence or review-needed marker
- candidate notes for a future corpus update

### Step 3. Emit Proposal Artifact

The workflow should write a proposal artifact to a local output path such as:

- `artifacts/github-intake/<timestamp>-proposal.json`

That artifact is the review boundary for humans and later automation.

### Step 4. Curate Into Corpus

After proposal generation, a follow-up workflow can convert selected proposals into:

- probationary corpus cases
- later promoted primary corpus cases
- benchmark metadata
- durable lessons log updates when the miss is durable enough

That write path should stay explicit and auditable even when `auto` is the default apply mode.

## Proposed Plugin Boundary

The plugin should own the intake workflow under:

- `plugins/codex-review/scripts/`

Initial planned script surface:

- `capture_github_mcp_feedback.py`
- `ingest_github_review_feedback.py`
- `fetch_github_review_feedback.py`
- `propose_corpus_updates.py`
- `score_candidate_quality.py`
- `promote_corpus_candidates.py`
- `promote_probationary_cases.py`
- `run_github_intake_pipeline.py`

Likely future additions:

- `verify_sync.py`
- `apply_corpus_updates.py`

## Proposed Normalized Schema

V1 should introduce a local schema file or documented JSON shape for normalized review misses.

Minimum fields:

- `source`
- `repo`
- `pr_number`
- `comment_id`
- `review_id`
- `source_type`
- `file_path`
- `line`
- `body`
- `normalized_category`
- `severity`
- `confidence`
- `needs_human_review`
- `candidate_expectations`
- `notes`

Schema rules:

- preserve raw evidence verbatim where possible
- do not collapse multiple distinct findings into one record unless the source evidence clearly does so
- keep normalized categories aligned with the review corpus categories already used in this repo
- allow uncertain classification to stay uncertain instead of forcing a false precise category

## Implementation Phases

## Phase A. Docs And Schema

- document the intake workflow
- define the normalized schema
- define proposal artifact location and naming
- define review rules for moving proposals into the curated corpus

Exit criteria:

- one durable plan document exists
- one documented normalized schema exists
- no ambiguity remains about raw evidence vs normalized proposal vs final corpus

## Phase B. Proposal-Only Intake Script

- add `plugins/codex-review/scripts/ingest_github_review_feedback.py`
- support repo-local JSON input first
- emit normalized proposal JSON
- add a small fixture and smoke validation path
- keep room for a later wrapper command without collapsing the explicit artifact boundaries

Exit criteria:

- one command can take a fixture input and emit a normalized proposal artifact
- validation proves the output shape is stable

## Phase C. Corpus Mapping Review

- define how normalized proposal records map to corpus cases
- document the criteria for when a proposal becomes a new durable case
- document when a finding should update the durable lessons log instead of or in addition to the corpus

Exit criteria:

- there is a written manual review loop for turning proposals into durable improvements

## Phase E. Controlled Corpus Apply

- add `plugins/codex-review/scripts/apply_corpus_updates.py`
- add `plugins/codex-review/scripts/promote_corpus_candidates.py`
- add `plugins/codex-review/scripts/score_candidate_quality.py`
- add `plugins/codex-review/scripts/run_github_intake_pipeline.py` as the thin orchestration entrypoint
- allow the wrapper to run optional before/after benchmark comparison when a real review artifact is supplied
- allow the wrapper to consume prepared `.codex-review` run directories directly instead of requiring manual extraction of `review.md`
- allow the wrapper to stop after proposal generation so Codex can write the review into the same shared run directory before a later scoring/apply pass
- allow the wrapper to resume from existing fetch/proposal/candidate artifacts in that same shared run directory
- make `auto` the default mode for straightforward safe additions
- keep `review` as an explicit no-write option
- keep `force` available for intentionally overriding soft warnings
- treat exact duplicates as idempotent no-ops instead of new corpus entries
- block malformed candidates and conflicting IDs instead of overwriting existing cases
- require evidence-based gating before a GitHub-derived candidate can auto-apply into the probationary lane
- require a later promotion step before probationary cases are treated as durable primary corpus entries
- require that later promotion step to use repeated review-artifact evidence, not just a convenience flag

Exit criteria:

- one command can apply clean corpus-candidate artifacts into `review-corpus-cases.json`
- repeat runs are idempotent for exact duplicates
- review mode can preview application without mutating the corpus
- promoted candidates can be marked auto-eligible without weakening default intake heuristics
- the wrapper command can run fetch, ingest, propose, optional promote, and apply into one per-run artifact directory
- optional benchmark comparison can produce before, after, and delta artifacts without inventing a fake improvement signal
- prepared review artifact directories can flow directly into wrapper scoring without an extra manual handoff step
- the wrapper can reuse a prepared review run directory and stop early so the review-authoring loop does not need path juggling across different artifact roots
- the wrapper can resume from the next missing stage instead of rerunning fetch/ingest/propose once those artifacts already exist
- the wrapper can gate GitHub-derived candidates against duplicate checks plus review-artifact evidence before auto-applying them into the probationary lane
- probationary cases can be promoted into the primary corpus only when repeated review artifacts support them strongly enough to count as durable knowledge

## Phase D. Live GitHub Input

- add a direct GitHub-backed input path only after the proposal-only flow is stable
- keep permissions minimal and workflow-specific
- prefer explicit exported input or narrowly scoped reads over broad repo mutation access

The first live GitHub slice should remain read-only:

- prefer the plugin's GitHub MCP connector as the live fetch boundary
- add a Codex-side capture helper that turns GitHub MCP tool output into a stable raw artifact file without requiring the user to save connector output manually
- import raw PR review comments and review threads from MCP-produced JSON snapshots
- save raw artifacts under ignored `artifacts/`
- hand off into the existing proposal-only normalizer
- avoid direct corpus writes or automatic proposal application
- keep raw artifact writes inside the ignored artifacts tree by default
- treat raw fetched review artifacts as potentially sensitive for private repos
- keep proposal artifact writes inside the ignored artifacts tree by default as well
- treat `--allow-outside-artifacts` as a local-output escape hatch only, not as any expansion of GitHub permissions or write behavior
- keep repository identifiers and GraphQL usage narrowly constrained so the fetch path remains auditable and read-only by construction
- configure the plugin MCP boundary with read-only mode and only the `pull_requests` toolset for this workflow
- keep the old `gh`-based fetch script as an explicit migration fallback, not the default live path

Exit criteria:

- live GitHub review data can feed the same normalized proposal flow without changing the downstream schema

## Validation Plan

For Phase B and later, validation should include:

- JSON parse validation for produced artifacts
- fixture-based smoke test for the intake script
- at least one fixture for each supported input adapter
- at least one test case with multiple findings from one review
- at least one uncertain classification that stays flagged for human review
- at least one comment with no file path or line
- confirmation that no corpus files are mutated in proposal-only mode

## Non-Goals

- building a generic GitHub analytics product
- replacing the current curated corpus with raw PR data
- auto-learning directly from all comments without review
- auto-promoting GitHub-derived probationary cases straight into the durable primary corpus
- making GitHub integration broader than needed for review improvement

## Initial Deliverables

The next implementation batch should produce:

1. this plan wired into repo docs
2. a documented normalized schema
3. a plugin-owned proposal-only intake script
4. one or more fixtures for local validation
5. usage docs for the proposal flow
6. a thin wrapper command for the full live pipeline once the underlying stages are stable

## Decision Record

Why this is the next step:

- it uses the plugin boundary for a workflow that should not stay as loose scripts forever
- it directly advances the self-improving CodeRabbit-style goal
- it avoids premature auto-write behavior
- it gives future GitHub integration one stable schema and proposal path instead of many one-off paths
