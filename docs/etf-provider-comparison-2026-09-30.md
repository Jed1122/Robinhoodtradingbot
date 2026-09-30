# ETF provider decision checkpoint — 2026-09-30

Scope: the approved 2016–2025 SPY/cash research study, not options subscriptions,
broker selection or live activation. Public documentation was inspected today.
No account entitlement, dataset completeness or license has been qualified here.

The operator reports installing Massive and is willing to pay for a data account
that meets the task. Evaluate paid sources instead of assuming a free-only budget.
This is not a purchase receipt or approval of an unspecified recurring contract.
No subscription, agreement acceptance, purchase or market-data request occurred.

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

The operator reports installation, but this session exposes no Massive tools.
Tool discovery, plugin-directory search and the local cached-plugin filename
check found no callable Massive integration. This does not prove installation
failed. Refresh/reconnect the installed plugin before testing its current access;
do not paste API keys. No second plugin installation is proposed.

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
