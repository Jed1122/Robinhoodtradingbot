# Capital research account boundary

Status: funding primitive and bounded synthetic account reconstruction implemented;
integrated review/release pending. The complete risk/corporate-action/recovery
composition and economic evaluator are **not implemented**.

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

The new `replay_capital_account` recomputes one cash account from at most4096
original typed events, never from caller-declared balances or reservations.
Orders use a research-only instrument namespace and the existing lifecycle
transition/fill accounting. It denies additions, overlapping active orders,
oversells, account/basis changes, conflicting duplicates, stale events and
unsupported symbols. Explicit sale-fill settlement and matching whole-episode
fee finality are necessary to release obligations. Pending, partial and terminal
incomplete histories remain incomplete; input end never forces a fill.

Thirty-six synthetic controls include independent cash expectations and a
separate-process reconstruction of partial, sold-unsettled and completed prefixes.
This is not durable checkpoint restoration or deployed recovery: those controls
reconstruct supplied fixtures, not a production store or broker observations.
The reducer has no canonical entry-approval or cost/source-qualified verdict.
It is not directly consumable by an execution service. Hashes are structural,
not authentication. All execution/promotion flags remain permanently false.

Finish exact-source integrated verification/review. Then compose canonical sizing,
current-equity loss latches, explicit marks, split basis/distribution entitlements
and versioned bounded checkpoints with this account reconstruction.
Only then compose the approved three strategy families and purged walk-forward
economic evaluator. Source acceptance, actual costs, prospective final testing,
trusted paper/shadow and deployed recovery remain separate unfinished stages.
Production limits/defaults are unchanged; live remains disabled.
