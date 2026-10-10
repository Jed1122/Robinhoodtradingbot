# Original-event capital path economics

`evaluate_capital_path_economics` replays one original `CapitalTrajectoryRequest`;
it accepts no supplied balances, results, trade counts, returns or support claims.
The new versioned report is permanently development-only, source/cost unqualified,
execution-disabled, economically unadmitted and nonpromotable.

The same v3 account-prefix reducer reconstructs unique applied events. Cash P&L
already includes assumed fill friction, fees and paid distributions, so reporting
does not deduct these twice. Only actually filled BUY episodes reaching explicit
settlement/payment/final-fee completion contribute finalized episode P&L. Duplicate
deliveries cannot increase turnover, fees, dividends or completed episode counts.
Unfilled requests are not trades. Shares, unsettled sales, receivables and final
cash remain visible independently of financial completion.

Final trading P&L and operating profit are unavailable for incomplete or held
accounts. Daily marked P&L remains a separate diagnostic, not executable liquidation
or proof of complete exit costs. A receivable enters NAV once, never buying power.
Recurring USD/day costs accrue over inclusive UTC calendar dates, including
weekends. Sunk research expense is reported separately and is not charged again
against operating profit. Actual tax treatment remains unknown.

Performance metrics reuse the shared Decimal implementation. They use net NAV
after recurring accrual and returns divided by preceding NAV, not fixed-capital
paired P&L fractions. Any nonpositive preceding net NAV makes all volatility,
Sharpe and Sortino ratios unavailable, without truncating the series. Financial
sums retain the shared exact context; descriptive ratios/performance use fixed
64-digit arithmetic. All derived outputs must satisfy existing Decimal bounds.

Episode expectancy is finalized trading USD before operating-cost allocation.
Turnover is total unique fill notional divided by initial capital. Close occupancy
and exposure are explicitly labeled daily proxies, not continuous execution
measurements. Spread/slippage components remain unknown because assumed friction
is embedded in prices. Independent opportunity support remains structurally
unknown: completed episodes and bootstrap draws cannot pass the support gate.

This adapter is not the full capital evaluator. Complete benchmark composition,
the aligned comparison family and dependent selection-aware uncertainty,
fold/neighbor reports, full workload/resource verification, executable freeze and
qualified authorized inputs remain required. No real study, broker/paper/shadow
qualification, deployed recovery, live permission or profitability follows.
