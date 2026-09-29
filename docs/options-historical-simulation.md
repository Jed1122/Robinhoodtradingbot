# Historical options simulation implementation status

The historical path is **partial**. This checkpoint implements pure modeled order
steps, an internal event-clock composition and an independent accounting journal,
not the complete imported-data episode,
continuing strategy/account runner or CLI.
Actual-source qualification remains blocked and no economic conclusion is available.

`StudyScenario` binds explicit latency, acknowledgement/cancel timing, rejection,
unknown-acceptance and unfilled assumptions, participation, tick slippage, cancel-race
ordering, fees and settlement delay. Calibration references are only hash inputs;
they do not certify the scenario. No calibrated defaults are supplied. Fee-bound
arithmetic uses a fixed high-precision Decimal context.

`HistoricalOrder` and `HistoricalOrderStep` model LIMIT/DAY long call/put orders
using the shared order state machine. `propose_order` labels simulated transitions;
it performs no actual broker review and is not risk admission. The later episode
owner must perform canonical risk checks before invoking it. Scenario/seed changes
are rejected after binding. Acknowledgement and fill occur on separate later
eligible events. Quotes do not prove real fills.

Both native market time and availability must strictly follow modeled acceptance.
A quote received late cannot fill the order using market liquidity observed before
or exactly at acceptance. This applies even when it otherwise follows the decision.

The proposal time must match the intent's exact upward nanosecond-to-microsecond
projection. Cancellation advances the event clock and cannot admit an older unseen
quote. Rejected/ambiguous submissions have no acceptance timestamp. When a due
cancel loses a race to a partial fill, that fill is recorded before the same-event
acknowledgement cancels the unfilled remainder; later quotes cannot keep filling it.

Fills use integer available size, explicit participation, side-aware adverse tick
slippage and the original limit price. Cancellation ordering is explicit; unknown
acceptance remains unresolved. Duplicate events within timestamp ties cannot reuse
liquidity, and an older clock cannot rewind the order. The helper returns cash-flow
effects, not settled cash. It never declares settlement complete. Multi-unit fixtures
exercise partial-fill bookkeeping only; they do not change the one-unit study limit.

The hand-accounted helper integration checks -25.50 entry and +19.50 exit cash flows,
1.00 total fees and -6.00 net. This is a hypothetical unit-payoff observation,
not an admissible account trade: the canonical feasibility helper denies it at
$100 and at $10,000. In addition to percentage limits, the unchanged $15 order
notional ceiling prevents the $25 premium at the larger tier. Increasing the
hypothetical balance does not remove that cap. Pending settlement retains the full 26.00 trial
reservation. This is not the complete episode acceptance test: it does not yet
exercise continuous event time, automatic signal/expiry exits or settled outcomes.

## Independent accounting foundation

`OptionsAccountPathState` and the closed `options-account-journal-entry-v1` facts
bind study, canonical configuration, scenario, hypothetical capital, initial time
and event-prefix hashes. Replay must start from the exact genesis and full ordered
prefix; a claimed intermediate snapshot is not a restart token. Exact duplicate
facts have no effect; conflicting identities, reordered/missing predecessors,
changed configuration/scenario and backwards clocks deny reconstruction.

The journal recomputes premium cash using price, whole units and the contract
multiplier, and separately checks scenario fees, side limits, ticks, cumulative
quantities, owned closing quantities and canonical order transitions. It does not
accept a supplied aggregate cash delta. Book cash includes unsettled flows;
`available_cash` additionally excludes positive unsettled proceeds. It is **not**
a buying-power or unencumbered-cash authorization: the execution owner must still
apply canonical reservation, portfolio, freshness and risk checks.

Full premium-plus-bounded-fees trial reservations persist until explicit completion
with flat positions, terminal known orders, modeled settlement and final fees.
Unknown outcomes cannot become reconciled fills from status labels alone. Profits,
deposits and restarts do not replenish consumed losing-episode capacity. Sizing
capital is capped at its initial hypothetical authorization and reduced by
flow-adjusted liquidation equity. Missing liquidation marks contribute zero to
the conservative arithmetic; this is not evidence of a zero-price executable exit.
Incidents and halts are retained; negative cash is automatically an incident.

This is accounting validation, **not policy admission**. Its multi-unit and $25
premium fixtures are hypothetical accounting cases, not admissible trial trades.
It does not validate mark provenance, evaluate loss-window halts, select contracts,
perform expiry monitoring or run continuous strategy decisions. No production
database or durable file format is changed. The simulated account identity prefix
does not relabel imported market data as synthetic. Real-data qualification and
economic assessment must still be established by the later episode/path consumer.

## Internal lifecycle clock

`_EpisodeClock` connects modeled order steps to the independent journal. It is an
internal component, not an alternative replay command, strategy selector, source
verifier or risk-admission API. Its supplied intents and calendar preimages need
the forthcoming historical episode owner's verification. It performs no broker
review, order call, deployment, account lookup or real settlement operation.

Known DAY expirations and explicitly modeled cancel/settlement timers advance in
chronological order. A cancel timer exactly tied to a quote uses the scenario's
race policy; an earlier timer precedes that observation. An unacknowledged order
at its deadline becomes unknown, not flat. Unknown outcomes retain reservations.
Only a flat, terminal, incident-free episode with final modeled settlement completes.
End of quotes never forces a sale, write-off, exercise or release of reservations.

Execution cash/fee deltas and order states are compared with the independent
fact-based journal projection. Multi-order observations share a bounded quantity
budget. A failed observation or timer batch rolls back all of its local mutations,
including liquidity consumption, so retry cannot retain a half-applied fill.
Exact duplicate observations are no-ops; backwards time is rejected.

Expiry assessment reuses the existing preceding-eligible-session policy. At that
session's open, the result identifies a required exit; it does **not yet generate
the strategy's closing intent**. A reached deadline records a latched incident at
the modeled deadline without flattening exposure. Missing calendars and unknown
orders cannot clear expiry readiness. Calendar binding does not certify its source.

Reconstruction uses the complete journal prefix, not a supplied balance snapshot.
Terminal/unknown orders and existing obligations can be inspected and continued;
active-order restart is deliberately rejected until a separately bound execution
cursor is implemented. No durable restart format is claimed. All result economic,
production and promotion eligibility flags remain false.

The composed -25.50/+19.50/-6.00 example remains a hypothetical accounting fixture
denied by the unchanged $15 notional cap, not a full-policy admitted trade. These
tests establish lifecycle mechanics only. A complete source-bound strategy/risk
vertical slice and an admissible small-premium example are still required.

Next: compose the reverified study, shortlist input preimage and causal stream into
the historical episode; add signal-invalidation/preceding-session expiry exits and
explicit settlement; carry exact account/trial state across episodes; independently
reconcile the journal. Costs/baselines, dependent uncertainty and private report/CLI
composition follow. No broker capability, live mode, promotion authority, production
ledger or risk limit changes are included.
