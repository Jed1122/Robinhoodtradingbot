# Offline synthetic order lifecycle

Date: 2026-09-17 (UTC)

Status: the operator approved the in-chat architectural scope and subsequently approved this
written specification. Implementation status is tracked in the companion
[implementation plan](../plans/2026-09-17-offline-order-lifecycle.md). Behavior below is a
contract, not a claim that every requirement has already been implemented.

Inspected base: `5a854edc18ccc0415f6254f5a8c3d3cf9aa34aa2`, branch
`codex/continue-implementation-from-commit-7c4dcd1`. Earlier provider-neutral documentation
and shutdown-test changes are present locally and are not part of this specification's commit.

## 1. Outcome and authority

Implement a deterministic, in-memory replay of one synthetic order from submission-pending
through scripted acceptance or rejection, partial and complete fills, cancellation, and
expiration. Each accepted event produces a coherent order, position, cash balance, and fee
total. This is an order-accounting primitive, not a complete strategy cycle or an exchange
execution model.

The affected simulation subsystem is **partial**: the repository already contains a
stateless fill calculator and a decision-cycle runner, but neither maintains this lifecycle.
The existing pure order state machine and partial-fill accounting helper are dependencies,
not replacements to be redesigned.

Authorized new spending is $0. This milestone needs no subscription, network request,
broker capability, credential, account access, production ledger, deployment, or Cloud task.
Implementation remains inline under the primary owner. No live authorization, promotion
evidence, accepted research, or qualifying paper/shadow observation can be created here.
The default service remains paused and unable to submit orders.

Dependency chain: approve this written specification -> implementation plan -> deterministic
record validation and replay -> accounting and event-identity tests -> regression verification
and documentation. This advances one prerequisite for later complete simulated outcomes;
source acceptance, realistic execution assumptions, research acceptance, and reviewed runtime
composition remain separate blockers on the path to qualifying paper/shadow cycles.

## 2. Chosen architecture and limits

Use a separate module under `trading_bot.simulation`, with explicit dependencies on canonical
domain records, `domain.order_state_machine.transition`, `execution.partial_fills.apply_fill`,
`simulation.events.EventCursor`, and the existing canonical content-hash utility. There is no
dependency on broker implementations, execution-service placement capabilities, persistence,
promotion, runtime startup, or provider transports.

Do not extend `FakeBroker` or change `SimulationEngine.run`, `FillModel.evaluate`, or the
existing `replay_twice` helper. Their current interfaces and semantics stay frozen. In
particular, do not reinterpret configured probabilities, change the existing partial-fill
fraction, or treat the current event-priority enum as an implemented event scheduler.

The initial component handles one account, one instrument, and one order per replay. It
accepts long-only equity or crypto LIMIT orders with GOOD_FOR_DAY or GOOD_TIL_CANCELED time
in force. Other asset classes, market/stop orders, and immediate-or-cancel orders are rejected
as unsupported. Expiration is an explicit scripted event, not an invented session calendar.
Empty or nonterminal scripts are permitted and reported as nonterminal, never as complete
strategy outcomes. Multiple concurrent orders, cash reservation, settlement, margin, exchange
quantity/tick metadata, corporate actions, and position-level exit policies are out of scope.

Scripted fills supply price, quantity, and fee explicitly. The component does not choose
prices, generate orders, judge strategy eligibility, or represent a risk approval. A starting
SUBMISSION_PENDING record is a fixture boundary only; no preliminary/final risk evidence or
provider submission is fabricated to reach it. All cash, price, fee, and position values in
one request use the same synthetic quote currency; foreign-exchange conversion is unsupported.

## 3. Proposed records and API

Expose a synchronous pure entry point, `replay_order_lifecycle(request)`, returning a frozen
`LifecycleResult`. Every call starts from the request's initial records; it does not reuse
mutable engine state. Do not add CLI commands, file readers/writers, resume snapshots, or
package-level exports to the existing runtime composition.

Use frozen, slotted records with exact-type validation:

