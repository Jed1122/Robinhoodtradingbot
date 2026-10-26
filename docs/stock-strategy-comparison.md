# Stock strategy evaluation: first price-only result

The frozen 50/200 daily trend rule did **not** establish an investment advantage
in the first study. It underperformed holding the same eight stocks and the
passive benchmarks at every modeled cost. All sixteen primary paired intervals
include zero. This first result does not justify activating that strategy.

This is a retrospective, dimensionless **price-only** cost ablation. It excludes
dividends, taxes, interest, actual spreads, broker fills and operating expenses.
It is not the full Task 5 economic/portfolio evaluation or an after-tax return
forecast. Independent numerical acceptance passed 2,000,489 checks with zero
failures, covering all targets, trace paths, 112 metric windows, nine training
grids and all 48 paired intervals. A reference-only final pending-target
convention error was corrected against the prospective protocol; its original
failed audit is preserved. Production code, outcomes and parameters did not change.

## Frozen experiment

The eight members are AXP, AAPL, BAC, CVX, KO, KHC, MCO and OXY, selected from the
original retained 2023Q4 institutional disclosure. SPY is a benchmark only. The
frame is a disclosed subset, not the full market. It becomes decision-eligible
on February 15, 2024; earlier prices serve warmup only. All nine original series
retain 706 sessions from January 2, 2024 through October 23, 2026.

The strict rule is close>SMA200 and SMA50>SMA200. The first possible execution is
October 17, 2024, after the October 16 signal. Signals execute at next-session
opens. Training ends September 30, 2025; the 268-session holdout runs October 1,
2025 through October 23, 2026. Holdings and pending targets cross the boundary
without a reset or liquidation. The terminal close incurs one declared exit
cost. The final signal is not executed.

Initial panel NAV is the mean of eight independently funded equal initial
sleeves. The exposure control uses prior-close target weights and NAV, then
trades SPY at the next open; it does not claim equal realized next-open exposure.
The cost convention is a NAV-allocation haircut, not actual broker notional fees.
The 75/15/10 dollar portfolio remains a separate study.

This ablation also does not apply production position caps, drawdown suspension,
liquidity/earnings eligibility or broker approvals. Its simulated holdings are
not eligible order proposals.

## Observed holdout price returns

These are cumulative holdout percentages after modeled transaction haircuts,
not annualized returns. Round-trip scenarios charge half the stated bps per leg.

| Round-trip cost | Trend 50/200 | Same stocks buy/hold | SPY buy/hold | 90% same stocks / 10% cash | Causal exposure SPY |
|---:|---:|---:|---:|---:|---:|
| 10 bps | 7.72% | 18.71% | 14.02% | 16.85% | 6.19% |
| 25 bps | 7.03% | 18.62% | 13.94% | 16.77% | 5.57% |
| 50 bps | 5.89% | 18.47% | 13.79% | 16.63% | 4.55% |
| 100 bps | 3.68% | 18.18% | 13.51% | 16.36% | 2.56% |

At 10 bps, trend holdout maximum segment drawdown is 5.26%, compared with 6.62%
for the same-stock buy/hold and 9.13% for SPY. Its inherited drawdown is 10.98%,
which includes the earlier high watermark. Lower drawdown alone does not establish
superior risk-adjusted performance. Training trend returns range from -6.45% to
-8.15% across the declared cost scenarios.

## Uncertainty and interpretation

The paired circular moving-block bootstrap uses seed 20261026, 5,000 replicates,
primary block length 20, and a sixteen-comparison Bonferroni adjustment. All sixteen
primary intervals for mean daily log-return differences include zero. The trend's
small observed advantage over the causal exposure control is therefore not
credible evidence of an incremental advantage in this sample.

All runs warn that the adjusted tail probability has fewer than ten expected
replicate observations. The 60-session sensitivity also has fewer than ten
effective blocks; two intervals for underperformance exclude zero in that
sensitivity, without establishing outperformance. The 5-session sensitivity is
also retained. These limitations must remain visible; changing block length or
parameters after observing results cannot create qualification.

The nine training-only SMA neighbors were evaluated without selecting a winner
or changing the holdout rule. This experiment does not settle the behavior of
other strategy families or establish durable performance across regimes.

## Reproducibility and completion boundary

Code commit: `86f35b21f6b26c5f0527dbc535529fbd2d9c470f`.

- Original input manifest: `07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3`.
- Protocol: `067ccbd11b9748db4202c15e2f08941ff8cf9065aff5bfc1d20706843b2fe419`.
- Actual native process: exit 0; source inventory unchanged before/after.
- Native terminal receipt: `a6b30cc0bafcbf402f8c61254238c3f72513ebeb9c325a190faac3b125e08bb7`.
- Summary: `8baa4fdc38916961929da05b6681b670b63dec8497ce7a0e46e64ce181a2e0cd.summary.json`.
- Study component result: `0fbee385994bb3ae199fe9c79bc8a5fd9c8f9d5df2a1a31e22bf47d273189f36`.
- Independent price-only acceptance: `9debaaa265ff9286858c7431340c73e9b51a05f77e3b7c05f89cc635c65290ac`.

The complete retained stock/shared suite at that source revision exited 0:
12,758 passed, no failures/skips, 35 SQLite resource warnings, one Starlette
deprecation warning, and 91.53% combined
line/branch coverage. The unchanged critical/stock-host coverage gate exited 0.
Native regression receipt:
`5d282970fe3f75a2e69eca107bbc5d2c3c8bbb90e7af3e53962f3497720acc77`.
All 338 new focused cases passed on Python 3.12 and 3.14. Repository Ruff and
strict mypy (468 source files) passed; expanded Bandit exited 0 with annotation
warnings retained. These checks are software evidence, not economic qualification.

Private originals, complete compressed traces and exact metrics remain in the
operator's evidence directory. No raw licensed source observations are published
here. See [the command guide](stock-price-study.md) and frozen design for replay.

The remaining required work includes source-admitted monetary cash flows,
75/15/10 allocation, tax lots/reserves, repeated exits and reinvestment, the other
strategy families, publication-aware factors/events/revision vintages, total-return
controls, cost/stress/walk-forward analysis and the full requirement audit. A
negative or insufficient-edge conclusion is valid; missing required comparisons
remain incomplete. Live execution is disabled and was not exercised.
