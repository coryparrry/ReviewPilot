# Codex Review 🧠🔍

An early-beta Codex plugin + skill stack for **serious code review**.

The goal is simple:

> make Codex behave more like a strong, release-blocking reviewer than a polite style bot.

This project focuses on:

- real correctness bugs
- security issues
- stale state and broken workflow logic
- contract drift
- missing negative-path handling
- missing or misleading tests

It is also designed to **improve over time** from:

- real GitHub PR review misses
- curated external benchmark lanes like SWE-bench

## 👋 Who This Is For

This repo is for people who want Codex to do **deeper, tougher code review** than the default happy-path version.

It is especially aimed at:

- people who want Codex to act more like a cautious senior reviewer
- people who want review quality to be measured, not guessed
- people who want a safe learning loop instead of blindly auto-training on everything
- people who are happy trying an early beta and living with some rough edges

If you want a one-click polished product today, this repo is not there yet.

If you want an ambitious early-beta review system you can run, inspect, and improve, this is the right place.

## 🚧 Status

**Very early beta.**

This repo is already useful for:

- deep local Codex reviews
- benchmarking review quality
- safe probationary self-learning from GitHub review misses
- external hardening with curated Hugging Face benchmark cases
- structured repair handoffs after a review run

This repo is **not** pretending to be fully polished yet.

Rough edges still exist around:

- packaging and install ergonomics
- automation polish
- some pipeline correctness issues the reviewer is still surfacing inside this repo
- polish and onboarding clarity

## ✨ What It Can Do Today

### Review like a blocker, not a cheerleader

The bundled review skill is here:

- [plugins/codex-review/skills/bug-hunting-code-review/SKILL.md](plugins/codex-review/skills/bug-hunting-code-review/SKILL.md)

It pushes Codex toward:

- aggressive bug-finding
- evidence-based findings
- four-pass review discipline
- real-world feature and workflow reasoning

### Run local reviews end to end

The main local review runner is:

- [plugins/codex-review/scripts/run_codex_review.py](plugins/codex-review/scripts/run_codex_review.py)

It can:

- prepare review artifacts
- invoke Codex non-interactively
- write `review.md`
- write benchmark artifacts
- emit a structured repair plan
- retry once automatically if review generation fails mechanically

### Learn from GitHub review misses safely

The GitHub learning path is built around:

- [plugins/codex-review/scripts/run_github_intake_pipeline.py](plugins/codex-review/scripts/run_github_intake_pipeline.py)

It can:

- ingest GitHub review feedback
- normalize comments into proposal artifacts
- generate corpus candidates
- gate them before admission
- apply only into the **probationary** lane by default
- require stronger evidence before promotion into the durable corpus

### Harden the reviewer against known benchmark bugs

The external hardening lane now exists here:

- [plugins/codex-review/skills/bug-hunting-code-review/scripts/run_hf_hardening_cycle.py](plugins/codex-review/skills/bug-hunting-code-review/scripts/run_hf_hardening_cycle.py)

It can:

- fetch curated rows from `SWE-bench/SWE-bench_Verified`
- hide the answer patch from the reviewer
- run Codex on the bug report only
- score whether Codex found the intended bug
- report **target-case recall**

### Turn reviews into repair handoffs

After a review run, the plugin can generate:

- `repair-plan.json`
- `repair-plan.md`

Then a bounded one-finding fix handoff can be prepared with:

- [plugins/codex-review/scripts/run_review_fix.py](plugins/codex-review/scripts/run_review_fix.py)

That path is safe by default:

- one finding at a time
- prepare-only by default
- explicit `--apply` needed for an edit pass

### Run as a Codex automation flow

There is now an automation-facing orchestration skill:

- [plugins/codex-review/skills/autonomous-review-cycle/SKILL.md](plugins/codex-review/skills/autonomous-review-cycle/SKILL.md)

and a wrapper underneath it:

- [plugins/codex-review/scripts/run_automation_cycle.py](plugins/codex-review/scripts/run_automation_cycle.py)

That path can orchestrate:

- local review
- repair handoff
- optional GitHub learning intake
- Hugging Face hardening

## 🧱 Project Shape

This repo is intentionally split in two:

### Skill = review brain

The skill owns:

- review posture
- bug classes
- evidence bar
- release-blocking standard
- benchmark expectations

### Plugin/scripts = execution layer

The plugin owns:

- Codex-facing automation
- GitHub intake
- benchmarking
- repair-plan generation
- bounded fix handoffs
- external hardening workflows

That split matters.

This project is still supposed to work as a **Codex skill**, not turn into a random pile of scripts.

## 📦 Install / Try It

The easiest way for normal users should be a **downloadable release zip**, not a source checkout.

### Recommended install for users

Download a release bundle, unzip it, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_plugin_to_codex.ps1
```

That is the intended public install path.

### npm-friendly installer path

This repo is now also set up for an npm-style installer command.

The goal is a future install experience like:

```bash
npx codex-review-install
```

That still installs into Codex Desktop's plugin folder under the hood, but it removes most of the manual steps for users.

### Repo checkout install

If you are developing the plugin or want the source repo too, you can still clone this repo and run the same installer from here.

Also: there are **two different setup paths** in this repo.

- **Plugin install**
  This makes Codex Desktop see the repo as a plugin bundle.
- **Skill sync**
  This updates the direct installed skill runtime under `.codex/skills`.

If you skip the plugin install, Codex Desktop may not discover the plugin bundle properly.

### What you need

- Python 3
- Codex available either as:
  - `codex`
  - or `npx @openai/codex`
- a local git repo to review

Optional:

- GitHub MCP access if you want the safer live GitHub intake path
- legacy `gh` only if you intentionally want the old fallback fetch path

### Basic setup

1. Clone this repo.
2. Install the plugin into Codex Desktop's local marketplace path with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_plugin_to_codex.ps1
```

