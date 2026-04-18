# Review Checklist

Use this checklist to force a broad, correctness-first review. Do not mechanically copy it into the final answer; use it to drive investigation.

## 1. Frame the Contract

Ask:

- What behavior is this patch trying to change?
- What invariant must still hold after the change?
- Which actor or system depends on that invariant?
- What would count as a real regression here?

If the contract is unclear, infer it from surrounding code, tests, routes, types, and existing behavior before reporting.

## 2. Expand Past the Hunk

Check:

- Callers
- Callees
- Shared helpers
- Central registries, allowlists, connector-family maps, and exact-key classifiers
- Validation and parsing
- Persistence layer
- Response shaping
- State refresh and subscribers
- Tests and fixtures
- Feature flags or config guards

If the patch changes a type, route contract, returned shape, or shared helper, review every nearby usage that can now become wrong.

## 3. Walk the Full Path

Trace the full path appropriate to the change:

### UI and stateful frontend

- User input or interaction
- Local draft state
- Derived UI state
- Request construction
- Response merge or resync
- Rerender and stale-response handling

Questions:

- Can old async results overwrite newer state?
- Can a backend refresh wipe in-progress local edits?
- Does permission loss clear stale controls?
- Does one tab failing incorrectly poison unrelated tabs?
- Does retry/bootstrap use fresh auth/session state or stale headers?

### Route/controller/service changes

- Request decode
- Validation
- Authorization
- Service mutation semantics
- Persistence write
- Error shaping
- Returned response

Questions:

- Does the route return the right status and shape for each failure mode?
- Does the service do more or less than the reviewer first assumes?
- Does the patch fix one path but leave create/update/delete inconsistent?
- Does the returned data match what the caller now expects?
- If runtime or binder context is duplicated, do all copied companion fields still match, or are only headline fields validated?

### Workflow/scheduler/background changes

- Matcher or due-item selection
- Validation
- Scope filtering
- Dispatch
- Per-item isolation
- Retry/failure behavior
- Persistence updates
- Audit/event emission

Questions:

- Can one failing item block unrelated items?
- Can a matcher fire at the wrong boundary or miss the right one?
- Can duplicates run after retry, wake, or reload?
- Is the failure persisted and surfaced correctly?
- Are routes, services, and scheduler logic still aligned?

### Persistence/bootstrap/migration/test-fixture changes

- Bootstrap or migration side effects
- Persisted store reload
- Fixture edits
- Auth/session continuity
- Later reads from the modified state

Questions:

- Is the code mutating a stale pre-bootstrap snapshot?
- Does bootstrap create or rotate data that later code must reload?
- Does the test prove a real invariant or only an imagined one?
- Could the fixture setup itself be the source of failure?

## 4. Probe High-Risk Bug Classes

### Security and trust-boundary failures

- Is any attacker-controlled input flowing into HTML, SQL, shell, file paths, external requests, redirects, or deserializers?
- Does the patch rely on escaping, validation, or framework defaults that may not apply on this path?
- Can a lower-privilege actor read or mutate data outside their intended scope?
- Can secrets or masked values leak through short values, error text, logs, or helper output?
- Is the code relying on hidden or hard-to-guess identifiers instead of explicit authorization or membership checks?
- If a privacy rule was added for one operation, do sibling operations still reach the same object without that check?

If yes, run a dedicated security pass and escalate to `$security-review` when the surface is substantial.

### Broken feature completion

- Can a real user start and finish the feature from the visible entry point?
- Are loading, empty, disabled, error, revoked, and retry states all coherent?
- Does the UI or caller refresh to the new source of truth after mutation?
- Is there any visible control that appears available but cannot actually succeed?
- Is any control editable even though the user cannot save or apply the result?
- Did a refactor make a dedicated page or tab reachable only through a hidden jump card or one-off entry point?
- After a transition, do queue flags, approval-required booleans, readiness badges, and summaries still agree with the primary status?

### UI affordance and accessibility integrity

- Do repeated/custom inputs have explicit labels or aria-labels rather than relying on placeholder text alone?
- Do interactive custom buttons/rows keep visible keyboard focus treatment?
- Are hard failures shown with error semantics rather than warning styling?
- Does a disabled/save-guard condition also disable or make read-only the underlying field controls?
- Does navigation clear stale inbox/selection state when moving into unrelated surfaces unless preservation is explicitly requested?
- Does frontend dedupe/grouping use an identity that is actually unique in backend data, or can valid distinct records disappear from display?

### Fallback and invalid-target logic

- Does a fallback convert an invalid action into a bad valid action?
- Does a blocked target resolve to a nearby allowed target?
- Does a degraded mode stay safe and local?
- Does a helper or test fixture replace an entire policy or feature-gate object when it should merge a narrow override?

### State sync and stale data

- Can stale snapshots survive after refresh or bootstrap?
- Can async responses arrive out of order and overwrite newer truth?
- Does local draft state resync correctly after backend changes?

