# Stock-history source semantics — October 21, 2026

Public-documentation research against repository base
`403c8921ffcff30170265a9f70218a07edfd3c15`. This document adds no source acceptance,
technical admission, strategy approval or investment authority. No private captures,
credentials, authenticated endpoints or host operations were used. The linked provider
pages are current documentation, not evidence of historical dataset vintages.

## Confirmed definitions and remaining gaps

| Source or property | Authoritative definition | Qualification limit |
| --- | --- | --- |
| Robinhood equity history | The public tool guide describes `get_equity_historicals` as historical OHLCV. | No definition of omitted interpolation, adjustment modes, missing-bar behavior or calendar completeness was found in the official guide and targeted official-site searches. |
| Alpaca adjustments | `raw` applies no adjustment; `split` adjusts price and volume for forward/reverse splits; `dividend` adjusts prices for cash dividends; `spin-off` and combined modes are supported. | The request definition does not prove that a particular response honored it, that action coverage is complete, or that adjusted history was available at a past decision time. |
| Alpaca aggregation and gaps | Minute/daily bars aggregate trades. No bar is emitted when any required OHLCV field remains zero, including no trades or only trades that cannot form prices. | A specific gap can still reflect incomplete retrieval. Do not fill it or classify its cause from absence alone. |
| Alpaca daily/session basis | Daily timestamps use the New York day. Trade-condition rules differ by field; extended-hours trades can update daily volume without updating daily OHLC. | Native `1Day` data is not interchangeable with the existing regular-session, exclusive-close minute-window aggregate. |
| Revisions and access | The stock stream documents revised minute bars. Paper Only accounts are restricted to IEX market data. | A delayed response does not prove finality. Public interface availability does not establish account entitlement or retention/cloud-use rights. |

Sources: Robinhood's [official tool guide](https://robinhood.com/us/en/support/articles/trading-with-your-agent/);
Alpaca's [historical-bars reference](https://docs.alpaca.markets/us/reference/stockbarsingle-1),
[aggregation FAQ](https://docs.alpaca.markets/us/docs/market-data-faq),
[stock-stream updates](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
and [Paper Only restriction](https://docs.alpaca.markets/us/docs/paper-trading).

## Field semantics do not supply missing evidence

The repository's [pinned Robinhood schema](../src/trading_bot/brokers/schema_snapshots/robinhood_stock_research.20261021.json)
allows an optional boolean `interpolated`, with no default; an explicit null is not
valid for that field. A nullable whole bar is a separate case. Omission remains
unknown, not false. `adjustment_type` is an optional string without a documented
enum/default in that snapshot. The normalizer's explicit `"none"` request declaration
is caller evidence, not independent proof of provider adjustment behavior.

Alpaca's [official stock-bar schema](https://github.com/alpacahq/cli/blob/main/api/specs/market-data-api.json)
describes `t,o,h,l,c,v,n,vw`, with no native interpolation field. Its documented
trade-aggregation rules may support a separately reviewed source contract; they do
not manufacture Robinhood's flag. `asof=-` disables symbol mapping, not identity
uncertainty. A symbol is not a permanent security identifier.

Preserve the existing [Paper Only/SIP blocker](alpaca-stock-data-feasibility-2026-10-21.md).
Do not make a blocked SIP request as an entitlement test or silently substitute IEX.
IEX cannot establish consolidated market volume. All existing source, strategy,
investment and live flags remain unchanged. Receipt-time availability remains distinct
from bar timestamps, session completion, publication time and historical availability.

## Smallest bounded verification using retained evidence

The root owner may inspect one already-retained individual-stock sample around one
forward or reverse split, covering at most five trading sessions. This is a sample
consistency check, not a source-wide qualification study. No new acquisition is part
of this protocol.

1. Freeze the exact security, event, sessions and comparison rules before examining
   price differences. Require original request/response hashes and receipts, feed,
   interval, adjustment declaration, symbol-mapping policy and relevant calendar
   evidence. Preserve pagination/completeness uncertainty.
2. Bind already-retained official issuer/exchange action evidence: original public
   URL, effective date, split ratio and unambiguous issuer/security identity. Missing
   identity or action evidence ends the check as unresolved. Do not infer a CIK from
   an opaque broker identifier.
3. Require an independent, already-retained officially sourced price anchor with
   matching date/session and known adjustment basis, or a properly matched retained
   raw/adjusted response pair. Record reference rounding and freeze tolerances from
   that evidence. A split announcement and a cross-day price ratio alone cannot
   distinguish adjustment treatment: market prices also move across sessions.
4. Compare the native prices and, where supported, split-volume treatment separately.
   Preserve original values and every discrepancy. Do not repair bars, apply an
   assumed factor, fill missing sessions or substitute total-return calculations.
5. Record `sample_consistent`, `sample_inconsistent` or `unresolved`, with hashes,
   comparison assumptions and missing inputs. A consistent sample supports only the
   checked event/window. Interpolation, gap causes, revisions, action completeness,
   historical availability, source qualification and technical eligibility remain
   independent questions.

Private sample values and payloads stay in their existing approved storage; a public
summary must not copy them into Git. If no suitable retained sample or reference
exists, report that precise missing prerequisite instead of issuing another capture.

Next: the root owner selects one eligible retained sample and anchor, or records why
that bounded comparison cannot yet be performed. Any later acquisition or alternative
IEX contract needs its own explicit source scope; this document grants neither.

## Root verification of the existing shortlist capture

Root rehashed the manifest-committed25observations in retained capture
`0b6f7bdd7a2add233e649ba83c4e9daa774bc3d743ad65f29a1a61b8f28f6a1b`
using the existing strict archive reader. It contains exactly one historical-price
request, declaring `adjustment_type=none`; its observation hash is
`4dfd4eb80b3ce995536089af970af4a056e52eb80d478d84167aba4d02570549`.
There is no matched raw/adjusted pair in this capture. The proposed split sample
comparison is therefore unresolved pending an independently matched retained price
anchor and issuer action binding, or a separately authorized permitted acquisition.
This bounded check did not search every private archive or obtain new market data.
No prices or private account information were copied into this report.

Root also reopened the linked official history reference, aggregation FAQ, Robinhood
tool guide, Paper Only restriction, stock-stream reference and official stock-bar
specification. The documentation findings above remain distinct from native response
semantics, selected-account entitlements and dataset qualification.
