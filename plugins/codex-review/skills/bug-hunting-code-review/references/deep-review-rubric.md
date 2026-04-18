# Deep Review Rubric

Use this rubric before declaring `No findings`.

The goal is not to produce more comments. The goal is to make sure the review actually reached CodeRabbit-level failure modes instead of stopping at tidy local code.

## Required Review Outputs

Before concluding a serious review, be able to answer all of these from source:

1. Contract:
   - What invariant or user-visible behavior is this patch changing?
   - What would a concrete regression look like?
2. Change map:
   - Which layers are involved: UI, route, service, persistence, scheduler, runtime, migration, tests, docs, config?
   - Which adjacent files did you inspect beyond the touched hunk?
3. Companion state:
   - Which secondary surfaces must stay aligned with the main state change?
   - Examples: `approvalRequired`, pending approvals, queue summaries, artifacts, readiness badges, mirrored runtime metadata.
4. Central synchronization points:
   - Which registry, allowlist, classifier, enum family, route map, or docs path must stay in sync with the patch?
5. Mirrored paths:
   - Which sibling create/update/delete/reply/react/write paths could bypass the same invariant?
6. Negative-path evidence:
   - Which unhappy path did you trace?
   - Which stale-state, retry, resume, reload, or partial-failure path did you trace?
7. Test integrity:
   - Would the tests fail for the exact bug you are worried about?
   - Are any helpers broadening permissions, feature gates, or policy state so the regression would stay hidden?
8. Reachability:
   - Do imports, example paths, command snippets, and claimed validation steps still resolve?

If any answer is missing, the review is not done.

## No-Findings Bar

`No findings` is acceptable only when all of these are true:

- The full execution path was traced, not just the diff hunk.
- At least one negative or stale-state path was inspected.
- Any trust boundary received an explicit security pass.
- Any workflow/state change was checked for companion-state symmetry.
- Any new type/family/connector/route/command was checked against central registries or allowlists.
- Tests were checked for both realism and masking risk.
- Validation claims were not accepted on faith; they were tied to real commands, hooks, or current repo wiring.

## Strong Finding Shapes

Prefer findings that look like this:

- "This transition updates `status` but leaves `approvalRequired` true, so API/UI surfaces disagree after a paused run resumes."
- "This helper rewrites the whole `featureGates` object, so tests will still pass even if the route starts depending on an unrelated capability."
- "This exact-key runtime-family helper now silently classifies the new connector as generic, so later governance checks hard-fail."
- "This route claims validation, but the create path still throws plain `Error` and returns 500 for invalid client input."
- "This wrapper looks harmless, but it dropped the disabled/read-only or accessible-name semantics the old primitive enforced."

Avoid weak findings like this:

- "This feels brittle."
- "Maybe add a test."
- "Consider sharing this helper."

Those can be open questions, not release-blocking findings.
