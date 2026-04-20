---
name: bug-hunting-code-review
description: Perform aggressive pre-commit and pre-release code review to find correctness bugs, security vulnerabilities, broken user flows, contract mismatches, missing edge-case handling, and missing tests before approval. Use when reviewing pull requests, diffs, refactors, feature work, auth or session changes, input-handling code, API or route or service updates, persistence changes, stateful UI patches, scheduler or workflow changes, or whenever Codex should act as a release blocker rather than a style reviewer.
---

# Bug-Hunting Code Review

Review code to find real release-blocking issues before they ship.

Prioritize bugs, vulnerabilities, and broken feature behavior over style, cleanup, or theoretical advice. Treat the diff as an entry point, not the review boundary.

## Quick Start

For any substantial repo review:

1. Read the diff and identify the repo root.
2. Load the required references.
3. Build the change map before declaring any opinion.
   - Prefer `python "<skill-path>\scripts\review_surface_scan.py" --repo .`
   - For PR-style review, prefer `python "<skill-path>\scripts\review_surface_scan.py" --repo . --base origin/main`
4. Run all four passes.
5. Do not conclude `No findings` until you can answer the rubric in `references/deep-review-rubric.md`.

When improving this skill itself, regression-check it against the corpus:

- `python "<skill-path>\scripts\review_corpus_score.py" --review-file ".\draft-review.md"`
- For the external benchmark lane, use `--corpus "<skill-path>\references\swebench-verified-review-cases.json"`
- To run both lanes together, use `python "<skill-path>\scripts\run_review_benchmarks.py" --review-file ".\draft-review.md"`
- To prepare and score a pre-PR review in one command with an existing Codex review artifact, use `python "<skill-path>\scripts\run_pre_pr_review.py" --base origin/main --review-file ".\draft-review.md"`
- To prepare artifacts only, use `python "<skill-path>\scripts\run_pre_pr_review.py" --base origin/main --prepare-only`
- To let the plugin prepare artifacts, invoke Codex, write `review.md`, and benchmark it in one command, use `python ".\plugins\codex-review\scripts\run_codex_review.py" --repo . --base origin/main`
- To stage a private Knowledge-Hub lessons log into a repo-local review snapshot, use `python "<skill-path>\scripts\refresh_lessons_reference.py" --source "<path-to-codex-lessons.md>"`
- The direct OpenAI API path is legacy-only and should be treated as optional rather than required

## Review Posture

- Assume the bug may live outside the touched hunk.
- Expand the review into adjacent callers, callees, contracts, tests, and state transitions.
- Look for failing scenarios, not code smells.
- Prefer a small number of strong findings over a long speculative list.
- Do not spend review budget on nits unless they hide a correctness problem.
- Do not approve a patch only because the local code looks tidy; trace the behavior.
- Treat security and broken feature behavior as first-class review outcomes, not special cases.
- Treat AI-slop as a correctness risk, not an aesthetic complaint: duplicated resolvers, speculative wrappers, copied contract shapes, fake readiness signals, and fail-open synthesized defaults are review targets when they can drift from source-of-truth behavior.
- Treat state-surface disagreement as a real bug: if status, approval flags, queues, artifacts, summaries, or companion metadata stop agreeing after a transition, the patch is not clean.
- Treat broken imports, dead file paths, stale examples, and lint or type failures as correctness issues when they make the reviewed code unreachable, misleading, or unverifiable.

## Mandatory Review Passes

Run all four passes on every non-trivial review:

- Correctness pass: find logic errors, regressions, state bugs, wrong contracts, and missing edge-case handling.
- Security pass: look for trust-boundary failures, attacker-controlled input reaching dangerous sinks, secret exposure, broken authorization, and unsafe defaults.
- Feature-completeness pass: check whether the feature actually works end to end for a real user, including loading, error, empty, permission-loss, retry, refresh, and cleanup paths.
- Integrity pass: check whether imports, file paths, registry or allowlist entries, validation hooks, lint or type expectations, and test fixtures still describe the real executable system.

Do not conclude `No findings` until each pass has been done.

## Required Reference Load

For any meaningful review, read these before declaring the patch clean:

