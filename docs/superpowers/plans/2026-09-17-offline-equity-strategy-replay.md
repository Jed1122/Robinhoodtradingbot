# Offline Equity Strategy Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution is inline and primary-owned, following the operator's selection and repository boundaries.

**Goal:** Replay synthetic equity strategy entries and exits through the existing decision pipeline with deterministic identity, shared-cash accounting and explicit incomplete outcomes.

**Architecture:** Extend the existing decision, portfolio and configured-simulator seams without introducing another sizing, fill or accounting model. New simulation-only value contracts and coordination own synthetic state; production execution, promotion and broker composition remain untouched.

**Tech Stack:** Python 3.12+, frozen dataclasses, Decimal, existing Pydantic config, pytest, Ruff, Mypy. No new dependencies.

**Spec:** [Approved offline equity replay design](../specs/2026-09-17-offline-equity-strategy-replay-design.md), approved by the operator on 2026-09-17 UTC.

## Global Constraints

- `assumptions_validated`, `evidence_promotable`, and `production_pretrade_eligible` remain false.
- No broker calls, credentials, production ledger, external data capture, deployment, live activation or subscription changes.
- All times are explicit UTC; calculations use existing fixed Decimal contexts and exact accounting.
- LIMIT, GOOD_FOR_DAY equity only; one candidate family per run and one active order per instrument.
- No averaging down, pyramiding, borrowing, automatic liquidation, blind retry, or risk-limit changes.
- Existing single-order/lifecycle APIs and their hashes remain compatible.
- Keep the existing 80% combined line/branch coverage floor and all promotion gates.
- Preserve the pre-existing dirty handoff, Alpaca documents, limitations/research documents, shutdown test and untracked artifacts.
- Existing linked worktree: `worktrees/robinhood-system-implementation`; branch `codex/continue-implementation-from-commit-7c4dcd1`; starting revision `ad39fd59710daf4e51981aa2cf4b4fd48c32a772`.

## Review and dependency order

The current simulator is complete for its single-order fixture scope. Whole-strategy replay and its CLI are absent. Provider/source/runtime/promotion layers remain separately blocked.

Integration seams -> scenario contracts -> incremental order transitions -> shared portfolio coordination -> configured exits/economic checks -> decision replay -> strict CLI -> adversarial/full verification.

The approved fee-bound rule needs an important implementation distinction: a session's declared opportunity schedule is immutable input known at submission, separate from delivered market events. Reserve against that declaration, not the number of future delivered events. Adding a delivery into an already declared slot must not change an earlier reservation, identity or outcome. A changed schedule is a changed scenario contract, not a mere stream extension.

## Verification environment

Run from the implementation worktree with `PYTHONPATH=src`. The existing interpreter is `/private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python`; its editable target must not override this worktree. Commands below use `python` to mean that interpreter. Do not synchronize dependencies or use authenticated tests.

Baseline: 384 focused simulation, portfolio and offline-CLI tests passed before changes.

## Task 1: Backward-compatible decision integration seams

**Files:** modify `src/trading_bot/portfolio/intents.py`, `src/trading_bot/portfolio/targets.py`, `src/trading_bot/app.py`; create `tests/unit/portfolio/test_replay_seams.py`, `tests/integration/simulation/test_cycle_outcome_encoding.py`.

**Interfaces:** `IntentPlanner(*, id_factory: Callable[[], OrderIntentId] = new_order_intent_id)`; `DecisionCycleService(..., outcome_encoder: Callable[[object], object] | None = None)`; `PerInstrumentDecisionCycleRequest(DecisionCycleRequest)` adds `exit_policies: tuple[tuple[InstrumentId, ExitPolicy], ...]`. The existing `exit_policy` field becomes `ExitPolicy | None`; `PortfolioConstructor.construct` accepts exactly one policy form. Keep the base request's fields unchanged: `PaperApplication.cycle_id` hashes that dataclass, so even a new field defaulted to None would invalidate legacy restart identities. This was reproduced by a failing regression test before selecting the subtype seam.

- [x] Write tests that exercise actual BUY and SELL planning with an injected ID sequence, missing/duplicate per-instrument policies, and real cycle journaling with a typed encoding. Legacy default invocation must retain its hash.

```python
ids = iter((OrderIntentId("replay-buy"), OrderIntentId("replay-sell")))
planner = IntentPlanner(id_factory=lambda: next(ids))
assert planner.plan(entry_target, flat_context)[0].id == "replay-buy"
assert planner.plan(exit_target, held_context)[0].id == "replay-sell"
```

