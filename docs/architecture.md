# Architecture

## Core Idea

This project is a Codex-native review plugin with a bundled review skill and supporting tooling.

The skill should remain the intelligence layer:

- review posture
- bug-hunting checklist
- deep review rubric
- corpus expectations
- CodeRabbit-style release-blocking review behavior

The plugin should provide the execution boundary for:

- future GitHub-safe review ingestion
- structured scoring and sync workflows
- future MCP-backed tool surfaces

Bundled scripts should support consistency:

- diff preparation
- review surface scanning
- benchmark scoring
- corpus fetch and curation helpers
- repo-to-installed sync and later verification helpers

## Improvement Model

The project should improve the skill from two durable sources:

1. Real GitHub PR review misses and follow-up review comments
2. Curated external benchmark datasets that are review-shaped enough to pressure real bug finding

Those two lanes should stay separate in scoring so the project can distinguish:

- how well the skill catches the user's real recurring review misses
- how well the skill generalizes to broader bug-finding cases

## Intended Layers

1. Skill instructions
2. References and rubric
3. Bundled deterministic helpers
4. Benchmark lanes
5. Evaluation and self-improvement workflow
6. Transition sync workflow from plugin-contained skill source to installed direct skill runtime
7. Future plugin install/runtime wiring and integration surfaces

## Non-Goals

- replacing Codex itself as the review engine
- turning the project into a standalone SaaS
- requiring an external API just to use the skill inside Codex
- forcing mirror deletes into the installed skill during normal syncs