- `references/review-checklist.md`
- `references/evidence-bar.md`
- `references/bug-patterns-from-lessons.md`
- `references/release-blockers.md`
- `references/deep-review-rubric.md`
- `references/review-corpus-workflow.md` when tuning the skill itself or evaluating review quality over time
- `references/external-benchmark-workflow.md` when extending the skill with curated Hugging Face benchmark cases

If the patch touches auth, secrets, external input, HTML rendering, SQL, shell execution, file access, external requests, redirects, serialization, or crypto, also use `$security-review` if it is available.

If the patch materially changes TSX, interactive UI controls, page navigation, or custom form fields, also use `$web-design-guidelines` if it is available.

## Review Workflow

### 1. Build the Change Map

- Read the diff, then identify the full execution surface it affects.
- Run `scripts/review_surface_scan.py` when the repo is available; use it to surface likely hot spots and missed-review patterns early.
- List the layers involved: UI, local state, network/client, route/controller, service, persistence, background job, scheduler, audit/eventing, tests, config.
- Identify the contract that is supposed to hold after the change.
- Identify what inputs, actors, and failure modes can hit that path.
- Identify whether the patch crosses a trust boundary or exposes new attacker-controlled input.
- Identify the user-visible feature flow that must succeed after the change.

If the patch touches only one file but participates in a wider flow, review the wider flow.

Treat the scan script as a prompt generator, not as proof. If it flags registry drift, companion-state symmetry, fixture masking, or path reachability, answer that prompt explicitly during review.

### 2. Run the Four Review Passes

#### Correctness pass

- Trace the intended flow.
- Trace at least one negative path.
- Trace at least one stale-state or retry path when state is involved.

#### Security pass

- Identify attacker-controlled inputs.
- Identify dangerous sinks, trust boundaries, and authorization boundaries.
- Check whether validation, sanitization, escaping, or allowlisting actually occurs on the real path.
- Check whether secrets, tokens, masked values, or private data can leak through helpers, errors, logs, or returned shapes.

#### Feature-completeness pass

- Ask whether a real user can start, complete, retry, refresh, and recover the feature.
- Check visible controls, disabled states, empty states, loading states, error states, and post-mutation refresh behavior.
- Check whether the feature still works after revoke, delete, reload, permission loss, or partial backend failure.

#### Integrity pass

- Check import and file-path reachability for touched modules, scripts, assets, examples, and generated entry points.
- Check whether central registries, allowlists, enum families, connector maps, or capability-family helpers now need updating.
- Check whether tests or helpers preserve unrelated persisted state instead of replacing entire config or policy objects.
- Check whether validation, lint, type, or build claims are backed by runnable paths or existing repo hooks rather than optimistic comments.

### 3. Trace End-to-End Behavior

Follow the actual path the system will take, including unhappy paths.

Examples:

- UI review: user action -> local draft/state -> request builder -> route -> service -> persistence -> response mapping -> state refresh -> rerender
- API review: request validation -> authz/authn -> service semantics -> persistence -> error shaping -> side effects -> returned contract
- Scheduler/workflow review: trigger selection -> matcher -> validation -> due-item fetch -> isolation -> dispatch -> retries/failures -> persistence updates
- Data/model review: normalization -> storage -> reload -> downstream readers -> masking/rendering -> mutation symmetry

Do not stop once the touched file looks plausible.

### 4. Hunt Bug Classes Explicitly

Actively try to break the patch across these classes:

