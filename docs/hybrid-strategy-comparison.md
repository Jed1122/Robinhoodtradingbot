# Hybrid exit component comparison — 21 October 2026

Status: **illustrative development comparison, unqualified**. No strategy was
selected or promoted. This is a component study, not a complete hybrid portfolio
backtest or a forecast. It introduces no paper-duration requirement.

## Executed analysis

The existing retained Alpaca daily archives and exchange calendar were read without
modification. Their recorded receipt/manifest hashes were verified with the existing
archive reader. The already-used development window, 3 January 2023 through
6 November 2025, contains 715 sessions for SPY, QQQ, IWM, SHY and IEF. The unused
suffix was excluded. Daily bar timestamps were mapped to verified exchange-session
closes before evaluation; a completed close cannot generate a fill at that close.

Each symbol was evaluated at explicit hypothetical slippage assumptions of 5, 20
and 40 basis points per fill. Each of these 15 scenarios compared six exit models:
principal-value retention at +15%; partial reductions at +12.5% and +20%; a 5%
trailing exit; full liquidation at +15%; a 20-session holding period; and buy-and-hold.
This produced **90 model results**. Signals execute at the following available open.

Each independent scenario begins with $1,000, assumes a $0.01 fee per order and
$144/252 operating expense per observation, and reserves modeled operating costs
before buying. Tax rate is explicitly unknown; every after-tax result is therefore
unknown. No gross proceeds were relabeled as realized gain.

## Reproducibility and evidence

The execution used source revision `8b4a9d1`; the private result also records the
comparator source hash. Later integration of additional pure strategy policies
neither changes these results nor evaluates those policies.

- Preregistration receipt SHA-256:
  `894b92f2f5e9273631ef77822bb3eb3946d8ed61fbd82c4d9a8a32a3df9934ae`
- Retained exchange calendar SHA-256:
  `6b68276707b93e5d4402e991746721843f56d9d4806d61bb910df168ad66eeff`
- Complete comparison JSON SHA-256:
  `0d4f1e16c0136d81b13e97bbf7c2d3600b95a38d4cb7cd016cce34a1040d0917`

The script, complete numeric outputs and summary remain in the private local
`~/.local/share/hybrid-equity-evaluation-20261021/` directory. Raw retained market
data and derived series were not added to Git or uploaded to the service because
redistribution rights have not been established. Preserve this directory when
reviewing the component study. The comparison is reproducible against those
retained inputs; the repository does not bundle a licensed replacement dataset.

## Interpretation and limits

All 90 results have `qualified=false`. The study uses previously inspected
development data, raw prices without dividend total returns, a single fractional
full-fill allocation episode, no capital recycling, and no complete portfolio risk
or allocation simulation. Provider coverage, corporate actions, point-in-time
universe completeness and licensing remain unqualified. There is no fresh holdout,
bootstrap uncertainty analysis or multiple-comparison qualification here. Reporting
a winner from these numbers would imply evidence the experiment does not provide.

The earlier, separately completed ETF Task 5 study remains unchanged: all 174
strategy decisions lacked sufficient evidence, and its declared operating-cost
overlay rejected all modeled paths. This new exit comparison does not overturn
that finding. At $1,000, the existing $12/month host charge alone represents 14.4%
of starting capital annually, which materially raises the economic hurdle.

Next, obtain qualified permitted point-in-time inputs, freeze the complete policy
and portfolio experiment, include distributions and realistic execution/cost/tax
assumptions, and evaluate untouched chronological holdouts. If that evidence does
not justify trading over passive alternatives, report the rejection and hold cash
or present passive investment as the alternative. Live activation remains a
separate user-controlled decision after readiness; no mandatory paper wait applies.
