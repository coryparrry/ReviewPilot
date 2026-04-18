# Installed Skill Relationship

The live installed skill currently lives at:

- `~\.codex\skills\bug-hunting-code-review`

This repo was created after the installed skill had already grown substantially.

## Current Rule

This repo now contains a source copy at:

- `skill/bug-hunting-code-review`

The installed skill under `.codex/skills/` is still the live runtime copy.

Do not edit both copies manually. Make changes in the repo copy, then sync them into the installed copy with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1
```

That workflow is one-way and non-destructive by default. It updates the installed runtime copy from the repo source copy without deleting extra files from the destination.

## Source-of-Truth Goal

This repo should now be treated as the maintained source project so that:

- the repo becomes the maintainable source project
- the installed skill can be updated from a known source
- docs, scripts, and references stop drifting across locations
- the skill can keep improving from real PR review misses and benchmark datasets in one place
