# Focused SPY-plus-cash research pilot

Date: 2026-09-30. Status: **written specification approved by the operator**.
This is a new research identity, not an implemented strategy, economic result,
options replacement, account allocation, or permission to trade.

### Explicit operator amendment — 2026-10-01

The operator waived original publication/correction-timeline evidence for this
research study and directed completion with existing access without further setup
questions. The research path may therefore use immutable latest-vintage history,
with verified retrieval receipts and an explicit later-correction/look-ahead
limitation. Original-version availability must not be fabricated. This amendment
supersedes only the original-timeline prerequisite below. Executable data coverage,
cost/calibration, risk, economic and paper/shadow criteria remain independent.
Latest-vintage exploratory results remain non-promotable. No live order or
production deployment is authorized by this amendment.

### Explicit operator amendment — 2026-10-05

The operator authorized continuing the Alpaca-only build without historical
halt/LULD and gap coverage. Those roles are no longer prerequisites for this
exploratory latest-vintage study. Missing controls/gaps remain unobserved; do not
fabricate OPEN messages, sequence continuity, market completeness or executions
inside unavailable intervals. Preserve the fixed strategy, risk/exit policy,
quote validity/freshness, cash accounting, cost uncertainty and holdout boundaries.

This changes the research evidence contract, not forward/paper/live safety controls
or promotion eligibility. A separately versioned exploratory source/replay
composition is required; sealed qualified-source factories and historical
diagnostic identities stay unchanged. Waived-coverage results are non-promotable,
not point-in-time execution validation or expected live performance. Remaining
price/action/size, execution-cost, economic and runtime prerequisites are not waived.
No additional provider, purchase, deployment or real-money order is authorized.

## 1. Approved intent and scope

The operator chose to prioritize an ETF research pilot and approved this design
brief: one unleveraged SPY position or cash; the existing fixed 20/100-day momentum
signal without parameter optimization; historical after-cost comparison with
buy-and-hold and cash; separate hypothetical $500/$1,000 reports; unchanged
risk/trial limits and live blocks. The objective is to determine whether this
smaller path warrants further development, not to establish a preferred answer.

Preserve all options work and historical evidence. Do not edit the existing
SPY/QQQ/IWM/DIA comparison into a one-symbol run or reuse its research identity.
Do not add a new provider, buy data, change credentials, deploy, or activate a
broker runtime as part of implementing this specification.

Alternatives considered: the existing four-ETF parameter grid requires more data
and multiple-testing controls; broker-native recurring investing avoids a custom
signal system but answers a different question. The approved one-ETF pilot is the
smallest custom research path, not proof of higher profitability or faster live use.

## 2. Architecture and immutable study identity

Extend the existing canonical configuration/release-envelope graph with a named
research-only study profile. Reuse Decimal/domain validation, source manifests,
feature pipeline, momentum predicate, economic risk functions, event lifecycle,
ledger accounting and report integrity where their contracts fit. Never relax the
synthetic replay's source restriction or label its fixtures as real data.

Separate components: source qualification and storage; session/action-aware data
assembly; fixed strategy; risk-constrained intent construction; historical
execution and account reconciliation; benchmark/uncertainty analysis; private
reporting. Strategy code cannot receive a broker transport. The coordinator owns
causal time, sizing, risk, restart state and final integrated review.

Before reading strategy outcomes, freeze a manifest binding code/config hashes,
instrument identity, requested dates, source versions/rights evidence, availability
rules, cost schedules, candidate/exit policy, splits and reporting assumptions.
Each modification creates a new study identity and retains prior attempts.

Requested history is `[2016-01-01, 2026-01-01)` in UTC, using the applicable US
equity sessions, including explicitly evidenced closures. This supplies more than
the unchanged 3,650 calendar days only if complete coverage is established. Use
at least 750 observed daily bars before an evaluated segment. Reserve calendar
years 2024–2025 as the untouched final holdout; development/validation uses earlier
eligible observations. Insufficient coverage denies the study; do not shorten the
window or inspect the holdout to choose a replacement. Earlier material exposure
to those outcomes must be declared; an exposed holdout cannot be called untouched.