- AI-slop integrity failures where generated-looking code adds duplicated resolvers, mappers, validators, or fallback logic that can drift from the real source of truth
- Request/response contract confusion where create or patch validation is derived from response DTOs, display models, or persisted shapes instead of the real input contract
- Speculative wrappers or UI refactors that look cleaner but drop disabled guards, accessible naming, error semantics, or linked-data visibility that the replaced primitive handled
- Fake readiness, support, or validation claims where status text, docs, or returned flags say the feature is ready or checked even though the executable path, connector, or command evidence says otherwise
- Fail-open synthesis that fabricates owner, session, package, connector, or fallback state instead of rejecting missing or cross-scope inputs explicitly
- Helper or fixture widening that rewrites full policy, feature-gate, or capability objects when the scenario only needs a narrow override
- Central allowlist or registry drift where a new family, connector, enum, route, or command path must be updated in one exact-key helper to remain reachable
- Contract mismatches across layers
- Broken feature wiring where the UI exposes an action that cannot complete successfully
- Context parity mismatches where duplicated runtime or binder metadata is validated only partially, letting inconsistent companion fields flow deeper into execution
- Privacy or authorization checks added to one operation but bypassed through a sibling create/update/reply path
- Wrong fallback behavior that turns an invalid action into a bad valid action
- Missing or incorrect negative-path handling
- Cross-scope moves that leave dependent references dangling or invalid after save
- Legacy data or pre-migration records becoming invisible, excluded, or reinterpreted after new field or enum assumptions
- Newly required persisted fields missing defaults or backfill during migration/upgrade
- Stale state, stale snapshots, or out-of-order async writes
- Auth, permission, and session-refresh mistakes
- Confusing acting-user authorization with durable owner, root-user, or system identity required by invariants
- Authorization bypass, missing tenant/workspace scoping, or attacker-controlled input reaching dangerous sinks
- Injection, XSS, SSRF, path traversal, unsafe deserialization, command execution, open redirects, and secret exposure when the surface allows them
- Wrong scoping or isolation across workspace, tenant, agent, user, or team boundaries
- Normalization, trimming, masking, and short-value disclosure bugs
- Partial availability bugs where one tab, feature, or action should degrade instead of hard-failing the whole surface
- Over-broad guards that block legitimate cleanup or revoked-state handling
- Resource lifecycle bugs where partial initialization, failed cleanup, or crash recovery leaves the system permanently wedged
- Time, schedule, retry, idempotency, or duplicate-execution bugs
- Concurrency bugs where timeout or age is mistaken for liveness and mutual exclusion can be broken
- Batch/loop processing that lets one item failure abort siblings or discard already completed work
- Trigger-specific capability or side-effect rules applied too broadly across manual, scheduled, heartbeat, and approval-driven paths
- State-machine inconsistencies where statuses, steps, approvals, and artifacts stop agreeing after transition
- Companion-state drift where one transition updates status but leaves approvalRequired, pending approvals, queue summaries, readiness flags, or UI-facing booleans stale
- Plain errors escaping typed error mapping and turning client faults into 500s
- Parser or validator behavior that silently accepts malformed input or turns impossible inputs into pathological runtime scans
- UI affordances that look editable, reachable, or actionable while the real behavior is disabled, hidden, or unsavable
- Custom inputs or buttons losing accessible naming, focus visibility, or correct error/warning semantics
- Navigation or dedupe logic that hides valid entities/features because frontend display identity diverges from backend uniqueness or routing reachability
- Broken import paths, moved docs/examples, or stale command references that make the advertised validation or execution path non-functional
- Missing audit/event emission or wrong event scope when behavior depends on downstream logs or history
- Missing regression coverage for the actual bug class introduced by the change

### 5. Pressure-Test Assumptions

