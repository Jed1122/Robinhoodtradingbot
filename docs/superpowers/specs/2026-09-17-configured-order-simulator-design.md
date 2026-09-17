# Configuration-driven synthetic single-order simulator

Date: 2026-09-17 (UTC)

Status: the operator approved the in-chat architectural scope. This written specification
is pending operator review; it describes proposed behavior, not completed implementation.

Inspected base: `083f53f398ffad2e13b58ebe536b18b2b17e7a57`, branch
`codex/continue-implementation-from-commit-7c4dcd1`. Existing dirty provider documentation,
handoff notes, shutdown tests, and local artifacts are outside this specification's commit.

## 1. Outcome, authority, and critical path

Add a deterministic, in-memory coordinator that turns one synthetic order, canonical
simulation/cost settings, and explicit synthetic market observations into a scripted
lifecycle. It models submission rejection, later fill opportunities, configured partial
sizes, virtual latency, session restrictions, cancellation races, and explicit expiration.
The existing lifecycle remains the sole authority for order transitions and accounting.

The simulation subsystem is **partial**. Scripted lifecycle replay is implemented; the
configuration-driven scheduler is absent. The existing `FillModel` uses conditional draws
and a fixed half-size partial fill, while canonical settings describe four outcome weights
and a configurable partial-size range. The new coordinator must resolve that mismatch
explicitly without changing the legacy model's interface or behavior.

Authorized new spending is $0. Work is inline under the primary owner. No network access,
provider calls, credentials, account access, production ledger, deployment, Cloud task,
subscription, or live operation is included. Default startup remains paused and fail-closed.
No risk, evidence, promotion, authorization, or elapsed-time gate may be relaxed.

Critical path: written-spec approval -> implementation plan -> validated input/sampling
adapter -> virtual scheduler and lifecycle composition -> adversarial/regression checks ->
documentation. Complete strategy outcomes, validated execution assumptions, accepted source
data/research, qualifying paper/shadow evidence, and reviewed runtime composition remain
separate work. This milestone does not make live operation eligible.

## 2. Architecture and frozen boundaries

Use small modules under `trading_bot.simulation`: `configured_models.py` for immutable
records and validation, `configured_fills.py` for probability/cost adaptation, and
`configured.py` for scheduling and composition. A private hashing helper may be isolated
if needed. Expose `simulate_configured_order(request)` only from its defining module.

Dependencies are canonical domain records, `SimulationSettings`, `CostSettings`,
`EventCursor`, `simulation.costs`, canonical content hashing, and
`replay_order_lifecycle`. Do not introduce a second settings schema or a second accounting
state machine. No dependency on broker adapters, `ExecutionService`, persistence, promotion,
runtime composition, or provider transports is allowed.

Preserve `FillModel.evaluate`, `FillRequest`, all lifecycle public contracts, `FakeBroker`,
`SimulationEngine.run`, `replay_twice`, canonical configuration, and the safety envelope.
The adapter selects outcomes itself and reuses `execution_price` and `execution_fee`;
it does not pass unconditional weights into the legacy conditional fill API. Existing
callers and legacy fill-model tests must remain unchanged. No CLI or package-level runtime
export is added. The existing event-priority enum is not repurposed as this scheduler.

Replay the growing generated lifecycle prefix from its original initial request to obtain
each current snapshot. This deliberately favors one authoritative accounting implementation
over efficiency for small trusted fixtures. There is no mutable public resume API or
duplicate balance/state update loop. A later incremental optimization is separate work.

## 3. Input and output contract

All records are frozen/slotted, exact-type checked, and revalidated at the public boundary.
Identifiers are synthetic fixture values only; inputs are not imported provider payloads.

- `ConfiguredOrderRequest`: an initial `LifecycleRequest` with an empty event tuple;
  canonical `SimulationSettings` and `CostSettings`; a nonnegative exact integer seed;
  the submission `SyntheticBarWindow`; an exact tuple of input events; a UTC `end_at`;
  and an explicit UTC `expires_at` for GOOD_FOR_DAY, otherwise `None`.
