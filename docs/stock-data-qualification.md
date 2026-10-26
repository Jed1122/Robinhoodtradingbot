# Individual-stock data qualification

This increment supplies source-bound data checks for the individual-stock bot.
It changes no deployed worker, account authorization or execution control.
The default dossier report remains byte-compatible; `--data-quality` explicitly
selects the additional schema-4 diagnostics. All live controls remain disabled.

## Source and use matrix

| Input | Retained actual evidence | Supported use | Remaining restriction |
| --- | --- | --- | --- |
| Robinhood daily regular-session raw/split bars | AAPL, MSFT, NVDA and benchmark-only SPY: 706 sessions each, January 2, 2024 through October 23, 2026 | Descriptive split-price returns, moving averages, volatility and drawdown after exact request/calendar admission | Last trade is not the official settled close; split-only returns exclude dividends. The named cohort is a diagnostic, not a historical stock-selection universe. No currency or historical receipt is invented. |
| Native interpolation contract | All 2,824 split-series bars have positive volume; optional native interpolation markers were omitted | Separately labeled positive-volume inference under the exact retained tool declaration | Native markers remain unknown. No gap filling or source-wide authentication. |
| Exchange calendar | Official Alpaca calendar: 706 date labels, naive local session times, including early closes and DST | Explicit America/New_York interpretation and completed-session coverage checks | The time-zone interpretation is external configuration, not an echoed native field. |
| Split consistency | Ten matching NVDA raw/split sessions; issuer FAQ identifies ten-for-one split trading June 10, 2024 | Exact rational pre/post OHLC and inverse-volume comparison | One event does not establish every action or dividend adjustment. |
| Existing research archive | Read-only restored snapshot; 25 original SDK observations covering ten companies | Receipt/observation freshness, missingness, quarantine and source-origin diagnostics | Nine valid 275-bar series; SKHY remains wholly quarantined. Unknown currency, publication, calendar and interpolation properties remain unknown. |
| Alpha Vantage historical listing | Requested January 1, 2024 active listing; 10,580 rows | Retrospective provider candidate frame and duplicate/missingness audit | 65 extra rows across 64 duplicate ticker groups, 63 conflicting groups; 27 blank names. Stock type includes non-common securities. No stable identifier, original-vintage availability or unambiguous common-stock universe is supplied. |
| Alpaca corporate actions | Four-symbol diagnostic: 44 cash dividends and one forward split | Native event/rate/date inspection and cross-source consistency checks | Pagination/data-quality state is absent from the connected wrapper; HTTP completeness cannot be inferred from row count. Currency and publication times are absent. NVDA record/payable dates differ from the issuer FAQ and remain unresolved. |
| Robinhood filing facts | Native NVDA 10-K index, 95 facts across eight concepts, and filtered missing-concept catalog | Original entity/unit/period/dimension inspection and explicit missing-concept reporting | Only 22 facts have explicitly empty axes; 73 are dimensional. Two requested concepts are absent. No FCF substitution, original accession, historical publication clock or cross-company comparison is invented. |
| Direct SEC public submissions route | One declared-agent request returned HTTP 403 | Documented unavailable route | No retry around the denial, authentication bypass or claim that filings are absent. |
| Alpha Vantage weekly adjusted diagnostic | NVDA: 1,407 weekly rows, November 1999 through October 2026 | Inspecting a separately documented lower-frequency source | Not interchangeable with daily parameters. Across 147 overlapping weekly labels, 143 raw closes match exactly and four differ; all 11 sampled dividend rates agree numerically with Alpaca. This does not establish exchange-close finality, currency or complete total-return economics. |
| Premium daily adjusted route | Existing connection returned an entitlement error | Explicit unavailable-input handling | No new subscription or credential-file dependency. |
| Original historical common-share frame | Original Berkshire 2023Q4 13F: all 138 tool-rendered SEC rows and 41 CUSIP/class groups independently reconciled | All original disclosed COM/SH/no-putcall aggregates at least USD 5 billion form the separately frozen eight-stock first-study cohort | Original XML unavailable; tool-rendered source retained. No later amendment, full-market, full-portfolio or historical operational claim. |
| First-study histories | Eight stock pairs plus benchmark-only SPY: nine 706-session raw/split histories, same verified calendar | Chronological 200/50 trend inputs and price-only cost ablation under the frozen contract | Native currency remains unknown; native interpolation remains omitted with separately labeled positive-volume inference. No USD/after-tax/total-return or investment promotion. |
| First-study events/independent prices | Native 100 cash rows match the nine expected CUSIPs; nine weekly sources provide 1,323 close overlaps | Separate identity and event/price consistency audit | Strict action parser rejects the whole response containing two unsupported merger rows. Twenty-five close differences, eleven dividend-rate differences and two weekly-only events are retained; no tolerance, repair or complete-book claim. |
| Supplemental current identity | AXP exact Equity/United States/USD search match; AAPL next request rate-limited; remaining six unrequested | Current AXP context only | Current matches do not backfill historical quote currency. Unavailable overview/current-search inputs remain missing. |

