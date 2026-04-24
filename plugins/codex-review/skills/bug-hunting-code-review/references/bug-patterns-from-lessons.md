# Bug Patterns From Lessons

These patterns are distilled from repeated Codex misses in the lessons log. Use them as forced prompts during review.

These lessons mostly capture operational and correctness misses rather than a full security corpus. Treat them as extra bug-hunting prompts, not a replacement for a real security pass.

## 1. Diff-Local Review Misses Cross-Layer Bugs

Repeated failure mode:

- The changed lines looked reasonable.
- The real bug lived in an adjacent route, service, matcher, scheduler, or persistence path.

Review response:

- Trace the entire flow across layers.
- Do not stop at the file named in the diff.
- Ask what other component must agree with this change for it to be correct.

## 2. Wrong Assumptions About Service Semantics Create Fake Bugs and Miss Real Ones

Repeated failure mode:

- The reviewer assumed create/update/delete semantics that the service did not actually implement.
- A test or review note was built on that false assumption.

Review response:

- Read the service and existing tests before judging expected behavior.
- Distinguish "surprising behavior" from "incorrect behavior."
- Prefer verified invariants over guessed ones.

## 3. Safe-Looking Fallbacks Can Produce Dangerous Wrong-Target Behavior

Repeated failure mode:

- A fallback intended to keep interactions smooth redirected an invalid or blocked action to a nearby valid-looking target.
- The result was a bad mutation rather than a harmless no-op.

Review response:

- Scrutinize fallback logic in drag/drop, nearest-match, default-target, and degraded-mode code.
- Ask whether invalid input should fail closed instead of picking the nearest allowed alternative.

## 4. Stale State Is a First-Class Bug Source

Repeated failure mode:

- Code reused stale pre-bootstrap state, stale sessions, stale drafts, or stale async results.
- The system then mutated or rendered against no-longer-current truth.

Review response:

- Check whether state is reloaded after bootstrap, migration, revoke, refresh, or backend mutation.
- Check whether old async responses are ignored when newer state exists.
- Check whether local drafts resync without erasing active edits.

## 5. Error-Path Shaping Matters as Much as the Happy Path

Repeated failure mode:

- The main flow worked, but `401`, `403`, `404`, missing-config, or validation paths were shaped incorrectly.
- The UI blanked, controls stayed stale, or the wrong failure surfaced.

Review response:

- Inspect unhappy-path behavior explicitly.
- Ask whether the surface should partially degrade instead of hard-failing.
- Make sure returned statuses, payloads, and UI refresh behavior stay aligned.

## 6. Small Helper Changes Can Hide Real Data Bugs

Repeated failure mode:

- A helper that looked minor introduced secret disclosure, whitespace corruption, or other value-handling regressions.

Review response:

- Review masking, trimming, normalization, and serialization helpers with the same care as core business logic.
- Check short strings, empty strings, exact-byte preservation, and delete-only states.

## 7. Scope and Isolation Bugs Hide in Multi-Item Systems

Repeated failure mode:

- One item's failure polluted siblings, or events were emitted with the wrong scope and disappeared from the place users depend on them.

Review response:

- For schedulers, queues, and multi-entity loops, verify per-item isolation.
- For audit and event code, verify downstream visibility and scope, not just emission existence.

## 8. Cleanup and Revoked-State Paths Often Need Different Rules

Repeated failure mode:

- A guard written for active-state safety accidentally blocked cleanup of revoked or inactive state.

Review response:

- Check whether guards should apply only to active entities or only to write paths.
- Review delete, revoke, and cleanup flows separately from create/update flows.

## 9. Environment Confusion Can Masquerade as a Product Bug

Repeated failure mode:

- A route mismatch, wrong server, wrong port, or worktree mismatch looked like a code regression.

Review response:

- Separate environment mismatch from product defect before reporting.
- If the review claim depends on runtime topology, confirm the topology from source or explicit evidence.
- Do not write a correctness finding that is actually a local-environment mix-up.

## 10. Real Regression Coverage Must Mirror the Product Flow

Repeated failure mode:

- Tests existed, but they asserted invented behavior or skipped the state transitions that make the bug real.

Review response:

- Prefer regression tests that mirror bootstrap, reload, resync, revoke, stale-response, or invalid-target flows.
- Ask whether the test would fail for the exact bug you are worried about.

## 11. Scope Moves Need Reverse-Reference Revalidation, Not Just Local Validation

Repeated failure mode:

- A team, parent, or workspace move updated the moved record and validated its direct fields.
- Existing dependents still pointed at the moved object across the old scope, creating persisted invalid references that broke later operations.

Review response:

- After any scope move, inspect all reverse references: members, children, assigned agents, linked teams, or downstream records.
- Ask whether the code migrates dependents, rejects the move, or runs full-graph validation before save.
- Do not accept "the moved entity validates" as proof that the graph still validates.

## 12. Acting User Identity Is Not Always the Invariant Identity

Repeated failure mode:

- The patch used the authorized request actor when calling a validator.
- The validator actually enforced an invariant tied to durable owner/root/system identity, so valid edits by non-owner admins failed or pushed the graph toward the wrong owner identity.

