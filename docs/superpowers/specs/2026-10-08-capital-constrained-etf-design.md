# Capital-constrained ETF research and paper/shadow design

Status: approved in conversation; implementation requested explicitly. This saved
artifact preserves the approved plan, not permission to trade or deploy.

## Intent and authority

Research economically credible, long-only, single-position ETF strategies for
$100–$1,000, also independently simulate $5,000/$10,000. Do not assume an edge.
Extend the existing Python/Decimal/canonical-config/accounting architecture.
Production configuration, old evidence, private originals and other plans remain
unchanged. No new subscription, spending, account change, direct broker order or
deployment is authorized. Native implementation preference is retained.

## Research contract

New policy: capital-constrained-etf-research-v1. Initial balances are exactly
100,250,500,1000,5000,10000 USD. Universe SPY,QQQ,IWM,SHY,IEF plus cash.
Current-equity planned risk is 0.5%, maximum position20%, cash floor40%, one
position, daily loss1%, existing weekly5%/drawdown10% protections. No leverage,
shorting, additions, automatic dividend reinvestment or guaranteed stop-loss claim.
Legacy fixed-dollar/live/trial limits remain production restrictions, not silently
reinterpreted as permissions granted by the research profile.

Use existing config loading and release-envelope validation. A versioned opt-in
research extension must preserve legacy exact canonical preimages and must deny
paper/shadow/live construction until separately reviewed composition exists.
Use the existing sizing implementation; instrument terms are explicit assumptions
until verified, never inferred from symbol or a connector declaration.

First output is six-balance risk/sizing and operating-cost feasibility, with no
market-data or broker transport. Real costs and unsupported routes stay unknown.
Cost sensitivities separate zero-data/zero-compute research from $12/month compute
and any actual still-active paid subscription. Sunk cost is not recurring cost.

## Data and families

Preserve native captures; add separately versioned multi-symbol Alpaca daily SIP
intake with explicit pagination, receipt/hash, session, basis, split/distribution
coverage. Free historical access must be verified; delayed/IEX cannot masquerade
as fresh consolidated order quotes. Never forward-fill executable prices.
Corrected/latest-vintage history and missing publication chronology stay explicit.

Bounded families: momentum full existing predicate with paired(5,20),(10,50),
(20,100); mean reversion WilderRSI2 at5/10 aboveSMA200, exitRSI2>=50;
volatility-adjusted rotation positive20/60-session total return divided by20-day
realized volatility, one selected ETF. Maximum holding2/5/10/20 sessions;
existing ATR protection convention initially fixed. No outcome-led expanded grid.
Regime combination follows standalone support: above SPY SMA200, training-selected
momentum in normal volatility and mean reversion when20-day volatility exceeds
its trailing252-observation median; below, positive Treasury rotation or cash.

## Validation and economics

2016–2023 is adaptive development. 2024–2025 independence is used/uncertain per
operator reply, never claimed untouched. Five126-session test folds, rolling750
training, label-overlap purge and20-session embargo. Train-only selection;
carry open positions/policy through folds without artificial resets/liquidation.
Future final test is126 eligible sessions after executable/selection freeze;
no peeking, early success, automatic extension or parameter changes.

Round-trip friction0.05/0.10/0.20/0.40 percent is split equally per side, fees
separate/once. Adverse next-open, worse opening stop gaps, adverse stop-first
ambiguous daily ranges; preserve partial/unfilled/cancel-race outcomes. Freeze
final-entry cutoff/settlement tail before outcomes; never force terminal fills.

Report actual USD P&L, net expectancy, profit factor, prior-NAV Sharpe/drawdown,
turnover, effective sample support, fold/neighbor stability, operating profit,
capital viability, SPY full/constrained and cash benchmarks, and separate tax
sensitivity/unknown tax treatment. Use dependent/selection-adjusted uncertainty.
Positive conservative expectancy, sufficient effective opportunities, at least3
positive folds, stressed drawdown<=10%, and unchanged stricter statistical gates
are required. Complete episodes alone are not independent opportunities.

## Conditional operations and verdicts

Only a surviving candidate justifies trusted single-writer paper/shadow service,
protected Robinhood integration and selected-runtime recovery. Reuse existing
journals/reservations/reconciliation; distinguish Alpaca paper, local simulation,
Robinhood assumptions and genuine measured execution. Verify fractional/dollar
route, account/settled funds, trade approval and standalone authentication.
No fabricated fractional limit or native stop support. Paused startup, fresh
quotes, ownership/fencing, kill controls, reconciliation and ambiguous-acceptance
handling remain mandatory. Actual alerts/backup restoration/restart are separate
proof. Existing paper/shadow quotas remain enforced.

Capital-specific GO/NO-GO/INSUFFICIENT/BLOCKED never enables live automatically.
No survivor => stop unnecessary acquisition/execution expansion and recommend
cash or consideration of passive allocation without promising returns.

## Verification

Fixture-first independent Decimal controls, exact-type/canonical identity,
legacy goldens, rounding/minimum/fees/cash, missing/cross-symbol data, settlement,
distributions, partial/ambiguous orders and recovery. Ruff/Mypy/pytest/Bandit,
locks/advisories/SBOM/manifests; unchanged80%overall/90%critical gates. Main owns
critical strategy/risk/execution/reconciliation/release. Preserve owned audit logs
recoverably instead of deleting them.
