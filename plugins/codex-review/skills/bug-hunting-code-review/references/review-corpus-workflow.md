# Review Corpus Workflow

Use this workflow to regression-check the `bug-hunting-code-review` skill against real missed-review examples.

## Purpose

The corpus is a compact set of concrete review failures pulled from the Knowledge-Hub GitHub review-comment lane.

It is not a benchmark for style. It is a benchmark for whether a review output catches the bug classes Codex has repeatedly missed:

- source-of-truth drift
- fixture masking
- state-symmetry bugs
- migration cleared-state bugs
- request or response contract drift
- legacy fallback source confusion
- queue claim or concurrency bugs

## Files

- `references/review-corpus-cases.json`
  The structured cases and matching expectations.
- `scripts/review_corpus_score.py`
  Score a review output against those cases.
- `scripts/run_review_benchmarks.py`
  Run both the primary GitHub corpus and the external benchmark lane together.
- `scripts/run_pre_pr_review.py`
  Prepare diff and scan context, run the review with the OpenAI API, and score the result in one command.

## Typical Usage

1. Save a review output to a file such as `draft-review.md`.
2. Run:

```powershell
python "<skill-path>\scripts\review_corpus_score.py" `
  --review-file ".\draft-review.md"
```

3. Read the report:
   - overall weighted recall
   - matched vs missed cases
   - category breakdown
   - critical or high misses

To score both benchmark lanes in one command:

```powershell
python "<skill-path>\scripts\run_review_benchmarks.py" `
  --review-file ".\draft-review.md"
```

To run the full pre-PR flow in one command:

```powershell
python "<skill-path>\scripts\run_pre_pr_review.py" `
  --base origin/main
```

## Interpretation

- Target `100%` recall on `critical` cases.
- Treat missed `high` cases as a sign the review workflow or prompt still needs work.
- Medium misses matter, but they are secondary to not missing high-severity correctness or security failures.

## Refreshing the Corpus

When you add a new raw clip under the GitHub review-comment lane:

1. Leave the raw file immutable.
2. Distill only durable cases into `review-corpus-cases.json`.
3. Keep each case concrete:
   - bug title
   - category
   - severity
   - source raw file
   - regex groups that represent what a good review should mention
4. Update the Knowledge-Hub lesson if the new case reflects a recurring miss class.

Do not add every nit. Add the cases that should change the review skill.
