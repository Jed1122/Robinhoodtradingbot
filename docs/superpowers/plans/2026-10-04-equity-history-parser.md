# Equity History Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse supplied nonempty equity orders and execution fees without manufacturing customer calibration or unlocking the authenticated adapter.

**Architecture:** Immutable evidence records plus a strict bounded pure page parser and supplied-chain assembler. Preserve the old authenticated mapping and production capabilities unchanged.

**Tech Stack:** Existing Python 3.12+, dataclasses, Decimal, JSON, hashlib, pytest; no new dependency.

**Spec:** `docs/superpowers/specs/2026-10-04-equity-history-parser-design.md`

## Global Constraints

- Scope is credential-free supplied-page parsing only. No broker calls, credentials, purchases, deployment changes, or risk changes.
- Pin Robinhood-2 declaration `ee8c4019da683b7bfd56ff62ad20f0cf1d3d4080f3baa5f6f785a50a218fd470`; do not alter authenticated empty-only pin.
- Native implementation under standing authority; exact base `5029f7791203820fcb36feb9dece97383a076ac8`, isolated `codex/equity-history-parser` branch.
- Outputs permanently unauthenticated, execution-ineligible and non-promotable. Final fees and full history completeness remain unknown.
- Bounds and financial/timestamp grammar are exactly those in the spec.

## Review Focus

- Untrusted callers can construct or mutate frozen page summaries: assembler reparses original bytes and binds all context.
- Completed pagination is not creation-filter-independent execution coverage: no full-history/fee-finality claims.
- Ambient Decimal context must not round partial-share or fee sums.
- Malformed nested/free-text inputs must not leak private content in errors or repr.
- Duplicate execution UUIDs across distinct orders must fail, not silently deduplicate real liabilities.

---

### Task 1: Strict immutable supplied-page observations

**Files:** Create `src/trading_bot/brokers/robinhood_equity_history.py`, declaration snapshot, and `tests/unit/brokers/test_robinhood_equity_history.py`.

**Interfaces:**
- Consumes: raw declared page bytes, exact request fingerprint/filters, requested opaque cursor, UTC receipt nanoseconds and declaration SHA.
- Produces: `EquityHistoryRequest(account_fingerprint: str, filters: tuple[tuple[str, str], ...] = ())`; `parse_equity_orders_page(body: bytes, *, request: EquityHistoryRequest, requested_cursor: str | None, received_at_ns: int, declaration_sha256: str) -> EquityOrdersPage`; immutable order/execution observations with issue codes and private repr.

- [ ] Step 1: Add tests with synthetic two-fill order: quantities `0.25`/`0.75`, fees `0.001`/`0.002`, cumulative `1.00` and fees `0.003`; exact totals and false authority flags. Dollar order retains null requested quantity. Unknown `confirmed` remains an issue. Missing fees never default. Add schema/decimal/time/identity/null/JSON bounds and conflict cases.
- [ ] Step 2: Run `PYTHONPATH=src .venv/bin/pytest tests/unit/brokers/test_robinhood_equity_history.py -q`; observe missing-module RED.
- [ ] Step 3: Implement exact parser and records in the declared module, preserving raw bytes/hash, UTC nanoseconds, presence and exact Decimal sums. Never construct domain orders/fills.
- [ ] Step 4: Run the new suite plus `test_robinhood_equity_mapping.py`, integration read/write locks and `test_etf_cost_calibration.py`; all pass. Run Ruff/Mypy and diff checks.
- [ ] Step 5: Commit only Task 1's files and plan/spec.

### Task 2: Bounded supplied-chain assembly and documented evidence limits

**Files:** Modify the parser and its tests; update `docs/architecture.md`, `docs/limitations.md`, and add `docs/equity-history-parser-2026-10-04.md`.

**Interfaces:**
- Consumes Task 1's `EquityOrdersPage` tuples.
- Produces `assemble_equity_order_history(pages: tuple[EquityOrdersPage, ...]) -> EquityOrderHistory` with unique source-order observations, duplicate counters, chain hash, exact context, supplied-chain completeness only and permanent false authority flags.

- [ ] Step 1: Add tests for two pages, URL-shaped opaque cursor, unchanged request, missing successor/loop, page receipt regression, changed same-order snapshot, cross-order execution reuse, hand-built/mutated page summaries and all chain resource bounds. Expect absent assembler RED.
- [ ] Step 2: Run new chain selection and observe absent-function failure.
- [ ] Step 3: Implement reparsing, bounded terminal chaining and first-delivery deduplication. Retain exact page hashes in chain identity; never fetch cursors.
- [ ] Step 4: Run parser/adapter/calibrator tests, Ruff/Mypy/Bandit, full offline suite, native optional subset and unchanged coverage gates; document evidence gaps and next forward/runtime contracts without pretending they ran.
- [ ] Step 5: Commit exact scoped files, obtain one fresh most-capable whole-branch review, fix Important/Critical findings RED→GREEN, publish PR against the established integration base and merge only green exact-head checks under standing authority.
