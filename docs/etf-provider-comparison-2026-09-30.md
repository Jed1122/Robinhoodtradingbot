# ETF provider decision checkpoint — 2026-09-30

Scope: the approved 2016–2025 SPY/cash research study, not options subscriptions,
broker selection or live activation. Public documentation was inspected today.
No account entitlement, dataset completeness or license has been qualified here.

The operator reports installing Massive and is willing to pay for a data account
that meets the task. Evaluate paid sources instead of assuming a free-only budget.
This is not a purchase receipt or approval of an unspecified recurring contract.
No subscription, agreement acceptance or paid market-data purchase occurred.
Later read-only account and free issuer-file checks are recorded below.

## Candidate comparison

| Candidate | Advertised monthly price | Relevant capability | Remaining qualification |
| --- | ---: | --- | --- |
| Alpaca Algo Trader Plus | $99 | Consolidated stock coverage and history since 2016 | Account-specific paid access; complete early corporate actions; publication/correction evidence |
| Massive Stocks Advanced | $199 | Historical NBBO quotes plus corporate actions; 20+ years of stock history | Automated-use/local-retention license; actual SPY coverage and causal semantics |
| Massive Stocks Starter / Developer | $29 / $79 | Bars and corporate actions; differing history windows | Historical NBBO quotes are excluded, so neither alone serves this study |

