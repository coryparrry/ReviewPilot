# Codex Review Skill

This repo is the source project for building and documenting a deep pre-PR code review skill for Codex.

Its core function is to make Codex behave more like a strong CodeRabbit-style reviewer: release-blocking when warranted, biased toward correctness and security, and continuously improvable from real review misses plus curated benchmark lanes.

## Current Status

The repo now contains a source copy of the skill at:

- `skill/bug-hunting-code-review`

The live installed skill still exists at:

- `~\.codex\skills\bug-hunting-code-review`

This repo is the dedicated project home for:

- skill design and prompt evolution
- bundled scripts and review helpers
- benchmark corpus management
- documentation and workflow notes
- the maintained source copy of the installed skill

## Core Function

The skill is meant to:

- review diffs like a serious pre-merge reviewer, not a style bot
- prioritize correctness bugs, security issues, broken feature behavior, contract drift, stale state, and missing negative-path coverage
- operate as a release blocker when the evidence supports it
- improve over time from two feedback lanes:
  real GitHub PR review misses and curated external benchmark datasets

This repo is where that improvement loop should live. The skill prompt, deterministic helpers, corpus files, and benchmark workflows should all evolve together here.

## Sync Workflow

The repo copy is now the maintained source for day-to-day skill changes:

- `skill/bug-hunting-code-review`

Push that source copy into the installed runtime copy with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1
```

Useful options:

- `-DryRun`
  Preview the directories and files that would be copied
- `-Destination <path>`
  Sync into a different test or runtime location

The sync is intentionally one-way and non-destructive: it overwrites files from the repo copy into the installed skill, but it does not delete stale files from the destination.

## Improvement Loop

The repo should keep the skill measurable and self-improving through:

- the bundled review corpus built from real GitHub PR review misses
- curated external review-oriented datasets
- repeatable benchmark commands that can score a draft review against both lanes
- future GitHub-linked workflow integration so review outputs and missed findings can be fed back into the corpus cleanly

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

1. Add post-sync verification so the installed skill can be proven to match repo source.
2. Strengthen the self-improvement loop around GitHub PR review intake and benchmark scoring.
3. Add packaging or CI only after the local source layout is stable.
