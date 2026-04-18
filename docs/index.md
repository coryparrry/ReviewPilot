# Project Overview

This repo exists to give the `bug-hunting-code-review` system a proper project home.

The repo is the maintained source of truth for the `codex-review` plugin, its bundled skill, and its evaluation workflow.

## Why This Repo Exists

The review system has grown beyond a single `SKILL.md` file. It now includes:

- a plugin container
- bundled review helpers
- benchmark lanes
- corpus management
- workflow documentation
- pre-PR orchestration scripts

The goal is not just to store prompt text. The goal is to improve a CodeRabbit-style review system over time using:

- real PR review misses
- curated external benchmark cases
- repeatable scoring workflows

That is large enough to justify its own repo and docs.

## Project Shape

- `docs/`
  Project documentation and decision records
- `plugins/codex-review/`
  Primary plugin container, including the bundled review skill
- `skill/`
  Transition notes about the installed direct skill runtime
- `scripts/`
  Project-owned automation and helper scripts, including repo-to-installed skill sync

## Near-Term Direction

- keep the installed skill working where it is today
- treat `plugins/codex-review` as the repo-backed primary container
- use the repo-owned sync script instead of editing two copies casually
- keep the review workflow measurable against GitHub review misses and external datasets