## 3. Fixed candidate and risk behavior

Use `FeaturePipeline(short_window=20, long_window=100)` and `MomentumStrategy`
with the most recent 100 eligible completed daily bars. Its predicate requires
positive return across that slice, the 20-day average above the 100-day average,
and latest close above the 100-day average. It is not simply a crossover rule.

Evaluate entry/deselection every five eligible sessions, anchored to the first
eligible evaluation session. One SPY position and one outstanding entry only;
no adding to a position, leverage, shorting, options or other instruments.
Use the existing portfolio-aware exit behavior: initial ATR-based stop, configured
reward target, maximum holding duration, and enabled regime/deselection exits.
HOLD in the strategy API alone is not a universal liquidation instruction. Freeze
entry policy; do not widen a stop or fabricate a fill after a trigger. Evaluate
protective conditions at every qualifying price event, not only rebalancing dates.

Retain canonical percentages and absolute limits, the $1,000 inclusive account
ceiling, one-position/one-new-position-per-session trial restriction, and the
$50 non-replenishing cumulative trial-loss boundary. Enforce the stricter applicable
cash/exposure constraints; the pilot must not inherit a looser legacy equity
default merely by changing asset class. Express any stricter research profile in
the one canonical graph, never a parallel risk loader.

The $500/$1,000 reports are hypothetical starting cash, not current balances or
increased authorization. Primary policy-feasibility runs retain the $100 risk-equity
reference and existing order/gross caps. At current base limits those include
$15 per order and $60 gross; tighter micro limits remain distinct. A deposit cannot
raise sizing authority. Infeasible sizing is a zero-entry result, not an exception.
Equity gap losses can exceed stop-based risk; reserve notional cash and apply full
exposure/stress checks. Profitable episodes and deposits do not replenish trial loss.

## 4. Data qualification before genuine results

Require licensed/permitted, immutable original responses and provider/schema/version
identities; source and receipt timestamps; original publication/correction handling;
exchange/session identity; instrument/ticker continuity; raw unadjusted price basis;
complete distributions/splits and their point-in-time revisions; complete interval
coverage distinguishing closed/no-trade/missing/degraded periods. Deny unknowns and
interpolation. A requested adjustment flag is not verified adjustment history.

Keep raw archives and financial source evidence outside Git, logs and Cloud agents.
Bulk history remains in existing partitioned Parquet/DuckDB infrastructure rather
than the transactional ledger. Hash-bound qualification must be role- and era-specific.

Daily bars can support features and an explicitly exploratory benchmark screen;
they cannot establish fills, intraday stop ordering or liquidity. Genuine event
results require timestamped bid/ask, sizes and control/gap/session observations
through entry, monitoring, cancellation, exit and settlement. Never substitute
one venue's quote for NBBO or reuse a quote after reset/staleness.

Current facts do not pass this gate: existing SPY XNAS bars start in May 2018 and
have unresolved publication/degraded-day issues. An Alpaca support reply dated
September 21, inspected September 30, denies historical SIP entitlement for this
paper-only account and identifies itself as AI-generated. It describes personal
retention within entitlements and corporate-action history from April 2020; it
does not establish a complete 2016–2025 package. No source is selected by this spec.
IEX may only be considered under a separately reviewed scope; never silently swap it
into a SIP study. No new agreement, subscription or cash spending is authorized.

## 5. Causal execution, cash flows and restart

Signals use only records whose completion and proven availability precede the
decision. Order submission and fills occur on later eligible events after latency;
never the signal bar's close or a retrospectively selected favorable price. Keep
exact source ordinal/nanosecond ordering and recorded control events.

Apply conservative/base/optimistic fill scenarios with explicit calibration status.
Uncalibrated assumptions never pass the economic acceptance gate. A buy cannot
fill below the contemporaneous admissible ask merely because a future bar traded
there; a sell uses executable bid information. Account for displayed capacity,
fractional increment/minimum/order-type restrictions, rejected/unfilled orders,
partial fills, pending cancels and cancel-race fills. Unknown state retains reserves
and blocks retries. Do not force liquidation at end-of-input or fold boundaries.

