# Lessons Workflow

This project can learn from an optional local lessons log, but it does that through a review step, not by copying raw notes straight into the committed prompt files.

## Why This Exists

Repeated review misses are useful training input.

Examples:

- missing companion state updates
- assuming the wrong service behavior
- stopping at the diff instead of tracing the full flow
- writing tests that do not mirror the real product path

Those patterns belong in the skill over time.

## Source File Shape

Keep lessons in a simple markdown file with one entry per lesson:

```md
### 2026-04-20
- Context: Reviewing a workflow patch with queue state and approval state.
- Mistake or correction: The review checked the main status change but missed that the queue summary and approval flags stayed stale.
- What changed: We now treat companion state drift as a first-class review bug.
- Prevention for next time: When status changes, check every related flag, summary, and downstream UI reader too.
```

Recommended qualities:

- short
- concrete
- based on a real miss, correction, or repeated mistake
- focused on future review behavior

Avoid putting these in the lessons file:

- secrets
- private URLs
- usernames
- internal hostnames
- vague personal reminders with no review value
- one-off environment accidents unless they teach a durable review lesson

## Build A Repo-Local Snapshot

Run:

```powershell
python .\plugins\codex-review\skills\bug-hunting-code-review\scripts\refresh_lessons_reference.py `
  --source C:\path\to\codex-lessons.md
```

That writes:

- `plugins/codex-review/skills/bug-hunting-code-review/references/local-lessons-snapshot.md`

This file is intentionally git-ignored. It is a local staging file, not the final public prompt source.

If you want the normal automation wrapper to do that refresh step for you, use:

```powershell
python .\plugins\codex-review\scripts\run_automation_cycle.py `
  --repo . `
  --lessons-source C:\path\to\codex-lessons.md
```

## Promote The Durable Patterns

After the snapshot is generated, review it and manually update:

- `plugins/codex-review/skills/bug-hunting-code-review/references/bug-patterns-from-lessons.md`

That committed file is the real skill-facing reference.

Use this rule:

- raw snapshot = local working input
- bug-patterns file = reviewed public prompt input

## When To Update

Refresh the lessons snapshot when:

- the reviewer misses the same bug class more than once
- a repeated correction changes how the review should be done
- you want to turn local review learning into a durable public prompt improvement