- `SyntheticBarWindow`: UTC `starts_at` and `ends_at`, with start strictly before end.
  It identifies a synthetic half-open time bucket, not an OHLC bar or verified calendar.
- `SyntheticMarketEvent`: nonempty event ID, input `EventCursor`, bar window, canonical
  `Quote`, canonical `MarketClock`, and nonnegative bounded Decimal `available_quantity`.
- `SyntheticCancelRequest`: nonempty event ID and input `EventCursor`. Its order identity
  comes exclusively from the enclosing one-order request; it cannot target another order.
- `ConfiguredDecision`: originating input/internal event ID and digest, virtual UTC time,
  disposition/reason enum, selected outcome and partial percentage when drawn, generated
  lifecycle event IDs, and the resulting lifecycle snapshot hash. No-fill and suppressed
  events are retained even when they create no lifecycle event.
- `ConfiguredOrderResult`: final `LifecycleResult`, immutable generated lifecycle-event
  and decision tuples, computed settings/input/result hashes, and fixed non-promotable
  synthetic labels. It has no accepted-research, runtime-authorization, or promotion API.

Reuse the lifecycle's equity/crypto LIMIT, long-only, single-currency, GFD/GTC constraints.
No market, stop, prediction, margin, concurrent-order, settlement, or automatic exit support
is added. Exchange lot sizes, minimum notional, and tick rounding remain unsupported;
the simulator must not claim venue-valid order construction or a pretrade risk approval.

Require both simulation evidence flags (`assumptions_validated`, `evidence_promotable`)
to be false for this fixture-only entry point. Revalidate canonical settings from their
values under the fixed exact Decimal context described below, take a private validated
copy, and compute a settings hash over both complete
settings objects. This is not a loaded-configuration hash or an attested release identity.
No environment, YAML, clock, random-global, filesystem, or network access occurs in the API.

## 4. Validation, event identity, and time

Submission time must lie within its bar window. Every market cursor time must lie within
its own window. Quote and clock observation times must equal that cursor time exactly;
their instrument/asset-class identities must match the initial order. Source/hash/timestamp
fields and all nested canonical records are validated, not trusted because of their type.
Quote source must be the literal `synthetic-configured-order-v1`. Its caller-supplied hash
is provenance only: compute the input-event digest from the complete validated payload.

Distinct windows may repeat exactly or be disjoint in chronological order, but cannot
overlap or move backward. The submission window participates in this check. Synthetic
windows may have gaps; do not infer missing liquidity, session status, or bar contents.

Unique input events must have strictly increasing sequence numbers after submission and
nondecreasing times at or after submission, in their supplied tuple order. Do not sort
malformed input into apparent validity. Exact duplicate event IDs/payloads are allowed
anywhere, including after terminal state, and yield duplicate decisions with no further
effect. A reused ID with a different payload fails the entire request. Validate and dedupe
before scheduling or sampling. A second distinct cancel request is unsupported and fails
validation, rather than silently producing another chance to fill.

`end_at` must be at or after submission and every input event. It is a simulation horizon,
not an inferred completion time. Generated actions beyond it do not run. GFD requires
`expires_at` strictly later than the submission acknowledgement time; GTC prohibits it.
Cancellation input before the scheduled submission acknowledgement is unsupported and
fails validation, even if a seeded submission would ultimately be rejected.

All timestamps are UTC. Compute latency offsets exactly from the configured integer
milliseconds; reject datetime overflow. There is no wall-clock delay or sleeping.

## 5. Deterministic outcome and cost semantics

Let R, N, F, and P denote the configured rejection, no-fill, full-fill, and partial-fill
weights, respectively; canonical validation requires their sum to be 100.