- Verify service semantics before treating a missing test or surprising behavior as a product bug.
- Verify whether state is freshly loaded or based on a stale pre-bootstrap snapshot.
- Verify whether fallback logic is truly safe for blocked or invalid targets.
- Verify whether the patch updates all related state, not just the happy-path state.
- Verify whether a helper that "just enables what the test needs" actually preserves unrelated persisted gates, policies, or capability settings.
- Verify whether old async responses can overwrite newer state.
- Verify whether a helper that looks minor can leak data or distort values.
- Verify whether the same change still behaves correctly after revoke, delete, retry, reload, or permission loss.
- Verify whether the feature remains operable for a user who is not in the golden-path role or state.
- Verify whether security claims depend on framework defaults, and confirm those defaults actually apply here.
- Verify whether copied resolver, mapper, validator, or fallback logic has already drifted from the shared source of truth it appears to mirror.
- Verify whether a generated-looking wrapper actually preserves the old primitive's disabled, null/empty, accessible-name, error-typing, and refresh semantics.
- Verify whether "ready", "supported", "validated", or "passed" claims are backed by the real executable path or actual command evidence rather than optimistic metadata or stale docs.
- Verify whether a move across workspace, team, parent, tenant, or ownership scope also revalidates or migrates every dependent entity that points at the moved object.
- Verify whether validators that enforce owner, root-user, chief-executive, or system-level invariants resolve identity from durable state rather than the acting request user.
- Verify whether a new authorization/privacy check is mirrored across sibling entry points that create, reply, react, edit, or otherwise write into the same protected object.
- Verify whether new enum or field filters preserve legacy records that predate the field, either by migration/backfill or safe default interpretation.
- Verify whether migrations that copy persisted entities verbatim also populate any newly required fields or derived metadata those entities now depend on.
- Verify whether lock, temp-file, or other critical resource initialization cleans up correctly if setup fails halfway through.
- Verify whether stale-lock or timeout recovery proves owner death or crash, rather than guessing from elapsed time alone.
- Verify whether a loop over agents, automations, approvals, or jobs isolates per-item failure so one bad record cannot abort the whole batch or suppress persistence of completed work.
- Verify whether trigger-specific rules are keyed to the actual trigger type instead of accidentally blocking manual runs with heartbeat-only capability checks or letting manual side effects delay scheduled work.
- Verify whether every state transition keeps related traces consistent: run status, active/pending steps, approval state, artifacts, audit records, and UI-facing summaries.
- Verify whether duplicated context objects stay fully aligned across layers, not just on one or two headline fields; if runtime family, connector type, trust, or capability sets are duplicated, review every copied field for mismatch handling.
- Verify whether user-input validation throws typed client errors all the way to the route boundary instead of plain Error that will surface as 500.
- Verify whether parser logic fully validates tokens and short-circuits impossible inputs rather than silently coercing malformed values or scanning pathologically.
- Verify whether visible UI mutability matches actual permissions and saveability, so controls are not editable when the user cannot commit the change.
- Verify whether repeated/custom fields have explicit accessible names and whether custom buttons/rows preserve keyboard focus visibility and severity semantics.
- Verify whether navigation state clears stale selections by default and whether every dedicated surface remains directly reachable after refactors.
- Verify whether display dedupe keys are aligned with backend uniqueness guarantees; if uniqueness is not enforced server-side, do not dedupe by display identity.
- Verify whether new connectors, families, commands, example paths, or docs moves are registered everywhere the runtime or reviewer now relies on exact-key checks or static paths.

### 6. Check Tests Like a Reviewer, Not a Builder

- Look for the real regression test that proves the bug class is covered.
- Prefer tests that exercise product semantics and error paths over invented assertions.
- Check whether test setup widens permissions, feature gates, or capability families so broadly that the reviewed path could be wrong and still pass.
- Treat missing tests as especially important when the change touches schedulers, workflow dispatch, state resync, authorization, persistence semantics, trust boundaries, or user-visible feature completion.
- If tests exist, check whether they would actually fail if the code were wrong in the way the patch can break.
- Check whether the tests cover security-sensitive negative paths and feature-completion paths, not just success cases.
- Check whether tests assert the real route payload shape, named entity, and persisted state transition rather than guessed wrappers, seed order, or helper-produced mirrors.

### 7. Report Findings

Report findings first, ordered by severity.

For each finding:

- Name the concrete failing scenario.
- Explain the invariant, contract, or user expectation that breaks.
- Point to the location that causes it.
- Explain why the surrounding code does not already prevent it.
- Mention the likely user-visible or system-visible impact.
- State whether the issue is primarily a correctness bug, security bug, or broken feature behavior.

If the evidence does not clear the bar in `references/evidence-bar.md`, do not upgrade it into a finding.

If no findings survive scrutiny, say so explicitly and mention the residual risk or test gap briefly.

## Reporting Rules

- Default to a code-review mindset, not an implementation mindset.
- Findings are the primary output.
- Keep summaries brief and secondary.
- Use file references and tight line references when available.
- Call out missing tests only when they materially hide a realistic bug class.
- Separate confirmed bugs from lower-confidence risks or open questions.
- Treat "this feature still does not actually work for a user" as a valid review finding even if the code shape looks reasonable.
- Treat high-confidence security concerns as release blockers, not optional hardening.

## Strong Review Habits

