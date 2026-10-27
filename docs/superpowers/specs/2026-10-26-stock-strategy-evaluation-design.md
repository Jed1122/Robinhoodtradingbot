# Task 5: stock strategy and portfolio evaluation

> Scope update: the later human instruction prioritizes current company research,
> long-term stock selection and one-to-two-calendar-month tactical decisions.
> The exhaustive historical evaluation below is preserved as deferred research;
> demonstrated profitability is no longer a first-release requirement. The
> [current stock investing design](2026-10-26-current-stock-investing-design.md)
> governs new implementation. Existing results and qualification limits are
> unchanged; live authorization and essential risk controls remain separate.

## First-release scope decision

The user selected the lean first-release scope: prioritize scheduled individual
stock research, evidence-backed selection and controlled execution. Elaborate
operational drills, extra backup destinations and dashboard expansion are
deferred. Essential authentication, restricted account identity, deterministic
risk limits, reconciliation, kill switch and truthful strategy validation remain
required. This approval does not activate live trading or change the scope of
the quantitative evaluation already underway.

## Objective and completion boundary

Implement and actually evaluate the individual-stock strategies, portfolio rules,
profit-taking and reinvestment hypotheses against passive alternatives with
chronological validation, realistic costs, distributions, tax assumptions and
uncertainty. A negative or insufficient-edge conclusion is valid. A completed
price-only probe, synthetic test suite or source-gap inventory alone is not the
complete Task 5 deliverable. Required inputs/comparisons must either be genuinely
evaluated or remain explicitly incomplete; do not redefine completion around a
smaller available subset. Live activation, deployment and a mandatory paper wait
are outside this task. No trading or account actions are authorized.

Preserve the original seven strategy families: cross-sectional momentum, trend,
breakout, quality momentum, selective mean reversion, PEAD and earnings revisions.
Preserve passive/quality long-term and hybrid portfolio comparisons, principal
retention, partial profit-taking and trailing exits, fixed/time/volatility exits,
and capital recycling. Economic qualification requires the relevant actual input
evidence; unavailable families do not become successful strategies.

## Existing evidence and architecture

Reuse the accepted Task 4 original-13F eight-stock frame, SPY benchmark and nine
706-session original raw/split series, manifest `07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3`.
Reuse its first daily 50/200 hypothesis, cost grid and dates without optimizing
on results. The failed twelve-slot source probe remains separate. The first
handoff admits only chronological price research and price-only cost ablation.
New source evidence may admit broader uses; it must not silently promote the
old observations or repair native missing fields.

Build three boundaries in the existing Python package, with no new service:

1. Pure normalized-price traces, policy targets, metrics and paired uncertainty.
2. A source-bound offline study adapter and durable result/report command.
3. Monetary portfolio replay using existing lot/execution/tax/settlement modules
   only after economic-input admission. Never fabricate a USD Quote, spread,
   tradability or calendar fact to force a legacy simulation wrapper to accept data.

The actual trend rule is in `hybrid_policies.evaluate_policies`; the similarly
named descriptive strategy score uses 20 sessions and is not interchangeable.
Existing `compare_returns` remains compatible. Its per-transition NAV haircut
is an experimental cost convention, distinct from actual execution-notional fees.
Generic dataset snapshots that force receipt time to equal historical request end
are unsuitable: keep collection clocks and reconstructed study timestamps separate.

## Frozen first-probe protocol, before results

- Members: AXP, AAPL, BAC, CVX, KO, KHC, MCO, OXY; SPY benchmark only. All slots
  remain in denominators. No replacement or successful-download subset.
- Full history January 2, 2024–October 23, 2026. Pre-disclosure prices supply
  warmup only; membership decisions are unavailable before February 15, 2024.
- First complete 200-session signal: October 16, 2024, execute October 17 open.
  Entry: close>SMA200 and SMA50>SMA200; equality fails. Exit when condition fails.
  All signals use prefixes and execute at the next regular-session open.
- One continuous run. Training ends September 30, 2025; final holdout begins
  October 1 and ends October 23, 2026. Carry holdings, cash, costs and pending
  targets across the cut. Do not reset flat or liquidate at the training boundary.
- First-probe initial NAV is one dimensionless unit per trace. The panel is the
  arithmetic mean of eight independently funded equal initial sleeves, with no
  cross-sleeve transfers/rebalancing. This is not a dollar portfolio or the
  investor's 75/15/10 allocation; that requires the monetary replay below.