Prices are advertised individual monthly rates, not authenticated checkout totals.
See [Alpaca plans](https://docs.alpaca.markets/us/docs/about-market-data-api),
[Massive plans](https://massive.com/pricing?product=stocks) and
[Massive quote access](https://massive.com/docs/rest/stocks/trades-quotes/quotes).
The previously inspected paper-only Basic reply is not evidence of paid access.

Massive is the strongest single-source technical candidate identified here, not
yet the selected/qualified provider. Its quote endpoint advertises history from
2003-09-10, exchange and SIP timestamps, prices, sizes and sequence numbers.
Sequence gaps are allowed and values reset each day; they cannot alone prove
missing events. A SIP receipt timestamp is not a provider-client delivery timestamp.
The [dividend endpoint](https://massive.com/docs/rest/stocks/corporate-actions/dividends)
advertises history to 2000-01-15 and original versus split-adjusted amounts; that
does not prove original historical publication/revision availability.

## Material limits before spending

Massive's published [market-data terms](https://massive.com/legal/market-data-terms-of-service),
updated August 28, 2025, default to display use absent an applicable further
agreement (§2) and restrict non-display/derived investment-strategy use without
licensing (§5). They also require ceasing use and deleting data when the agreement
or account is terminated, restricted or suspended (§8). An applicable account
agreement or express permission must establish the intended automated private
research and retention scope. Do not assume one paid month permits indefinite
use of downloaded data, or that the public price includes that permission.

Massive's [September 22 changelog](https://massive.com/changelog) documents a
historical SPY tape-label defect: pre-September-21-2026 Tape B records still carry
Tape A labels. Any adapter must retain original bytes and use evidenced dated
listing identity for interpretation, rather than trusting the label or silently
rewriting the archive. This reinforces the need for era-specific source tests.

## Connection and next actions

Initial discovery exposed no Massive tools. On the subsequent continuation,
Massive's endpoint-search and API tools became callable. Two endpoint-documentation
lookups succeeded, including the dividend schema. No authenticated price/quote
or dividend payload was requested. This verifies callable schema discovery, not
the account's paid plan, historical entitlements or automated-use rights. No second
plugin installation or reconnection is currently needed for schema discovery.

Massive's [Codex connection documentation](https://massive.com/docs/ai-tools/clients/codex)
states that MCP requests inherit account entitlements: installing the connector
does not purchase data access. The connector is useful for bounded schema/access
checks; an auditable bulk archive still needs immutable acquisition receipts.

1. Verify the connected account's applicable automated-use/retention scope and
   current plan. If missing, obtain the applicable offer/terms before purchasing.
2. Verify bounded early/middle/late SPY samples and action/session coverage without
   inspecting strategy outcomes or contaminating the holdout.
3. Freeze a complete useful package and all-in recurring price; do not buy both
   providers simply because both exist. Then acquire/import under explicit scope.
4. Run qualified causal after-cost testing, preserve NO-GO results, and only then
   evaluate paper/shadow and separate broker/runtime gates. No profit is promised.

## Cost-first continuation: authenticated offer and issuer coverage

The operator subsequently emphasized the most cost-effective approach and signed
in to Alpaca for the approved read-only plan inspection. The account dashboard
showed Paper Trading, current subscription Basic, and Eligible to upgrade. The
Market Data plan selector offered Algo Trader Plus at **$99/month** after selecting
the monthly display. It initially displayed **$1,089/year**; that annual offer was
not selected or accepted. The upgrade button was not activated. No payment details,
API credentials, account application, trading settings or orders were changed.
The displayed offer establishes account-specific upgrade availability, not paid
entitlement or complete actual historical data. The Basic entitlement denial in
the earlier provider reply is retained.

The free [US issuer distribution workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx),
linked from [State Street's distribution page](https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions),
was downloaded to local scratch outside Git and inspected read-only. The retained
file SHA-256 is `51a16a450298a663b3fa088883a17c75f4464e87c911b0e83902a0ad46877c54`.
The `dividend` worksheet has 136 SPY rows with ex-dates from 1993-03-19 through
2026-09-18. It includes 40 SPY rows in 2016–2025, four per year, with no duplicate
ex-dates or missing record/pay dates in that window. One consistent instrument
identifier was present. Columns include dividend and separate short/long capital
gain amounts. Raw values and workbook bytes remain outside the repository.

This removes the uncertainty about whether an issuer file contains distributions
through the requested years. It does **not** independently prove completeness,
raw-versus-adjusted amount semantics, historical announcement/revision timestamps,
split history or permission for automated ingestion and continued local retention.
The sheet has no announcement, publication, receipt or revision columns. Do not
invent them from ex-dates or today's download time, or use current revisions in
earlier decisions. No strategy outcomes were evaluated.

Alpaca now documents [corporate-action event replay](https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse)
with insert/update/delete events and `since`/`since_id` replay. Its earliest retained
events, account access and 2016–2025 historical coverage remain unverified; do not
describe revision handling as categorically unavailable. The public
[terms](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf)
describe recurring advance subscription charges, automatic renewal until canceled,
and no obligation to refund an unused term. They reference additional applicable
market-data agreements. No agreement was accepted during inspection.

**Current cost-first candidate:** Alpaca Plus monthly plus issuer distributions
if those roles qualify. Do not buy Massive as well solely to obtain dividend dates.
The cheapest complete qualified package is still unproven, and no purchase is
recommended as a guarantee of qualification. Confirm paid SIP use/retention and
earliest original/revision history, then test bounded quote/control coverage before
freezing acquisition. If the retained public/account evidence cannot answer those
questions, obtain a targeted provider clarification rather than treating a passed
HTTP request as a license. Do not send correspondence without operator authority.

The operator subsequently explicitly approved one Alpaca support inquiry. A reply
was sent in the existing support conversation and the mail service returned SENT.
It requests a human clarification of the paper-only paid SIP entitlement, private
automated use, retention after cancellation, and earliest original/corrected history.
No credentials, account identifiers, balances, raw data or subscription acceptance
were included. The response is outstanding; sending a question is not evidence of
the answer. Personal message IDs and correspondence remain outside Git.

Ongoing data costs must remain separate from one-time research acquisition costs.
At $99 each month, the subscription alone would total $1,188 over twelve months
before any other operating cost. The economic report must charge costs actually
required to keep the resulting system running, even if trading P&L is positive.
