# Offline equity strategy replay design

Date: 2026-09-17 UTC.
Source reviewed: `a447de05da54e078b1b28859cdb5a04085d46e2b`.
Status: **written design approved by the operator on 2026-09-17 UTC; implementation in progress**.

The integration seams, strict scenario-input/outcome contracts, separated audit/receipt identities,
incremental single-order sessions, opt-in equity tick/lot handling, and truthful configuration-only
CLI status are implemented. The full event/portfolio replay,
aggregate result derivation and scenario CLI path remain incomplete; see the
[implementation checklist](../plans/2026-09-17-offline-equity-strategy-replay.md).

The operator selected offline strategy replay and then approved this written design. This document
defines that implementation scope. Approval does not authorize broker calls, real-data capture,
deployment, live activation, new risk thresholds, or promotion claims.

## 1. Objective and alternatives

Build a deterministic, synthetic-only equity replay through the existing decision pipeline.
Connect strategy decisions, canonical sizing and economic risk checks, simulated order events,
cash/positions, and exit completion. Expose incomplete outcomes honestly. Keep the existing
single-order and scripted lifecycle APIs backward compatible.

Approaches considered:

1. **Extend the existing decision pipeline (recommended).** More integration work than a separate
   research loop, but strategy, sizing, configuration, fill assumptions, and lifecycle accounting
   keep their existing owners. This is the selected direction.
2. Extend only the ETF comparison report. Quicker to produce another report, but would preserve a
   second execution/accounting path instead of closing the decision-cycle integration gap.
3. Build a broker-connected runner first. Requires missing external evidence and introduces
   account/operational authority before the offline lifecycle has been verified. Deferred.

This is an engineering replay, not accepted research, a full production pretrade evaluation, or
a broker backtest. It cannot close source-rights, real-data, provider, deployment, or elapsed-time
blockers. It makes no claims about trading performance.

## 2. Scope and permanent boundaries

Included:

- A finite fixture scenario with verified synthetic bundle data, explicit UTC decision times,
  quote/session/liquidity events, instrument metadata, and initial synthetic cash.
- One existing equity candidate family per run: momentum or relative strength. Candidate window,
  ranking and exposure choices must be members of the canonical configuration's allowed sets.
- Multiple equity instruments and positions, but at most one active order per instrument.
  Opposing orders and overlapping entry/exit intents for the same instrument are denied.
- LIMIT, GOOD_FOR_DAY orders; explicit fixture session expiry, no inferred exchange calendar.
- Complete event and decision records, exact cash/fee/quantity accounting, open exposure, and
  explicit terminal/incomplete status.

Excluded:

- Real source ingestion, provider transports, authentication, cloud/host access, production
  persistence, research acceptance writes, promotion observations and scheduling.
- Crypto, prediction markets, options, shorts, margin, market orders, withdrawals, automatic
  liquidation, averaging down, pyramiding, retry-size escalation, or a new strategy.
- Broker settlement rules, validated exchange calendars, calibrated execution assumptions,
  tax-lot reporting, and probabilistic claims inferred from synthetic results.

Every scenario/result has a distinct versioned synthetic source kind. Result fields
`assumptions_validated` and `evidence_promotable` are immutable false values, not caller options.
The run rejects live-enabled configuration, non-simulation mode, enabled promotion assumptions,
and real-account/provider identifiers. Scenario accounts use a reserved synthetic namespace.

## 3. Composition and interfaces

Use `DecisionCycleService`, `BundleSnapshotLoader`, `FeaturePipeline`, the existing strategy
classes, `PortfolioConstructor`, `IntentPlanner`, canonical economic risk functions, configured
fill/cost logic, and the existing lifecycle/accounting authority. Do not create an alternative
sizing model or replicate BUY/SELL accounting formulas.

New replay modules under `src/trading_bot/simulation/` own:

- Immutable request/result and per-event contracts.
- Scenario validation and canonical serialization.
- A virtual-time coordinator with portfolio and active-order state.
- An execution stage that records submitted synthetic orders rather than draining a future
  timeline synchronously inside `DecisionCycleService.run_cycle`.
- A configuration-derived exit-policy adapter and a typed in-memory cycle journal.

Necessary existing seams are explicit:

- `IntentPlanner` gains an optional ID factory. Existing callers retain the current factory;
  replay binds a deterministic factory derived from the scenario, cycle, target, and ordinal.
  Do not monkeypatch UUID generation or global random state.
- Add an optional typed outcome encoder to the decision-cycle composition. Preserve existing
  callers' behavior and legacy hashes. Replay selects a versioned canonical encoder which
  rejects unknown objects; it never hashes `str(object)` as outcome evidence.
- Allow per-instrument exit-policy values in the portfolio composition, mutually exclusive with
  the existing single-policy form. They are derived from the same canonical config and visible
  features, not an additional config schema. Existing single-policy callers remain unchanged.
- Extract a reusable incremental configured-order transition seam from the current private
  scheduler. The current single-order API becomes a wrapper over the same transition logic.
  Existing fixture outputs/hashes, tie ordering, RNG behavior and denial rules must remain stable.

Public top-level replay entry point: asynchronous `replay_equity_strategy(request)` returning a
strict immutable `EquityStrategyReplayResult`. It accepts values only, not arbitrary callbacks,
credentials, provider objects, executable fixture code, or persistence stores. Internal
composition seams remain testable without being exposed in the scenario format.

## 4. Time, visibility, identity and ordering

All times are explicit UTC. No wall-clock sleep, network or ambient current time enters a run.
Validate finite ordered events, duplicate IDs and payload equality before execution. Identical
redelivery is recorded without a second application; conflicting duplicates reject the run.

At a timestamp, apply the existing configured-order control precedence first: expiry,
submission acknowledgement, cancel request, cancel acknowledgement, then market opportunities.
Strategy decisions run after already-scheduled events at that instant. Instruments and orders
use stable canonical IDs as tie breakers. A newly generated order cannot consume the triggering
market event or any event from its submission bar; the existing no-same-bar guard stays in force.

Each decision receives only bundle records visible at its `as_of`, completed historical bars,
current portfolio state, and quotes no newer than that instant. The loader's coverage,
membership, action and interpolation denials remain unchanged. Insufficient/future/gapped data
does not become a HOLD or a fabricated successful observation: the run reports the denial.

IDs and RNG keys bind a stable synthetic run namespace, seed, strategy/parameter identity,
config identity, the canonical as-of decision input, cycle identity and order identity. They
must not depend on future events, later deliveries, or the full scenario audit digest. Economic
input identity deduplicates identical deliveries before hashing; a separate delivery-receipt
digest records every delivery. Hashes use canonical typed fields and fixed Decimal contexts.
Tests must show that ambient Decimal precision, hash seed, wall time, unrelated RNG use and
identical duplicate delivery do not change economic outcomes. Appending later events cannot
change decisions or executions already completed in the earlier prefix.

## 5. Portfolio state and order funding

Start flat with explicit synthetic cash; no implicit pre-existing lots. Maintain account cash,
per-instrument position/entry metadata, active orders, reserved cash/shares, fills, fees and
decision records. Mark positions only with an as-of visible verified synthetic quote. Unknown
or stale valuation cannot silently refresh equity or create buying power.

Order admission is deterministic. Evaluate exits before entries at each decision time, then
sort by instrument/intent ID. Recompute the projected state and canonical economic checks after
each accepted order; do not size every order against the same unreserved cash snapshot.

Each BUY order receives a disjoint synthetic cash allocation sufficient for its limit notional
and a conservative fee bound. For the current equity cost model, reserve configured commission
for at most one fill per remaining supplied market opportunity through that order's expiry;
the bound uses only the declared schedule, not future prices, liquidity or sampled outcomes.
This is an explicit conservative fixture funding assumption, not a broker buying-power model.
Reject when the bound cannot be funded; do not silently shrink, retry, borrow, or increase risk.

