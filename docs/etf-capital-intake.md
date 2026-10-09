# Capital-research daily intake

Task4 is in progress. Its first credential-free component is a separately
versioned request/page parser for SPY, QQQ, IWM, SHY and IEF. It is not a capture
transport, complete historical dataset or economic-qualification factory.

`CapitalDailyRequest` uses a symbol-bound single-stock daily-bars path. Query
construction reuses the existing raw-SIP/USD/asof-minus/ascending request syntax.
The old SPY request, page, record and archive hashes are unchanged. Original body
bytes are hashed directly; no symbol rewriting is used to reuse SPY parsing.
The underlying native bar retains its origin hash, page/row identity and exact
Decimal and nanosecond observations. A distinct wrapper binds the actual symbol.

Pages are limited to1MiB,10,000rows and128pages per supplied chain, preserving
existing native bounds. Strict keys, hashes, symbol/currency, ranges and monotonic
timestamps are checked. Cursor loops, extra pages after terminal pagination,
duplicate session timestamps and changed requests deny. Parsing exceptions use
the sanitized native-invalid reason. Financial records have private representations.

The assessment establishes **pagination completeness only**. It cannot establish
that every expected trading session exists, that corporate actions/distributions
are complete, or that the observed daily aggregation timestamp is an original
publication time. All source/promotion flags remain false. Zero observations
and incomplete pagination stay explicit. This component uses fabricated fixtures
only and adds no credentials, network access or acquisitions.

## API references and outstanding checks

[Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars)
and [the official stock request model](https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html)
document historical request parameters. [The official historical-data guide](https://alpaca.markets/learn/fetch-historical-data)
describes access to data older than15minutes; this is documentation, not verified
access for this account or a fresh execution quote. Do not change subscriptions,
silently substitute IEX, or use delayed history as current SIP/NBBO evidence.

Next are descriptor-bound raw capture/archive manifests using the existing private
storage primitives, then symbol/session/calendar/split/distribution/availability
dataset controls. These must be verified and frozen before the walk-forward
strategy study. No genuine economic result, qualifying paper/shadow behavior or
broker/runtime readiness follows from this parser.
