# Installed Skill Relationship

The live installed skill currently lives at:

- `~/.codex/skills/bug-hunting-code-review`

This repo was created after the installed skill had already grown substantially.

The maintained source has now moved under the plugin container at:

- `plugins/codex-review/skills/bug-hunting-code-review`

## Current Rule

The installed skill under `.codex/skills/` is still the live runtime copy.

Do not edit both copies manually. Make changes in the plugin-contained repo copy, then sync them into the installed copy with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1
```

That workflow is one-way and non-destructive by default. It updates the installed runtime copy from the plugin-contained repo source copy without deleting extra files from the destination.

## What The Skill Source Covers

The maintained source inside this repo now covers more than the core review prompt.

It also contains:

- the review router that decides what kind of review context to load
- the automation router that points Codex toward the right workflow entrypoint
- the review-surface scan and prompt-prep scripts
- the benchmark, calibration, and learning references that support safer review tuning

The intent is that the repo copy stays the maintained source-of-truth, while the installed copy stays the runtime copy Codex uses locally.

## Source-of-Truth Goal

This repo should now be treated as the maintained source project so that:

- the plugin becomes the primary project container
- the installed skill can be updated from a known source
- docs, scripts, and references stop drifting across locations
- the skill can keep improving from real PR review misses and benchmark datasets in one place

In practice, that means:

- edit the plugin-contained source here
- sync it into the installed runtime when needed
- treat the repo docs as the place to explain new review features such as PR triage, escalation-based deep review, and cache reuse
