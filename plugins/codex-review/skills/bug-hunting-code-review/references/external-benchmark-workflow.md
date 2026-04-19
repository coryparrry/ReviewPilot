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

This lane is useful when you want the skill to keep learning and hardening without manufacturing buggy PRs in your own repos. It should influence prompts, scorer expectations, and benchmark pressure, but it should not auto-write directly into the GitHub-derived corpus lanes.

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

## Blind Hardening Automation

To automate a small blind hardening pass from Hugging Face:

```powershell
python "<skill-path>\scripts\run_hf_hardening_cycle.py" `
  --repo . `
  --offset 0 `
  --length 5
```

That workflow:

1. fetches a slice of `SWE-bench/SWE-bench_Verified`
2. keeps only rows that already map to the curated external corpus
3. builds a blind prompt from the problem statement without the fix patch
4. runs Codex to write a review artifact for each selected case
5. scores each review artifact against the external SWE-bench lane
6. writes per-case artifacts plus a run summary under `artifacts/hf-hardening/`

For a dry run that only prepares prompts and metadata:

```powershell
python "<skill-path>\scripts\run_hf_hardening_cycle.py" `
  --repo . `
  --offset 0 `
  --length 5 `
  --prepare-only
```

## Boundaries

- Do not mix synthetic external scores into the primary GitHub review score by default.
- Keep the external lane separate so regressions in real PR-review quality stay visible.
- Prefer a small curated set of high-signal cases over bulk import.
- The blind hardening cycle is benchmark pressure, not direct corpus-writing automation.
