# Private capital economic test-window accounting

This internal assembler is development-only. It is not an original-source public
study evaluator, accepted economics, an executable study freeze or a trading
capability. Source/cost/execution/economic/promotion flags remain false.

`research/etf_capital_economic_window.py` reconstructs the original action-account
prefixes with the existing reducer and validates every trajectory close against
its original observation frontier. The baseline is the first close; test dates
must be the next contiguous supplied closes. Later points are explicitly an
exit-only tail, not additional test observations. The implemented source-owned
panel enforces the frozen630-session study window. This private generic assembler
also accepts smaller windows for independent literal fixtures.

The same private assembler accepts two exact, separately typed result families:
strategy trajectories require exact strategy points; constrained-SPY results
require exact constrained points. It never converts a benchmark into counterfeit
strategy records or accepts a caller-selected family. Both use the same original
account, frontier, exposure and metric arithmetic. Strategy window preimages stay
unchanged; constrained windows have the distinct
`capital-private-constrained-economic-window-v1` namespace. This consistency seam
is not authentication of arbitrary saved results and is not a public study API.

The shared original-risk clock admission checks all observations against both
their last applied event and next unique event, including tail observations.
Reordered observations or coordinated future-prefix/account substitutions deny.
Every point must be the exact record type with a canonical UTC datetime and
bounded exact-Decimal equity. All account financial fields and completion/flags
are strictly typed before comparison with reconstructed prefixes; Python numeric
equality cannot make integers/booleans canonical financial evidence.

Cash, fees, distributions, reservations and settlement status come from the
account at the cutoff—not from the later final account. An episode settled or
fee-finalized only in the tail remains incomplete at cutoff. Completed episode
P&L is selected by completion clock; an episode opened before baseline may
include earlier economics, so it is never substituted for within-window P&L.
Cash trading P&L is available only when both endpoints are flat and complete.
Otherwise marked NAV change remains separate from unknown cash trading P&L.
Marked NAV is not an executable liquidation or a forced closing fill.

Declared recurring expense accrues elapsed UTC calendar days from baseline:
baseline zero, weekends counted once, tail excluded. Unknown expense stays
unknown; sunk research expense remains separate and does not change trading P&L.
Taxes are unknown. Fees/friction already present in original cash flows are not
subtracted again.

Shared performance metrics receive prior-positive-NAV returns, including the
baseline denominator. A nonpositive preceding NAV makes conventional return
ratios explicitly undefined, not a fabricated zero or truncated prefix. These
returns are not the fixed-initial-capital paired increments used by resampling.
Legacy Sortino is not labeled a standard target-downside-deviation estimate.
Independent opportunity support and measured spread/slippage remain unknown.

The original window's independent review found two cutoff/UTC-type validation
defects, reproduced by17 failing regressions. Corrected source2d0b7a1 completed
10,490 full and20 native tests,92.45301242056057% combined coverage and unchanged
80overall/90critical gates. These results do not certify later changed source.

The constrained-family review additionally found that tuple membership invokes
metaclass equality instead of exact identity. A watched regression confirmed
the subclass bypass; explicit `is` checks now reject it. Corrected two-window
suites64passed and related357passed. Fresh current-source global and release
gates remain necessary. Old strategy preimages are still literal-fixture bound.

The original-source-owned four-reference panel and conditional dependent
statistics are implemented/reviewed. Next: corrected-source global/native/release
verification; measure the complete workload; freeze executable identities and
criteria; admit qualified authorized inputs before one development evaluation.
No deployment, broker authorization or profitability follows from this code.
