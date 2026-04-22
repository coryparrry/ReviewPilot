---
name: bug-hunting-code-review
description: Review code like a release blocker. Route Codex to the right review references and scripts based on review size, risk, and whether the task is review, scoring, or skill tuning.
---

# Bug-Hunting Code Review

Use this skill when Codex should review code for real bugs, not style.

Prioritize:
- correctness
- security
- broken feature behavior
- stale state and contract drift
- missing negative-path handling
- missing regression coverage for realistic failures

Ignore style and cleanup unless they clearly cause a real bug.

## Router

Start by classifying the task, then load only the references needed for that class.

### 1. Small Review

Use for:
- a small diff
- one file or one narrow bugfix
- a quick confidence pass

Load:
- `references/review-checklist.md`
- `references/evidence-bar.md`

Then:
- review the changed code and adjacent flow
- keep findings short and high-confidence
- do not load the full deep-review stack unless the change proves wider risk

### 2. Standard Review

Use for:
- normal PR review
- multi-file change
- stateful feature change
- API, persistence, auth, workflow, or UI behavior change

Load:
- `references/review-checklist.md`
- `references/evidence-bar.md`
- `references/bug-patterns-from-lessons.md`
- `references/release-blockers.md`
- `references/deep-review-rubric.md`

Also use:
- `scripts/review_surface_scan.py`

### 3. Deep Or High-Risk Review

Use for:
- auth or session changes
- external input handling
- persistence semantics
- schedulers, workflows, retries, or state machines
- changes where the diff is only one clue

Load the full standard-review set and treat the diff as an entry point, not the boundary.

### 4. Review-Quality Tuning

Use when:
- scoring review artifacts
- tuning the skill itself
- checking recall against the corpus or hardening lanes

Also load as needed:
- `references/review-corpus-workflow.md`
- `references/external-benchmark-workflow.md`
- `references/review-entrypoints.md`

### 5. Lessons Refresh

Use when:
- staging local lessons
- updating review guidance from repeated mistakes

Load:
- `references/review-entrypoints.md`

## Entry Points

For script selection and commands, read:

- `references/review-entrypoints.md`

That file is the command map for:
- surface scan
- pre-PR review prep
- full plugin review runs
- benchmark scoring
- inline review comment rendering
- lessons refresh

## Output Rules

- Findings come first.
- Prefer a short list of strong findings over a long list of weak ones.
- If there are no findings, say so explicitly and mention residual risk or test gaps briefly.
- Use inline review comments as the preferred review output when the task is an actual code review.

## Good Habits

- Treat the diff as the entry point, not the review boundary.
- Trace adjacent callers, callees, contracts, tests, and state transitions.
- Reconstruct behavior from source, not comments.
- Check mirrored write paths and sibling entry points.
- Re-check negative paths, retries, and stale-state behavior.
- Do not upgrade a weak hunch into a finding if the evidence bar is not met.