Reconcile cash, shares, fees, distributions, reservations and settlement after each
event. Apply distributions once to eligible held shares and credit cash when payable;
do not both total-return-adjust prices and separately credit the same dividend.
Corporate-action price normalization for features must use only then-visible facts.
Use conservative executable marks; open/unresolved episodes remain incomplete.

Persist study/run/event identities, intent-before-simulation, immutable cash-flow
events, reservations, loss consumption and cursors in the existing ledger framework.
Restart verifies all identities, restores paused state, reconstructs accounting,
rejects duplicate/conflicting or out-of-order events, and reconciles before another
decision. No automatic promotion or provider transport is constructed.

## 6. Benchmarks, costs, uncertainty and honest verdicts

Report candidate, cash and SPY buy-and-hold on identical evaluation dates. The primary
buy-and-hold comparison uses the same permitted exposure/cash constraints; a fully
invested reference is separately labeled and is not authorized capital deployment.
Record actual implementability/constraint breaches of each benchmark, not just returns.

Use effective-date commissions/regulatory fees, observed spreads, calibrated extra
slippage/latency, distribution cash flows and itemized operating/data/model/server
costs. Count spread/slippage exactly once when embedded in simulated fill prices.
Fund expenses already embedded in price/returns are not deducted twice. Separate
trading P&L from operating profit and capital-feasibility results. Use a zero-yield
cash scenario and separately sourced attainable cash-rate benchmark; do not assume
the account earns a Treasury or sweep yield without evidence.

Retain five purged walk-forward folds, at least 50 test bars per fold, embargo at
least the configured minimum and the full overlap horizon, at least 30 independent
opportunities, and all existing drawdown/fold/concentration/benchmark thresholds.
Use seeded, preregistered dependent-outcome block resampling, 1,000 draws and 95%
intervals for after-cost expectancy/excess return; insufficient effective sample
size or intervals not supporting positive net excess produce NO-GO.

No parameter search or winner selection occurs in this pilot. Existing required
parameter-stability/multiple-testing gates must remain explicitly unmet where this
single-candidate design cannot evaluate them. Any follow-on robustness study needs
its own preregistration before access to its untouched tests. Do not fabricate
neighbor results or disable `assess_research` checks to approve the fixed candidate.

Each report separates data qualification, engineering correctness, economic
acceptance, broker/runtime capability and operator authority. Synthetic, partial,
unqualified or exploratory runs are permanently non-promotable. Insufficient
evidence is `ECONOMIC_NO_GO` with specific reasons, never a selected winner.

## 7. Verification and progression

Test first with independent exact expectations: source substitution/revisions and
missing coverage; action/distribution accounting; DST and closures; future bars and
quotes; signal timing; next-event/partial/cancel races; cost attribution; cash/share
conservation; risk/trial exhaustion; restart and duplicate events; incomplete exits;
benchmark alignment; dependent resampling; holdout contamination; synthetic rejection.
Preserve 80% overall coverage and 90% branch coverage for critical modules, then run
Ruff, Mypy, full supported-Python regression, Bandit, locked audits and manifest checks.

Only independently accepted research can proceed to qualifying paper outcomes and
shadow observations. Preserve the existing 100 eligible paper cycles and seven
distinct UTC shadow dates; accelerated fixtures cannot create them. Normal-live
has additional unchanged requirements. Current interactive broker reads do not
verify unattended authentication, write semantics, operational recovery or renewal.
No live-mode change or order follows from approving this research specification.

## 8. Handoff

Review this written specification before the implementation plan. The plan should
first establish study/config identity and source qualification, then causal risk/
execution/account replay, then benchmarks/uncertainty and private reports. Source
acquisition, genuine data sufficiency, paper/shadow duration and broker/runtime proof
must remain explicit dependencies, not promised completion dates.
