# Task 4 implementation plan

**Goal:** qualify the individual-stock data needed for the next stock strategy
evaluation, with reproducible checks and actual source evidence. Follow the
[design](../specs/2026-10-25-stock-data-qualification-design.md). Root owns provider
reads and integration; independent agents implement/review separate pure modules.
Use the existing Python 3.12+ stack and source readers; add no dependency.

## Review focus

- Omitted interpolation must remain unknown; no implied native false marker.
- Split adjustments must not become dividends/total return or source-wide proof.
- Fresh collection must not hide stale values or retroactively available facts.
- Missing prices, financial units, identity, calendar or history must produce
  explicit blocked uses, not zero values or a smaller undisclosed denominator.
- Synthetic fixture success must never become actual qualification evidence.

## 1. Freeze source scope and recover evidence

- [x] Inspect current clean revision, stock contracts, relevant sibling work and
  current official tool declarations/docs. Record unavailable premium access.
- [x] Retain the fixed NVDA raw/split request intent and actual MCP tool receipts.
- [x] Save the source/usage matrix and exact evidence references. Freeze the wider
  universe, historical window, calendar/action inputs and costs before capture.

## 2. Deterministic source-quality assessment

Create `research/stock_data_quality.py` and focused unit tests. Reuse existing
immutable stock dossier/fact/history types. Return source-specific counts, receipt
and observation ages, missing-property reasons and purpose-specific blocked uses.
Validate aware UTC clocks and explicit policy bounds; never infer publication
from period end. Include complete provenance in deterministic report hashes.
Tests cover future/unavailable receipts, stale fetched values, period/receipt
distinction, null/unknown/quarantined histories, missing currency/filing identity,
changed provenance and prohibition on investment/live promotion.

Implemented and independently reviewed. The opt-in dossier report adds quality
diagnostics without changing default report bytes. Actual restored-archive v2
reconstruction and independent read-only terminal re-verification succeeded.

## 3. Exact adjustment comparison and source-neutral seam

Create a pure Robinhood raw/split comparison with tests for request identity,
original payload hashes, canonical symbol/interval/bounds, matching timestamps,
positive consistent OHLC/volume, exact pre/post factors and unrelated events.
Use exact rational arithmetic. Empty, incomplete, mismatched or varying factors
remain unresolved. Preserve absent interpolation and any explicit contradictions.
Use original source bytes/receipts, not manually transcribed prices.

Implemented and independently reviewed: exact split comparison, calendar-bound
daily-series admission and dimensionless features. Listing and corporate-action
parsers preserve original rows, unknowns and unsupported-use restrictions.

Review any subsequent source-neutral technical input contract independently
before admitting data. Its eligibility must bind the documented source semantics,
original request, calendar/session, currency/basis and receipt availability. Legacy
Robinhood normalizers and their unknown fields remain truthful.

## 4. Actual input verification and Task 5 handoff

Root captures only permitted, predeclared data through official tools/endpoints.
Reuse existing SEC parsers for actual filings where compatible. Rehash/reconstruct
the price, action, calendar, universe and fact inputs independently. Produce an
inspectable command/report containing coverage, missingness, temporal limits and
allowed/blocked uses. Acquire enough observations for every used feature; do not
equate a split sample with historical stock-selection qualification.

## 5. Integration and completion audit

Run focused quality/comparison tests, relevant stock research regressions and
static checks. Review integrated changes independently. Record exact source and
actual terminal results. Complete the goal only after every required input/use
in the declared strategy handoff is supported; otherwise retain the active goal
and report the precise missing evidence. Live trading stays disabled.

## Completed first-stage acceptance

- [x] Source/use matrix, native declarations, licensing/access limits and original
  successful/failed receipts retained; no paid plan or credential-file dependency.
- [x] Pure quality, split, daily/calendar, listing and action modules plus explicit
  opt-in report integration implemented and independently reviewed.
- [x] Original archive and actual price features reconstructed independently;
  missing native fields, quarantine and receipt origins remain truthful.
- [x] Failed twelve-slot frame preserved. Separate original-13F common-share
  cohort frozen before new prices; nine 706-session series and all 63 features
  bound in corrected manifest `07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3`.
- [x] Corrected handoff independently accepted, including warm-up/decision
  separation; all five design deliverables audited for the declared price-only use.
- [x] Full local stock/shared suite: 12,420 passed, 36 disclosed warnings, actual
  exit 0 and unchanged inventory; 91.55% coverage and critical-branch gate passed.
  All 228 new tests and relevant lint/type/security checks passed.

See the [verification record](../../stock-data-verification-2026-10-25.md).
Broader total-return, USD/after-tax wealth, historical financial ranking, strategy
promotion and live claims remain restricted. Next is Task 5's frozen stock-policy
evaluation and additional inputs needed for those broader economic claims.