- [x] Run `python -m pytest tests/unit/portfolio/test_replay_seams.py tests/integration/simulation/test_cycle_outcome_encoding.py -q`; observe missing seams fail before edits. Observed 15 failures and one legacy compatibility pass; the separately added restart-key regression also failed before its fix.
- [x] Add constructor injection and replace both UUID call sites; validate exactly one exit-policy form before target calculation, unique policy keys, and coverage for every actual entry. Preserve exit-only semantics and legacy target hashes. Only pass the new keyword for the explicit per-instrument request subtype.

```python
encoded = tuple(
    str(item) if self.outcome_encoder is None else self.outcome_encoder(item)
    for item in outcomes
)
```

- [x] Rerun new tests, existing portfolio tests and simulation integration tests; lint/type-check changed source. The expanded selection passed 70 tests (one existing Starlette/httpx warning); all-source Ruff and Mypy passed. Architecture documentation records that these are seams only.
- [x] Commit only Task 1 files with `feat: add deterministic offline cycle integration seams` (`5e1be75`).

## Task 2: Strict synthetic scenario and outcome contracts

**Files:** create `simulation/equity_replay_models.py`, `simulation/equity_replay_codec.py`, `tests/unit/simulation/test_equity_replay_models.py`, `tests/unit/simulation/_equity_replay_fixtures.py` under the existing source/test roots.

**Interfaces:** frozen `ReplayCandidate(strategy_id, short_window, long_window, top_n, exposure_multiplier)`; `ReplaySession(instrument_id, window, opportunity_times)`; `ReplayDecision(event_id, cursor)`; `EquityStrategyReplayRequest(namespace, config, config_hash, seed, bundle, snapshot_settings, instruments, sessions, decisions, markets, starts_at, end_at, initial_cash)` plus candidate; frozen `ReplayOrderOutcome(intent_id, accepted, reasons, order_id)` with no eligibility fields; `EquityStrategyReplayResult` with validity, terminal/flat/completion facts, cycles, order results, portfolio snapshots, reason codes, hashes and immutable false flags.

- [ ] Write construction tests for wrong exact types, live mode, enabled evidence flags, candidate outside canonical grids, non-UTC dates, duplicate instrument IDs, unknown instrument/session references, negative cash and conflicting duplicate delivery. Include a false-flag mutation rejection test.

```python
result = replace(valid_result, positions_flat=False)
assert not result.strategy_outcomes_complete
assert result.evidence_promotable is False
```

- [ ] Observe failures with `python -m pytest tests/unit/simulation/test_equity_replay_models.py -q`.
- [ ] Validate a detached `AppConfig` and its `config_hash`, existing verified bundle and domain metadata. Synthetic account ID derives internally from a constrained `synthetic:` namespace. Sessions declare finite strictly ordered opportunity times, each inside its window; each market delivery must occupy its instrument's declared slot. Deduplicate deliveries by ID and canonical payload before economic hashing; keep delivery receipts separately. Reject arbitrary objects before serialization, never call their `str`/`repr`.

```python
payload = {"domain": "synthetic-equity-replay-v1", "value": validated_value}
digest = content_hash(payload)
```

- [ ] Rerun model tests plus existing bundle/configured model tests; commit scoped files.

## Task 3: Incremental configured-order transition seam

**Files:** modify `simulation/configured.py`, `configured_models.py`, `configured_fills.py`; create `simulation/configured_session.py`, `tests/unit/simulation/test_configured_session.py`.

**Interfaces:** `ConfiguredOrderSession(request)`; `advance_to(now) -> ConfiguredOrderResult`; `deliver(event) -> None`; `next_event_at: datetime | None`. Optional instrument-aware replay execution settings are explicit and versioned; default wrapper behavior stays unchanged.

- [ ] Pin existing representative partial/full/cancel/expiry result hashes, then test splitting an input into deliveries/advances against the existing complete-run result. Verify late/backdated deliveries reject without changing published state.

```python
session = ConfiguredOrderSession(request)
session.advance_to(first_time)
incremental = session.advance_to(request.end_at)
assert incremental == simulate_configured_order(request)
```