The separately frozen twelve-slot historical-listing probe preserves all selected
members. Independent exchange notices show that QTTB and IMA are later ticker
aliases in the purported January 2024 frame. Its first native price attempt also
returned `inactive_instruments` for GLDD. These are material restrictions on that
frame and provider history route, not permission to replace failed members or
normalize a backtest to the surviving downloads. The source investigation was
stopped with its original three receipts retained; no completed twelve-member
price collection or qualified study is claimed.

The historical-listing duplicate count is **extra rows**, not 65 distinct duplicate
tickers. Ambiguous identities must stay in the rejection denominator; they cannot
be silently repaired or replaced by successful price downloads.

## Reproduction and integration

The pure interfaces and their bounds are documented in
[daily descriptive series](stock-daily-descriptive-series.md),
[split comparison](stock-split-comparison.md) and
[dossier quality](stock-data-quality.md). They make no provider calls. The existing
archive reader supplies original SDK observations to the dossier compiler; no
writer, lock, provider connection or ledger-head update is needed to compile a
quality report in memory. A locally derived history projection is explicitly
linked to its original source receipt rather than presented as another provider
observation.

For a separate private archive on which report publication is authorized:

```sh
PYTHONPATH=src python -m trading_bot.runtime.stock_dossier_report \
  --archive-root /absolute/private/archive \
  --manifest HASH.stock-capture.json \
  --as-of ORIGINAL_UTC_CUTOFF --data-quality
```

Do not publish into a preserved restore snapshot. Default reports, scheduled worker configuration
and research limits are unchanged by this opt-in report interface.

Private provider payloads, prices and financial facts remain excluded from Git.
Retained evidence is under `.superpowers/sdd/2026-10-25-task4-data/` and
`.superpowers/sdd/2026-10-25-stock-data-qualification/` in the Task 4 worktree.
Original content strings are preserved; they are MCP/SDK content, not a claim
to original HTTP wire bytes. Hashes establish identity, not source authenticity.

## Next study boundary

The [first stock-study handoff](stock-first-study-inputs.md) binds a separately
frozen historical common-share cohort, used windows, price basis, calendar,
identity corroboration, missing-member treatment, costs and passive comparisons.
The four named diagnostic series and failed twelve-slot source probe are retained
separately. The first-stage handoff permits actual price-only stock-policy
research; it does not qualify every data use or establish investment readiness.

A latest-retrieved historical price study can be legitimate exploratory research.
It must use chronological signal prefixes and later execution prices, retain
original receipt times, and disclose revisions and retrospective membership
limits. It cannot claim to reproduce exactly what the bot knew historically.
Current financial data must not enter past decisions. An unavailable member
cannot be silently dropped or replaced after its performance is inspected.

Task 5 tests economic performance. These data checks supply no predicted return,
calibrated confidence, trading edge, investment approval or live authorization.

## Official source contracts

- [Robinhood agent tools](https://robinhood.com/us/en/support/articles/trading-with-your-agent/), supplemented by the retained actual tool declaration for adjustment and interpolation semantics.
- [Alpha Vantage endpoint documentation](https://www.alphavantage.co/documentation/) and [adjustment/usage FAQ](https://www.alphavantage.co/support/).
- [Alpaca corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1) and [calendar](https://docs.alpaca.markets/us/v1.1/reference/getcalendar-1).
- [NVIDIA issuer split FAQ](https://s201.q4cdn.com/141608511/files/doc_downloads/2024/06/nvidia-2024-stock-split_faq_investors.pdf).
- [Nasdaq 2024 calendar](https://www.nasdaqtrader.com/content/technicalsupport/2024tradingcalendar.pdf).
- [SEC automated-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

Connected account access does not grant redistribution or an unattended runtime
license for another provider. Keep captures for the authorized individual's private
research and check applicable source terms before adding persistent acquisition.
