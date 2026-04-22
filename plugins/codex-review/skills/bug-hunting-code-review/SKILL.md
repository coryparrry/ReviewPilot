---
name: bug-hunting-code-review
description: Perform aggressive pre-commit and pre-release code review to find correctness bugs, security vulnerabilities, broken user flows, contract mismatches, missing edge-case handling, and missing tests before approval. Use when reviewing pull requests, diffs, refactors, feature work, auth or session changes, input-handling code, API or route or service updates, persistence changes, stateful UI patches, scheduler or workflow changes, or whenever Codex should act as a release blocker rather than a style reviewer.
---

# Bug-Hunting Code Review

Use this skill when Codex should review code like a release blocker.

Prioritize:
- correctness bugs
- security bugs
- broken user flows
- stale state and contract drift
- missing negative-path handling
- missing tests for realistic regressions

Do not spend review budget on style, cleanup, or speculative architecture advice unless it clearly causes a real bug.

## Core Rules

- Treat the diff as the entry point, not the review boundary.
- Trace adjacent callers, callees, contracts, tests, and state transitions.
- Prefer a short list of strong findings over a long list of weak ones.
- Findings come first.
- If there are no findings, say so explicitly and mention residual risk or test gaps briefly.

## Default Workflow

For any non-trivial review:

1. Read the diff and identify the repo root.
2. Build the change map.
3. Run the surface scan.
4. Run the required review passes.
5. Do not conclude `No findings` until the evidence bar is met.

Preferred commands:

```sh
python "<skill-path>/scripts/review_surface_scan.py" --repo .
python "<skill-path>/scripts/review_surface_scan.py" --repo . --base origin/main
```

If you are working from an existing review artifact:

```sh
python "<skill-path>/scripts/run_pre_pr_review.py" --base origin/main --review-file "./draft-review.md"
python "<skill-path>/scripts/run_pre_pr_review.py" --base origin/main --prepare-only
python "./plugins/codex-review/scripts/run_codex_review.py" --repo . --base origin/main
python "./plugins/codex-review/scripts/emit_inline_review_comments.py" --review-dir "<review-run-dir>"
```

For skill-quality regression checks:

```sh
python "<skill-path>/scripts/review_corpus_score.py" --review-file "./draft-review.md"
python "<skill-path>/scripts/run_review_benchmarks.py" --review-file "./draft-review.md"
```

For optional lessons refresh:

```sh
python "<skill-path>/scripts/refresh_lessons_reference.py" --source "<path-to-codex-lessons.md>"
```

## Required References

Read these before declaring a meaningful patch clean:

- `references/review-checklist.md`
- `references/evidence-bar.md`
- `references/bug-patterns-from-lessons.md`
- `references/release-blockers.md`
- `references/deep-review-rubric.md`

Also use:
- `references/review-corpus-workflow.md` when tuning the skill itself
- `references/external-benchmark-workflow.md` when working on the Hugging Face lane

## Required Review Passes

Run all four passes on every non-trivial review:

1. Correctness
   - logic errors
   - regressions
   - stale state
   - contract mismatches
   - missing edge-case handling

2. Security
   - trust boundaries
   - attacker-controlled input
   - dangerous sinks
   - auth and authorization failures
   - secret exposure

3. Feature completeness
   - success path
   - negative path
   - loading, empty, error, retry, refresh, cleanup
   - permission-loss and partial-failure behavior

4. Integrity
   - imports and file reachability
   - registries and allowlists
   - validator and hook coverage
   - lint, type, and test claims that do not match the real executable path

## Change Map Checklist

Before you decide a patch is clean, identify:

- the real execution surface it touches
- the contract that must hold after the change
- the inputs, actors, and failure modes on that path
- whether the patch crosses a trust boundary
- the real user-visible flow that must still work

If the patch looks local but participates in a wider flow, review the wider flow.

## Bug Classes To Hunt

Actively pressure-test these failure classes:

- source-of-truth drift
- stale or unsynchronized state
- contract mismatches across layers
- broken retries, resets, cleanup, or refresh paths
- authorization gaps or privacy leaks
- fail-open fallbacks
- missing validation on real inputs
- registry or allowlist drift
- helper or fixture widening that hides the real behavior
- broken imports, paths, or example commands
- missing regression coverage for the actual bug class introduced

## Review Output

Report findings first, ordered by severity.

For each finding:
- name the failing scenario
- explain the broken invariant or user expectation
- point to the concrete location that causes it
- explain the user-visible or system-visible impact
- classify it as correctness, security, or broken feature behavior

Use inline review comments as the preferred output when the task is an actual code review.
Treat `inline-findings.json` and `codex-inline-comments.txt` as first-class artifacts.

## Good Habits

- Reconstruct behavior from source, not comments.
- Check neighboring files when contracts or persistence change.
- Search for mirrored write paths and sibling entry points.
- Re-check negative paths, retries, and stale-state behavior.
- Check whether tests would actually fail for the bug you suspect.
- Do not upgrade a weak hunch into a finding if the evidence bar is not met.
