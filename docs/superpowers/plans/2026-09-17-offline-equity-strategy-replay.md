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

At plan creation the simulator was complete only for its single-order fixture scope, with
whole-strategy replay and its CLI absent. The completed tasks below now include the offline
coordinator; the private scenario CLI and final milestone checks remain pending.
Provider/source/runtime/promotion layers remain separately blocked.

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

**Interfaces:** frozen `ReplayCandidate(strategy_id, short_window, long_window, top_n, exposure_multiplier)`; `ReplaySession(instrument_id, window, opportunity_times)`; `ReplayDecision(event_id, cursor)`; `EquityStrategyReplayRequest(namespace, loaded, seed, candidate, bundle, snapshot_settings, instruments, sessions, decisions, markets, starts_at, end_at, initial_cash)`; frozen `ReplayOrderOutcome(intent_id, accepted, reasons, order_id)` with no eligibility fields. Reuse and detach the existing `LoadedConfig` to bind both canonical config and its safety envelope, rather than introducing a separate config/hash carrier. Task 6 implements the aggregate `EquityStrategyReplayResult`, deriving terminal/flat/completion facts from Task 4's authoritative portfolio/order records, not independent caller-selected booleans.

- [x] Write request/outcome construction tests for wrong exact types, live mode, enabled evidence flags, candidate outside canonical grids, non-UTC dates, duplicate instrument IDs, unknown instrument/session references, negative cash and conflicting duplicate delivery. Include false-flag mutation rejection tests. Aggregate-result tests were added with Task 6 once authoritative records were available.

```python
assert request.evidence_promotable is False
assert replay_identity(request).input_hash == replay_identity(redelivered).input_hash
assert replay_identity(request).delivery_hash != replay_identity(redelivered).delivery_hash
```

- [x] Observe failures with `python -m pytest tests/unit/simulation/test_equity_replay_models.py -q`. Initial collection failed on the missing codec. A later adversarial warning-capture test reproduced Pydantic attempting to format an injected unknown object; the config-tree preflight now denies before serialization with no warning.
- [x] Validate a detached `LoadedConfig` and its config/envelope identity, existing verified bundle and domain metadata. Synthetic account ID derives internally from a constrained `synthetic:` namespace. Sessions declare finite strictly ordered opportunity times, each inside its window; each market delivery must occupy its instrument's declared slot. Deduplicate deliveries by ID and canonical payload before economic hashing; keep delivery receipts separately. Reject arbitrary objects before serialization, never call their `str`/`repr`.

```python
payload = {"domain": "synthetic-equity-replay-v1", "value": validated_value}
digest = content_hash(payload)
```

- [x] Rerun model tests plus existing bundle/configured model tests: 43 new contract tests and 539 tests in the expanded selection passed; all-source Ruff and Mypy (186 source files) passed.
- [x] Derive and test the aggregate result contract alongside Task 6 coordination: construction is internal, eligibility fields are immutable false, and authoritative terminal orders do not imply flat positions. A valid incomplete run retains explicit unresolved reasons.
- [x] Commit the verified input/identity slice and document its remaining boundary (`feat: add strict synthetic equity replay input contracts`).

## Task 3: Incremental configured-order transition seam

Continuation at `a9cea06`: **completed and verified on 2026-09-18 UTC**. The existing linked worktree and all unrelated
dirty paths were preserved; 428 simulation unit/integration tests passed before edits.
First add forward-only incremental scheduling and atomic publication, then opt-in versioned
instrument constraints. The public one-shot API must retain its exact default hashes.

**Files:** modify `simulation/configured.py`, `configured_models.py`, `configured_fills.py`; create `simulation/configured_session.py`, `tests/unit/simulation/test_configured_session.py`.

**Interfaces:** `ConfiguredOrderSession(request)`; `advance_to(now) -> ConfiguredOrderResult`; `deliver(event) -> None`; `next_event_at: datetime | None`. Optional instrument-aware replay execution settings are explicit and versioned; default wrapper behavior stays unchanged.

- [x] Pin existing representative partial/full/cancel/expiry result hashes, then test splitting an input into deliveries/advances against the existing complete-run result. Verify late/backdated deliveries reject without changing published state. All four pinned legacy hashes remain unchanged.

