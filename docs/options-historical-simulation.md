# Historical options simulation implementation status

The historical path is **partial**. This checkpoint implements pure modeled order
steps, not the complete imported-data episode, continuing account runner or CLI.
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

Next: compose the reverified study, shortlist input preimage and causal stream into
the historical episode; add signal-invalidation/preceding-session expiry exits and
explicit settlement; carry exact account/trial state across episodes; independently
reconcile the journal. Costs/baselines, dependent uncertainty and private report/CLI
composition follow. No broker capability, live mode, promotion authority, production
ledger or risk limit changes are included.
