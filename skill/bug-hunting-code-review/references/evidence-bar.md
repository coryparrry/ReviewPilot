# Evidence Bar

Use this file to decide whether something is strong enough to report as a review finding.

## Report a Finding Only When All of These Are True

- A concrete failing scenario exists.
- The scenario follows from the code as written, not from a vague possibility.
- The broken invariant, contract, or user expectation is identifiable.
- The code path that causes the break is localizable to specific files or lines.
- The issue would matter in a real release, not only as a stylistic preference.

If any of these are missing, downgrade the item to an open question or residual risk.

## Strong Finding Template

A strong finding answers all of these:

1. Who or what triggers the failure?
2. What exact sequence causes the failure?
3. What becomes incorrect?
4. Why does the current code allow it?
5. Why is that a real bug instead of a preference?

## Acceptable Evidence Sources

- Control-flow tracing through the changed code and its neighbors
- Existing tests that demonstrate the intended contract
- Contradictions between route/service/UI layers
- Clear missing state refresh, stale-state overwrite, or invalid fallback behavior
- Observable invariant breaks such as wrong scope, wrong returned shape, wrong event emission, wrong masking, or wrong status handling
- Clear trust-boundary failures or attacker-controlled input reaching dangerous sinks
- Clear user-visible feature failure where the flow cannot complete or recover correctly

## Weak Evidence: Do Not Report As a Finding

- "This might be wrong"
- "I would have implemented it differently"
- Style concerns
- Pure naming discomfort
- Hypothetical issues with no failing path
- Concerns that depend on unknown product semantics you did not check

## Missing-Semantics Rule

If a concern depends on product semantics that are not obvious:

- Read surrounding code and tests first.
- Check whether the service intentionally auto-heals, auto-assigns, reloads, or degrades.
- Do not invent a bug from a false assumption about expected behavior.

## Missing-Test Rule

Missing tests are not automatically findings.

Report a test gap only when:

- the patch touches a high-risk invariant, and
- the absent coverage would likely allow a real regression to ship unnoticed

Otherwise, mention the gap only as residual risk.

## Preferred Wording

Use language like:

- "This breaks when..."
- "After X, the code still..."
- "Because the response/state/helper is not updated here..."
- "The route and service now disagree about..."
- "This fallback can resolve to the wrong target when..."

Avoid language like:

- "Nit:"
- "Consider changing..."
- "Maybe..."
- "Possibly..."

## Severity Heuristic

Use severity relative to user or system impact:

- High: likely production break, authorization mistake, wrong target mutation, wrong-scope data leak, scheduler isolation break
- Medium: realistic broken flow, stale state, missing partial degradation, contract mismatch, invalid cleanup block
- Low: real but narrow bug with limited surface area

Prefer severity discipline over exaggeration.