### Auth, role, permission, and session handling

- Does the patch refresh identity after revoke, expiry, or permission loss?
- Does it reuse stale session identifiers or headers?
- Does one success path accidentally re-authorize an invalid session?

### Scope and isolation

- Is the effect correctly limited per tenant, workspace, team, or agent?
- Can one item's failure poison sibling items?
- Are audit events emitted with the right scope to be visible downstream?
- If an entity moves across workspace, team, parent, or tenant scope, do all dependent references either migrate too or fail validation before save?
- Does the patch validate only the moved object while leaving reverse references or member links invalid?

### Legacy-data and migration compatibility

- What happens to records created before this new field, enum, or filter existed?
- Does missing `kind`/status/type/default data now silently exclude or reinterpret legacy records?
- Is there a migration, backfill, or safe fallback for pre-existing persisted data?
- Could an upgrade make a previously visible feature look empty or broken until data is rewritten?
- Are newly required persisted fields or trigger metadata left undefined because the migration just cloned old records verbatim?
- Does heartbeat/scheduling/runtime logic now read fields that older stores never had?

### Actor identity vs durable invariant identity

- Does authorization use the acting user while invariant validation should use a durable owner/root/system identity?
- Is a validator being passed `authContext.user.id` or another request-scoped actor when the invariant is really anchored to persisted workspace/company ownership?
- Could an authorized non-owner actor now trip a validator incorrectly or "fix" the invariant only by rewriting ownership to themselves?

### Data transformation and secrecy

- Are values trimmed, normalized, masked, or serialized incorrectly?
- Do short values leak their entire contents when masked?
- Does delete stay possible when create/update is disabled?
- Do helper changes preserve exact user-entered bytes when required?

### Error-path behavior

- Does `401`, `403`, `404`, validation failure, or missing config produce the right behavior?
- Should the feature degrade partially instead of blanking the entire surface?
- Can stale errors remain visible after success?

### Time and concurrency

- Is the code safe across retries, duplicates, reloads, or repeated clicks?
- Are time boundaries, timezone assumptions, and schedule windows handled correctly?
- Are cleanup and revoked-state paths treated differently from active-state paths when needed?
- Does timeout or file age get treated as proof that another owner is dead when it may just be slow?
- If initialization fails after acquiring a lock/resource, does the code close handles and remove stranded artifacts?
- After a crash, is there a liveness-based recovery path, or can one orphaned artifact wedge the system indefinitely?
- Can overlapping poll cycles or interval ticks run concurrently against the same store and duplicate or race work?
- Do cron/date computations use the right semantics, including sparse schedules, impossible dates, malformed tokens, and day-of-month/day-of-week rules?

### Loop and batch isolation

- If one item in a loop throws, do sibling items still run?
- Is already completed work persisted even if a later sibling fails?
- Does the batch finalize per-item errors, or does one failure abort wake/poll progress until manual intervention?

### Trigger-specific behavior and state-machine symmetry

- Are capability checks keyed to the actual trigger type?
- Do manual runs accidentally update heartbeat/scheduler state that should only move on scheduled or heartbeat paths?
- Do approval, run status, step trace, and artifact creation all stay in sync after approve/reject/resume?
- When a paused or migrated state resumes, is there a pending next step or terminal completion path?
- When pending approvals are superseded or a run leaves a gated state, are companion flags such as `approvalRequired` cleared too?

### Integrity and reachability

- Do import paths, file references, docs links, or command examples still resolve after the change?
- Does a new connector family, runtime family, enum value, route, or command need registration in a central classifier or allowlist?
- Are lint, type, or validation claims backed by actual hooks, scripts, or executable paths in the repo?

### Error typing and route mapping

- Do service/helpers throw typed errors that routes map to 4xx when the fault is user input or missing records?
- Can plain `Error` from validation/not-found paths escape and become 500 even though the client made a bad request?

## 5. Check the Tests With Adversarial Intent

Ask:

- What realistic bug would still pass these tests?
- Does the test hit the real contract or a simplified mock world?
- Does the test cover the negative path introduced by the patch?
- Does the test reload state when the product flow would reload state?
- Does the test prove isolation, not just a single happy-path item?
- Does the test cover the security-sensitive path when untrusted input or authz is involved?
- Does the test cover the real feature-completion path rather than only the mutation helper?
- Does the fixture preserve unrelated policy or capability state, or does it broaden permissions so much that regressions become invisible?
- Would the test fail if the code forgot one companion state update, such as queue flags, approval-required booleans, or mirrored capability metadata?

Treat missing tests as a finding only when the missing coverage materially hides a realistic regression.

## 6. Decide the Output Class

Before reporting, classify each concern:

- `Finding`: concrete bug with a plausible failing scenario and source evidence
- `Open question`: meaningful uncertainty that could hide a bug, but evidence is incomplete
- `Residual risk`: no confirmed bug, but test or validation scope is thin

Use `references/evidence-bar.md` for the standard.
