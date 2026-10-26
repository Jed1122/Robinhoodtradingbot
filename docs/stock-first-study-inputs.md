# First individual-stock study input contract

The first declared study uses a fixed historical cohort selected from the original
Berkshire Hathaway 2023 fourth-quarter Form 13F, accession
`0000950123-24-002518`. Include every disclosed common-stock CUSIP/class group
whose aggregate reported value is at least USD 5 billion. Count each original row
once; manager labels and voting-authority columns do not multiply positions.
This produces AXP, AAPL, BAC, CVX, KO, KHC, MCO and OXY, with SPY as a benchmark.
The cohort is a research sampling frame, not an investment recommendation or a
restriction on the bot's separately configured broad current-stock discovery.

The [original SEC table](https://www.sec.gov/Archives/edgar/data/1067983/000095012324002518/xslForm13F_X02/30197.xml)
has 138 rows and 41 CUSIP/class groups. The original table's value total agrees
exactly with the [original cover page](https://www.sec.gov/Archives/edgar/data/1067983/000095012324002518/xslForm13F_X02/primary_doc.xml).
Values are nearest U.S. dollars, rather than the prior thousand-dollar convention.
This is the originally disclosed subset; later amendments and confidential
holdings are excluded. It is not the full U.S. market or the institution's full
eventual portfolio.

## Source and time boundaries

The [original filing index](https://www.sec.gov/Archives/edgar/data/1067983/000095012324002518/0000950123-24-002518-index.htm)
reports a December 31, 2023 reporting period and February 14, 2024 filing and
acceptance. Membership use starts no earlier than February 15, 2024. Actual
first study signals require 200 consecutive completed sessions and occur later
in 2024, after disclosure. Earlier prices serve only as warm-up observations.

Retain original returned web-tool page text and independently reconstruct all
rows and overlapping page segments. This is tool-rendered official SEC source
evidence, not original XML or HTTP-wire bytes. The separate direct XML request
returned 403 and was not retried. The original collection/receipt times remain
in October 2026; they are never moved back to a reporting period or trade date.

The source 13F supplies issuer, class and CUSIP; the lookup ticker labels are
separately proposed. Native Alpaca cash-action rows corroborate each of the eight
CUSIPs plus the benchmark's CUSIP. That corroboration does not authenticate every
historical security lifecycle or cashflow. Current symbol-search evidence must
remain current: AXP's exact Equity/United States/USD match is observed; AAPL's
request was rate-limited and the remaining six searches were not issued.
The overview request also returned an explicit unavailable-source error.
No missing currency or financial metric is filled from these failed requests.

## Frozen data and study rules

The capture intent predates the new cohort-price reads. Reuse the original AAPL
and SPY diagnostic pairs and calendar, and collect one raw and one split-adjusted
regular-session daily series for each of the other seven members. The window is
January 1, 2024 through October 23, 2026; the historical API's exclusive end is
October 24 at midnight UTC. Use every original slot with no replacement after
failed lookup, history, identity or action checks.

The first policy hypothesis is the existing daily trend rule: after 200 complete
sessions, require both the latest split close and the 50-session arithmetic mean
to exceed the 200-session arithmetic mean. Equality fails. A held position exits
when that condition no longer holds. Missing history produces an unavailable
decision. Every signal uses only its chronological prefix and executes, under
the study's explicit fill assumption, at a subsequent regular-session open.
The final signal without a next session is unexecuted.

The training cutoff is September 30, 2025; the frozen final holdout is October 1,
2025 through October 23, 2026. Round-trip cost scenarios are 10, 25, 50 and 100
basis points. The existing comparison function charges each leg, so pass exactly
half those values per entry/exit. Compare with the same fixed cohort's buy and
hold, matched stock/cash exposure and the SPY benchmark. Do not tune on the
holdout or call these cost scenarios actual executed fills.

## Admitted and blocked uses

Admission is purpose-specific: verified calendar-aligned split-price histories
can supply chronological ratio signals and a retrospective price-only cost
ablation. Preserve native missing interpolation markers, positive-volume
inferences, source metadata, original request/receipt hashes and every series'
restrictions. Last-trade daily closes are not guaranteed exchange closing-auction
prices. Do not backdate financial facts or equate source receipts with historical
publication times.

The complete new action response contains 100 cash-dividend rows and two
CVX-as-acquirer stock-merger rows. The current strict action parser rejects this
whole unchanged response because stock mergers are outside its reviewed profile.
No filtered response is presented as original or passed. Native merger dates
remain as reported; differences from issuer completion evidence do not justify
silently repairing dates or applying an acquirer's share conversion.

Independent weekly adjusted source captures support event/price consistency
inspection. They do not replace daily policy parameters or prove a complete
corporate-action book. Currency, publication, completeness and lifecycle limits
still block total-return, after-tax cash-wealth, historical fundamental-ranking
and capital-allocation claims that need those properties. The first ablation is
one research step; it cannot establish investment readiness by itself.

The failed twelve-slot listing investigation remains a separate retained
negative result, with all original members and unattempted requests visible.
These eight stocks are a new primary-source contract, not replacements in that
failed panel. No strategy performance, trading edge, deployment or live operation
is claimed by this input contract. Task 5 evaluates performance; live activation
remains a separate user decision.
