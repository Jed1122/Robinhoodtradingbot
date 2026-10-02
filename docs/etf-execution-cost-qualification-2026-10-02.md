# ETF execution-data and cost qualification result

The current retained package does **not** qualify for the frozen executable study.
The assessment was run, rather than inferred from a subscription or passing tests.
No economic acceptance, broker operation, deployment or live authority follows.

## Checks completed

| Scope | Result |
|---|---|
| Retained native receipts and raw-byte integrity | All three bar pages and two quote pages revalidated, including request hashes, pagination, receipt chain, timestamps and raw bodies. |
| Latest-vintage daily bars | 2,514 SPY SIP bars; exact dates match all 2,514 retained provider-calendar sessions, with no missing or extra bar dates. This is date alignment, not calendar/control authenticity. |
| Quote syntax and documented field interpretation | 1,074 retained observations; side-condition scope documented for every row; all raw sizes are in the documented round-lot era. No round-lot multiplier is inferred. |
| Quote quality inventory | 128 crossed, 133 locked, 813 two-sided uncrossed. Uncrossed does not mean executable. No observations are discarded or turned into fills. |
| Requested development execution coverage | Zero of 1,262 eligible development sessions have retained quotes or complete requested quote spans. First eligible date is December 26, 2018; the existing one-second probe is in the warmup. |
| Statutory fee references | Eleven SEC charge-date epochs and four FINRA member TAF trade-date epochs cover 2016–2025. These reference rates are not broker customer charges. |
| Full execution-data and customer-cost qualification | `BLOCKED_INPUTS`; `ECONOMIC_NO_GO`. |

The 2024–2025 holdout was not evaluated. Only input inventory was inspected;
no candidate returns, trades or research winners were selected. Latest-vintage
history retains the operator-approved original-publication/correction waiver and
its non-promotability limitation.

## Supported REST facts

