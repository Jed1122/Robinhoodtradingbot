# Lean ETF cost and sizing feasibility

Date: October 7, 2026. This is a current-policy diagnostic, not an economic
strategy result, order approval, current account-balance verification or live
authorization. No subscription, funding, risk configuration or broker state changed.

## Result

The existing native whole-share route admits **zero SPY shares** under both
hypothetical capital tiers and both base/micro cap profiles. The saved native
bar reader reverified retrieval receipts and source hashes. All 2,012 retained
pre-2024 development observations have every OHLC price above the applicable
$15/$5 order cap. This necessary notional test needs no signal outcome, assumed
fill or holdout price. The 502 remaining records were counted, not evaluated.

The diagnostic's disposition is
`NATIVE_WHOLE_SHARE_SIZING_NO_GO_FRACTIONAL_ROUTE_UNVERIFIED`. It does not reject
the momentum hypothesis on statistical grounds: the strategy's edge has not
been evaluated. More whole-history quotes cannot resolve the sizing mismatch.

## Unchanged canonical limits

| Constraint | $500 hypothetical cash | $1,000 hypothetical cash |
|---|---:|---:|
| Authorized reference used by the existing ETF research profile | $100 | $100 |
| Stop-risk budget before episode fees | $0.50 | $0.50 |
| Base initial order/position ceiling | $15 | $15 |
| Micro initial order ceiling | $5 | $5 |
| Base gross ceiling | $60 | $60 |
| Micro gross ceiling | $20 | $20 |
| Non-replenishing trial-loss boundary | $50 | $50 |
| Native whole-share feasible quantity on retained development inputs | 0 | 0 |

These follow from `configs/base.yaml`, `configs/micro_live.yaml`, the release
envelope and the fixed reference in `research/etf_study.py`. The separate $1,000
account ceiling does not enlarge risk authority. One held SPY position cannot
be repeatedly topped up to use the larger gross ceiling: position and no-add
restrictions still apply.

The shared sizing function uses the stricter of stop-risk and notional limits,
then rounds down to the instrument increment. ETF account admission additionally
requires stop risk **plus** bounded episode fees within $0.50, settled entry cash,
the stricter 80% unencumbered-cash rule, and reservation of entry notional plus fees
against remaining trial capacity. Generic sizing alone is not account admission.
Fee-sensitive sizing may be denied by the account owner even when generic sizing
allows it; this diagnostic did not silently resize or repair that behavior.

## Fractional arithmetic is feasible only under assumptions

Independent literal expectations were checked against the real shared sizing
function at both capital tiers. The inputs below are fabricated: $500/share,
$10/share stop distance, 0.001-share increment/minimum, $1 minimum notional,
fractional eligibility, clean settled cash and a $0.10 episode-fee reserve.

| Profile | Hypothetical quantity | Notional | Stop risk plus assumed fees |
|---|---:|---:|---:|
| Base | 0.030 | $15 | $0.40 |
| Micro | 0.010 | $5 | $0.20 |

The existing integer-only path returns zero for the same fabricated prices.
These calculations demonstrate only numerical feasibility. They do not prove
actual SPY metadata, fee bounds, account eligibility or standalone broker behavior.

The current Codex-session equity review declaration permits fractional quantities
only for market orders during regular hours, with eligible accounts and at most
six decimal places. Dollar orders are also market-only. This is session evidence,
not standalone runtime authentication or native fractional stop/limit protection.
A monitored exit is not a guaranteed stop price. Preserve those limitations when
designing any supported fractional owner; do not relax the integer native reader.
Robinhood publicly describes fractional stock/ETF trading from $1, but public
product availability does not verify this account or execution composition.
[Robinhood fractional-share information](https://robinhood.com/us/en/support/articles/fractional-shares/).

## Recurring cost hurdle

Alpaca currently lists Basic as free and Algo Trader Plus as $99/month. Historical
SIP queries ending at least 15 minutes ago are documented as available without
the subscription. Basic live IEX is one venue, not consolidated SIP/NBBO; a delayed
historical quote cannot be substituted at order time. Basic entitlement and a
fresh supported low-cost execution quote route remain unverified here.
[Alpaca plans](https://docs.alpaca.markets/us/docs/about-market-data-api),
[Alpaca historical-feed FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

| Monthly data scenario | Monthly compute assumption | Annual fixed hurdle | Hurdle / $500 | Hurdle / $1,000 |
|---|---|---:|---:|---:|
| $99 | $0 | $1,188 | 237.6% | 118.8% |
| $99 | $12 | $1,332 | 266.4% | 133.2% |
| $0 | $0 | $0 | 0% | 0% |
| $0 | $12 | $144 | 28.8% | 14.4% |

The $12 compute figure is a scenario, not a reconciled current invoice. Zero
compute is a lower-bound incremental-cost scenario, not a free qualified runtime.
Electricity, hardware, alerting and other costs remain unknown, not zero. Already
incurred research expense is separate from recurring operating expense and was
not inspected or reconciled during this diagnostic.

The first row alone is 7,920% of the $15 initial base allocation or 23,760% of
the $5 initial micro allocation annually. These are arithmetic hurdles, not
forecast returns or impossibility proofs. Increasing cash without increasing
authorized sizing does not make those expenses easier for this strategy to earn.

## Verification and retained evidence

- Receipt-verified bars: 2,012 development records; 502 holdout records counted.
  No 2024–2025 strategy, price or cost outcomes evaluated.
- Existing narrow regression: 91 passed in 7.10 seconds across sizing, fixed-study
  and benchmark-screen tests. An initial command omitted `PYTHONPATH=src` and
  failed import collection; the corrected frozen-environment command passed.
- Offline probe checked current caps, whole/fractional literal expectations,
  fee/cash/trial bounds and fixed-cost arithmetic using Decimal. This probe is
  a report calculation, not a new production capital-feasibility API.
- Private canonical report SHA-256:
  `1c3e839247405bbfdd0a69d4f02ac2f00c7d4ff93ddf6e28b79cea36832d7973`.
  Original report bytes were independently hashed; report mode 0600 and directory
  mode 0700, both current-user owned. Original licensed captures remain intact.
- Public source/cost/execution/promotion fields remain false. Customer billing,
  genuine fills, final fees and causal quote/order clocks were not inspected.

No production Python/configuration changed; a full runtime-suite rerun was not
required for this human report. PR22 separately merged at
`73ccd6c19ad0138e522d8cbf64541415fafec317`, tree
`90353d7fa6d7917363e63630afe67a60f785aa1a`, exactly matching its reviewed candidate
after all fourteen hosted checks passed. That is integration, not deployment.

## Next work

Do not expand native whole-share execution or bulk history for this failed sizing
route. A separately frozen daily-data screen may test the approved strategy using
explicit hypothetical fractional research terms and unchanged numerical caps.
It must preserve all source/execution limitations, fixed exits/cadence, conservative
costs, and untouched holdout. It cannot approve actual fractional trading.

The next bounded implementation is that fixture-first daily assumption owner and
private report, reusing existing features/accounting/statistics rather than
fabricating quote events. Actual broker fractional terms, bounded market-order
economics and protective runtime behavior remain separate proof requirements.
