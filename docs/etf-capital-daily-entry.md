# Synthetic next-open capital entry adapter

`simulate_capital_daily_entry` is a bounded research-assumption adapter, not the
full daily strategy/economic runner. It consumes canonical research config,
all original v3 account facts and risk observations, declared instrument terms,
decision/open/lifecycle clocks and explicit hypothetical fill proportions.
It reconstructs account/risk state and uses the existing entry/sizing gate.
It never consumes saved caller balances, risk latches or a cached sizing result.

Half the declared whole-percent round-trip friction is applied adversely at
entry, then price rounds up to the declared tick. Full episode fees remain
reserved; entry fees are charged once. Rejected, unfilled and partial outcomes
are explicit. No implicit cancellation, settlement, fee finality or terminal
sale is manufactured. Incomplete existing obligations deny another entry.

The declared decision must precede the open; the last original-state observation
must bind the current input frontier at that open. The shared lifecycle requires
strictly ordered timestamps, so acceptance/fill cursors are supplied explicitly,
strictly increasing and on the same declared UTC date. They are synthetic
assumptions, not measured latency, market-session proof or causal order timing.
Marks based on the supplied opening value are assumptions, not fresh quotes.

Internal LIMIT-shaped records are synthetic lifecycle carriers only. They do
not establish a supported fractional/dollar broker order route. Decision/source
hashes bind declarations, not authenticated strategy or provider evidence.
Source/cost/execution/economic/promotion markers remain false. No credential,
transport, live OrderIntent factory or production risk change is included.

Next: integrate reviewed exact-source verification, then compose actual candidate
signals/ATR protection/exits and original actions/settlements in the daily owner.
Train-only selection, policy carryover, complete-grid performance, uncertainty,
executable study freeze and genuine economic evaluation remain unfinished.
