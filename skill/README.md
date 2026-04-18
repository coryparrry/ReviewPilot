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

## Source-of-Truth Goal

This repo should now be treated as the maintained source project so that:

- the plugin becomes the primary project container
- the installed skill can be updated from a known source
- docs, scripts, and references stop drifting across locations
- the skill can keep improving from real PR review misses and benchmark datasets in one place