- [ ] Observe missing-session failures. Extract the existing queue/processing logic, preserve priorities and generated event IDs, and avoid dropping a queued event when advancing only to an earlier horizon. Stage candidate changes before publishing them. Reuse configured outcome sampling, costs and lifecycle replay.
- [ ] Add lot/tick tests before instrument-aware changes: quantity floors through canonical quantization, zero-size becomes no-fill, adverse price rounding is rechecked against the limit. Legacy requests have no new instrument behavior.
- [ ] Run `python -m pytest tests/unit/simulation -q`, then commit the extraction and tests.

## Task 4: Shared funding and portfolio state

**Files:** create `simulation/equity_replay_portfolio.py`, `tests/unit/simulation/test_equity_replay_portfolio.py`.

**Interfaces:** `ReplayPortfolio(request)`, `reserve(intent, fee_opportunities) -> ReplayOrderOutcome`, `apply(order_id, configured_result) -> None`, `snapshot(as_of, quotes) -> PortfolioSnapshot`. Only this owner changes unallocated cash/reservations and published positions. Initial order records use the existing `LifecycleRequest`.

- [ ] Write literal two-order funding tests: initial cash 100, a BUY reservation 60 leaves 40 allocatable; another 50 reservation is denied; cancellation without fills releases 60 exactly once. A fill costing 20 plus fee 1 reduces total cash to 79, not 19. SELL cannot reserve more than held shares.
- [ ] Observe failures; implement allocation transfers, not duplicate fill accounting. Each order's current lifecycle cash is its allocation balance; total cash is unallocated cash plus active allocations. Derive position and fill effects only from validated lifecycle results. Repeated identical snapshots cannot release funds or apply fees twice.

```python
total_cash = unallocated_cash + sum(active_allocations, Decimal(0))
assert total_cash >= 0
```

- [ ] Require one active order per instrument; cash and position conservation failure invalidates the replay. Mark held positions with visible fresh quotes; no unobserved mark or implicit closing fill.
- [ ] Run portfolio tests and lifecycle tests, then commit scoped files.

## Task 5: Configured exits and canonical economic checks

**Files:** create `simulation/equity_replay_policy.py`, `simulation/equity_replay_risk.py`, `tests/unit/simulation/test_equity_replay_policy.py`, `tests/unit/simulation/test_equity_replay_risk.py`.

**Interfaces:** immutable `ReplayEntryPolicy(entry_limit, stop_distance, target_price, stop_price, first_fill_at, holding_bars, version)`; `derive_entry_policy(config, features, entry_limit)`; `exit_reason(policy, bid, holding_bars, selected, config) -> str | None`; `economic_checks(intent, portfolio_state, request, now) -> tuple[CheckResult, ...]`.

- [ ] Test hand-derived entry limit 10, ATR 1 and configured multiplier 2: stop 8; configured reward-to-risk 2: target 14. Partial entry fills do not widen the stop. Stop priority wins simultaneous conditions; stale/missing bid does not trigger a fabricated fill.
- [ ] Test exact max-holding boundary, momentum predicate loss, scheduled relative-strength deselection, missing ATR and negative stop. Observe failures; call existing features/strategies and canonical config only.
- [ ] Test economic denial against existing `evaluate_exposure_limits`, `evaluate_loss_limits`, and `evaluate_activity_limits`; derive their snapshots from synthetic state without claiming production evidence. Freeze authorized risk equity at initial cash, use fresh current equity and reservations, maintain UTC baselines from observed history, and deny unknown reset state.

```python
checks = evaluate_exposure_limits(
    projection,
    portfolio=config.portfolio,
    position_risk=config.position_risk,
    crypto=config.crypto,
)
allowed = all(check.allowed for check in checks)
```

- [ ] Activity counts entry submissions, including simulated rejection, once per unique intent. Follow canonical purpose-aware loss rules for exits; hard-stop never creates a liquidation.
- [ ] Rerun policy/risk tests and existing `tests/unit/risk`; commit scoped files.

## Task 6: Full offline decision/event coordinator

**Files:** create `simulation/equity_replay.py`, `simulation/equity_replay_cycle.py`, `tests/integration/simulation/test_equity_strategy_replay.py`.

**Interfaces:** `async replay_equity_strategy(request: EquityStrategyReplayRequest) -> EquityStrategyReplayResult`; `ReplayCycleComposition` internally binds the existing service, loader, feature wrapper, chosen strategy, portfolio, planner, execution recorder and journal.

