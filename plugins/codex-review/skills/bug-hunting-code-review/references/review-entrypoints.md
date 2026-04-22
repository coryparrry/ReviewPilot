# Review Entrypoints

Use this file when the task is operational and you need the right helper or script for the job.

## Review Surface Scan

Use for standard or deep reviews when the repo is available.

```sh
python "<skill-path>/scripts/review_surface_scan.py" --repo .
python "<skill-path>/scripts/review_surface_scan.py" --repo . --base origin/main
```

## Prepare Or Score A Review Artifact

Use when you already have a review artifact or want to prepare one.

```sh
python "<skill-path>/scripts/run_pre_pr_review.py" --base origin/main --review-file "./draft-review.md"
python "<skill-path>/scripts/run_pre_pr_review.py" --base origin/main --prepare-only
```

## Full Plugin Review Run

Use when Codex should prepare artifacts, invoke the plugin review runner, write `review.md`, and benchmark it.

```sh
python "./plugins/codex-review/scripts/run_codex_review.py" --repo . --base origin/main
```

## Inline Review Comments

Use when the task is an actual code review and Codex should emit inline review cards from a completed run.

```sh
python "./plugins/codex-review/scripts/emit_inline_review_comments.py" --review-dir "<review-run-dir>"
```

Treat `inline-findings.json` and `codex-inline-comments.txt` as first-class review artifacts.

## Regression Scoring

Use when scoring review quality against the bundled corpus or benchmark lanes.

```sh
python "<skill-path>/scripts/review_corpus_score.py" --review-file "./draft-review.md"
python "<skill-path>/scripts/run_review_benchmarks.py" --review-file "./draft-review.md"
```

## Lessons Refresh

Use when staging a local lessons file into the repo-local snapshot.

```sh
python "<skill-path>/scripts/refresh_lessons_reference.py" --source "<path-to-codex-lessons.md>"
```
