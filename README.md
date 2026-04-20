<p align="left">
  <img src="./plugins/codex-review/assets/reviewpilot-logo-graphite.svg" alt="ReviewPilot" width="320">
</p>

# ReviewPilot 🧠🔍

ReviewPilot is an early-beta Codex plugin and skill stack for deeper code review.

It pushes Codex toward:

- real correctness bugs
- security issues
- stale state and broken workflow logic
- contract drift
- missing negative-path handling
- missing or misleading tests

It is designed to improve over time from:

- real GitHub PR review misses
- curated external benchmark lanes like SWE-bench
- reviewed lessons from a private Knowledge-Hub log

## Why It Stands Out ✨

- Runs deep local reviews and writes `review.md`
- Scores review output against bundled benchmark lanes
- Produces bounded repair handoffs from review findings
- Learns safely from GitHub review feedback into a probationary corpus
- Supports external hardening with curated Hugging Face benchmark cases
- Can now refresh lessons snapshots and run the main automation flow from one wrapper

## Feature Highlights 🚀

- `run_codex_review.py`: one-command local review with explicit `changes`, `dirty`, `full`, `quick`, and `deep` review modes
- `run_review_fix.py`: one-finding repair handoff instead of loose "go fix things" prompts
- `run_github_intake_pipeline.py`: safer learning intake with gating and corpus controls
- `compare_review_quality.py`: compares a review artifact against fresh GitHub review intake and explains what the plugin still missed
- `approve_quality_learning_candidates.py`: turns comparison-approved corpus-gap misses into tightly gated probationary learning candidates
- `run_automation_cycle.py`: end-to-end wrapper for review, lessons refresh, GitHub intake, repair handoff, calibration, and hardening
- `refresh_lessons_reference.py`: bridges private lessons into a repo-local training snapshot without committing raw private notes

## Docs At A Glance 📚

- [Plugin overview](plugins/codex-review/README.md)
- [GitHub MCP setup](docs/github-mcp-setup.md)
- [Lessons workflow](docs/lessons-workflow.md)
- [Public release checklist](docs/public-release-checklist.md)
- [Architecture](docs/architecture.md)
- [Installed skill relationship](skill/README.md)

## Install 📦

Recommended install:

```bash
npx --yes --package=@reviewpilot/codex-review-install -- codex-review-install
```

Manual fallback from a repo checkout or release bundle:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_plugin_to_codex.ps1
```

After install, restart Codex Desktop.

## Quick Start ⚡

Run a local review:

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py `
  --repo . `
  --mode changes `
  --depth deep `
  --base origin/main
```

That gives you:

- a review artifact
- benchmark output
- a repair plan

Review modes:

- `changes`: reviews the committed `base...HEAD` diff
- `dirty`: reviews local uncommitted edits
- `full`: uses a broader repo scan and treats the diff as only one clue
- `quick`: skips the benchmark step
- `deep`: keeps the fuller prompt package and benchmark step

Quick local dirty-worktree review:

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py `
  --repo . `
  --mode dirty `
  --depth quick
```

Prepare a bounded repair handoff:

```powershell
python .\plugins\codex-review\scripts\run_review_fix.py `
  --repo . `
  --repair-plan .\.codex-review\<run>\repair-plan.json `
  --finding-index 1
```

Run the automation wrapper:

```powershell
python .\plugins\codex-review\scripts\run_automation_cycle.py `
  --repo . `
  --lessons-source C:\path\to\codex-lessons.md `
  --skip-github-intake `
  --hardening-length 1
```

## GitHub Learning Setup 🔌

If you want to use the GitHub learning flow, connect GitHub in Codex Desktop and then follow:

- [GitHub MCP setup](docs/github-mcp-setup.md)

That guide explains:

- what the plugin already ships in `.mcp.json`
- what you still need to connect in Codex
- how to capture GitHub MCP output
- how to feed that output into the learning pipeline

The fresh GitHub path is also the recommended quality-tuning loop. After you capture and normalize live review threads, compare them against a review artifact with:

```powershell
python .\plugins\codex-review\scripts\compare_review_quality.py `
  --review-file .\artifacts\github-intake\pipeline\<run>\review.md `
  --proposal .\artifacts\github-intake\pipeline\<run>\graphql-proposal.json `
  --candidates .\artifacts\github-intake\pipeline\<run>\graphql-candidates.json
```

That writes a plain-English summary plus a machine-readable comparison artifact you can feed back into later `run_codex_review.py --quality-comparison ...` runs.

## Lessons Workflow 🧠

If you keep review lessons in a private Knowledge-Hub, turn them into repo-local training input with:

```powershell
python .\plugins\codex-review\skills\bug-hunting-code-review\scripts\refresh_lessons_reference.py `
  --source C:\path\to\codex-lessons.md
```

That creates a local snapshot used to refresh the committed bug-pattern prompts.

Full instructions:

- [Lessons workflow](docs/lessons-workflow.md)

## Publish Readiness ✅

Before publishing, run:

```powershell
python .\scripts\validate_public_release.py
```

That checks:

- package metadata
- plugin metadata
- required public files
- Python script syntax

Release checklist:

- [Public release checklist](docs/public-release-checklist.md)

## More Docs 🔎

- [Project overview](docs/index.md)
- [Architecture](docs/architecture.md)
- [Plugin README](plugins/codex-review/README.md)
- [GitHub MCP setup](docs/github-mcp-setup.md)
- [Installed skill relationship](skill/README.md)
- [Lessons workflow](docs/lessons-workflow.md)
- [Public release checklist](docs/public-release-checklist.md)

## License

This repo is licensed under the MIT license. See [LICENSE](LICENSE).