```python
session = ConfiguredOrderSession(request)
session.advance_to(first_time)
incremental = session.advance_to(request.end_at)
assert incremental == simulate_configured_order(request)
```

- [x] Observe missing-session failures: 15 new session tests failed before implementation and four baseline hash tests passed. Extract the queue/processing logic, preserve priorities and generated event IDs, and avoid dropping a queued event when advancing only to an earlier horizon. Stage candidate changes before publishing them. Reuse configured outcome sampling, costs and lifecycle replay.
- [x] Add lot/tick tests before instrument-aware changes: 15 tests failed on the missing opt-in request before implementation. Quantities floor through canonical quantization, zero-size becomes no-fill, and adverse price rounding is rechecked against the limit. A subsequent failing audit regression proved that the sampled partial percentage must survive a sub-lot no-fill; it is now retained. Legacy requests have no new instrument behavior.
- [x] Run the simulation unit/integration suite: 466 tests passed, including 38 new session/increment cases. Ruff and Mypy (187 source files) passed. Additional cases check immutable future-extension prefixes, ambient Decimal precision and disabled network/SQLite boundaries.
- [x] Commit the verified extraction, opt-in increment behavior and documentation (`feat: add incremental configured equity order simulation`).

Session timing contract: a timestamp becomes closed when `advance_to` publishes through it.
`deliver` cannot insert a later-discovered control or market input into that closed timestamp,
including duplicate redelivery. The eventual coordinator must give newly generated same-time
actions an explicit causal phase with bound audit identity; it must not backdate a cancel,
silently reorder an already-applied quote, or invent a later timestamp. This integration detail
was deferred until Task 6, which now implements the explicit causal phase. Current session delivery
rebuilds a private prefix for correctness, not production-scale throughput.

## Task 4: Shared funding and portfolio state

**Files:** create `simulation/equity_replay_portfolio.py`, the boundary-validation helper
`simulation/equity_replay_portfolio_checks.py`, `tests/unit/simulation/test_equity_replay_portfolio.py`
and its synthetic-only two-symbol fixture helper.

**Interfaces:** `ReplayPortfolio(request)`, `reserve(intent, fee_opportunities) -> ReplayOrderOutcome`, `apply(order_id, configured_result) -> None`, `snapshot(as_of, quotes) -> PortfolioSnapshot`. Only this owner changes unallocated cash/reservations and published positions. Initial order records use the existing `LifecycleRequest`.

- [x] Write literal two-order funding tests: initial cash 100, a BUY reservation 60 leaves 40 allocatable; another 50 reservation is denied; cancellation without fills releases 60 exactly once. A fill costing 20 plus fee 1 reduces total cash to 79, not 19. SELL cannot reserve more than held shares.
- [x] Observe failures; implement allocation transfers, not duplicate fill accounting. After correcting synthetic source fixture identities, 21 tests failed on the missing portfolio before implementation. Each order's current lifecycle cash is its allocation balance; total cash is unallocated cash plus active allocations. Derive position and fill effects only from validated lifecycle results. Repeated identical snapshots cannot release funds or apply fees twice.

```python
total_cash = unallocated_cash + sum(active_allocations, Decimal(0))
assert total_cash >= 0
```

- [x] Require one active order per instrument; cash and position conservation failure invalidates the replay. Mark held positions with visible fresh quotes; no unobserved mark or implicit closing fill. Valuation uses the bid. Realized fields recognize fully traced, terminal, flat round trips only; partial-exit cash flows stay with open marked exposure, not broker tax lots.
- [x] Run portfolio tests and lifecycle tests: 43 portfolio cases and 522 tests in the broader simulation/portfolio selection passed. Commit only Task 4 source, tests and its architecture/spec/plan updates; preserve the already-dirty handoff and unrelated paths outside that commit.

Continuation note: 43 portfolio cases now cover disjoint allocations, canonical commission
capacity, shared ordering, cancellation/rejection/expiry, duplicate and conflicting updates,
freshness boundaries, fixed Decimal precision, bid marks, partial exits and forbidden I/O.
Separate failing audit regressions exposed future-input digests leaking into a current
portfolio hash and omitted configured decisions hiding generated event times. Current-state
identity now excludes future audit hashes; decision prefixes are linked back to lifecycle
events, timestamps and snapshot hashes. Both defects were reproduced before correction.
At that checkpoint the book supplied authoritative order/flat facts, but the complete strategy
result contract was deferred until Task 6 supplied decisions, exit reasons and completion context.

