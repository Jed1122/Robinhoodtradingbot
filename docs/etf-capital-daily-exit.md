# Synthetic capital exit and protection adapters

`simulate_capital_daily_exit` reconstructs the complete supplied original v3
account/action/risk tape. It cannot accept caller cash, quantity, basis, fee
reserves or loss latches. The current observation must consume the entire tape.
Purpose-aware canonical loss decisions permit compatible risk-reducing exits
without granting entry permission. Drawdown/kill and unknown-state denials are
not bypassed; unresolved active orders still deny a second order.

SELL price is a declared base price minus half the whole-percent roundtrip
friction, rounded down to the declared price tick. Shared lifecycle/accounting
charges the explicit side fee once and preserves episode fee reserves. Full,
partial, rejected and unfilled outcomes are explicit. Sale settlement, payment,
cancellation and episode-bound fee finality are never generated implicitly.
Split-adjusted quantity/basis come from original actions, not rewritten orders.

`select_capital_protection` provides only the adverse price convention: worse
opening stop gap, conservative target-gap price, and stop-first ambiguous daily
ranges. Omitting a range means opening-only facts. Levels, ranges and source
hashes are declarations, not qualified source data or derived ATR policy.

The internal LIMIT carrier, fractional disposal and supplied clocks are research
assumptions, not verified brokerage capabilities or measured timing. A full exit
uses all original held shares, including declared split-adjusted dust; this does
not establish an executable broker route. All source/cost/execution/economic/
promotion flags remain false. No credentials, transport or live order factory.

The complete candidate scheduler, ATR/hold/regime policy owner, cross-fold
selection/carryover, workload/statistical evaluation and economic study remain
unfinished. Local fixtures and release checks cannot establish profitability,
genuine customer costs, paper/shadow readiness or deployed recovery.