- `LifecycleRequest`: initial canonical `BrokerOrder`, canonical `Position`, initial cash,
  submission `EventCursor`, and an exact tuple of scripted events.
- `LifecycleControlEvent`: nonempty event ID, cursor, account/instrument/broker-order identity,
  and one supported canonical `OrderEvent`.
- `LifecycleFillEvent`: nonempty event ID, cursor, and a canonical `Fill`. The fill identifies
  its account, instrument, broker order, and side. Its timestamp must equal the cursor time.
- `LifecycleSnapshot`: current order, position, cash, accumulated fees, remaining quantity,
  last applied cursor, and a computed snapshot hash. It is output, not an accepted resume input.
- `LifecycleReceipt`: event ID, computed event digest, applied/duplicate disposition, stable
  reason code, and resulting snapshot hash.
- `LifecycleResult`: final snapshot, ordered immutable receipt tuple, a derived
  `order_terminal` boolean, a computed result hash, and fixed synthetic/non-promotable labels.

Validate exact canonical record types, finite bounded Decimal values, UTC timestamps,
nonempty identities, exact tuples, and exact enum types before processing. Reuse existing
validators and Decimal rendering rather than creating a competing domain/config schema.
Do not accept booleans as sequence integers or floats as monetary inputs.

The initial order must be SUBMISSION_PENDING with zero filled quantity. Its creation and
update timestamps equal the submission cursor timestamp. Its account and instrument must
match the initial position. Cash and position quantity are nonnegative; a positive position
requires a positive average price, and a flat position requires no average price and zero
market value. Position observation cannot be later than submission. Validate all monetary
fields, including optional prices when present, against the existing bounded-Decimal rules.
No initial applied-ID registry, fee total, or completed order may be supplied to skip history.

## 4. Event identity, ordering, and transitions

Process the supplied tuple in its given order; do not sort a malformed script into validity.
All duplicate registries are private to one replay, initialized empty, and derived from
successfully applied events. Bind digests to a versioned synthetic namespace, the exact
initial order identity, and every field of the event envelope and payload.

For each event:

1. Validate its shape and identity against the request, and compute its canonical digest.
2. Check event-ID and fill-ID registries before current-state, cursor, or remaining-quantity
   checks. An exact repeat of an applied event is an economic no-op, even after completion.
   It appends a duplicate receipt but cannot change the snapshot or last applied cursor.
3. The same event ID with any different envelope/payload is a conflict. Reusing a fill ID
   under a different event ID is also a conflict, even with otherwise identical fill fields.
   This first version requires one stable event envelope per execution; it does not infer
   whether a newly identified report is a retransmission. Conflicts fail closed.
4. A new event requires a sequence strictly greater than the last applied sequence and a
   UTC timestamp no earlier than the last applied timestamp. No automatic buffering or
   reordering is allowed. All fills must occur strictly after submission time as well as
   after its sequence; control events may share a timestamp when their sequences increase.
5. Resolve the canonical next state, validate accounting, construct and validate all new
   records and hashes, then accept the event. Only then register its event/fill IDs.

Supported control events are BROKER_ACCEPTED, BROKER_REJECTED, REQUEST_CANCEL,
CANCEL_CONFIRMED, and BROKER_EXPIRED. Every transition goes through the existing domain
transition function; no parallel transition table or new state is introduced. In particular,
BROKER_REJECTED is valid only while submission is pending. Ambiguity, cancel rejection,
reconciliation drift, and reconciliation-resolution events are unsupported and rejected;
this component must not pretend to resolve unknown order state.

A fill event derives PARTIAL_FILL or FILL from cumulative quantity, not a caller-selected
status. Cumulative filled quantity must never exceed requested quantity. Requesting a cancel
does not cancel the order; only a later valid CANCEL_CONFIRMED event does so. A partial fill
while CANCEL_PENDING leaves the order CANCEL_PENDING, and a full fill moves it to FILLED,
exactly as the existing state machine specifies. A new cancel confirmation after FILLED is
invalid, while a byte-equivalent canonical duplicate of an already-applied event is a no-op.
New events never reopen FILLED, CANCELED, REJECTED, or EXPIRED orders.

