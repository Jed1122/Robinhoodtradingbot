# Alpaca individual-stock data feasibility — October 21

Public documentation supports designing a bounded data-only connector for the existing
[stock-minute proof](alpaca-stock-minute-contract.md). It does not establish permitted
SIP access for the selected account or qualify a dataset. This review made no
authenticated request, credential inspection, private-archive read, purchase, upgrade,
agreement acceptance or provider contact. Existing ETF contracts remain unchanged.

## Confirmed public interface and limits

The documented single-symbol endpoint is
`GET https://data.alpaca.markets/v2/stocks/{symbol}/bars`. The existing proof fixes
`timeframe=1Min`, `feed=sip`, `adjustment=raw`, `currency=USD`, `asof=-`, `sort=asc`
and `limit=1000`. Inclusive end is one nanosecond before the declared session close.
Follow the returned cursor even after a short page. The API's larger page allowance
does not enlarge the local two-page/session, four-page overall or byte limits.
[Historical bars reference](https://docs.alpaca.markets/us/reference/stockbarsingle-1).

Native stock rows contain `t,o,h,l,c,v,n,vw`; top-level currency may be omitted.
Retain original bytes, optional-field uncertainty and RFC3339 timestamp precision.
There is no native interpolation, publication-time or finality field that resolves
those properties. A retained response cannot prove the requested feed/adjustment
without the exact request receipt.
[Official OpenAPI](https://github.com/alpacahq/cli/blob/main/api/specs/market-data-api.json).

Raw adjustment disables adjustment, and `asof=-` disables historical symbol mapping.
Neither establishes stable security identity, historical vintage, corporate-action
completeness or total returns.
[Request semantics](https://docs.alpaca.markets/us/reference/stockbarsingle-1).

## Account access remains unresolved

The generic FAQ describes historical SIP access for sufficiently delayed requests;
the plan table advertises Basic history since 2016 and 200 historical calls/minute.
These are public descriptions, not this account's verified access or completeness.
[FAQ](https://docs.alpaca.markets/us/docs/market-data-faq),
[plan description](https://docs.alpaca.markets/us/docs/about-market-data-api).

The Paper Trading documentation separately restricts Paper Only accounts to IEX
market data. The existing [provider-response checkpoint](etf-data-source-checkpoint-2026-09-30.md)
also preserves rejection of a blanket delayed-SIP entitlement for that route.
A successful HTTP response cannot override a usage restriction. There is no automatic
IEX fallback, account upgrade or alternate-key discovery in this design.
[Paper Only restriction](https://docs.alpaca.markets/us/docs/paper-trading).

Terms describe personal/noncommercial use and restrict redistribution. Public provider
clarification supports local retention/replay within entitlement, but does not establish
the selected agreement, retention duration, cancellation effect or cloud/third-party
sharing permission. Resolve the applicable scope before actual acquisition or transfer.
[Terms](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf),
[provider clarification](https://forum.alpaca.markets/t/sip-data-collection/19863).

## Calendar, gaps and revisions

Obtain and retain authentic calendar evidence independently, including holidays,
early closes and applicable venue. The legacy calendar has a finite documented year
range; the current calendar offers explicit market identifiers and UTC output.
Do not silently change the existing ETF calendar contract.
[Legacy calendar](https://docs.alpaca.markets/us/reference/legacycalendar),
[current calendar](https://docs.alpaca.markets/us/reference/calendar-2).

Trade-derived minute data may omit a minute with no eligible price-forming trade.
VWAP and displayed volume can have different eligible-trade bases. Preserve gaps;
do not carry prices forward, zero-fill, substitute daily bars, infer consolidated
liquidity from IEX or represent an incomplete grid as complete.
[Aggregation FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

Late trades and corrections can revise bars; a fifteen-minute delay is not a finality
guarantee. Current and older provider explanations differ on the exact timestamp used
for aggregation. Historical trade-clock/vintage semantics therefore remain a named
source-qualification gap. Corporate actions are separate and can arrive with delays.
[Stock stream](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data),
[older minute-bar explanation](https://alpaca.markets/learn/stock-minute-bars),
[corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1).

## Smallest coherent next implementation

Prepare an offline manifest for one exact symbol and two declared sessions, binding
authentic calendar receipt/hash, config/code identities, explicit request fields and
the existing strict byte/page/deadline bounds. Actual transport must first establish
permitted SIP access and retention scope; it must not infer them from keys or a GET.

Reuse compatible private immutable capture/receipt mechanisms, exclusive attempt
markers, secret screening and no replay after ambiguity. Use fixed HTTPS host/path,
no proxy/redirect/retry, bounded streaming, ten-second I/O limits, an actual monotonic
60-second deadline and at most four bar GETs. Preserve partial captures. Feed unchanged
bytes into the existing pure proof, then independently rehash/reconstruct the output.

All source/strategy/investment/live flags remain false and interpolation remains
unknown. Two complete minute grids would establish only bounded retrieval and local
coverage. Broader source qualification, a source-neutral technical input contract,
point-in-time company data and out-of-sample cost/tax validation remain outstanding.