Alpaca's historical REST OpenAPI explicitly distinguishes pre-November 3, 2025
round-lot sizes from subsequent share sizes. A single condition applies to both
sides; two conditions apply in bid/ask order. A zero side price is inactive.
The exact transition timezone is unspecified, so the existing conservative
UTC/New York transition window remains unresolved. The additive assessment does
not rewrite legacy native records or their hashes. [Historical quote schema](https://docs.alpaca.markets/us/reference/stockquotes-1.md),
[dated size notice](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change).

The reviewed Markdown reference has SHA256
`d408356bc3fc73d19fbab43a01501f05d1e888da60e21a03460cd3d2d7696cd9`.
`alpaca_rest_reference` records those descriptive facts without claiming
condition eligibility, share capacity, historical availability or source approval.

The historical quote object does not expose sequences, gaps, historical halt
state or LULD eligibility. Alpaca's documented status/LULD channels are real-time,
not a demonstrated historical backfill. A scheduled market opening and a regular
quote cannot supply missing controls. CTA separately defines side eligibility
and LULD non-executable indicators. [Alpaca stream controls](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data),
[CTA CQS specification](https://www.ctaplan.com/publicdocs/ctaplan/CQS_Pillar_Output_Specification.pdf).

## Cost reference versus actual customer economics

`etf_fee_reference` is a bounded documentation lookup, not a second cost engine
or configuration. SEC lookup requires an explicit **charge date**; FINRA lookup
requires a **trade date**. It does not infer their mapping, round customer fees,
assess a transaction or construct canonical `EtfCostEvidence`. Unsupported dates,
including 2026, deny instead of extending stale rates. No `known_at` is backdated.

| SEC charge-date start | USD per million covered sales | Primary reference |
|---|---:|---|
| 2016-01-01 | 18.40 | [2016 advisory](https://www.sec.gov/news/pressrelease/2016-2.html) |
| 2016-02-16 | 21.80 | [2016 advisory](https://www.sec.gov/news/pressrelease/2016-2.html) |
| 2017-07-04 | 23.10 | [2017 advisory](https://www.sec.gov/newsroom/press-releases/2017-111) |
| 2018-05-22 | 13.00 | [2018 advisory](https://www.sec.gov/newsroom/press-releases/2018-67) |
| 2019-04-16 | 20.70 | [2019 advisory](https://www.sec.gov/newsroom/press-releases/2019-30) |
| 2020-02-18 | 22.10 | [2020 advisory](https://www.sec.gov/newsroom/press-releases/2020-7) |
| 2021-02-25 | 5.10 | [2021 advisory](https://www.sec.gov/newsroom/press-releases/2021-8) |
| 2022-05-14 | 22.90 | [2022 advisory](https://www.sec.gov/newsroom/press-releases/2022-60) |
| 2023-02-27 | 8.00 | [2023 advisory](https://www.sec.gov/newsroom/press-releases/2023-15) |
| 2024-05-22 | 27.80 | [2024 advisory](https://www.sec.gov/rules-regulations/fee-rate-advisories/2024-2) |
| 2025-05-14 | 0.00 | [2025 advisory](https://www.sec.gov/rules-regulations/fee-rate-advisories/2025-2) |

FINRA member TAF reference rates/caps are 0.000119/5.95 in 2016–2021,
0.000130/6.49 in 2022, 0.000145/7.27 in 2023, and 0.000166/8.30 in
2024–2025, denominated USD per covered-sale share / USD maximum per trade.
These are member assessments, not customer penny rounding or customer exemptions.
[FINRA 2020 immediately effective filing, p. 6](https://www.finra.org/sites/default/files/2020-10/NOF%20IMM%20EFF%20FINRA-2020-032.pdf),
[amendment effective dates](https://www.finra.org/rules-guidance/rulebooks/corporate-organization/section-1-member-regulatory-fees),
[TAF calculation FAQ](https://www.finra.org/rules-guidance/guidance/faqs/trading-activity-fee).

Robinhood separately documents sell-only SEC/TAF customer fees and a CAT
per-share charge on equity orders. Waivers, cap, cent rounding, partial executions
and order/trade grouping matter. The current canonical flat, both-side
`regulatory_per_notional` fixture role cannot express those independently and
remains unverified; no production fee behavior was changed.
[Robinhood charges](https://robinhood.com/us/en/support/articles/trading-fees-on-robinhood/),
[broker fee schedule](https://cdn.robinhood.com/assets/robinhood/legal/RHF%20Fee%20Schedule.pdf).

As of this review, FINRA's October–December 2026 assessment pause differs from
Robinhood's posted normal TAF schedule. The statutory pause expressly does not
guarantee a firm's customer treatment. Neither broker collection nor waiver is
inferred. [SEC release 34-106409](https://www.sec.gov/files/rules/sro/finra/2026/34-106409.pdf).

Current fractional terms permit venue-dependent five or six decimal-place
holdings, rather than universal six-place precision; Not Held execution can
involve time/price discretion. Published terms do not measure fills, slippage or
latency. A current-cost/fractional overlay across old prices would be a disclosed
counterfactual, not historical broker replication, and is not silently substituted
into this study. [Customer agreement, section 22](https://cdn.robinhood.com/assets/robinhood/legal/Robinhood-Customer-Agreement.pdf),
[fractional execution terms](https://robinhood.com/us/en/support/articles/fractional-shares/).

## Reproduce the retained-input assessment

Run the existing offline `execution-coverage-run` with its saved capture,
calendar and private report arguments plus:

```text
--page-bounded-quotes --qualify-inputs
```

The opt-in v2 report contains aggregate schema/quality counts, actual receipt
verification scope, a statutory reference-catalog identity and explicit missing
qualification roles. It writes only a private content-addressed report and exits
2 for blocked inputs. Without `--qualify-inputs`, the v1 report/hash behavior is
unchanged. It opens no credentials and makes no provider/broker/network call.
The v2 scope explicitly distinguishes reader-verified native receipts from the
non-I/O coverage inventory and hash-checked, unqualified calendar projection.

Private report SHA256 for the inspected package:
`d836da7a9ae58c8a18a4a3a1633496ac7160bcf58a64e3d0a425ca68752f1a2b`.
No raw market data, customer information or credential source is included here.

## Remaining evidence and acquisition decision

Complete requested quote coverage is necessary but not sufficient: historical
halt/LULD/continuity, tape/era conditions and lot capacity, corporate-action
identity, account/channel fractional terms and dated customer cost grouping must
also be established. Slippage/latency, cash yield and operating costs need their
own evidence. Another quote-only download cannot establish those missing roles.

The authenticated Databento portal was inspected read-only: the existing requested
jobs were ready, and remaining credits were visible. No new job, cash charge,
subscription or license was submitted. The public Mini feed is not a SIP-equivalent
substitute and starts in 2023; sampled BBO is not complete protective-monitoring
history. [Mini dataset scope](https://databento.com/docs/venues-and-datasets/equs-mini),
[Mini history start](https://databento.com/blog/databento-us-equities-mini-now-available).

The installed Massive connector was also checked with one historical SPY quote
request; it returned `NOT_ENTITLED`. No upgrade was attempted. Its documented
sequence values are non-contiguous, so sequence gaps alone cannot certify missing
records. A request-level `status` is not a security's trading status.
[Massive historical quotes](https://massive.com/docs/rest/stocks/quotes).

NYSE Daily TAQ documents NBBO, quotes, LULD and administrative files covering the
study in principle. This is a possible evidence source, not verified account
access, a cost estimate, an approved purchase or a recommendation to subscribe.
[Daily TAQ v4.3](https://www.nyse.com/publicdocs/nyse/data/Daily_TAQ_Client_Spec_v4.3.pdf).

### Active path: Alpaca only

The operator subsequently selected Alpaca as the ETF bot's only market-data
channel. The provider checks above record completed investigations, not a request
to buy another source. No additional ETF provider purchase will be pursued.

Next: continue native Alpaca capture/validation and latest-vintage exploratory
research. Qualify only the evidence actually supplied. Alpaca's forward
status/LULD/quote channels now have a separate bounded local observation workflow
with lossless parsing, private receipt audit and explicit restart discontinuities.
The offline customer-cost measurement workflow groups partial fills and reports
charged fees, signed slippage and same-clock timings without installing canonical
costs. Both are synthetic-tested; actual capture/customer calibration is blocked
by unavailable local private inputs and timed-out Alpaca connector access.
See [workflow and limitations](alpaca-execution-observations.md). They cannot
retroactively fill historical controls. Historical fills and genuine after-cost acceptance remain
blocked where inputs or customer-cost calibration are missing. Broker/runtime
and 100 eligible paper cycles/seven shadow dates remain separate later gates.
The qualification task must not be described as passed or complete.
