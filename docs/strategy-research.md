# Strategy research

Research uses content-addressed, point-in-time market data and completed bars only. Candidate
families include equity momentum, relative strength, regime scaling, research-only mean
reversion, and long-only crypto trend/breakout. Every attempted parameter set is retained,
including rejected attempts.

Reports bind code, configuration, data-manifest, feature, decision, order, fill, and result
hashes. Spread, slippage, commissions, exchange fees, latency, rejection, no-fill, and partial
fill assumptions are explicit. Walk-forward and purged validation, stability checks, seeded
Monte Carlo, and probability-of-backtest-overfitting evidence feed a fail-closed acceptance
gate. Research eligibility cannot activate paper, shadow, or live modes.

Backtests and simulations use recorded data and the fake broker. Paper uses simulated
execution and starts paused. No research result guarantees future performance or profit.
