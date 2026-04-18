# Sync Plan

## Current State

There are currently two copies of the skill:

1. Repo source copy:
   - `plugins/codex-review/skills/bug-hunting-code-review`
2. Installed runtime copy:
   - `~/.codex/skills/bug-hunting-code-review`

## Rule Right Now

Do not edit both copies casually.

Edit the plugin-contained repo source copy, then push it into the installed runtime copy with the repo sync script.

## Intended Direction

- make the repo copy the maintained source
- push updates from the repo copy into the installed runtime copy when needed
- keep validation runnable against the repo copy before syncing
- add an explicit verification step so sync results can be proven, not just copied
- treat the current direct skill runtime as a transition path while the plugin install/runtime workflow is being defined

## Implemented Workflow

Sync repo source to the installed skill with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1
```

Preview the sync first with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1 -DryRun
```

Current behavior:

- one-way only: plugin-contained repo copy -> installed direct skill copy
- overwrites existing files in the installed copy
- creates missing directories
- skips `__pycache__` by default
- does not delete stale destination files

## Follow-Up

- decide whether stale-file cleanup should stay manual or become an explicit opt-in mirror mode
- add lightweight validation around the sync step if the workflow grows
- keep the sync workflow secondary to the actual skill mission: improving CodeRabbit-style review quality from GitHub review misses and dataset-backed benchmark lanes
- define the separate plugin install/runtime workflow so plugin metadata, future MCP config, and skill runtime can be synced or installed together