1. At the scheduled submission acknowledgement, draw once against R/100. Emit either
   BROKER_REJECTED or BROKER_ACCEPTED. Rejection never occurs again for an accepted order.
2. At each later eligible market opportunity, choose no-fill, full, or partial with
   conditional weights N/(100-R), F/(100-R), and P/(100-R), in that interval order.
   Use half-open cumulative intervals and exact comparisons, not rounded floating point.
   With R=100, rejection is certain and no fill-outcome division is reachable.
3. At the first otherwise eligible opportunity, the nominal unconditional probabilities
   therefore recover R/N/F/P. These are not observed execution rates: guards, liquidity,
   horizon length, repeated opportunities, and cancellation change realized frequencies.

For baseline settings the weights are 5/35/40/20, partial size is 10-50%, latency is
500 ms, and the cancel-race allowance is 5%. These are unvalidated synthetic assumptions,
not measured broker behavior. Read values from canonical settings; do not embed them as
logic defaults.

Sampling is keyed per purpose/event, not one mutable stream. Compute a domain-separated
SHA-256 seed from format version, operator seed, initial lifecycle inputs, submission
window, complete settings, current event digest, and purpose (`submission`, `outcome`,
`partial_size`, or `cancel_race`). Do not include the full input tuple, future market
events, end horizon, or final result hash. Construct a local `random.Random` for each key.
Bernoulli/categorical sampling uses `getrandbits(53)` divided conceptually by 2**53;
perform threshold comparisons using exact integer/rational arithmetic without Decimal
rounding or binary floats. Golden fixtures pin this versioned sampling contract.

For a chosen partial outcome, draw an integer k uniformly with `randrange(10001)`, and
set percentage = min + (max - min) * k / 10000. This gives 10,001 equally spaced points
including both configured endpoints; equal endpoints produce a constant percentage.
The grid resolution is a versioned sampler convention, not a new strategy threshold.
Requested partial quantity is the **current remaining quantity** times percentage/100.
For full outcome it is all current remaining quantity. Cap either by the event's explicit
available quantity; never increase the original order size. Record nominal and realized
outcome separately: scarce liquidity can turn a nominal full into an actual partial,
and a configured 100% partial can realize a full fill. Each unique market event offers
one incremental liquidity budget, not a cumulative depth snapshot; duplicate delivery
must not replenish it. There is no queue-position or shared-liquidity claim.

Build `SimulatedCosts` from the canonical settings: configured assumed slippage for both
supported assets; equity commission plus zero percentage fee for equity; crypto percentage
fee plus zero commission for crypto. Existing helpers calculate ask-based BUY or bid-based
SELL execution price and per-fill fee. Supplied bid/ask already express spread, so do not
apply assumed spread percentages a second time. Prediction and stress settings are hashed
but not consumed; stressed simulation is explicitly outside this milestone.

Compute partial quantities, prices, and fees under the same fixed precision-28 exact-money
policy as lifecycle accounting, with deterministic traps and preservation of the caller's
Decimal context. Reuse its internal context helper without changing its behavior. Any
inexact or invalid quantity/cost calculation fails closed; do not round cash, clamp prices,
waive fees, shrink to affordable size, or synthesize a fill to repair an invalid scenario.
Weighted-average accounting retains the lifecycle's existing documented rounding exception.

## 6. Scheduler, eligibility, and cancellation

Schedule submission acknowledgement at submitted time + configured latency. Merge generated
actions and validated input events by virtual time, then these private priorities:

| Priority | Action at an equal UTC timestamp |
| --- | --- |
| 0 | Explicit GFD expiration |
| 1 | Submission acknowledgement |
| 2 | Cancel request |
| 3 | Cancel acknowledgement |
| 4 | Market opportunity |

Input sequence breaks ties within the same priority; generated actions have unique stable
identities. Assign generated lifecycle cursors consecutively after the initial submission
sequence, independent of input sequence, while preserving processed UTC time. Thus later
input can never masquerade as an earlier acknowledgement or a same-time pre-cancel fill.