## 5. Accounting and atomicity

Before calling `apply_fill`, bind fill/order/position account and instrument, broker-order ID,
and fill/order side. Reject short-position creation and quantities above the outstanding
remainder. A BUY fill price cannot exceed the order limit; a SELL fill price cannot be below
it. Limit compliance is an input-consistency check, not a simulated price-discovery policy.

Use the existing helper for position updates and fill deltas, with duplicate handling owned
by the lifecycle wrapper. The helper currently checks excess quantity before its own ID-only
duplicate check and does not enforce every cross-record identity. Do not assume those checks
provide this wrapper's stronger contract, and do not broaden this milestone into a general
execution-helper rewrite. New safety checks belong at the new lifecycle boundary.

For a BUY, cash decreases by executed quantity times fill price plus the supplied fee. For a
SELL, cash increases by executed quantity times fill price minus the supplied fee. Accumulate
fees exactly once per distinct execution. Reject any event that would leave negative cash or
position quantity. These are synthetic accounting consistency checks, not replacements for
the canonical pretrade risk engine, cash-reserve limits, or loss policies.

Use a fresh local Decimal context with precision 28, ROUND_HALF_EVEN, Emin=-999999,
Emax=999999, clamp=0, and cleared flags. Trap InvalidOperation, DivisionByZero, Overflow,
and Underflow in both calculation phases; all other traps are off except Inexact in the
exact-accounting phase. Never inherit caller precision, rounding, flags, or traps.
Before invoking the helper, compute and require exact quantity, remainder, gross notional,
cash, fee-total, and mark-value operations in that context, trapping Inexact, overflow,
underflow, invalid operations, and division by zero. Inputs whose exact accounting exceeds
that supported precision fail without effects rather than being silently rounded. Precision
28 is this version's arithmetic-format contract, not a strategy or risk threshold.

Weighted-average price follows the existing helper formula under that same fixed context;
rounding is allowed for this derived average only. Its returned average must remain positive
for a nonzero position, and None for a closed position. Validate helper deltas and exact
quantity/mark fields against the checked calculations before accepting its result. Fees remain
separate from average price. Do not describe the rounded average as an exact realized-cost
ledger, compute realized/unrealized P&L, or manufacture equity/buying-power attestations.

Preserve the helper's mark-at-last-fill convention for position market value, and label it as
such in documentation; it is not a fresh market valuation. Control events update order state
and order timestamp but do not change position quantity, cash, fees, or position observation
time. Remaining quantity always means requested minus actually filled, including the unfilled
remainder of a canceled or expired order; it does not imply an active order.

Construct candidate records, monetary totals, and receipts locally. A failure at any stage
returns no successful result and cannot mutate the original request, its records, a previous
result, a registry in another run, a file, or a ledger. Do not expose an incremental mutation
API or partially successful result on error in this version.

## 6. Provenance and replay results

Reuse `market_data.recording.content_hash` and its canonical Decimal/UTC encoding. Add an
explicit `synthetic-order-lifecycle-v1` domain tag and record-kind tag to each hash preimage.
Never hash a record containing the hash being computed. Caller-provided source hashes on
synthetic inputs are preserved as input provenance, not trusted as event identities.

The initial snapshot digest binds all starting records and the submission cursor. Each
event digest binds that initial digest as well as its full validated envelope and payload;
updated order and fill-updated position data hashes identify the applied event. Subsequent
snapshot hashes bind the initial digest, current records, all balances, remaining quantity,
last applied cursor, and the ordered digests of applied events. A control event leaves the
position's earlier data hash intact. A duplicate does not change any snapshot field or hash.

The result hash binds the version tag, initial snapshot digest, final snapshot digest, and
all ordered receipts. Thus inserting a duplicate changes the receipt history/result hash,
but not the economic snapshot hash. Repeating the exact full request from fresh state gives
identical records, receipts, and hashes, regardless of wall-clock time or ambient Decimal
context. No random values, UUID generation, system clock, or broker access is needed.