## Task 5: Configured exits and canonical economic checks

**Files:** create `simulation/equity_replay_policy.py`, `simulation/equity_replay_risk.py`, `simulation/equity_replay_risk_state.py`, `tests/unit/simulation/test_equity_replay_policy.py`, `tests/unit/simulation/test_equity_replay_risk.py`; expose the portfolio's immutable scenario identity in `simulation/equity_replay_portfolio.py`.

**Implemented interfaces:** immutable `ReplayEntryPolicy` carries the instrument/config/feature identity, observation time, frozen price basis and observed first-fill/holding state, with a derived immutable `version`; `derive_entry_policy(request, features, entry_limit)`; `observe_entry(policy, entry, bars, as_of, request)`; `exit_reason(policy, quote, selected, as_of, request) -> str | None`; `planning_policy(policy, request)`; `selected_instruments(request, context, completed_bars=...)`; `ReplayRiskState(request, portfolio)`; `economic_checks(intent, portfolio_state, request, now) -> tuple[CheckResult, ...]`. Typed quotes and explicit time replace the planned bare-bid seam so source/freshness cannot be omitted. The observed history is separated from the projection adapter to keep each module focused.

- [x] Test hand-derived entry limit 10, ATR 1 and configured multiplier 2: stop 8; configured reward-to-risk 2: target 14. Partial entry fills do not widen the stop. Stop priority wins simultaneous conditions; stale/missing bid does not trigger a fabricated fill.
- [x] Test exact max-holding boundary, momentum predicate loss, scheduled relative-strength deselection, missing ATR and negative stop. Observe failures; call existing features/strategies and canonical config only. The initial policy selection produced 23 missing-module failures before implementation.
- [x] Test economic denial against existing `evaluate_exposure_limits`, `evaluate_loss_limits`, and `evaluate_activity_limits`; derive their snapshots from synthetic state without claiming production evidence. Freeze authorized risk equity at initial cash, use fresh current equity and reservations, maintain UTC baselines from observed history, and deny unknown reset state. Initially 16 risk-adapter tests failed on the missing module while the policy/planner seam passed.

```python
checks = evaluate_exposure_limits(
    projection,
    portfolio=config.portfolio,
    position_risk=config.position_risk,
    crypto=config.crypto,
)
allowed = all(check.allowed for check in checks)
```

- [x] Activity counts entry submissions, including simulated rejection, once per unique intent. Follow canonical purpose-aware loss rules for exits; hard-stop never creates a liquidation. Tests cover exact daily/weekly reset, daily/symbol caps, 30-minute spacing, lifecycle-derived consecutive losses and the configured pause boundary.
- [x] Rerun policy/risk tests and existing `tests/unit/risk`; commit scoped files. The 57 new cases and expanded 324-case risk selection pass; full verification is recorded below. The pre-existing dirty handoff and unrelated files are excluded from this commit.

The focused Task 5 selection passes 57 cases. Additional audit regressions first reproduced
skipped mark/fill history, an older fresh mark hiding a later visible quote, drawdown clearing
after recovery, stale quote redelivery displacing a current mark, and entry-record identity
drift. The state/policy adapters now deny those inconsistencies or preserve the required
history. Full-suite and final checkpoint verification is recorded below.

## Task 6: Full offline decision/event coordinator

**Files:** create `simulation/equity_replay.py`, `simulation/equity_replay_cycle.py`,
`simulation/equity_replay_state.py`, `simulation/equity_replay_records.py`,
`tests/integration/simulation/test_equity_strategy_replay.py` and its synthetic fixture helper;
extend `simulation/configured_session.py` and add `tests/unit/simulation/test_configured_coordination.py`.

**Interfaces:** `async replay_equity_strategy(request: EquityStrategyReplayRequest) -> EquityStrategyReplayResult`; `ReplayCycleComposition` internally binds the existing service, loader, feature wrapper, chosen strategy, portfolio, planner, execution recorder and journal.

