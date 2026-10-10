# Policy-managed SPY reference

`simulation.etf_capital_constrained.replay_capital_constrained` is a separate,
offline reference, not a strategy-grid candidate or unconditional buy-and-hold.
It receives original `CapitalResearchDataset` records, one configured research
capital tier, five declared instruments, a contiguous calendar schedule and the
same explicit cost and fill assumptions as the original-dataset trajectory.
Prepared sources, account balances, risk latches and callbacks are not inputs.
All qualification, execution, economic-admission and promotion flags stay false.

The frontend owns and prepares originals internally. With 200 completed bars
and positive SPY ATR, its prior-close instruction may attempt entry at the next
original opening. It has no momentum, mean-reversion or rotation predicate.
It uses the unchanged shared account/risk/sizing/execution owner, including the
research 20% position, 0.5% risk, cash-reserve and loss gates. It does not enlarge
production limits or establish a fractional brokerage route.

The original first BUY fill binds the entry session and ATR stop distance.
Subsequent ATR values cannot replace that protection. Splits reciprocally adjust
quantity and stop levels without resetting the entry clock. Opening-gap and
stop-first intraday protections remain active. The twentieth inclusive holding
session schedules an exit for the next eligible opening, even when new-entry
history is unavailable. There is no strategy regime exit or same-session
re-entry. Ending input never forces a sale, payment or settlement.

Daily reconciliation, dated weekly review, fractional terms, adverse half-side
execution friction, fee bounds, fill outcomes and T+2 are explicit assumptions.
Unknown fees and missing obligations retain existing denials. Receivables count
once in NAV but are not spendable cash. An overnight split invalidates a pending
entry based on old ATR units. Bars and model clocks are not executable quotes
or measured broker timestamps.

Distinct private policy/opening types and the
`capital-constrained-spy-trajectory-v1` identity bind these conventions, original
source, preparation, schedule and costs. Existing public strategy-owner and
trajectory types reject constrained policies; their historical preimages remain
unchanged. No second cash, risk, configuration or order-lifecycle engine exists.

The private `_replay_owned_capital_constrained` seam supports common market-only
preparation inside a future original-input comparison invocation. It checks the
source/config/calendar/day metadata and maps schedule dates into that preparation
instead of assuming the first prepared row is the account baseline. It still
constructs an independent account through the same owner. Public original-input
admission and schedule-only hash preimages are unchanged; a larger private
preparation correctly binds a different input hash, not a counterfeit old one.

This output retains all owner observations; it is not yet the aligned 630-date
economic comparison panel. Test-window attribution, exposure-matched and cash
references, operating expenses, dependent statistics, full workload validation
and the immutable economic study freeze remain separate work. Qualified,
authorized five-symbol inputs and genuine customer execution costs are not
established by this implementation or its fabricated fixtures.
