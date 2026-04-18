# GitHub Intake Schema

## Purpose

This document defines the normalized proposal schema for plugin-owned GitHub review intake.

It sits between:

- raw GitHub review feedback or exported review data
- curated durable corpus entries in `review-corpus-cases.json`

This schema is intentionally proposal-oriented. It is not the final corpus shape.

## Proposal Artifact Shape

The intake script should emit a JSON object with this top-level structure:

```json
{
  "schema_version": "codex-review.github-intake.v1",
  "generated_at": "2026-04-18T14:00:00Z",
  "source_file": "C:/path/to/input.json",
  "source_format": "github_rest_review_comments",
  "records": []
}
```

## Record Shape

Each normalized record must contain:

```json
{
  "source": "fixture-sample",
  "repo": "example/repo",
  "pr_number": 42,
  "review_id": "PRR_123",
  "comment_id": "PRRC_456",
  "source_type": "github_review_comment",
  "file_path": "src/example.ts",
  "line": 17,
  "body": "This helper rewrites the whole feature gate object instead of preserving existing keys.",
  "normalized_category": "fixture-masking",
  "severity": "high",
  "confidence": "medium",
  "needs_human_review": true,
  "candidate_expectations": [
    "feature gates",
    "preserve existing keys",
    "full object overwrite"
  ],
  "notes": "Heuristic classification from proposal-only intake."
}
```

## Field Definitions

- `source`
  Human-readable origin label from the input file.
- `repo`
  Repository name or owner/repo string.
- `pr_number`
  Pull request number when known.
- `review_id`
  Review identifier when known.
- `comment_id`
  Comment identifier when known.
- `source_type`
  Input record type. V1 defaults to `github_review_comment`.
- `file_path`
  Reviewed file path when available.
- `line`
  Reviewed line number when available.
- `body`
  Original feedback text preserved verbatim.
- `normalized_category`
  Best-effort mapped category aligned to the existing review corpus.
- `severity`
  Best-effort severity guess. Allowed values: `critical`, `high`, `medium`, `low`, `unknown`.
- `confidence`
  Confidence in normalization. Allowed values: `high`, `medium`, `low`.
- `needs_human_review`
  Always treat proposal records as reviewable; keep this `true` when classification is heuristic or incomplete.
- `candidate_expectations`
  Short phrases that may help a later workflow build corpus expectations or matching heuristics.
- `notes`
  Freeform normalization notes.

## Top-Level Fields

- `schema_version`
  Current proposal schema identifier.
- `generated_at`
  UTC timestamp for artifact creation.
- `source_file`
  Local input path used to generate the artifact.
- `source_format`
  Detected or selected input adapter. Current values:
  `custom_review_bundle`, `github_rest_review_comments`, `github_graphql_review_threads`.
- `records`
  Normalized proposal records.

## Category Set

V1 should normalize into the existing corpus vocabulary where possible:

- `fixture-masking`
- `registry-drift`
- `state-symmetry`
- `migration-backfill`
- `error-shaping`
- `request-contract`
- `fail-open-synthesis`
- `source-of-truth-drift`
- `migration-cleared-state`
- `concurrency-queue-claim`
- `test-realism`
- `legacy-fallback-source`
- `response-contract`
- `uncategorized`

Use `uncategorized` when the evidence does not cleanly match an existing durable class.

## Schema Rules

- Preserve original review text in `body`.
- Do not silently drop records because classification is uncertain.
- Prefer `needs_human_review: true` to false certainty.
- Do not mutate the curated corpus in proposal-only mode.
- Do not require live GitHub access to produce a valid proposal artifact.

## Review Rules

A normalized proposal record should become a corpus candidate only when:

- the bug class is durable rather than repo-specific noise
- the comment is concrete enough to express as a review expectation
- the inferred category aligns to an existing corpus lane or justifies a new durable category
- a human has checked that the wording is not overfit to one raw comment
