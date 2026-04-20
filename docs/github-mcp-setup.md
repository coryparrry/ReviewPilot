# GitHub MCP Setup

If you want ReviewPilot to learn from GitHub pull request review feedback, you need the GitHub MCP connection available in Codex.

## What The Plugin Already Includes

This repo already ships a plugin-owned MCP config in:

- `plugins/codex-review/.mcp.json`

That config points ReviewPilot at GitHub in read-only mode and limits the toolset to pull request review work.

So you do **not** need to hand-write the GitHub MCP config for this plugin.

## What You Still Need To Do

You still need Codex Desktop to have a working GitHub connection for your account.

In plain English, that means:

1. Install the plugin.
2. Open Codex Desktop.
3. Make sure GitHub is connected and authenticated in the app.
4. Restart Codex Desktop if you just installed the plugin or changed the connection.

The exact GitHub sign-in flow belongs to Codex Desktop, not this repo, so it may vary slightly by app version.

## How To Tell It Is Working

The simplest sanity check is:

1. make sure the plugin is installed
2. make sure GitHub is connected in Codex
3. run a GitHub-intake workflow with a captured MCP artifact

Example:

```powershell
python .\plugins\codex-review\scripts\run_github_intake_pipeline.py `
  --repo owner/name `
  --pr 123 `
  --raw-input .\artifacts\github-intake\mcp\pr-123-comments.json `
  --raw-format github_mcp_pr_comments `
  --apply-mode review
```

If you want to keep the whole local workflow in one entrypoint, use:

```powershell
python .\plugins\codex-review\scripts\run_automation_cycle.py `
  --repo . `
  --github-repo owner/name `
  --github-pr 123 `
  --github-raw-input .\artifacts\github-intake\mcp\pr-123-comments.json
```

## Capturing GitHub MCP Output

ReviewPilot expects a local artifact file as input to the learning pipeline.

Typical flow:

1. Use the GitHub connector in Codex to fetch PR comments or review threads.
2. Save that tool output into a local file.
3. Convert it into a stable local artifact with:

```powershell
python .\plugins\codex-review\scripts\capture_github_mcp_feedback.py `
  --repo owner/name `
  --pr 123 `
  --kind pr_comments `
  --input .\artifacts\github-intake\mcp-tool-output.json
```

4. Feed the captured artifact into the intake pipeline or automation wrapper.

## Why It Works This Way

The plugin keeps GitHub access read-only and local-artifact-based on purpose.

That gives you:

- a safer public default
- reproducible intake runs
- a clear handoff between Codex connector output and repo-local learning scripts