- Reconstruct the behavior from source instead of trusting comments or variable names.
- Check adjacent files whenever the patch changes contracts, types, routes, or persistence.
- Search for central registries, family classifiers, allowlists, feature-gate helpers, and exact-key maps that must stay in sync with the change.
- Search for mirrored create/update/delete paths and make sure the invariant holds in each direction.
- Search for mirrored write paths and make sure a new privacy or auth rule closes every equivalent path, not just the one in the diff.
- Check whether the patch handles short values, empty values, revoked values, duplicate values, and stale values.
- Check whether new fields, enums, or filters have a defined meaning for old persisted records.
- Check whether the patch is symmetric across bootstrap, refresh, retry, and reload paths.
- For migrations, compare old-store shape to new runtime assumptions and look for missing required keys, derived defaults, and recomputation metadata.
- After parent or workspace moves, follow all reverse references to confirm no dangling cross-scope links survive persistence.
- When auth is involved, separate "who is allowed to make this change" from "which durable identity the invariant is defined against."
- For lock or persistence code, reason through slow writer, init failure, crash after acquire, and concurrent contender paths before trusting the happy path.
- For loops or pollers, ask what happens after the first thrown item and whether already-finished sibling work is persisted or lost.
- For schedulers and state machines, compare every trigger path and every transition edge, not just the main scheduled happy path.
- For workflow and runtime changes, compare the primary state field with every companion state surface the UI, queue, or executor reads.
- For UI diffs, check editability, accessibility naming, focus states, navigation reachability, stale selection state, and whether frontend grouping/dedupe matches backend identity rules.
- For test diffs, inspect helpers and fixtures for over-broad rewrites that hide the bug instead of modeling the real preconditions.
- When the code feels AI-generated or over-abstracted, search for the single source of truth first, then compare every copied helper or wrapper against it before trusting the abstraction.
- Check whether a real user can reach success from the UI or API entry point without hidden manual repair steps.
- Ask what an attacker, confused user, or low-permission user can still do wrong with this flow.
- Re-read the diff after the first pass and ask what bug would be embarrassing to miss.

## Bundled Resources

### `scripts/review_surface_scan.py`

Generate a change map, layer breakdown, recurring-risk prompts, adjacency hints, and required review questions from the current repo diff.

Examples:

- `python "<skill-path>\scripts\review_surface_scan.py" --repo .`
- `python "<skill-path>\scripts\review_surface_scan.py" --repo . --base origin/main`
- `python "<skill-path>\scripts\review_surface_scan.py" --repo . --base origin/main --json`

Use it before deep review when the repo is available, especially for workflow, runtime, migration, API-contract, and test-heavy diffs.

### `references/deep-review-rubric.md`

Use this before writing `No findings`. It forces explicit answers for contract, companion state, central registries, mirrored paths, test masking, and reachability.

### `scripts/review_corpus_score.py`

Score a review output against the curated missed-review corpus from the review-comment archive lane.

Examples:

- `python "<skill-path>\scripts\review_corpus_score.py" --review-file ".\draft-review.md"`
- `python "<skill-path>\scripts\review_corpus_score.py" --review-file ".\draft-review.md" --json`
- `python "<skill-path>\scripts\review_corpus_score.py" --list-cases`

Use this when tuning the skill, comparing prompt revisions, or checking whether a new workflow still catches the bug classes Codex has repeatedly missed.

### `references/review-corpus-workflow.md`

Use this when maintaining the corpus. It explains how to add new durable cases from raw GitHub review-comment clips without editing the raw source lane itself.

### `scripts/fetch_hf_dataset_rows.py`

Fetch rows from the Hugging Face Dataset Viewer API so you can inspect external benchmark candidates without writing one-off curl commands.

Examples:

- `python "<skill-path>\scripts\fetch_hf_dataset_rows.py" --dataset "SWE-bench/SWE-bench_Verified" --config default --split test --offset 0 --length 5`
- `python "<skill-path>\scripts\fetch_hf_dataset_rows.py" --dataset "SWE-bench/SWE-bench_Verified" --config default --split test --offset 10 --length 5 --output ".\swebench-sample.json"`

### `references/external-benchmark-workflow.md`

Use this when building or refreshing curated external benchmark lanes. The current workflow covers `SWE-bench/SWE-bench_Verified` as a secondary review-oriented corpus.

## Output Shape

Use this structure:

```markdown
Findings

1. [Severity] Short title - `path/to/file:line`
   Failing scenario, why it breaks, and impact.

Open questions

- Only include when the evidence is incomplete and the question matters.

Change summary

- Brief secondary summary only after findings.
```

If there are no findings, say:

```markdown
No findings.

Residual risk:
- ...
```