- [x] Build a synthetic bundle fixture with visible coverage/membership and 750 completed daily bars; explicit subsequent quote slots permit actual momentum and relative-strength entry and exit. Assert exact entry/exit intent purpose, literal quantities/cash/fees, true flatness only after the SELL fills, and permanently false evidence flags.
- [x] Observe the absent runner failure: eight initial integration cases failed before implementation. Sixteen initial scheduler cases likewise failed on the missing per-action/causal seam. Merge finite event sources with configured control priorities; run strategy decisions after prior events at equal time. Recheck admission from fresh state, exits first, then stable instrument order. Bind IDs to as-of inputs, never future scenario content.
- [x] When an entry remainder exists at an exit trigger, queue its cancel; wait for terminal state and account for the race fill before another declared decision recomputes the current trigger, actual quantity, quote and checks. No implicit decision on acknowledgement, old quantity or expired quote.
- [x] Add incomplete/prefix tests before implementing result derivation:

```python
assert canceled_entry.orders_terminal
assert not canceled_entry.positions_flat
assert not canceled_entry.strategy_outcomes_complete
assert short_run.cycles == extended_run.cycles[: len(short_run.cycles)]
```

- [x] Rejection, expiry, no-fill and open positions are explicit; malformed/accounting failures return no completed result. The 46 new coordination/integration cases and expanded 605-case simulation/paper/promotion selection pass. Full verification and scoped commit are recorded in the checkpoint below.

Audit regressions reproduced zero-latency cancellation acknowledgements interleaving before
other same-time causal requests, and missing readable loss-cancellation reasons. Requests now
all precede their same-time acknowledgements, and the immutable result retains cancellation
order/time/reason. Prefix checks include a pending cancel race; a later decision after a price
recovery does not reuse the previous stop trigger. Final stale marks and insufficient history
deny without fabricating completion. No production runtime, broker or risk config is changed.

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
checks passed after the correction.

Input/identity checkpoint on 2026-09-17 UTC: the full local suite passed **4,490 tests** with
**87.56% combined line/branch coverage**, above the unchanged 80% floor. Ruff, Mypy (186 source
files), Bandit and `uv lock --check --offline` passed. The frozen dependency audit earlier in
this implementation turn found no known vulnerabilities; dependencies were not changed.
The existing Starlette/httpx deprecation and Bandit comment warnings remain. Both standalone
simulation/backtest scripts returned `configuration_only` and `executed=false`. No remote
CI, broker, provider, deployment or production-ledger checks were performed.

That checkpoint verified the implemented slices only, not completion of Tasks 2-8. The subsequent
Task 3 checkpoint below supersedes its incremental-simulator status.

Incremental/instrument checkpoint on **2026-09-18 UTC**: **4,528 tests passed**, with **87.63%**
combined coverage and the unchanged 80% floor. Ruff, Mypy (187 source files), Bandit, offline
lock verification and the frozen dependency audit passed; no known dependency vulnerabilities
were reported. Existing Starlette/httpx and Bandit comment warnings remain. The audit tool also
printed its general pinned-dependency hashing guidance. Dependencies were not modified.

Three isolated in-memory mutation probes were detected at their intended assertions: discarded
future queue entries, omitted commission, and quantities rounded upward. No mutated source was
written to disk. The unmodified targeted tests were rerun after the probes. Prefix compatibility,
control ordering, atomic failures, lot/tick behavior and false eligibility flags were reviewed.
No broker, credential, production-ledger, deployment, remote CI, push or merge action occurred.

At that Task 3 checkpoint, shared funding and the subsequent strategy layers remained open.
The following Task 4 checkpoint supersedes the portfolio-funding status only.

Shared-portfolio checkpoint on **2026-09-18 UTC**: **4,571 tests passed**, with **87.72%**
combined coverage and the unchanged 80% floor. Ruff, Mypy (189 source files), Bandit, offline
lock verification and the frozen dependency audit passed; no known dependency vulnerabilities
were reported. The existing Starlette/httpx warning, Bandit comment warnings and audit hashing
guidance remain. Dependencies and canonical risk configuration were not changed.

