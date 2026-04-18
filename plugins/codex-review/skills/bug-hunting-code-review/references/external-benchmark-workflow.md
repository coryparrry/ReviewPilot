# External Benchmark Workflow

Use this workflow to turn external bug-fix datasets into review-oriented benchmark lanes for `bug-hunting-code-review`.

## Current External Lane

- Dataset: `SWE-bench/SWE-bench_Verified`
- Dataset fetch helper: `scripts/fetch_hf_dataset_rows.py`
- Curated cases: `references/swebench-verified-review-cases.json`

## Purpose

The external lane is not a replacement for the GitHub review corpus.

Use it to add broader correctness pressure on bug classes that may not appear often enough in your own PR history:

- invariant reasoning
- parser semantics
- placeholder/default misuse
- error-contract shaping
- mixed-type interop behavior
- missing guard rails around malformed input

## Workflow

1. Fetch candidate rows from Hugging Face:

```powershell
python "<skill-path>\scripts\fetch_hf_dataset_rows.py" `
  --dataset "SWE-bench/SWE-bench_Verified" `
  --config default `
  --split test `
  --offset 0 `
  --length 5
```

2. Select only cases that translate cleanly into review-shaped concerns.
3. Encode the durable cases in a corpus JSON file.
4. Score review outputs with the existing scorer:

```powershell
python "<skill-path>\scripts\review_corpus_score.py" `
  --corpus "<skill-path>\references\swebench-verified-review-cases.json" `
  --review-file ".\draft-review.md"
```

Or run both the primary and external lanes together:

```powershell
python "<skill-path>\scripts\run_review_benchmarks.py" `
  --review-file ".\draft-review.md"
```

The full automated pre-PR flow can call both lanes automatically with:

```powershell
python "<skill-path>\scripts\run_pre_pr_review.py" `
  --base origin/main `
  --review-file ".\draft-review.md"
```

## Boundaries

- Do not mix synthetic external scores into the primary GitHub review score by default.
- Keep the external lane separate so regressions in real PR-review quality stay visible.
- Prefer a small curated set of high-signal cases over bulk import.
