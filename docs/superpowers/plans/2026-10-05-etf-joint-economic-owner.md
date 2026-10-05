# Independent ETF Economic Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the retained native implementation. Steps use checkbox syntax.

**Goal:** Reconstruct independent cash, shares, allocations, signed obligations and trial history atomically with owned execution facts.

**Architecture:** Pure immutable accounting facts and projection reuse checked lifecycle/trial arithmetic. One additive SQLite journal is a sibling repository inside the existing UnitOfWork; provider observations never populate it.

**Tech Stack:** Existing Python, Decimal, dataclasses, SQLAlchemy/Alembic/SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-etf-joint-economic-owner-design.md`.

## Global Constraints

- Base004390f0380d6fdb167271d0a847a3c0c43817e5; preserve unrelated/private files.
- No credentials, real provider/broker calls, orders, deployment, risk/config changes or history adoption.
- Source/cost/execution/promotion eligibility permanently false; exact 28-digit money arithmetic, only weighted average rounds.
- One flat-start equity instrument/account; one incomplete episode; existing pretrade gates unchanged.
-10,000 economic events,16KiB payloads, complete-or-error recovery; unchanged80% overall/90% critical branch gates.

## Review Focus

- A caught exception after execution flush must make commit impossible, not publish half an effect (Task2).
- A duplicate lifecycle fact with missing economic counterpart denies, not silently adopts it (Task2).
- Terminal cancellation with unsettled debit or unknown final charges keeps allocations held (Task1/2).
- Funding/profits cannot reset earlier loss history, even after reconstruction (Task1/3).
- Cross-account/order links and capacity failures deny before mutation; hashes alone do not authenticate genesis (Task2/3).

### Task 1: Immutable economic facts and exact projection

**Files:** Create `src/trading_bot/accounting/__init__.py`, `owned_economic_models.py`, `owned_economic_codec.py`, `owned_economic_projection.py`; tests `tests/unit/accounting/test_owned_economics.py`.

**Interfaces:** `EconomicEvent(id, account_id, occurred_at, source_hash, config_hash, payload)`, closed payload dataclasses; `encode_economic_event(event)->str`, `decode_economic_event(payload)->EconomicEvent`; `project_economics(events:tuple[EconomicEvent,...])->EconomicState`. State exposes settled/book/available cash, Position, allocations, obligations and existing TrialLossState, plus immutable false readiness properties.

- [ ] Write missing-API failing tests for opening500, reserve0.10at101 plus0.05fee, partial0.04at100fee0.02, cancel race, explicit signed settlement and delayed final fees. Expected feature absence.
- [ ] Implement closed types/codec and pure exact projection with checked lifecycle arithmetic; no observation adoption.
- [ ] Add failing double-entry/exit reservation, stale identity, inexact arithmetic, final fee bound, cash/episode completion and funding/non-replenishment tests; implement necessary denials.
- [ ] Run `env PYTHONPATH=src uv run --offline --no-sync pytest tests/unit/accounting -q`; Expected all pass. Commit scoped types/tests/spec/plan.

### Task 2: Atomic economic/execution journal and additive schema

**Files:** `src/trading_bot/persistence/owned_economic_journal.py`, `models/owned_economics.py`, `models/__init__.py`, `unit_of_work.py`, `migrations/versions/0010_owned_economics.py`; integration `tests/integration/persistence/test_owned_economic_journal.py` and additive migration expectations.

**Interfaces:** sibling `uow.economics.append(event: EconomicEvent)->bool`, `uow.economics.get(account_id:AccountId)->EconomicState|None`; same existing session/config/active guards. Execution payloads atomically invoke the existing owned lifecycle writer and link its exact event.

- [ ] Write missing-API failing real-SQL tests for genesis, reserve/bind/fill joint commit and independent-engine restart. Expected unavailable economics API/schema.
- [ ] Implement bounded chain reconstruction, full counterpart/link verification, secret screening and rollback on any joint append error. Stage dependencies explicitly because autoflush=False; never own a separate commit.
- [ ] Write RED tests for caught error then commit, orphan/damaged/cross-order counterparts, duplicate conflict, raw UPDATE/DELETE/REPLACE, downgrade with history and concurrent stale writers. Implement required guards.
- [ ] Run unit accounting, owned economic/lifecycle journal, migration and UOW tests; Expected all pass. Commit scoped code/tests/migration.

### Task 3: Crash/finality controls and release handoff

**Files:** integration tests plus fixture crash worker, `scripts/check_critical_branch_coverage.py`, `docs/etf-joint-economic-owner.md`, architecture/transition checkpoint.

**Interfaces:** consumes Tasks1/2 only; no provider/runtime capability.

- [ ] Write real SIGKILL tests after owned execution flush/before economic flush and after commit. Expected old or exactly complete new joint state; validate no cash/trial reset.
- [ ] Test exact bounded history denial and restart reconstruction after positive episodes/funding and incomplete settlement; enroll new critical modules in unchanged gate.
- [ ] Document precise offline boundary and remaining prerequisites, including false qualification/finality authenticity and complete-rollback limitations. Commit scoped paths.
- [ ] Run complete full/native coverage, Ruff/Mypy/Bandit, frozen main/research locks and advisory audits, SBOM and deployment manifests. Expected all actual passing, no skipped current-candidate certification.
- [ ] One strongest-model independent whole-branch review; Important fixes RED-to-GREEN with fresh full regression; inspect all exact-head current CI and review findings. Merge only green to codex/robinhood-system-implementation; retain worktree and recoverably archive only this plan's scratch.
