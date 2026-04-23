# Roadmap

This document is the working plan for ReviewPilot from this point forward.

The project is now past the early scaffolding stage. The plugin exists, the public install path exists, the public repo is live, and the main review, triage, learning, and release workflows are in place.

The next job is not to add lots of new surface area. The next job is to make ReviewPilot sharper, easier to trust, and easier to use.

## What Is Already In Place

- a public `codex-review` plugin
- a public npm install path
- local review modes with `quick` and `deep`
- PR queue triage
- review-quality comparison against real GitHub review feedback
- safer probationary learning
- release validation and publish automation

## Current Priority

Improve review quality and prove it with better evaluation.

That means ReviewPilot should:

- find more real bugs
- produce fewer weak or noisy findings
- use less review budget on low-risk PRs
- make the learning loop safer and more explainable

## Phase A: Improve The Review Output

Focus on the actual quality of findings first.

- improve prioritization so the most important bugs appear first
- reduce vague or low-signal findings
- make inline comments clearer and easier to act on
- strengthen `quick` mode for smaller PRs so it is useful without feeling shallow
- keep `deep` mode for higher-risk PRs, but make it earn the extra spend

## Phase B: Add Better Evaluation

ReviewPilot now needs stronger evidence, not just more features.

- build a small real-world evaluation set from real PRs
- track whether `quick` was enough or should have escalated
- track whether `deep` found materially better issues
- measure token usage and cache reuse across review modes
- make it easy to compare runs over time

## Phase C: Improve The GitHub User Flow

The engine is now stronger than the product experience. Tighten the path around it.

- make it obvious when to use `quick`, `deep`, or `skip`
- make PR triage output easier to read and act on
- make one-PR review and multi-PR triage feel like the default workflow
- make review-quality comparison easier to run after a review finishes

## Phase D: Tighten The Learning Loop

Learning from misses is a core differentiator, so it needs to stay careful.

- improve approval gates before learning from GitHub misses
- keep a clear audit trail for what was learned and why
- make rollback easy if a bad lesson gets through
- keep probationary lessons clearly separate from durable lessons

## Phase E: Product Polish

Keep improving the public product surface without turning the repo into marketing fluff.

- add better screenshots or demo visuals
- keep the README focused on features and install
- keep contributor docs obvious and simple
- keep maintainer-only docs clearly marked as maintainer docs

## What Should Wait

These ideas are valid, but they should not lead the next phase.

- broad new automation layers
- major new benchmark lanes
- large refactors for style alone
- SaaS-style product expansion
- extra packaging complexity that does not improve review quality or usability

## Near-Term Execution Order

1. improve the quality of review findings
2. add better evaluation and reporting around real PR reviews
3. tighten the PR triage and review flow
4. harden the learning loop further
5. keep polishing the public plugin surface

## Success Criteria

The next phase is working if:

- users trust the findings more
- low-risk PRs are cheaper to review
- high-risk PRs still get strong deep reviews
- learning changes are safer and easier to audit
- the plugin feels more like a dependable product than an experimental repo
