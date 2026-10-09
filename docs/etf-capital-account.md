# Capital research account boundary

Status: first funding primitive implemented; integrated review/release pending.
The complete capital-aware account/replay owner is **not implemented**.

`simulation.etf_capital_funding.capital_order_reservation` validates original
broker-neutral LIMIT order records and explicit bounded whole-episode fee facts.
It reserves remaining BUY limit notional for pending, partial, cancel-pending and
unknown/reconciling orders. A terminal order releases only unfilled notional.
Unused episode fees remain reserved until explicit finality and flat holdings.
An active SELL cannot request more remaining shares than the supplied holdings;
it does not consume BUY notional. Input identity includes the complete order,
fee bound/charged fees/finality and held quantity even for equal reservations.

`capital_available_cash` subtracts explicit unsettled sale proceeds and one
current reservation from total economic cash. Insufficient or invalid balances
deny rather than clamp to zero. These are fixed-context Decimal calculations;
they are not a second risk engine, configuration loader or trading authority.

Literal fabricated example:100 initial cash,0.2-share limit100 and0.10 episode
fee bound reserve20.10. A0.1-share fill at99 with0.04 fee leaves90.06 cash and
10.06 reservation,80.00 available. Confirmed cancellation releases10 unfilled
notional but retains0.06 episode fees, leaving90.00 available. A0.1-share sale
at101 with0.05 fee yields100.11 economic cash,10.05 unsettled proceeds and0.01
unused fee capacity:90.05 available. After explicit settlement and final fees,
100.11 is available. Fees total0.09 and net profit0.11 in this fixture only.
No real fill, fee or settlement has been observed or asserted here.

The output is informational, with permanently false execution/promotion flags.
Its hash is not authenticated account evidence. A future authoritative owner
must recompute it from validated current events, never adopt a caller's declared
reservation. This function does not validate account-wide completeness,
instrument increments, live capability, strategy selection, market sessions,
freshness, cash floors, loss limits, cancellation ownership or settlement source.
Those independent checks remain necessary; no order factory is introduced.

## Next steps

Finish integrated verification/review. Then implement one bounded versioned
capital account owner using shared sizing, lifecycle transitions/fill accounting
and canonical loss rules. Preserve partial/rejected/unfilled/uncertain orders,
explicit settlement and final fees, split basis/distribution entitlements,
single-position limits, event deduplication and restart-equivalent prefixes.
Only then compose the approved three strategy families and purged walk-forward
economic evaluator. Source acceptance, actual costs, prospective final testing,
trusted paper/shadow and deployed recovery remain separate unfinished stages.
Production limits/defaults are unchanged; live remains disabled.
