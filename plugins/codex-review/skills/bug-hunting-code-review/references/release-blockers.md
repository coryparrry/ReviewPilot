# Release Blockers

Use this file to decide whether a patch is truly ready to ship.

## Mandatory Three-Pass Gate

Before saying `No findings`, complete all three:

1. Correctness pass
2. Security pass
3. Feature-completeness pass

If any pass is weak or unvalidated, say so as residual risk.

## Release-Blocking Outcomes

Treat these as release blockers when supported by source evidence:

- A core feature path cannot complete successfully
- An action mutates the wrong target or wrong scope
- A parent, team, or workspace move leaves persisted dependent references invalid
- A validator uses the acting request user instead of the durable owner or root identity the invariant is defined against
- A privacy boundary is enforced for one write path but bypassed through another equivalent path
- A new field or filter hides legacy persisted data after upgrade
- A migration copies old entities without backfilling newly required persisted fields or trigger metadata
- Authorization or tenant/workspace isolation can be bypassed
- Attacker-controlled input can reach a dangerous sink
- Secrets or private data can leak through helpers, logs, errors, or masking bugs
- Partial failures blank or poison unrelated surfaces instead of degrading locally
- Stale state or stale sessions keep privileged controls or wrong data alive
- Scheduler or workflow bugs can skip, duplicate, or cross-contaminate work
- Locking or persistence can wedge permanently after crash or partial initialization
- Contention recovery can break mutual exclusion by treating age as proof of owner death
- One failing item in a batch/poller aborts sibling processing or loses already-completed work
- Trigger-specific validation or side effects block valid manual paths or delay valid scheduled paths
- Approval/run/step/artifact state becomes contradictory after transition
- Client validation or not-found faults surface as 500 because typed error mapping is bypassed
- Cron/parser behavior silently accepts malformed input or misses/blocks valid schedules
- Frontend dedupe or navigation hides valid entities/features because UI identity or route reachability is wrong
- Cleanup, revoke, delete, or retry paths are broken in realistic usage

## Security Review Triggers

Run a focused security pass whenever the diff touches:

- Authentication or authorization
- Sessions, tokens, secrets, API keys, encryption, hashing, or masking
- User-controlled HTML, Markdown, templates, or rendering
- SQL, shell commands, subprocesses, eval-like execution, or deserialization
- File paths, uploads, downloads, archives, or storage access
- External URLs, redirects, fetch proxies, webhooks, or internal service requests
- Multi-tenant or multi-workspace access rules

Security questions:

- What input is attacker-controlled here?
- Where can that input end up?
- What trust boundary is crossed?
- What validation or escaping actually happens on the real path?
- Can a lower-privilege actor read, write, execute, or redirect more than intended?

If the surface is substantial, pair this skill with `$security-review`.

## Feature-Completeness Review

Check whether the feature actually works for a real user.

Questions:

- Can the user start the flow from the intended entry point?
- Can the user complete it without hidden setup or stale state?
- Do loading, empty, error, disabled, revoked, and retry states behave sensibly?
- Does the screen or API refresh into the new truth after mutation?
- Does the feature still work after reload or background changes?
- Does a partial backend failure degrade locally instead of breaking the whole surface?
- Are the visible controls aligned with what the backend will actually allow?

Broken feature behavior is a valid review finding even when no low-level code smell is obvious.

## "No Findings" Gate

Do not say `No findings` unless all of these are true:

- You traced the real end-to-end path.
- You checked at least one unhappy path.
- You considered whether the change crosses a trust boundary.
- You considered whether a real user can still complete the feature.
- You did not confuse missing validation evidence with proof of safety.