Review response:

- Separate authorization identity from invariant identity.
- Trace where owner, root user, chief executive anchor, or system principal should come from in durable state.
- Flag any path where a validator accepts or requires the acting user when the invariant belongs to persisted workspace or company ownership.

## 13. Privacy Fixes Must Close Every Equivalent Write Path

Repeated failure mode:

- A diff added authorization or membership checks to one write action.
- Another sibling path could still create or mutate the same private object without that check.

Review response:

- Enumerate every equivalent create/reply/react/edit/write entry point for the protected object.
- Treat hidden ids or low discoverability as non-security arguments; require explicit authz or membership on each path.
- Do not accept "message writes are protected" if thread creation, root-post creation, or other sibling writes still bypass the same privacy boundary.

## 14. New Fields Must Have a Legacy-Data Story

Repeated failure mode:

- A new field, enum, or filter was correct for freshly written records.
- Older persisted records without that field silently disappeared, changed meaning, or made the UI look empty after upgrade.

Review response:

- Ask how pre-existing data is interpreted when the field is missing.
- Require either migration/backfill or a safe default for legacy records.
- Treat "works on new stores" as incomplete unless the change is explicitly migration-only.

## 15. Locking Code Must Be Safe Under Slow Writers, Init Failure, and Crash Recovery

Repeated failure mode:

- The happy path looked fine, but lock age was mistaken for owner death, init failure left stranded artifacts, or crash recovery was missing entirely.
- The result was broken mutual exclusion, lost updates, or permanent local bricking until manual cleanup.

Review response:

- Walk the lock lifecycle: acquire, initialize metadata, critical section, release, init failure, slow writer, crash, and recovery.
- Require proof of owner death or liveness failure before breaking a lock.
- Check that partial initialization closes handles and removes artifacts.
- Check that orphaned artifacts do not wedge future readers/writers forever.

## 16. Migrations Must Backfill New Runtime Assumptions

Repeated failure mode:

- A migration copied old persisted entities forward unchanged.
- New code now expected required fields, trigger metadata, or derived defaults that those older records did not contain.

Review response:

- Compare the old persisted shape with the new runtime/schema expectations.
- Require backfill, normalization, or safe derived defaults during migration.
- Treat "schema version bumped" as insufficient if post-migration reads still see undefined required values.

## 17. Loops Need Per-Item Failure Isolation

Repeated failure mode:

- A poller or loop called the per-item worker directly.
- One thrown item aborted the whole batch, skipped siblings, and sometimes lost already completed work because persistence/finalization never ran.

Review response:

- Review the control flow after the first throw inside every agent/automation/job loop.
- Ask whether per-item failures are caught, recorded, and isolated.
- Verify that already completed sibling work is still finalized and persisted.

## 18. Trigger-Specific Rules Must Not Leak Across Paths

Repeated failure mode:

- A check or side effect intended for heartbeat/scheduled runs was applied to manual runs too, or vice versa.
- Valid launches were blocked or unrelated schedulers were delayed by the wrong timestamp/state mutation.

Review response:

- Enumerate trigger types explicitly: manual, scheduled, heartbeat, approval resume, migration recovery.
- For each check or side effect, ask which trigger types it should apply to.
- Flag any shared path that updates heartbeat/schedule state or capability gates without discriminating by trigger.

## 19. State Machines Must Keep Status, Steps, and Outputs Aligned

Repeated failure mode:

- A run or approval transition updated one surface such as status.
- Related surfaces such as active step, pending next step, artifact creation, or approval state were left contradictory.

Review response:

- Check every transition edge, not just initial creation.
- Require a consistent story across status, step trace, approvals, outputs/artifacts, and downstream UI readers.
- Pay extra attention to migrated paused states and post-approval resume paths.

## 20. Typed Client Errors Must Survive to the Route Boundary

Repeated failure mode:

- Helpers threw plain `Error` for missing records or invalid user input.
- Route layers only mapped typed/domain errors, so user mistakes surfaced as 500 instead of 4xx.

Review response:

- Trace not-found and validation errors from helper to route.
- Ensure typed/domain errors are thrown where the route expects them, or the route maps those failures explicitly.
- Treat incorrect 500s for client faults as correctness bugs because they break retry and UI semantics.

## 21. Parser Correctness Includes Rejection and Runtime Bounds

Repeated failure mode:

- Parsing accepted malformed tokens by partial coercion, or valid-but-pathological inputs caused long blocking scans.
- Schedule semantics also diverged from expected standards on edge cases.

Review response:

- Verify full-token validation, not partial parsing.
- Check impossible-value short-circuits and runtime bounds for sparse inputs.
- Compare edge-case semantics against the intended standard, especially cron day fields and sparse schedules.

## 22. UI Editability Must Match Real Actionability

Repeated failure mode:

- A refactor preserved visual editing controls but dropped the old disable/read-only guard or save path.
- Users could change local draft state that they could never actually commit, creating misleading or unsavable UI.

Review response:

- For every visible control, ask whether the user can actually persist the change.
- If save is disabled for a role or self-edit path, the underlying fields should usually be disabled or read-only too.
- Treat editable-but-unsavable state as a correctness bug, not just UX polish.

