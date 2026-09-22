# Historical options data: documentation comparison

Public documentation reviewed **2026-09-18 UTC**. No account access, sample download,
restricted data acquisition, purchase or subscription occurred. These are vendor claims,
not measured coverage or a legal determination of this account's rights. No provider is
selected. Advertised prices are not all-in costs or permission to use automated trading.

## Coverage and integration

| Provider | Historical quotes and chain identity | Time and availability | Corporate actions/dividends |
| --- | --- | --- | --- |
| Databento | OPRA definitions and parent symbology support option-chain discovery, including strike/expiry. Trades, minute NBBO and definitions gained older history in the 2025 expansion; exact ranges must be checked per schema and date. [Options guide](https://databento.com/docs/examples/options/equity-options-introduction), [expansion](https://databento.com/blog/introducing-new-opra-pricing-plans). | Nanosecond timestamping is documented; preserve publisher event and capture times separately, and do not confuse resolution with accuracy. Historical and last-24-hour live replay are separate interfaces. [Timestamp guide](https://databento.com/docs/architecture/timestamping-guide), [dataset/API overview](https://databento.com/datasets/OPRA.PILLAR). | A separate reference product covers dividends and other actions. Inclusion in an options plan and joins to adjusted deliverables remain unverified. [Schema](https://databento.com/docs/schemas-and-data-formats/corporate-actions). |
| ThetaData | V3 NBBO quote history can request all expirations/strikes for an underlying on a date; multi-day requests require an expiration and are bounded to one month. Value starts 2020 at minute granularity, Standard 2016 at tick granularity, Pro June 2012 at tick granularity. Verify expired-universe completeness independently. [Quote endpoint](https://docs.thetadata.us/operations/option_history_quote.html), [subscriptions](https://docs.thetadata.us/Articles/Getting-Started/Subscriptions.html). | Returned timestamp format has milliseconds without a displayed offset in the quote schema. Timezone/DST and actual data-availability semantics need explicit confirmation before import. Cited REST flow requires Theta Terminal. [Quote endpoint](https://docs.thetadata.us/operations/option_history_quote.html). | Current roadmap still labels V3 splits/dividends and symbology forthcoming; this is not sufficient evidence of point-in-time corporate-action support. [Roadmap](https://thetadata.net/roadmap). |
| Massive | Reference endpoint includes active/expired contracts; reference coverage does not by itself establish complete historical chains. Quote flat files start March 7, 2022, separately from older trade/bar history. [Contracts](https://massive.com/docs/rest/options/contracts/all-contracts), [quote inventory](https://massive.com/docs/flat-files/options/quotes). | Quote files advertise nanoseconds and next-day publication at 11 a.m. ET. General overview says Unix UTC seconds: importer must bind units to each endpoint schema and reject ambiguity. [Quotes](https://massive.com/docs/flat-files/options/quotes), [overview](https://massive.com/docs/flat-files/options/overview). | Stock dividend endpoints exist; options-only entitlement and adjusted-contract history semantics remain unverified. [Dividends](https://massive.com/docs/rest/stocks/corporate-actions/dividends). |

Quotes and trade-derived bars serve different purposes. Research must not infer executable
bid/ask prices from OHLC bars, interpret a missing quote as zero, or assume current chains
contain every historically eligible contract. Adjusted deliverables remain unsupported.

## Advertised costs, rights and retention

**Databento:** historical usage-based billing remains available; the OPRA announcement
lists Standard at $199/month. Current pricing advertises $125 introductory credits.
Request-specific volume, schema, licenses and underlying/reference products must be priced
before approval. [OPRA announcement](https://databento.com/blog/introducing-new-opra-pricing-plans),
[pricing](https://databento.com/pricing).
The licensing portal distinguishes non-display usage. Actual classification/fees require
the license workflow. Batch re-download availability for 30 days is not a grant of
post-subscription retention or redistribution rights; those remain unverified for the
intended OPRA use. [Licensing and download documentation](https://databento.com/docs/portal).

**ThetaData:** retail options prices shown are $40/$80/$160 monthly for Value/Standard/Pro.
Documentation advertises a free EOD tier, not free intraday quote coverage. Current text
and tables differ on free-tier history/rate limits; verify entitlement before use.
[Pricing](https://thetadata.net/pricing),
[subscription table](https://docs.thetadata.us/Articles/Getting-Started/Subscriptions.html).
The subscriber agreement limits personal/internal use to the permitted scope, restricts
redistribution/derived works and requires deletion/return on termination, including a
30-day expungement rule. Exact automated non-display rights and any negotiated exceptions
are unverified; retail marketing is not sufficient approval.
[Subscriber agreement](https://www.thetadata.net/subscriber-agreement).

**Massive:** options documentation lists Basic free, Starter $29, Developer $79 and Advanced
$199 per month. Quote flat files are included only in Advanced among those individual
tiers. This does not establish the license needed for this system.
[Quote plan access](https://massive.com/docs/flat-files/options/quotes).
Market-data terms restrict non-display/derived use unless licensed, restrict sharing, and
require deletion after termination. The exact order form, personal/professional status
and any underlying/reference add-ons control total cost and rights.
[Market-data terms](https://massive.com/legal/market-data-terms-of-service).

All-in cost remains **UNKNOWN** for each provider. Before any procurement: specify a
bounded symbol/date/schema request; confirm point-in-time coverage, corrections, event
and availability timestamps, expired contracts, dividends and corporate actions; obtain
written rights for private automated research/trading, retention, backups and derived
results; then obtain a complete quote including licenses, storage, compute and taxes.
Do not send raw licensed data to Cloud agents or public artifacts. Free credits/samples
do not remove licensing requirements. These open questions block only provider acquisition
and empirical research, not credential-free fixture/parser development.
