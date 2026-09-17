# PIT-VALIDATION-003 review

## Scope and checkout

- **Owner:** isolated Cloud agent for PIT-VALIDATION-003.
- **Objective:** add independent, synthetic, test-only boundary coverage for the
  primary-approved stricter point-in-time universe input-validation contract.
- **Exact base:** `095e5c02b01aea95fd7858a549a7765e7b0488c0`.
- **Checkout:** isolated local branch `work`; before any edits, `git rev-parse HEAD`
  returned the exact approved base above and `git status --short --branch` reported
  `## work` with no changes. The checkout was therefore already at the exact base;
  no newer revision was used and no integration branch was modified.
- **Owned paths:**
  `tests/unit/market_data/test_universe_validation_contract.py` and this review.
- **Classification:** universe input validation is **partial** at the approved base.
  Existing point-in-time behavior passes, but the approved strict input boundaries
  and contradictory-event rejection are not implemented.

The dependency chain is the public `UniverseMembership` constructor, followed by the
public `PointInTimeUniverse` constructor, followed by `members_at`; all timestamp
validation is expected to use the existing `trading_bot.clock.require_utc` behavior.
The critical path is primary-owned production validation in
`src/trading_bot/market_data/universe.py`, followed by rerunning this focused contract
and the existing universe baseline. This task does not alter that production path.

## Test design

The new tests use only synthetic identifiers and timestamps and invoke the public
constructors and lookup method directly. They cover:

- exact nonblank string membership identifiers without requiring normalization;
- aware-UTC membership timestamps and lookup timestamps, including lookup validation
  for an empty universe;
- exact booleans for `included` and `history_complete`;
- an exact immutable tuple populated only by `UniverseMembership` records;
- contradictory event rejection in both orders, before those future events are
  visible;
- allowance of identical duplicates, distinct-timestamp changes, and a legitimate
  late announcement;
- canonical sorted outputs, equality boundaries, order invariance, and unchanged
  complete/incomplete eligibility reasons.

The suite does not require proof of history completeness, identifier whitespace or
case normalization, rejection merely because announcement follows effectivity, a new
interval policy, or a read-only `history_complete` property.

## Verification evidence

Commands were run from `/workspace/Robinhoodtradingbot` against the exact base plus
only the owned test file (and, for the lint check, subsequently this review file was
irrelevant):

1. `git rev-parse HEAD`
   - Result: pass; exactly
     `095e5c02b01aea95fd7858a549a7765e7b0488c0` before edits.
2. `uv run pytest tests/unit/market_data/test_universe.py tests/unit/market_data/test_universe_contract.py -q`
   - Initial result: **18 passed, 0 failed**.
   - Compatibility rerun result after adding the owned test: **18 passed, 0 failed**.
3. `uv run pytest tests/unit/market_data/test_universe_validation_contract.py -q`
   - Expected-red result: **3 passed, 34 failed**.
   - The three passing cases demonstrate preserved valid behavior: identical
     duplicates, late-announcement/distinct-timestamp/order-invariant behavior with
     literal expected IDs, and the complete empty-universe boundary.
   - The 34 expected failures expose the missing validation at the approved base:
     constructors accept invalid IDs, timestamps, booleans, and collection shapes;
     empty lookups do not validate `as_of`; populated invalid lookups either do not
     raise or leak `TypeError` rather than `DomainValidationError`; and contradictory
     same-key events are accepted in both input orders. This red result is the required
     TDD evidence and was not weakened with skips, xfails, mocks, or source-text checks.
4. `uv run ruff check tests/unit/market_data/test_universe_validation_contract.py`
   - Result: **1 file checked, 0 errors** (`All checks passed!`).

## Original Cloud disposition at frozen base (historical)

- `InstrumentId` is a runtime string alias, so strict membership-ID enforcement is
  asserted at the public `UniverseMembership` boundary.
- `DomainValidationError` is the approved common base; tests intentionally accept a
  more specific subclass such as the existing `InvalidTimestamp`.
- The exact error message and internal validation order are not frozen and are not
  asserted.
- At the frozen base, the expected-red suite required primary-owned implementation of the
  approved production contract, diff inspection, and central reruns. That historical test-only
  result was not a release decision; the later central integration is recorded below.
- No broker call, credential operation, external write, production ledger, live
  control, deployment, risk/pricing/sizing decision, dependency, or configuration was
  used or changed.

**Disposition: READY_FOR_INTEGRATION** as test-only TDD evidence for the primary-owned
production implementation. This disposition makes no claim about release or live
readiness.

## Central integration (2026-09-16)

The primary inspected the complete two-file Cloud diff and reproduced the original contract's
**34 failures and 3 passes** within a combined Cloud run against a secrets-free archive of the
exact `095e5c0` base. The original Cloud contracts together produced **140 failures and 8 passes** on that
base, then **148 passes** against the primary-owned validation patch. This is independent central
verification, not reliance on the worker's transcript.

The primary retained the original 37 cases and added three exact-type subclass cases for IDs,
tuple containers, and membership records; the integrated Cloud-owned file has 40 cases.
Separate primary regression controls cover an opposite
inclusion value with only the effective timestamp changed, and with only the announcement
timestamp changed. Both remain valid and preserve visibility boundaries in either input order.
Source/interval provenance and actual historical completeness remain unverified. Full repository
verification is recorded in the orchestration report; this review is not promotion evidence.