For a market opportunity, apply guards in this stable order before any outcome draw:

1. Order is accepted and active, with positive remaining quantity; otherwise record
   `submission_pending` or `order_terminal` without a lifecycle mutation.
2. Time is at or after the acknowledgement time and strictly after submission; the window
   starts at or after the submission window ends. A later sequence within the submission
   window still records `same_bar_forbidden` and cannot fill.
3. Quote freshness is explicitly true; clock is open and not halted, trading-disabled, or
   cancel-only. Each failure has its own reason. Session checks apply to both asset classes;
   never assume crypto is always open. Invalid timestamps/identity fail validation rather
   than becoming a synthetic no-fill.
4. If cancellation is pending, its one race allowance remains available as specified below.
5. Available quantity is positive, and the calculated cost-adjusted price is within the
   original limit (BUY <= limit; SELL >= limit). Otherwise record `no_liquidity` or
   `limit_price_not_executable`. Never use bar high/low, future quotes, or price clamping.

An eligible no-fill draw has no lifecycle event. A generated fill uses only the current
quote, availability, remaining quantity, and configured costs; the original lifecycle must
accept its complete prefix before the simulator publishes its decision. Insufficient cash,
overselling, invalid transition, precision loss, or any other lifecycle denial fails the
whole call without returning partially accepted results. This is not automatic resizing.

A cancel request for an accepted active order emits REQUEST_CANCEL and schedules
CANCEL_CONFIRMED at request time + the same configured latency. Draw once at that request
against `cancel_race_probability_pct`. A successful draw permits at most **one eligible
fill opportunity** while cancel-pending, in [request time, acknowledgement time); it does
not guarantee a fill. That first eligible opportunity consumes the allowance even if its
outcome draw is no-fill. Guards failing before eligibility do not consume it. Other
pending-cancel market events record a suppressed-race reason without an outcome draw.

This makes the configured percentage a race-opportunity allowance, not a measured frequency
of completed cancellation races. It is never redrawn to obtain a desired fill. No future
event is searched for a favorable execution. At zero latency the race window is empty;
at the acknowledgement timestamp cancellation wins over market events. A partial race
fill stays CANCEL_PENDING; a full race fill becomes FILLED. The pending acknowledgement
then records `already_terminal`, not a second terminal transition. Requests delivered to
terminal orders similarly produce only a decision, with no generated acknowledgement.

Expiration emits BROKER_EXPIRED only for an active accepted order, including CANCEL_PENDING.
If already terminal, record `already_terminal`. At equal time expiration wins over cancel
acknowledgement and fills. Explicit fixture expiry is not proof of a real trading session;
MarketClock opening/closing hints do not silently reschedule it. A horizon before the
acknowledgement, expiry, or complete fill is a valid nonterminal result.

## 7. Audit, causality, and failure behavior

Use namespace `synthetic-configured-order-v1` and existing canonical serialization. Hash
the complete validated settings, initial state, seed, windows, horizon, expiry, input tuple,
all no-fill/control decisions, generated lifecycle events, and final lifecycle result into
the appropriate settings/input/result hashes. Result/input hashes may change when future
inputs or duplicates are appended; prior unique generated fills and their sampling values
must not. Do not use an all-events hash as a random seed or fill ID.

Generated event IDs use a reserved simulator namespace and bind the initial inputs plus
their triggering event/purpose. Forbid caller IDs in that namespace. The duplicate registry
compares full computed payload digests, excluding tuple delivery index, before any effect.
Duplicate decisions reference
the original decision and do not replay its lifecycle events. They are represented at the
original event's virtual instant immediately after its decision, in duplicate delivery
order; retain tuple delivery index separately to avoid backdating actual state transitions.

