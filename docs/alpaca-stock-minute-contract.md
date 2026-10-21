# Alpaca individual-stock minute proof contract

This additive, pure module prepares an independently inspectable stock data proof.
It performs no provider I/O, reads no credentials or files, and admits no data to
the technical-feature or investment pipeline. The existing Robinhood interpolation
unknowns, SPY/five-ETF adapters and 2016–2025 calendar contract remain unchanged.

## Interface and implementation boundary

`trading_bot.market_data.alpaca_stock_minutes` exposes frozen, slotted types:

- `StockCoreSessionDeclaration`: caller-supplied session date, UTC open/close,
  calendar source URL/body SHA-256 and calendar receipt time. Local New York
  times must be 09:30–16:00 or 09:30–13:00 on one weekday. DST conversion is
  checked using `America/New_York`; these syntax checks do not verify that the
  date is a trading day or an early close. Calendar authenticity stays false.
- `StockMinuteRequest(symbol, session)`: one exact uppercase symbol, maximum
  16 characters, with letters/digits and internal dot/hyphen groups. The request
  hash binds the entire declared calendar context. Symbol mapping is disabled;
  this neither resolves security identity nor establishes historical membership.
- `parse_stock_minute_page(body: bytes, *, request, expected_sha256,
  capture_started_at, received_at, page_index=0, requested_page_token=None)`:
  returns a `StockMinutePage` with original immutable bytes, body hash/size,
  request, cursor chain, page and row indices, exact Decimal native values and
  declared receipt clocks. Native currency is retained as `None` when omitted;
  requested USD is a distinct declaration. Provider authenticity stays false.
- `assess_stock_minute_proof(*, requests: tuple[StockMinuteRequest, ...],
  pages: tuple[StockMinutePage, ...], as_of: datetime)`:
  returns `StockMinuteProofAssessment` containing immutable per-window assessments,
  missing minute timestamps and optional `StockCoreWindowAggregate` objects.

The implementation sequence is request/calendar validation, lossless native-byte
parsing, receipt/page correlation, then coverage assessment and local aggregation.
Tests exercise these boundaries with wholly fictional native-shaped observations.
There is no transport, cache, scheduler, runtime or technical admission change.

## Fixed documented request