Only the existing lifecycle authority applies fill cash, fees and position quantity. Aggregate
portfolio cash from unallocated cash plus current order allocations; reservation transfers are
not economic debits. Release unused allocation only after a terminal order state. Allocate
SELL shares from the current position and deny overselling; proceeds are not spendable by new
entries until the synthetic order is terminal. This conservative settlement assumption must be
included in result limitations.

One active order per instrument prevents independent lifecycle snapshots from overwriting the
same position. Orders in different instruments share a single admission/reservation authority.
Liquidity belongs to a unique instrument/event and cannot be consumed twice by redelivery.
Arithmetic overflow, negative cash/quantity, identity drift or ledger disagreement rejects the
candidate event and invalidates the run; no partially valid result is published as completed.

Tick and lot constraints come from scenario instrument metadata, not hard-coded thresholds.
The replay transition adapter uses canonical downward quantity quantization; a sub-lot sampled
fill becomes an explicit no-fill. Any price rounding must be adverse and checked again against
the limit. These instrument-aware rules are versioned replay behavior, not a silent change to
legacy single-order fixture semantics.

## 6. Risk evaluation and exit policy

All numeric limits come from the loaded canonical config. Reuse sizing, exposure, activity and
loss-limit functions with fresh synthetic portfolio projections; never implement a looser
parallel formula. Record synthetic initial equity and UTC day/week reset baselines from the
scenario's own complete observed history, not an assumed production reconciliation. Unknown
baseline state denies entry. Count simulated submissions conservatively for activity limits, including
rejected submissions. Reservations count toward projected entry exposure. No new entry while
an existing position or entry remainder exists in that instrument.

The replay does not fabricate accepted research, provider health, live leases, or production
reconciliation to make `PretradeEngine` pass. Its results explicitly say
`production_pretrade_eligible=false`; missing external attestations remain missing. Exercising
pure economic functions within a synthetic simulator is not authority to execute an order.

For each entry candidate, use visible `average_true_range` multiplied by the canonical equity
stop-loss multiplier. Missing/nonpositive ATR denies entry. Freeze the initial stop distance
and entry limit as the position's policy basis. Stop and reward target are entry-limit minus
distance and entry-limit plus distance times configured reward-to-risk. Nonpositive thresholds
or nonrepresentable arithmetic deny entry. Never move the stop
farther away after a loss or partial fill. Record actual fill prices separately.

Evaluate configured exits against fresh visible quote bids, never future bar highs/lows:

1. Stop threshold reached.
2. Reward target reached.
3. Configured maximum holding bars reached, counting completed bars after the first fill.
4. A configured regime exit or scheduled candidate deselection/exit-to-cash.

The ordering only determines the recorded reason when triggers coincide. Regime loss for
momentum means its existing entry predicate is no longer satisfied; relative-strength
deselection follows its existing canonical ranking/top-N selection at configured rebalance
boundaries. Wrap existing strategy decisions with the portfolio-aware exit adapter rather than
silently changing the strategy classes or treating every HOLD as an exit.

If an entry remainder is active when an exit triggers, request cancellation first. Apply any
permitted cancel-race fill, wait for terminal entry state, then create a freshly checked exit
for the actual remaining position. No simultaneous BUY and SELL, blind replace, automatic
resubmission, or market-order escape path is allowed.

Exit orders use the existing LIMIT intent path with the then-visible bid as the price input,
subject to instrument constraints. A stop trigger is not a guaranteed stop fill. A gap, partial
fill, closed session, expired order or inadequate liquidity can leave exposure unresolved. A
later exit attempt requires a new decision and fresh checks; it cannot bypass loss, health or
state controls. End-of-scenario never forcibly flattens a position or assumes a closing fill.

## 7. Result and operator surface

Return separate facts rather than one ambiguous success flag:

- `run_valid`: all processed input, accounting and identity contracts held.
- `orders_terminal`: no submitted/partial/cancel-pending/unknown order remains.
- `positions_flat`: every tracked quantity is zero.
- `strategy_outcomes_complete`: valid run, terminal orders and flat positions.
- Immutable false research/promotion and production-pretrade eligibility fields.
- Decisions, accepted/denied intents, order transitions, fills, fees, cash, reservations,
  position marks, configured exit reasons, unresolved-exposure reasons and canonical hashes.

Do not report complete strategy outcomes just because an entry was filled or canceled.
Realized round-trip cash results can be recorded only from fully traced completed entry/exit
flows; open-position marks remain separate. This slice does not implement research selection,
performance scoring or acceptance.

Add a real `simulate --scenario PATH --config configs/simulation.yaml --seed N` path using a
strict synthetic JSON scenario and the existing private bundle reader. Reject unknown keys,
unsafe/symlink paths and real-source kinds. Print only sanitized summary data to stdout; no
production ledger is opened. A valid but incomplete run prints its reasons and exits nonzero.

Without a scenario, `simulate` must identify itself as configuration-only and
`executed=false`, not `completed_offline`. Apply the same truthful wording to the currently
summary-only `backtest` command, but do not relabel this synthetic replay as an implemented
research backtest. Update CLI tests/docs for the deliberate summary-contract correction.

## 8. Verification and delivery boundaries

Primary-owned implementation; no protected risk/accounting/composition delegation. No broker,
credential, provider-data, production-ledger or host operations in tests. No new plugin needed.

Required tests, narrow first:

- Existing single-order fixtures/hashes and lifecycle tests unchanged under the extracted seam.
- End-to-end synthetic momentum and relative-strength entry, partial fill, cancel and actual
  exit through the existing decision pipeline; deterministic replay and canonical outcome hashes.
- Two-symbol cash reservation contention, no double liquidity consumption, no averaging down,
  lot/tick boundaries, configured fees and fee-reservation release.
- Stop/target/holding/regime exits, cancel-race before exit, rejection/expiry/no-fill, and unresolved
  end-of-scenario exposure. Denied exits never become implicit liquidation.
- Future/incomplete/missing coverage, stale quotes, closed/halted/cancel-only sessions, conflicting
  duplicates, arithmetic failure, ID/hash corruption and candidate/config mismatch.
- Canonical loss/activity/exposure denial and fresh projections after each order admission.
- Fixture architecture tests prove absence of provider/network, production persistence,
  authorization/lease creation and promotion-writing capabilities.
- Mutation checks for same-bar fills, fees omitted, cash reuse, duplicate fills, bypassed exit
  cancellation and terminal-order-implies-flat mistakes.

Then run Ruff, Mypy, full non-authenticated tests with branch coverage >=80%, Bandit, frozen
lock verification and the locked dependency audit. Do not claim remote CI or deployment without
separate observed results and authority. All existing dirty work is preserved.

Suggested implementation sequence after written-spec approval: immutable contracts and tests;
backward-compatible integration seams; event coordinator and reservations; exit policy adapter;
end-to-end CLI wiring; adversarial verification and documentation. The implementation plan will
specify exact owned paths and commit boundaries only after this design is approved.

Completion closes the offline replay slice, not all of B01's future real-world modeling scope
and not B02-B11 in the [blocker register](../../blocker-register-2026-09-17.md). The default
deployment remains paused and live trading remains unavailable.

## 9. Design review checkpoint

Self-review checked source interfaces, legacy-compatibility boundaries, duplicate-delivery
identity, future-data isolation, cash reservation, exit races, incomplete outcomes, and the
permanent non-promotable boundary. This paragraph records the original design review, not completion
of the runner. Implementation tests now cover the initial integration and contract slices; the
implementation checklist tracks the still-missing replay and final verification. Operator approval
of this written specification was received before the implementation plan.