Return fixed `source_kind=synthetic-configured-order-v1`, `assumptions_validated=false`,
and `evidence_promotable=false` with no caller override. Order-terminal status remains
distinct from flat positions and complete strategy outcomes. The existing final lifecycle
valuation remains marked at the last fill, not at the latest market event. No P&L report,
performance claim, calibrated execution rate, or evidence acceptance is produced.

Errors use stable, value-free reason enums for input, identity, ordering, duplicate conflict,
unsupported input, arithmetic, hashing, and lifecycle denial. Preserve the safe lifecycle
reason when wrapping it; suppress raw exception causes and never render arbitrary payloads.
Reject malformed data before sampling/scheduling; reject later calculation/transition errors
before returning any result. All effects are local and discarded on failure. No logging
of fixture payloads, persistence, retries, or continuation after a failed call is added.

## 8. Verification and implementation boundaries

Implement tests first, with synthetic names and small deterministic fixtures:

- Exact settings validation; booleans masquerading as integers; malformed nested records;
  unsupported assets/orders; nonempty starting scripts; unsafe evidence flags.
- Rejection 0/100 and exact interval boundaries; rejection only at submission; R=100
  denominator safety; normalized N/F/P weights; deterministic partial endpoints and caps.
- Seed reproducibility and purpose separation; duplicate insertions and future suffixes
  do not change earlier fills; input/result hashes still bind changed inputs.
- 499/500 ms baseline boundary; zero latency; later event in the same bar; next-bar boundary;
  overlapping windows; future/stale observations; every session restriction and identity.
- BUY/SELL limits after slippage; available quantity caps; equity/crypto fee mapping;
  no double spread; per-fill commission; zero liquidity; decimal-context independence;
  inexact money, insufficient cash, and unsupported rounding fail closed.
- Pending submission and early horizons; partial-to-full; no-fill; cancel allowance 0/100;
  denied/consumed allowance; no-fill consumes allowance; partial/full race; zero latency;
  equal-time priorities; expiry versus fill/cancel; nonterminal horizon reporting.
- Exact duplicate control/market delivery before and after terminal state; conflict rejection;
  generated ID uniqueness; no fee/liquidity reuse; no negative balances, fills beyond the
  original remainder, or automatic size escalation. Expected BUY inventory increases and
  SELL cash increases remain valid accounting effects.
- Lifecycle replay equivalence for the emitted script; permanently synthetic labels;
  no broker, ledger, provider, runtime, filesystem, sleeping, or global RNG calls.

After narrow tests, run Ruff, mypy, the full non-authenticated suite with branch coverage
and the unchanged 80% floor, Bandit, and offline lock consistency. A package-index dependency
audit is separate: report it unrun if network remains outside scope, not as a full security
pass. Check the legacy fill/lifecycle suites unchanged and use focused mutation checks on
duplicate suppression, same-bar/session guards, cancel timing, limit checks, and accounting.

Only new simulation modules and corresponding tests are implementation-owned initially.
Update `docs/architecture.md`, `docs/limitations.md`, and the handoff to distinguish exactly
what is implemented from remaining blockers, preserving pre-existing dirty edits. Do not
change canonical config/models, safety envelope, old fill/lifecycle contracts, broker/risk/
promotion/runtime logic, production persistence, deployment, or connected research behavior.

## 9. Acceptance and remaining limitations

Completion means a reviewed pure one-order API passes the above checks, emits replayable
accounting-consistent synthetic scripts with auditable decisions, and preserves every
existing fail-closed boundary. A passing synthetic run is not a qualifying paper cycle.

This model does not calibrate execution assumptions, validate market-data rights or quality,
reproduce queue priority, model real exchange lot/tick constraints or session calendars,
reserve cash across orders, or complete strategy-level entry/exit outcomes. Repeatedly
partial orders may remain open indefinitely; do not force terminal status at the horizon.
These limits must remain visible when this primitive is integrated in any later milestone.
