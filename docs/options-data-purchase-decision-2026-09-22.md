# Options research data and capital decision

Recorded 2026-09-22 UTC against implementation commit
`24472cc0aa67aac85ce23de815a1faa2ed0a8030`.
Scope: public vendor comparison, acquisition requirements and offline capital checks.
This is not a purchase, a validated strategy, or live authorization.

## Decision

Continue the **Databento credits-first, narrow-scope research path**. The user's
willingness to pay $40/month adds a fallback budget preference, not authorization
for a higher-priced package, renewal, terms acceptance or brokerage transfer.
Do not increase the trading balance to build or test software: hypothetical research
balances already work without deposits. Do not repurchase the acquired definitions.

The [existing scope](options-data-budget-scope.md) records option-only estimates of
$29.66 for Q1 2023 and $48.78 for January–May 2023. These are alternative engineering
pilots, not multi-year validation. Neither estimate nor the earlier $113.57 credit
balance was refreshed here. Underlying and other inputs remain unpriced; these are
not complete budgets or charge caps. The prior $12 definitions authorization does
not authorize quote purchases.

## ThetaData comparison

Official public pages checked 2026-09-22. Monthly retail inputs exclude unverified
taxes and other applicable charges.

| Candidate | Advertised monthly subtotal | Limitation |
| --- | ---: | --- |
| Options Value | $40 | Minute options history; matching stock entitlement is not established as included. |
| Options Value + Stocks Value | $70 | $40 + $30; stock pricing says 15-minute intervals, but subscription documentation says one minute. |
| Options Value + Stocks Standard | $120 | $40 + $80; stock pricing advertises one-minute intervals. Coverage, rights and total charges still need confirmation. |

