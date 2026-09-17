# Strategy research

Promotion-eligible research requires content-addressed, point-in-time market data and completed bars only. Candidate
families include equity momentum, relative strength, regime scaling, research-only mean
reversion, and long-only crypto trend/breakout. Every attempted parameter set is retained,
including rejected attempts.

The local `adjust_bars` primitive requires a canonical UTC `as_of`, including for empty input.
It applies only an action for the bar's own instrument, whose announcement is known by `as_of`
and whose effective date is on or before the query's UTC date. Bars ending on or after that
effective date are not backward-adjusted. Date-only effectivity is a UTC-date convention, not
proof of an exchange-session event timestamp. Exact synthetic split and cash-dividend tests cover
these filters; they do not establish complete corporate-action history, chronological treatment
of combined split/dividend sequences, source provenance, or provider adjustment correctness.
This helper is not integrated into the connected comparison described below and does not make
that comparison eligible for promotion.

The separate `PointInTimeUniverse` primitive validates nonblank instrument IDs, exact boolean
flags, immutable record tuples, and timezone-aware UTC membership/query timestamps. Contradictory
inclusion values at the same instrument/effective/announcement key are rejected instead of being
resolved by input order. Identical duplicates and legitimate late announcements remain valid;
visibility still requires both timestamps to be at or before the query. `history_complete` is a
strictly typed caller declaration, not verified interval coverage or source provenance. This
primitive is not connected to the comparison and cannot establish accepted membership evidence.

The separate seeded fill primitive validates exact bounded finite Decimal inputs, positive order
quantities and bid/ask prices, nonnegative available quantity and costs, uncrossed quotes, exact
cursor/side/boolean/cost types, and each independent conditional probability in `[0,1]`. Invalid
request fields fail at construction before evaluation can consume randomness. Direct price and
fee helpers enforce the same boundaries and reject invalid arithmetic results; slippage cannot
produce a zero or negative execution price. Zero liquidity remains a valid no-liquidity outcome,
zero costs and equal bid/ask remain valid, and existing arithmetic and seeded outcomes are
unchanged for valid inputs. These checks reuse domain numeric bounds, not new strategy thresholds
or a second config schema. They do not establish fill calibration, latency/exit lifecycles,
provider realism, or qualifying execution outcomes, and are not a complete simulation composition.

The current connected equity comparison has one exact config-bound research candidate universe:
`SPY`, `QQQ`, `IWM`, and `DIA`. It compares only `equity_momentum` and
`equity_relative_strength`. This tuple is not an execution allowlist and does not make any symbol
eligible for an order. Momentum parameters use the configured short/long grids; relative strength
uses the configured long-window lookbacks and top-N values. Candidate identities bind those
parameters. Momentum uses the latest completed close—not the historical maximum high—for its
price-above-long-average condition.

The comparison applies signals from a completed daily close no earlier than the next bar open.
Every configured five bars, selected ETFs receive equal weights within the configured 60% gross
exposure ceiling; unselected symbols target cash. The remaining allocation starts in cash. Baseline
and two-times-stressed one-way spread, slippage, and per-order commission assumptions come from the
single canonical configuration graph. Walk-forward folds reset holdings to cash at fold
boundaries. Results include every parameter attempt, a same-period 60%-exposure SPY benchmark, and
deterministic Monte Carlo opportunity resampling.

The connected report binds the claimed image-derived code hash, exact resolved shadow configuration
and safety envelope, complete data-manifest preimage, cleaned bar snapshot, request interval,
provider declaration hash, raw-response hashes, parameter identities, stressed metrics,
walk-forward results, benchmark result, and seeded Monte Carlo result. The deployed profile now
requires a root-owned release artifact that binds the executing image ID, resolved configuration,
Compose hash, and release key before it marks code identity verified. That identity evidence does
not validate the research. The comparison does not produce feature, decision, order, fill, or
execution-result records; use purged validation; retain raw provider response bodies; or calculate
probability-of-backtest-overfitting. Those omissions are explicit blockers, not implied evidence.
Research eligibility cannot activate paper, shadow, or live modes.

Run the authenticated comparison only through the explicit one-shot profile:

```shell
docker compose --profile connected-research run --rm --no-deps connected-research
```

It uses only the locally allowlisted Robinhood read tools, writes a private content-addressed JSON
report under `/var/lib/trading-bot/evidence/research`, and appends an accepted-or-rejected
assessment to the existing evidence ledger. Robinhood describes `get_equity_historicals` as an
OHLCV read over a time range:
<https://robinhood.com/us/en/support/articles/trading-with-your-agent/>.

The current release deliberately rejects the resulting report for promotion. The fixed present-day
ETF list is not point-in-time membership evidence; the provider request proves only requested split
adjustment, not complete dividend/distribution treatment; the authenticated historical shape does
not prove a non-interpolated flag; PBO remains unavailable; multiple-testing resolution is
incomplete; configured stochastic fills and stop/target/holding exits are not yet integrated; and
both research-assumption and promotion flags remain false in the base config and release envelope.
The comparison also has no stage-independent translation from its shadow configuration identity to
the paper runtime and no end-to-end paper decision binding for one selected parameter hash.
Exploratory metrics assume complete next-open target fills. They may still be recorded when a
missing interpolation field is conservatively marked tainted, but those bars can never create
accepted evidence.

Backtests and simulations use recorded data and the fake broker. Paper uses simulated
execution and starts paused. No research result guarantees future performance or profit.
