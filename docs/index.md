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

## Active Plans

- [Roadmap](roadmap.md)
  Current project direction and next-phase priorities after the public plugin release
- [GitHub Intake Plan](github-intake-plan.md)
  Plugin-owned workflow plan for ingesting GitHub PR review feedback, generating corpus candidates, and applying safe additions

## Practical Guides

- [GitHub MCP setup](github-mcp-setup.md)
  How to connect the GitHub side of the plugin's learning flow
- [Lessons workflow](lessons-workflow.md)
  How to turn local review lessons into reviewed prompt improvements safely
- [Public release checklist](public-release-checklist.md)
  What to run and confirm before making the repo public

## Near-Term Direction

- improve the quality of review findings before adding broad new surface area
- measure review quality and cost more clearly on real PRs
- make `quick`, `deep`, and triage feel like the normal user flow
- keep the learning loop safe, auditable, and deliberate