Three isolated, expected-failing in-memory mutation probes detected reuse of reserved cash,
duplicate terminal cash release, and terminal orders incorrectly implying flat positions. Each
failed at the intended literal assertion; the unmodified tests were rerun afterward. The probes
also produced an in-process Pytest plugin rewrite warning. No mutated source was written.
The complete local suite, focused checks, and scoped review found no changed broker, runtime,
risk, execution or configuration files. No remote CI, external broker/provider, credentials,
production ledger, deployment, push, merge, account changes or spending occurred.

At that checkpoint, Task 4 was complete and Task 5 (configured exits and canonical economic
checks) was next. The
aggregate strategy result, decision coordinator (including same-time causal phases), private
scenario CLI and whole-strategy end-to-end/adversarial tests remain open. The complete offline
replay milestone and live readiness are not claimed.

Configured-policy/economic-check checkpoint on **2026-09-18 UTC**: **4,628 tests passed**, with
**87.72% combined coverage**, retaining the 80% floor. The 57 new tests and expanded 324-case
risk selection passed independently. Ruff, Mypy (192 source files), Bandit, offline lock
verification and the frozen pinned-dependency audit passed; no known vulnerabilities were
reported. Existing Starlette/httpx, Bandit comment and audit hashing-guidance warnings remain.
No dependencies or canonical risk thresholds were changed.

Four isolated in-memory mutation probes were caught at their intended assertions: ignored
pending correlated exposure, erased loss observations, skipped history completeness, and a
maximum-holding exit overriding stop/target priority. No source file was mutated; the
unmodified 324-case risk selection was rerun afterward. Test-first audit corrections also
preserve drawdown hard-stops after recovery, select current marks despite old quote redelivery,
and bind observed entry state back to its submitted identity and quantity.

At that checkpoint Task 5 was complete and Task 6 (the full offline decision/event coordinator)
was next. Aggregate result derivation, same-time causal phases, cancel-race-aware exits, strict
private scenario CLI, and whole-strategy verification remained open. No real provider,
broker, credential, production-ledger, remote CI, deployment, push, merge, account, subscription
or live operation was performed. No new plugin or spending is required for the next offline
task. All protected strategy/risk work remained primary-owned and inline; unrelated dirty
paths were preserved.

Decision/event coordinator checkpoint on **2026-09-18 UTC**: **4,674 tests passed** with
**87.86% combined line/branch coverage**, retaining the 80% floor. The 46 new scheduling and
full-pipeline integration cases passed; 605 simulation/paper/promotion regressions also passed
independently. Ruff, Mypy (196 source files), Bandit, offline lock verification and the frozen
pinned-dependency audit passed; no known dependency vulnerabilities were reported. Existing
Starlette/httpx, Bandit comment and audit hashing-guidance warnings remain. No dependencies,
canonical risk thresholds, production runtime, broker or deployment files were changed.

Three isolated in-memory mutations were detected at their intended assertions: same-bar fills,
ignored cancel-race fills, and terminal entries incorrectly treated as flat positions. No source
files were mutated; the unmodified 46-case selection was rerun afterward. Full-suite verification
also passed after the implementation and included unchanged legacy hash, paper restart and
promotion-denial contracts. Scoped review confirmed that eligibility flags remain false and no
provider, broker, ledger, credential, authorization or promotion-writing capability was added.

**Task 6 and the remaining Task 2 aggregate-result contract are complete. Task 7's private
scenario CLI is next; Task 8's complete milestone-level adversarial review remains pending.**
The runner is a value-only Python entry point, not a completed operator CLI or live-readiness
milestone. No remote CI, provider/broker calls, account or credential operations, production
ledger access, deployment, push, merge, subscriptions, spending or live activation occurred.
Protected work stayed primary-owned and inline. The pre-existing dirty handoff was updated
locally and left outside the scoped commit, together with all other unrelated changes.

Every spec section maps to Tasks 1-8: interfaces (1), contracts/identity/time (2-3), funding (4), configured risk/exits (5), strategy composition/completion (6), operator surface (7), verification (8). Session opportunity declarations separate structural capacity from future market delivery. No new broker, persistence or promotion implementation is included. All protected changes remain primary-owned.