Source: [pricing](https://www.thetadata.net/pricing), including the Stocks tab.
The independent public audit exposed the underlying-data add-on and discrepancy;
the coordinator retained both rather than describing $40 as an all-in package.
No credentials or licensed data were shared with the audit.

The [subscription table](https://thetadata.net/docs/Articles/Getting-Started/Subscriptions.html)
lists Options Value minute history from 2020 and Stocks Value minute history from
2021; option marketing instead advertises four years. Free stock EOD is described
as one year, insufficient for 2023–2025 plus warmup. Account entitlements and actual
session completeness remain unverified. The existing [Alpaca review](alpaca-data-access-review.md)
also records unresolved paper-account feed/retention questions; no free consolidated
source is silently substituted here.

[Option quote documentation](https://thetadata.net/docs/operations/option_history_quote.html)
describes interval samples with timestamp, bid/ask, sizes and contract identity.
Samples do not establish the intervening path, queue position or fills. A separate
original quote-event timestamp is not established by the published row contract;
do not invent freshness from interval labels or equate its semantics to CBBO-1m.

[Terms](https://www.thetadata.net/terms-and-conditions), sections 2.1, 12 and 13.4,
leave product-specific questions about automation, archives and post-cancellation
reuse. Other product agreements may control. This is unresolved suitability, not a
finding that all API research is prohibited. Section 14 specifies renewal and
generally nonrefundable subscriptions. Do not assume one paid month grants perpetual
dataset use.

## Required acquisition inputs

These are fixed input requirements, **not a completed executable contract shortlist**.
No new strategy thresholds or risk configuration are introduced.

| Input | Required scope |
| --- | --- |
| Instrument scope | SPY underlying; standard-deliverable long calls/puts for the first directional hypothesis. No adjusted options, shorts, spreads or other tickers in this proposal. |
| Option observations | Point-in-time bid/ask, sizes, quality fields, contract identity, timestamps, availability/timezone/interval semantics and coverage gaps. Zero bids remain observations, not automatic entry permission. |
| Underlying history | Daily observations preceding decisions with sufficient 20/100 warmup and longer applicable research history; matching timestamped observations for selection, marking and exits. Identify venue/consolidation and raw versus adjusted prices. Bars are not executable quotes. |
| Contract/session enrichment | Reuse definitions; verify multiplier, deliverable, exercise/settlement attributes, holidays, early closes and last-trading deadlines. Native receive time and expiration alone are insufficient. |
| Corporate events | Dividends/actions with announcement, availability and effective dates; no future adjustments in earlier decisions. |
| Execution inputs | Bounded fees and explicit next-event/conservative fill assumptions. Quotes alone cannot prove execution, exercise or settlement. |
| Provenance | Private immutable manifests, exact hashes/Decimal values, provider schema and known gaps. Raw licensed data stays outside Git and Cloud tasks. |

The candidate 2023–2025 interval is not proof that all gates can be satisfied. Retain
the 3,650-calendar-day exploratory history request, 750 minimum history bars, five
folds, 50 test bars per fold and 30 independent opportunities wherever applicable.
Do not lower gates to fit a provider tier. Holdout outcomes remain unexamined.

Exact-symbol cost estimation now works, but a causal shortlist still requires
underlying inputs and a preregistered expiry/strike/tie/missing-data rule. The existing
20/100 implementation produces direction, not contract selection. Do not estimate
invented example contracts and call that the real study price.

The earlier [underlying estimate](options-readiness-2026-09-22.md) uses EQUS.MINI
beginning March 28, 2023: it misses January pilot entries and warmup and does not
establish consolidated NBBO. Small cost is not complete coverage. Pilot follow-through
also depends on a separately frozen holding/expiry horizon; preserve incomplete
obligations rather than inventing end-of-input liquidation or settlement.

## Fresh capital checks, no deposits

The existing offline command used unchanged configuration hash
`c742c2ffc44bc850c08a8560080c3b2b0ca65394fd5bebbd177167fbf1b9197b`.
Both examples use multiplier 100 and a hypothetical $1 round-trip fee reserve,
not current prices or verified brokerage fees.

| Hypothetical input | Observed necessary-filter result |
| --- | --- |
| $0.10 premium: $10 premium + $1 reserve = $11 risk | Zero units at tested $100/$500/$1,000 tiers; one at tested $2,500 through $50,000 tiers. Not final pretrade approval or recommended deposits. |
| $0.25 premium: $25 premium + $1 reserve = $26 risk | Zero units at every tested tier through $50,000; the retained $15 order-notional cap independently blocks this contract. |
| $40/month for twelve continuous months | $480, or 480% of hypothetical $100 capital and 19.2% of $2,500. Subscription-only cost ratios, not expected returns or all-in break-even estimates. |
| $70/month for twelve continuous months | $840, or 840% of $100 and 33.6% of $2,500. Excludes hosting, taxes and other costs; duration is not selected. |

All outputs retain `live_authorized=false`, `production_eligible=false` and
`ECONOMIC_NO_GO`. At the $100 capital assumption, the 0.5% per-trade budget is $0.50.
The $150 live equity ceiling and non-replenishing $50 trial-loss ceiling are unchanged.
Adding money may exceed that envelope; it does not validate a strategy.

Reproduce from the repository root in a verified local Python environment:

```sh
PYTHONPATH=src python -m trading_bot.cli.options_research capital-feasibility --premium 0.10 --annual-operating-cost 480
PYTHONPATH=src python -m trading_bot.cli.options_research capital-feasibility --premium 0.25 --annual-operating-cost 840
```

## ThetaData clarification draft

Not sent; no account created or subscription activated:

> For private personal automated historical research on SPY options at another
> broker, does Options Value include matching stock history? I need 2023–2025
> expired-option minute bid/ask, matching underlying observations and daily SPY
> warmup before 2023. Stocks Value pricing says 15-minute intervals while the
> subscription table says one minute: which applies, and what is the complete
> monthly price? Please identify the product terms allowing automated API use,
> private storage/backups and derived results, including reuse after cancellation.
> Also clarify quote timestamp timezone, original event-time availability and
> historical session gaps. This inquiry does not authorize an upgrade or charge.

This is a new-vendor question, not another request for a Databento OPRA agreement.
The existing Databento personal-use/retention attestation remains accepted as an
attestation; provider access controls must still be respected.

## Remaining boundary

Resolve/price the complete underlying inputs and freeze the causal selector, then
prepare one deduplicated manifest with separate costs, quote times, fresh credits
and an explicit acquisition maximum. Purchase requires concrete authorization.
Source checks and genuine historical experiments follow acquisition; an engineering
pilot cannot be relabeled final economic validation.

Completed here: public comparison, two offline capital commands, and 20 passing
existing risk/CLI tests (`test_options_economics.py`, `test_options_research_cli.py`).
This was documentation-only; the full suite was not rerun. Not completed: a complete
priced dataset, selector, acquisition, genuine return testing or runtime verification.
No spending, credential access, broker calls, deployment or risk-limit changes occurred.
