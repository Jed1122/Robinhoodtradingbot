# Durable Owned Equity Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native execution is the operator's standing preference.

**Goal:** Persist and reconstruct complete local equity order/fill lifecycle facts without changing broker capability or live readiness.

**Architecture:** Add a pure versioned fact/reducer and an append-only journal behind the existing transaction owner. Preserve original order responses and use existing FillRow and OrderTransitionRow. Read projections are reconstructed from the journal; no broker snapshot is adopted.

**Tech Stack:** Python 3.12–3.14, Decimal, SQLAlchemy async SQLite, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-etf-durable-equity-lifecycle-design.md`

## Global Constraints

- No external calls, secrets, customer data, deployment, trades, risk changes or promotion claims.
- Preserve original OrderRow/submission hashes and all unrelated worktrees/private evidence.
- Initial owned equity anchor has complete intent/review/submission provenance and zero fills.
- Missing fees do not become zero; immutable exact domain Fill is required for a fill event.
- At most 10,000 events per order; at most 16 KiB per canonical payload.
- Keep 80% overall and 90% critical branch gates unchanged; all current exact-head merge checks are required.

## Review Focus

- Concurrent append, crash/rollback and duplicate terminal redelivery must not multiply effects.
- Forged or mutated domain records must fail before SQL or serialization side effects.
- Foreign native execution keys and unrelated transitions must not become owned history.
- Terminal cancel with raced fills must retain actual quantity and cannot reopen.
- Missing or modified rows and truncated journal links must deny recovery rather than return a clean projection.

### Task 1: Pure owned lifecycle contract

**Files:** Create `src/trading_bot/execution/owned_order_lifecycle.py`; test `tests/unit/execution/test_owned_order_lifecycle.py`.

**Interfaces:** Consumes exact `BrokerOrder`, `Fill`, `OrderEvent`, canonical `transition`. Produces `OwnedOrderEvent`, `encode_owned_event(event) -> str`, `decode_owned_event(payload) -> OwnedOrderEvent`, `advance_owned_order(order, event) -> BrokerOrder`.

- [ ] Write failing tests for partial/full quantities, pending-cancel races, terminal closure, reconciliation without invented fills, wrong identities/times, absent fees, forged records, and exact codecs.
- [ ] Run `uv run pytest tests/unit/execution/test_owned_order_lifecycle.py -q`; Expected: missing production API assertion fails.
- [ ] Implement exact immutable records, bounded canonical codec and state-machine advancement with trapped Decimal inexact arithmetic.
- [ ] Run the same command; Expected: all pass.
- [ ] Commit only task-owned paths and specification/plan.

### Task 2: Atomic journal and fill storage

**Files:** Create `src/trading_bot/persistence/owned_order_journal.py`, `src/trading_bot/persistence/models/owned_orders.py`, `migrations/versions/0009_owned_order_lifecycle.py`; modify ORM registry, repositories and unit-of-work; test `tests/integration/persistence/test_owned_order_journal.py`.

**Interfaces:** Consumes Task 1 codec/reducer. Produces `OrderRepository.record_event(event: OwnedOrderEvent) -> bool`, `get_broker_order(order_id: OrderId) -> BrokerOrder | None`, and `FillRepository.get(fill_id: FillId) -> Fill | None`, `list_for_account(account_id: AccountId, since: datetime) -> tuple[Fill, ...]`.

- [ ] Write failing real-SQL tests for complete partial/full lifecycle, restart, exact duplicate/conflict, wrong provider key/account/order, transaction rollback, bounds, altered links and missing rows.
- [ ] Run `uv run pytest tests/integration/persistence/test_owned_order_journal.py -q`; Expected: new API behavior missing.
- [ ] Add migration/journal with append-only fill guards, strict ownership verification and same-transaction event/transition/fill staging. No updates of original order response; no legacy adoption.
- [ ] Run journal, migration, UOW and execution suites; Expected: all pass and original order hash unchanged.
- [ ] Commit only task paths.

### Task 3: Recovery verification and release handoff

**Files:** Task 2 tests, `scripts/check_critical_branch_coverage.py`, `docs/architecture.md`, `Codex.md`, `docs/etf-durable-equity-lifecycle.md`.

**Interfaces:** Consumes Task 2 APIs; no new runtime or provider interface.

- [ ] Add failing append-only UPDATE/DELETE/REPLACE/raw-SQL and independent-engine restart/control tests plus critical gate inclusion; Expected: protections missing before implementation.
- [ ] Implement only required protections and enroll the journal in the unchanged critical gate.
- [ ] Run `uv run pytest tests/unit/execution/test_owned_order_lifecycle.py tests/integration/persistence/test_owned_order_journal.py tests/integration/persistence/test_migrations.py tests/integration/persistence/test_unit_of_work.py tests/integration/execution -q`; Expected: all pass.
- [ ] Update accurate handoff and architectural boundaries; commit task paths.
- [ ] Run complete pytest with coverage, native fixture subset, Ruff/Mypy/Bandit, frozen locks, advisory audit, temporary-output SBOM and manifests; Expected: all pass or explicitly blocked, never bypassed.
- [ ] One fresh strongest-model whole-branch review; Important/Critical fixes RED-to-GREEN and broader tests. Publish PR to the unchanged integration target, inspect every exact-head CI result and substantive review; merge only green. Preserve linked worktree and archive only this plan's scratch after merge.