- Comparisons: same-cohort buy/hold, SPY buy/hold, passive 90% cohort/10% constant
  cash, and a causal prior-close target-exposure SPY control. All passive entries
  start at the same first eligible next open, with the same per-leg cost scenario.
- At close t, control target is sum(target_i[t]*sleeve_NAV_i[t])/sum(sleeve_NAV_i[t]).
  This is known at t and executes on t+1; it matches prior-close target exposure,
  not the unknowable next-open realized dollar exposure. Mutating future prices
  must not change earlier control targets.
- Round-trip scenarios 10/25/50/100 bps correspond to 5/12.5/25/50 per leg. The
  binary entry/exit trace exactly preserves `(1-c)` NAV haircuts of the existing
  comparator. A flat round trip is `(1-c)^2`, not `1-2c`.
- Fractional control rebalancing uses cost=c*abs(target*preopen_NAV-current_stock_value),
  then allocates the remaining NAV between target stock and cash. Record both
  the cost basis for this approximation and the actual normalized turnover; do
  not call it broker notional fees. Cash return is zero by explicit convention.
- Final signal is unexecuted. Terminal liquidation at the last retained close is
  a predeclared horizon convention, charged once and independently of that signal.
- Metrics use daily simple returns, annualization 252, risk-free convention zero,
  sample standard deviation, and Sortino downside RMS relative to zero over ALL
  returns. Undefined ratios remain undefined. Report segment drawdown separately
  from inherited high-watermark drawdown. No trade win rate without defined trades.
- Training-only sensitivity: fast40/50/60 crossed with slow180/200/220. Preserve
  baseline50/200 for holdout; no winning-neighbor selection. These are hypotheses,
  not established optimal thresholds.
- Paired circular moving-block bootstrap: seed20261026,5,000 replicates, primary
  block20 sessions, sensitivity blocks5/60. Shared draws across compared columns
  retain cross-stock dependence. Resample paired realized daily log-return
  differences (strategy log NAV change minus control log NAV change); reported
  path metrics above continue to use simple returns. Intervals estimate the mean
  daily log difference, not excess CAGR or the chance of future outperformance.
  Do not pretend to rerun the strategy on synthetic prices. Primary family:4costs x4references;
  use Bonferroni-adjusted two-sided intervals and explicitly report sample limits.
  No bootstrap result can override missing economic data or enable promotion.

## Full evaluation workstreams

Source admission must separately bind dated currency/security identity, original
cash distribution amounts, declaration/ex/pay dates, complete pagination, split
and merger semantics, original filing periods/units/public availability, earnings
events and estimate vintages where needed. Current values cannot enter past
decisions. Latest-retrieved retrospective price reconstruction is allowed with
revision/lifecycle limits disclosed; original realtime receipts are not required
for every historical price. Financial report-period filters are not publication
filters. Unpaid entitled distributions are receivables, not deployable cash.

Monetary replay starts with simulated $1,000, uses separately configured equity/
cash sleeves75/15/10 and the existing hard risk limits. Reuse actual lot basis,
realized gain versus proceeds, taxes as labeled scenarios, settlement/reservation,
fractional/minimum-order constraints and one-time tactical exit rungs. Compare all
three profit-taking models with buy/hold, fixed holding/target, volatility/time
and rebalance controls over repeated entries and capital recycling. Test gaps,
cost/slippage stress, drawdown suspensions, regimes and benchmark exposure.

For each family/model report dataset eligibility, valid train/test windows,
walk-forward/sensitivity/stress coverage, returns/risk/turnover/holding periods,
sector/beta/concentration, tax/trading/operating-cost drag, uncertainty and multiple
comparison limits. Disclose insufficient histories and unavailable inputs. Freeze
new subprotocols before their outcomes are inspected; do not reuse a final holdout
for optimization. No fabricated study values or synthetic-to-actual relabeling.

## Deliverables and safety

Deliver executable source ingestion/admission, source-independent execution and
statistical tests, reproducible study commands, durable actual run/exit receipts,
machine-readable traces and source-bound reports, a strategy/exit/portfolio
comparison, economic acceptance or documented no-go, limitations and a complete
requirement audit. Local tests establish behavior; actual source/run artifacts
establish empirical findings. Keep all investment/promotion/live flags disabled
until separately qualified and authorized. Never place/review/cancel a broker
order, read an account or credentials, change a subscription or deploy here.