## 23. Frontend Identity Must Match Backend Identity

Repeated failure mode:

- Frontend display code deduped or grouped entities by a human-readable identity.
- Backend uniqueness was actually by id, so valid distinct records disappeared from the UI.

Review response:

- Check what the backend truly guarantees as unique.
- If the backend does not enforce `(workspace, kind, name)`-style uniqueness, do not dedupe by display fields alone.
- Flag any UI data-shaping step that can silently hide valid records.

## 24. Accessibility and Severity Semantics Regress Easily in UI Refactors

Repeated failure mode:

- Custom fields lost explicit labels, interactive elements lost focus-visible styling, or hard errors were rendered as soft warnings.
- The UI still "worked" visually for mouse users but became misleading or less usable.

Review response:

- Review repeated/custom controls for explicit accessible naming.
- Check keyboard focus visibility on non-native button treatments.
- Check that warning/error/success variants still match the real severity of the state.
- When replacing native controls with wrappers, verify old accessibility and disabled semantics still flow through.

## 25. Navigation Refactors Can Hide Real Surfaces

Repeated failure mode:

- A page/tab refactor preserved the route or page implementation.
- The normal shell navigation no longer provided a direct way back to it, or stale selection state remained highlighted after navigation.

Review response:

- Verify direct reachability of every dedicated surface after navigation refactors.
- Check whether default navigation clears unrelated selection state unless preservation is explicitly intended.
- Treat hidden-but-still-existing surfaces and stale highlighted context as functional regressions.

## 26. AI-Slop Usually Means Drift, Fake Certainty, or Wrapper Loss, Not Just Ugly Code

Repeated failure mode:

- Generated-looking code duplicated resolver, mapper, validator, or fallback logic instead of reusing the real source of truth.
- The duplicate path drifted and started enforcing the wrong contract, defaulting missing state unsafely, claiming validation that never ran, or dropping behavior that the wrapped primitive used to preserve.

Review response:

- Compare duplicated helpers and preview/readiness paths against the canonical resolver or runtime path.
- Flag request validation copied from response DTOs, display models, or persisted shapes instead of real input contracts.
- Flag wrappers that silently lose disabled semantics, explicit accessibility naming, null or empty distinctions, typed error shaping, or linked-data visibility.
- Treat optimistic "ready", "supported", "passed", or "validated" claims as bugs when the executable path or actual evidence does not support them.

## 27. Central Classifiers and Allowlist Helpers Drift Quietly

Repeated failure mode:

- A new connector family, runtime family, route type, or enum value was added in one layer.
- A central exact-key helper or allowlist still classified it as generic, unsupported, or unreachable.

Review response:

- Search for family classifiers, registries, allowlists, and exact-match helpers whenever the change introduces a new kind of thing.
- Ask whether the classification should really be derived from canonical metadata instead of copied exact-key checks.
- Treat silent fallback to generic or unsupported handling as a correctness bug when later code hard-fails or hides the feature.

## 28. Partial Parity Checks Let Inconsistent Context Leak Deeper

Repeated failure mode:

- The patch validated one or two duplicated metadata fields across layers.
- Other copied fields such as capability families or companion flags were left unchecked, so inconsistent context flowed into execution or UI state.

Review response:

- When runtime, binder, scheduler, or UI context is duplicated, compare every field the downstream path relies on, not just the obvious headline fields.
- Look for mismatches between primary state and companion booleans, families, summaries, or queue markers.
- Treat "mostly matched context" as insufficient when downstream behavior depends on exact parity.

## 29. Test Helpers Can Hide Regressions by Overwriting the World

Repeated failure mode:

- A test helper replaced the whole feature-gate, policy, or capability object to enable one scenario.
- The tests kept passing even when the product started depending on unrelated capabilities or the persisted default state changed.

Review response:

- Inspect whether fixtures merge with persisted policy or overwrite it entirely.
- Prefer narrow test setup that flips only the capability required by the scenario.
- Treat broad helper rewrites as review-relevant because they can invalidate regression coverage.

## 30. State Exits Must Clear Companion Flags and Queues

Repeated failure mode:

- A run, approval, or workflow status moved out of a gated or paused state.
- Companion booleans, pending approvals, queue summaries, or UI-facing readiness flags were left behind, so different surfaces disagreed about the current state.

Review response:

- For every transition, list the companion state surfaces that should change with it.
- Verify that leaving a gated state clears the gating artifacts as well as the headline status.
- Treat disagreement between status and queue or approval surfaces as a correctness bug even when the main transition "worked."

## 31. Optimistic Rollback Must Cover Thrown Failures

Repeated failure mode:

- A UI applied an optimistic local state update before awaiting a server action.
- The rollback path only ran when the action returned an `{ error }` payload.
- If the action threw instead, the optimistic state stayed visible and drifted from persisted truth.

Review response:

- Check both returned-error and thrown-exception paths for every optimistic mutation.
- Require rollback, resync, or invalidation in a `catch`/`finally` path when the mutation can throw.
- Treat "the action usually returns errors" as incomplete unless the caller also handles thrown transport, validation, or unexpected failures.
