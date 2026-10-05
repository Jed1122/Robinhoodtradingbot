# Incremental ETF Replay and Protected Cost Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reduce account/source facts incrementally and connect protected execution observations to private timing/final-fee receipts without enabling a live adapter.

**Architecture:** One shared account reducer and one shared lifecycle loop preserve legacy behavior. A separately versioned chunk consumer binds verified source prefixes; an optional owner observer records only after the existing durable/risk boundaries.

**Tech Stack:** Existing Python, Decimal, canonical hashing, SQLite execution owner, private receipt storage and pytest. No dependency/config changes.

**Spec:** `docs/superpowers/specs/2026-10-05-etf-incremental-replay-timing-design.md`

## Global Constraints

- Fixed SPY/cash 20/100 strategy; existing risk/config/trial limits unchanged.
- 10,000 physical account facts; 10,000 source events/chunk; 100,000,000 total source events; 10,000 retained detailed decisions.
- 150,000 nonquote baseline events; 1,024 distinct source reasons; one session per trading date. Overflow returns no result; exact counts are not collapsed.
- Preserve v1 identities; v2 results paused, execution-disabled, non-promotable.
- Verify restart prefix once; no claimed constant-time recovery.
- No live adapter from declarations; no bypass, credentials, deployment or sample trades during offline implementation.

## Review Focus

- Generator suspension must not leak Decimal context into callers.
- Failed advancement must not permit continued use of partially changed state.
- Chunk boundaries must not finalize sessions or clear unresolved schedules.
- A source exception must not publish a completed result.
- Recorder failure after a durable attempt must never cause an automatic retry.

### Task 1: Shared incremental account owner

**Files:** Modify `src/trading_bot/simulation/etf_account.py`, `src/trading_bot/simulation/etf_native_history.py`; create `tests/unit/simulation/test_etf_account_incremental.py`.

**Interfaces:** Produces `EtfAccountStepper(request: EtfAccountRequest)`, `.apply(event: EtfAccountEvent) -> EtfAccountResult`, `.state`, `.events`, `.failed`. Legacy `_run` remains compatible, including forward-origin callers. Native append uses the same reducer; pending admission stays isolated.

- [x] Write prefix parity, independent cash/fee/trial-loss, duplicate, invalid-event poisoning, context isolation and no old-fact reapplication tests.
- [x] Run `PYTHONPATH=src .venv/bin/pytest -q tests/unit/simulation/test_etf_account_incremental.py`; expected missing API failures.
- [x] Extract suspended reducer with incremental exact JSON-array hashing and implement the validated stepper; integrate native append without changing legacy hashes.
- [x] Run incremental/account/pending/native/forward focused suites; expected all pass.
- [x] Commit scoped account changes and record RED/GREEN evidence.

### Task 2: Versioned incremental native source consumer

**Files:** Modify `simulation/etf_native_history.py`, `market_data/etf_replay_adapter.py`; create `simulation/etf_incremental_history.py`, corresponding unit tests, and `docs/etf-incremental-replay-timing.md`.

**Interfaces:** Consumes Task 1 reducer. Produces lazy `iter_native_etf_events(baseline, quotes)`; `run_incremental_etf_history(context, source, *, catalog_hash, checkpoint=None, through_count=None)` returning a versioned checkpoint/result with complete-source status, decision counts and permanently false eligibility. Internal chunk lifecycle uses the unchanged owner. Recovery compares reconstructed checkpoints before continuing.

- [x] Write lifecycle parity over arbitrary chunks, 150,000-plus blocked-source traversal with bounded decision retention, lazy stable merge/duplicates, untrusted restart, holdout and source-exception tests.
- [x] Run new incremental/adapter tests; expected missing API failures.
- [x] Implement chunk feed, shared suspended lifecycle, versioned prefix/checkpoint verifier and lazy native merge. Never strip unverified execution reasons.
- [x] Run new and legacy native/adversarial/economics/catalog suites; expected all pass.
- [x] Commit replay changes and public limitations documentation.

### Task 3: Protected observer and delayed final fees

**Files:** Modify `execution/service.py`, `research/etf_execution_receipts.py`; create `execution/etf_cost_observer.py`, unit tests; extend `tests/integration/execution/test_service.py` and receipt tests.

**Interfaces:** `ExecutionObserver` async decision/submitting/responded methods consume canonical domain objects. `ExecutionService(observer=None)` is backwards compatible and still rejects live modes. `EtfCostObserver` projects safe receipt payloads using a preselected same-sink quote hash. Add `final_fees` with receipt-v2 schema and exact terminal/source binding; v1 unchanged.

- [x] Write committed-before-record-before-transport tests, initial/final denial, sink failure before/after transport, timeout/mismatch no invented acknowledgement, no-retry and delayed/conflicting final-fee tests.
- [x] Run new observer/receipt/service tests; expected API/schema failures.
- [x] Implement optional observer at protected boundaries and additive final-fee linkage. Keep missing values distinct from zero.
- [ ] Run all affected unit/integration suites, Ruff/Mypy and full default pytest; expected all pass with existing optional skips only.
- [ ] Commit, independent exact-candidate review, unchanged coverage/security/dependency/SBOM/manifest checks, then publish/merge only with green required checks. Report genuine execution gates separately.