3. Restart Codex if the plugin does not appear right away.
4. Open the repo in Codex.
5. Keep the plugin-contained skill as the source of truth in this repo.
6. If you also want the direct installed skill runtime updated, sync it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_skill_to_codex.ps1
```

What those two scripts do:

- `install_plugin_to_codex.ps1`
  Copies the plugin bundle into `~/.codex/local-marketplaces/<marketplace-name>/plugins/codex-review` and writes `.agents/plugins/marketplace.json` inside that marketplace so Codex Desktop can discover it.
- `sync_skill_to_codex.ps1`
  Copies the maintained review skill into the direct runtime skill path under `.codex/skills/bug-hunting-code-review`

If you are just exploring the repo and reading the code, you do **not** need to sync the runtime skill first.

### Build a downloadable release bundle

If you are maintaining the project and want a shareable install zip:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_plugin_release_bundle.ps1
```

That writes a release folder and zip under `artifacts/release-bundles/`.

It also builds an npm tarball with `npm pack` into the same output folder.

### Fastest first run

If you want to see the project do something useful right away, run:

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py `
  --repo . `
  --base origin/main
```

That gives you:

- a real review artifact
- benchmark output
- a repair plan

So the simplest way to try this repo is:

- clone it
- run one local review
- inspect the generated artifacts
- then decide whether you want the GitHub learning loop too

## 🛡️ Safety Model

This repo is deliberately conservative.

### GitHub

- preferred GitHub path is MCP-backed and read-only
- GitHub write access is not part of the normal workflow
- learning defaults into the **probationary** corpus, not the main durable corpus

### Repairs

- repair plans are generated automatically
- actual code fixes are still bounded and explicit
- one-finding fix execution is opt-in

### External benchmarks

- SWE-bench style data is used as **hardening pressure**
- it is **not** treated as direct truth for auto-writing the GitHub-derived corpora

## 🚀 Quick Start

### 1. Run a deep local review

```powershell
python .\plugins\codex-review\scripts\run_codex_review.py `
  --repo . `
  --base origin/main
```

What you get:

- review artifact
- benchmark summary
- repair plan

### 2. Prepare a bounded fix handoff

```powershell
python .\plugins\codex-review\scripts\run_review_fix.py `
  --repo . `
  --repair-plan .\.codex-review\<run>\repair-plan.json `
  --finding-index 1
```

### 3. Run a blind external hardening batch

```powershell
python .\plugins\codex-review\skills\bug-hunting-code-review\scripts\run_hf_hardening_cycle.py `
  --repo . `
  --offset 0 `
  --length 5
```

### 4. Run the automation wrapper

```powershell
python .\plugins\codex-review\scripts\run_automation_cycle.py `
  --repo . `
  --skip-github-intake `
  --hardening-length 1
```

## 🧭 Best Way To Use It Right Now

If you are new to the repo, this is the best order:

1. Run a local review.
2. Read the generated `review.md`.
3. Look at the repair plan.
4. Try one bounded repair handoff.
5. Only after that, try the GitHub learning flow.
6. Use the Hugging Face hardening lane to pressure-test the reviewer without needing your own buggy PRs all the time.

That gives you the most value with the least confusion.

## 🧪 GitHub Learning Flow

If you already have captured GitHub MCP review output, the intake pipeline can use it directly.

Capture helper:

- [plugins/codex-review/scripts/capture_github_mcp_feedback.py](plugins/codex-review/scripts/capture_github_mcp_feedback.py)

Pipeline:

- [plugins/codex-review/scripts/run_github_intake_pipeline.py](plugins/codex-review/scripts/run_github_intake_pipeline.py)

Recommended behavior:

- score against a real review artifact
- gate candidates
- apply into the probationary lane
- promote to the primary lane only with stronger repeated evidence

## 📚 Docs

- [Project Overview](docs/index.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Plugin README](plugins/codex-review/README.md)
- [Installed Skill Relationship](skill/README.md)

## 🧪 Early Beta Notes

This project is already useful, but it is still early.

You should expect:

- fast iteration
- rough edges in setup
- ongoing improvements to automation and learning quality
- a review system that is ambitious by design, not quietly minimal

If you like sharp tools in beta, this is for you.

## 🗺️ Near-Term Roadmap

- tighten the remaining pipeline correctness issues the reviewer is surfacing
- make the GitHub MCP capture path smoother inside the automation loop
- improve benchmark reporting and repeated-miss handling
- keep the skill judgment inside the skill while making the plugin automation more polished
- document install and usage for other people cleanly

## 💥 Why This Repo Exists

Because “AI code review” is usually too soft.

This project is trying to build something sharper:

- more suspicious
- more benchmarked
- more measurable
- more honest about misses
- more useful before merge, not after prod breaks

If that sounds fun, you’re in the right repo.
