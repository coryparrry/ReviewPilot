# Maintainer Release Checklist

This document is for ReviewPilot maintainers.

Use this checklist before pushing a public release or publishing the npm installer.

If you want GitHub to prepare the version bump for you, run the **Prepare release** workflow first. It takes one version input and:

- `package.json`
- `plugins/codex-review/.codex-plugin/plugin.json`

Then it:

- creates a release branch
- commits the version update onto that branch
- opens or updates a release PR back into `main`

After that PR is merged, create the matching GitHub Release to trigger the npm publish workflow.

## Required

1. Run:

```powershell
python .\scripts\validate_public_release.py
```

and then:

```powershell
python .\scripts\smoke_test_release.py
```

2. Confirm the public metadata is final:

- `package.json`
- `plugins/codex-review/.codex-plugin/plugin.json`
- those two version fields must match exactly

3. Confirm the public URLs are correct:

- package metadata should point at the public GitHub repo
- plugin homepage and website URL should point at the public GitHub repo
- privacy and terms URLs can stay blank until you have real public policy pages

4. Confirm `LICENSE` is present and matches the metadata.

5. Read the top-level `README.md` as a first-time user and make sure:

- install is obvious
- first run is obvious
- the beta status is honest
- docs links are enough to go deeper

## Recommended

1. Smoke-test the installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_plugin_to_codex.ps1
```

Or run the combined scripted smoke test:

```powershell
npm run smoke:release
```

2. Smoke-test a local review:

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py `
  --repo . `
  --base origin/main
```

3. Smoke-test the lessons snapshot flow:

```powershell
python .\plugins\codex-review\skills\bug-hunting-code-review\scripts\refresh_lessons_reference.py `
  --source C:\path\to\codex-lessons.md `
  --output .\artifacts\tmp-lessons-check.md
```

4. Build a release bundle if you plan to ship zip installs:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_plugin_release_bundle.ps1
```

## Current Automation Boundary

This repo now automates the main local workflow more cleanly, including optional lessons refresh and same-run GitHub promotion flags in the automation wrapper.

The GitHub publish workflow does not choose versions for you by itself. It publishes the versions already committed in:

- `package.json`
- `plugins/codex-review/.codex-plugin/plugin.json`

So before cutting a release, make sure those committed version numbers are already the ones you intend to publish.

Remaining early-beta edges:

- live GitHub intake still depends on captured connector output or the legacy fallback path
- durable promotion still needs explicit ids or wrapper inputs rather than blind always-promote behavior
- the automation flow is end-to-end for known inputs, but live service access still depends on the environment you run it in

That is acceptable for a public early beta as long as the README stays honest about it.
