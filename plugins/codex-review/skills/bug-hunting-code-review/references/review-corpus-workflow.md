# Review Corpus Workflow

Use this workflow to regression-check the `bug-hunting-code-review` skill against real missed-review examples.

## Purpose

The corpus is a compact set of concrete review failures pulled from the review-comment archive lane.

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
- `references/probationary-review-cases.json`
  Gate-approved GitHub-derived cases that are still in the probationary lane.
- `scripts/review_corpus_score.py`
  Score a review output against those cases.
- `scripts/run_review_benchmarks.py`
  Run the primary GitHub corpus, probationary GitHub corpus, and external benchmark lane together.
- `scripts/run_pre_pr_review.py`
  Prepare diff and scan context, then score a supplied review artifact in one command. The direct OpenAI API path is optional legacy behavior.

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
  --base origin/main `
  --review-file ".\draft-review.md"
```

To only prepare the diff, scan, and prompt artifacts for a Codex-native review step:

```powershell
python "<skill-path>\scripts\run_pre_pr_review.py" `
  --base origin/main `
  --prepare-only
```

## Interpretation

- Target `100%` recall on `critical` cases.
- Treat missed `high` cases as a sign the review workflow or prompt still needs work.
- Medium misses matter, but they are secondary to not missing high-severity correctness or security failures.

## Refreshing the Corpus

When you add a new raw clip under the GitHub review-comment lane:

1. Leave the raw file immutable.
2. Gate new cases into `probationary-review-cases.json` first when they are evidence-backed but not yet durable enough for the primary lane.
3. Distill only durable cases into `review-corpus-cases.json`.
4. Keep each case concrete:
   - bug title
   - category
   - severity
   - source raw file
   - regex groups that represent what a good review should mention
5. Promote from probationary into the primary corpus only after the case has proved durable enough to justify that stricter lane.
6. Update the durable lessons log if the new case reflects a recurring miss class.

Do not add every nit. Add the cases that should change the review skill.