`order_terminal` is true only for FILLED, CANCELED, REJECTED, or EXPIRED. It does not mean
the position is flat, all strategy outcomes are complete, or promotion requirements are met.
Results have fixed `source_kind="synthetic-order-lifecycle-v1"` and
`evidence_promotable=False`; callers cannot supply these labels or enable promotion.
Hashes prove deterministic internal consistency only, not authenticated execution or data.

## 7. Errors and prohibited side effects

Use a lifecycle-specific validation error with fixed, enumerated reason codes for unsupported
input, identity mismatch, duplicate conflict, invalid ordering, invalid transition, invalid
accounting, and invalid hashable data. Messages must not render supplied identities, records,
payloads, object representations, or chained external error text. Wrap known domain and
Decimal failures with a safe reason and no raw exception chain. Do not swallow unexpected
programming defects as successful or partial results.

No retry, repair, size adjustment, replacement order, inferred cancellation, automatic
expiration, liquidation, or reconciliation is attempted after an error. No new config keys,
dependencies, production schema, risk thresholds, or allowed execution modes are introduced.
Synthetic labels are an explicit usage contract, not proof that arbitrary caller inputs are
synthetic; fixtures and callers must never contain real account or provider data.

## 8. Acceptance and verification

Use deterministic synthetic fixtures and independent expected values, not expectations
computed by the same production helper under test. Required coverage includes:

- acceptance then one full fill; multiple partial fills then completion; submission rejection;
  cancellation before a fill; partial fill then cancellation; expiration after a partial fill;
  partial and full fills racing a pending cancellation;
- BUY and SELL cash/fee/position calculations, closure of a position, nonterminating average
  division, insufficient cash, shorting, overfill, and out-of-limit fill rejection;
- exact duplicates before and after terminal completion, conflict variants for every identity
  and economic field, reused fill ID under a new event ID, and proof that duplicate receipts
  cannot change balances, applied cursor, snapshot hashes, or subsequent valid processing;
- stale/equal sequences, backward timestamps, same-submission-time fills, and timestamp/payload
  mismatch; no state reopening, acceptance replay with a new ID, or post-submission rejection;
- strict type/UTC/Decimal validation, missing average-price state, oversized arithmetic,
  unsupported order/event types, and safe error messages that do not echo sentinel secrets;
- replay from a fresh initial request twice, altered ambient Decimal contexts, and a changed
  input producing appropriately different provenance; immutable inputs after every rejection;
- empty and unfinished scripts honestly returning nonterminal results, and terminal orders
  with remaining positions never becoming strategy-complete or promotable evidence.

Start with new lifecycle unit/contract tests, then existing simulation, partial-fill,
order-state-machine, execution, replay, and documentation tests. Follow with the repository
baseline: Ruff, mypy, full non-authenticated Pytest with branch coverage and the unchanged
80% floor, Bandit, and lock consistency. Record skipped/external checks explicitly; this
design commit does not claim implementation tests, fresh full-suite results, or remote CI.

## 9. Intended implementation paths and completion boundary

Keep models/validation, pure replay orchestration, and hash encoding in small modules such as
`src/trading_bot/simulation/lifecycle_models.py`, `lifecycle.py`, and `lifecycle_codec.py`.
Their detailed file split is an implementation-plan choice, not three competing abstractions.
Add focused tests under `tests/unit/simulation/`; update `docs/architecture.md`,
`docs/limitations.md`, and the orchestration handoff when implementation status actually changes.
Existing state-machine transitions, shared accounting-helper semantics, broker interfaces,
runtime composition, strategy/risk code, configuration, and promotion stores remain unchanged.

Completion means the isolated lifecycle contract is implemented and locally verified, with
accurate limitations and a reviewed diff. It does not mean the bot is ready for live trading.
Connecting stochastic fills, modeling latency/liquidity/session behavior, producing complete
strategy outcomes, accepting real data, or wiring qualifying paper observations requires
separate follow-on designs. Do not push, merge, deploy, or contact a provider as part of this
specification or its local implementation.