Only `GET https://data.alpaca.markets/v2/stocks/{symbol}/bars` is described by
the request object. Parameters are fixed to `timeframe=1Min`, `feed=sip`,
`adjustment=raw`, `currency=USD`, `asof=-`, `sort=asc` and `limit=1000`.
`start` is the declared session open; inclusive API `end` is one nanosecond before
the declared close. The only cursor change is the prior page's next-page token.
Alpaca documents raw adjustments, inclusive boundaries, symbol remapping controls
and the requirement to follow pagination even after a short page.
[Official historical bars reference](https://docs.alpaca.markets/us/reference/stockbarsingle-1).

Alpaca documents historical SIP access without a subscription when `end` is at
least 15 minutes old. This contract conservatively requires capture start at
least 15 minutes after the declared close. The Basic plan lists zero cost and
200 historical API calls/minute. Actual account access, applicable retention
rights and successful data coverage have not been verified here. No paid upgrade,
automatic IEX fallback or entitlement assertion is part of this module.
[Official FAQ](https://docs.alpaca.markets/us/docs/market-data-faq),
[official plan limits](https://docs.alpaca.markets/us/docs/about-market-data-api).

The proof accepts one symbol and one or two distinct chronological sessions,
at most two pages per session/four pages overall, at most 1,048,576 bytes/page
and 4,194,304 bytes total. Every page uses the same caller-declared capture start;
receipts must increase strictly and fall within its 60-second deadline. Calendar
receipt must precede capture start, and every required receipt must be at or
before injected UTC `as_of`. Per-window and aggregate `available_at` are
conservatively the assessment's `as_of`, never a bar's left edge or session end.
All supplied timestamps must be aware with UTC offset zero. These checks attest
clock consistency only; the clocks themselves remain caller declarations.

A future transport would additionally need a ten-second I/O timeout, fixed HTTPS
host/path, no redirects, no environment proxies, no automatic retries and a
maximum of four bars GETs for this proof. The pure module cannot verify these
transport conditions, HTTP response status, an account quota reservation or a
real elapsed wall-clock duration. They remain outstanding capture obligations.
An unconsumed next-page token remains `pagination_incomplete`; caps never justify
truncation or a complete-coverage claim.

## Native integrity, coverage and local derivation

The parser requires the exact symbol and an array of rows containing exactly
`t,o,h,l,c,v,n,vw`. It retains optional top-level USD currency without inventing
a response default. Duplicate JSON keys, unknown shapes, nonfinite/unsafe
numbers, zero/nonpositive OHLC/VWAP/volume/trade counts, inconsistent OHLC,
duplicate/reordered or non-minute-aligned timestamps, out-of-window observations
and hash mismatches fail closed. Malformed real observations are never repaired
or omitted. Errors expose only `alpaca_stock_minutes_invalid`. The raw bytes and
parsed record correspondence are rechecked during dataclass reconstruction and
assessment, including request/hash/page/row binding.

Page sequences must begin at index zero with no requested cursor, match every
prior cursor exactly, and have no cursor cycles, extra pages after termination,
receipt reversals or cross-page timestamp overlap. Unknown requests, mixed
symbols, duplicate/reversed sessions and future receipts reject the whole proof.
Missing responses and valid empty arrays remain unavailable. Missing minute
starts are retained explicitly, with no carry-forward or zero filling. Gaps may
mean no eligible trade or incomplete source coverage; this module cannot
distinguish them. A local aggregate exists only for a terminal page chain and
an observed row at every expected minute start.

Alpaca documents stock minute bars as trade aggregates with left-edge timestamps;
no qualifying price-forming trade can mean no emitted bar. Its daily volume
rules can include extended-hours trades, so native `1Day` data is not substituted
for this window. IEX is one exchange and cannot establish consolidated liquidity.
[Official stock bar construction and feed semantics](https://docs.alpaca.markets/us/docs/market-data-faq).

The local recipe uses first open, maximum high, minimum low, last close and sums
of share volume/trade count. It retains every contributing record hash and source
body hash. No derived VWAP or actual dollar turnover is claimed: Alpaca's native
VWAP construction can use a volume basis different from its volume field.
`native_interpolated=None` stays absent/unknown; `no_fill_applied=True` describes
only this local recipe. No Robinhood native receipt or interpolation flag is
created or changed.

The explicit session basis is `core_window_[open,close)`. NYSE documents its
closing auction at 16:00 Eastern (or the applicable early close), so this
exclusive-close window must not be described as an official auction close or
complete daily regular-session volume. Including the entire close minute could
also mix subsequent trades. Supply a current calendar with applicable venue
coverage; Alpaca's calendar documents early closes and dates through 2029, but
caller-supplied URL/hash/time declarations alone do not authenticate it.
[NYSE hours](https://www.nyse.com/trade/hours-calendars),
[Alpaca calendar](https://alpaca.markets/sdks/python/api_reference/trading/calendar.html).

## Evidence limits and next steps

`two_session_proof_complete` means two locally complete minute grids only.
It never means source qualification, historical availability, provider finality,
economic validation, investment eligibility or live authorization. All such flags
are permanently false. Publication time remains unknown. Raw price changes are
not total returns; corporate actions, corrections, stable security identity,
historical universe coverage and provider completeness remain unqualified.

The next step is independent review of this parser and its fictional fixtures.
Then the owner can prepare a separately authorized one-stock/two-session data-only
capture with calendar evidence, immutable receipt archival and transport limits.
A separately reviewed source-neutral technical input contract is required before
using these aggregates for descriptive features. Two sessions do not supply the
200 accepted observations required for all existing technical windows. No source
or investment promotion follows automatically from any of these steps.
