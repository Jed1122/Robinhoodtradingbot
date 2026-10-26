# Modeled operating costs

`research.stock_operating_costs` applies a frozen, labeled budget to the same
paused account used by the dividend book. It performs no billing operation or
money transfer. Amounts and due timestamps are explicit modeling assumptions;
the module does not claim to observe hosting, data or model spending.

`ModeledOperatingCostPlan` binds a label and ordered, unique
`ModeledOperatingCharge` records. A known amount is a nonnegative USD Decimal;
`None` means unknown. Changing the complete plan after a payment fails fresh
history validation. Paid charges must form an ordered prefix of that plan.

`apply_stock_operating_costs` pays known due charges once, oldest first, using
settled cash after order and tax reserves. It records an operating-expense action
in the existing book. It preserves lots, fills, settlement claims, gains,
execution fees, taxes and safety state. Exact rational verification prevents a
rounded cash balance from recording a payment that was never debited.

An unknown or unaffordable due charge pauses later payments. Known unpaid costs
remain liabilities and reduce net economic equity. Unknown due amounts make
that equity unavailable and leave no investable cash. Future charges are not
already incurred. An explicitly modeled zero-cost sensitivity is distinct from
missing costs. This module creates no billing calendar or production scheduler.

Gross marked equity already reflects paid cash debits.
`net_equity_after_operating_costs` subtracts only unpaid liabilities, preventing
double counting. Its result can be negative when liabilities exceed assets;
this never creates cash or margin. Tax estimates remain separate, and these
costs are not automatically tax deductions.

Fictional tests and independent review cover chronology, repeat/restart behavior,
reserved cash, unpaid amounts, precision and retained dividend/account history.
The optional kernel integration accepts the frozen plan only at
`begin_stock_economic_replay`. It applies due costs from activated session 200,
after legitimate credits/settlements and before pending orders, and again at the
close. Pre-activation charges reject. Unknown or nonpositive after-cost net equity
blocks purchases while eligible existing risk exits remain available.

Every explicit plan, including a zero-cost sensitivity, uses the same pre-open
loss observation phase. Closed high-watermark references are not updated
intraday, and the existing sticky loss thresholds remain unchanged. Paying a cost
can therefore suspend new tactical entries. Nonpositive gross equity fails with
an explicit depletion error instead of inventing a positive account value.

Cost mode returns a separate immutable report of phase-level gross/net values,
payments and liabilities. Each phase summary binds to an owned zero-cash ledger
entry. Revalidation derives payment and liability history from the frozen plan
and ledger, then checks the complete phase payload against that entry. Altered
summaries cannot hide an unknown cost, rewrite paid totals or erase an unpaid
future plan after its first recorded phase.

The absent-plan path preserves old result/snapshot/
protocol shapes and evidence hashes. Actual economic comparisons and operating-
cost qualification remain separate. All investment and live-execution flags
remain disabled.
