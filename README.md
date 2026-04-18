# Codex Review

This repo is the source project for building and documenting a plugin-backed deep pre-PR code review system for Codex.

Its core function is to make Codex behave more like a strong CodeRabbit-style reviewer: release-blocking when warranted, biased toward correctness and security, and continuously improvable from real review misses plus curated benchmark lanes.

## Current Status

The primary project container is now the repo-local plugin at:

- `plugins/codex-review`

The bundled review skill now lives inside that plugin at:

- `plugins/codex-review/skills/bug-hunting-code-review`

The live installed skill still exists at:

- `~/.codex/skills/bug-hunting-code-review`

This repo is the dedicated project home for:

- skill design and prompt evolution
- plugin packaging and future safe integration points
- bundled scripts and review helpers
- benchmark corpus management
- documentation and workflow notes
- the maintained source copy of the installed review system

## Core Function

The review system is meant to:

- review diffs like a serious pre-merge reviewer, not a style bot
- prioritize correctness bugs, security issues, broken feature behavior, contract drift, stale state, and missing negative-path coverage
- operate as a release blocker when the evidence supports it
- improve over time from two feedback lanes:
  real GitHub PR review misses and curated external benchmark datasets

This repo is where that improvement loop should live. The plugin container, skill prompt, deterministic helpers, corpus files, and benchmark workflows should all evolve together here.

## Plugin Shape

The plugin is the primary container now:

- `plugins/codex-review/.codex-plugin/plugin.json`
- `plugins/codex-review/skills/bug-hunting-code-review`
- `plugins/codex-review/.mcp.json`

The skill remains part of the plugin. The plugin boundary is where future GitHub-safe ingestion, review scoring, sync verification, and other structured workflows should live.

## Sync Workflow

The repo copy is now the maintained source for day-to-day review changes:

- `plugins/codex-review/skills/bug-hunting-code-review`

Push that source copy into the installed runtime copy with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1
```

Useful options:

- `-DryRun`
  Preview the directories and files that would be copied
- `-Destination <path>`
  Sync into a different test or runtime location

The current sync is intentionally one-way and non-destructive: it overwrites files from the plugin-contained repo copy into the installed skill runtime, but it does not delete stale files from the destination.

This is a transition path. The plugin scaffold now exists in the repo, but the runtime install flow for the plugin itself is still a follow-up step.

## Improvement Loop

The repo should keep the skill measurable and self-improving through:

- the bundled review corpus built from real GitHub PR review misses
- curated external review-oriented datasets
- repeatable benchmark commands that can score a draft review against both lanes
- GitHub-facing plugin integration so review outputs and missed findings can be fed back into the corpus cleanly through one wrapper pipeline plus explicit underlying stages

## Initial Goals

- keep the review skill CodeRabbit-style and release-blocking
- catch correctness, security, stale-state, AI-slop, broken-path, and test-masking issues
- make the skill measurable with both real GitHub review misses and curated external benchmark lanes
- bundle scripts that make the skill consistent without turning it into a separate product

## Docs

- [Project Overview](docs/index.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Installed Skill Relationship](skill/README.md)

## Next Steps

1. Add post-sync verification so the installed runtime can be proven to match plugin-contained source.
2. Harden the GitHub self-improvement loop around real repo data, corpus scoring, and apply safety.
3. Add plugin install/runtime documentation before broader CI or packaging work.