- [ ] Build a synthetic bundle fixture with visible coverage/membership and completed bars; explicit subsequent quote slots permit actual entry and exit. Assert exact entry/exit intent purpose, literal quantities/cash/fees, true flatness only after the SELL fills, and permanently false evidence flags.
- [ ] Observe the absent runner failure. Merge finite event sources with the configured control priorities; run strategy decisions after prior events at equal time. Size/admit each intent from fresh state, exits first, then stable instrument order. Bind ID factories to as-of inputs, never future scenario content.
- [ ] When an entry remainder exists at an exit trigger, queue its cancel; wait for terminal state and account for the race fill before making a new exit decision. No reusing an old quantity or expired quote.
- [ ] Add incomplete/prefix tests before implementing result derivation:

```python
assert canceled_entry.orders_terminal
assert not canceled_entry.positions_flat
assert not canceled_entry.strategy_outcomes_complete
assert short_run.cycles == extended_run.cycles[: len(short_run.cycles)]
```

- [ ] Rejection, expiry, no-fill and open positions are explicit; malformed/accounting failures return no completed result. Rerun simulation and paper/promotion denial tests; commit scoped files.

## Task 7: Strict local CLI and truthful summary behavior

**Files:** create `simulation/equity_replay_io.py`, `tests/unit/simulation/test_equity_replay_io.py`, `tests/integration/cli/test_equity_replay.py`; modify `cli/main.py`, `tests/integration/cli/test_offline_modes.py`, `docs/architecture.md`, `docs/limitations.md` (only this change's paragraph), `README.md`.

**Interfaces:** `read_replay_scenario(path, loaded, seed, repository_root) -> EquityStrategyReplayRequest`; `simulate` accepts optional `--scenario`. Use existing private bundle reading and existing explicit bundle limits; scenario input must be a bounded, current-owner private regular file, outside repository, with no symlink traversal.

- [ ] Test JSON unknown keys, duplicate keys, NaN/floats/noncanonical decimals, unsafe permissions, oversized data, provider kinds and symlinks; errors contain only stable codes, not file content or paths. Observe failures before implementation.
- [ ] Test the CLI on a temporary private synthetic scenario: complete run exits 0, incomplete run exits 2 with sanitized reason codes, malformed input exits 2 without raw exceptions.
- [x] Test configuration-only commands and implement the deliberate response correction. This independent substep was pulled forward before the runner: two regression tests failed on `completed_offline`, then passed with `configuration_only` and `executed=false`. The scenario-loading/runner substeps remain incomplete.

```python
assert response["status"] == "configuration_only"
assert response["executed"] is False
assert "completed_offline" not in response.values()
```

- [ ] No real `backtest` runner is claimed. Update docs with exact input format, limitations and exit codes. Run CLI/simulation tests and commit only owned hunks.

## Task 8: Adversarial and final verification

**Files:** create `tests/unit/simulation/test_equity_replay_adversarial.py`; update this plan and the current handoff with observed results only.

- [ ] Add tests for ambient Decimal precision, duplicate delivery, future extensions, two-symbol cash conflicts, rejected cancel/exit assumptions, and wrong config/identity. Each assertion names its intended broken behavior.
- [ ] Prove architecture behavior with incapable boundaries and a forbidden-I/O test guard; do not rely only on source-string checks.
- [ ] Exercise in-memory mutations for fees omitted, cash reused, duplicate fills, same-bar fill, ignored cancel race and terminal-entry-implies-flat. Each must be caught; do not write mutated production files.
- [ ] Run Ruff, Mypy, full tests with branch coverage >=80%, Bandit and frozen lock verification. Audit pinned dependencies using frozen `uv export` piped into `pip_audit --requirement /dev/stdin --no-deps --disable-pip`; no fixes or upgrades.
- [ ] Review every diff for weakened gates, secret exposure, duplicate schemas/formulas, changed legacy hashes or hidden economic assumptions. Record all warnings and skipped external checks.
- [ ] Commit final task files only; leave unrelated pre-existing modifications intact. Report local verification, remaining blockers and exact commits. Do not push, merge or deploy without separate authority.

## Plan self-review

First integration checkpoint: the full local suite initially reported 4,446 passed and one
README phrase-contract failure, with 87.44% combined coverage. The README now preserves that
contract while explicitly describing configuration-only behavior; all 29 CLI/documentation
checks passed after the correction. Full verification will be repeated after the next slice.

Every spec section maps to Tasks 1-8: interfaces (1), contracts/identity/time (2-3), funding (4), configured risk/exits (5), strategy composition/completion (6), operator surface (7), verification (8). Session opportunity declarations separate structural capacity from future market delivery. No new broker, persistence or promotion implementation is included. All protected changes remain primary-owned.
