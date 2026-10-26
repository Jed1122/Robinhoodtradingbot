# Daily descriptive input seam

`market_data.stock_daily_series` is separate from the legacy raw-only normalizer
and technical DTOs. It does not relabel split-adjusted bars as raw, convert an
omitted native interpolation flag to false, or authenticate a source.

`parse_stock_daily_calendar(original_content_json, expected_sha256=...,
received_at=..., market_timezone="America/New_York")` parses the original
Alpaca MCP **result-string bytes** with the closed shape
`{request:{start_date,end_date},calendar:[{date,open,close}]}`. It retains the
naive wire strings and separately derives UTC instants using the explicitly
supplied external New York clock interpretation. Dates must be unique, ascending
weekdays within the inclusive range, with exact same-date 09:30 opens and 13:00
or 16:00 closes. Early closes and daylight saving time are respected. This is a
structural check, not proof that a supplied calendar is authentic or complete.

`admit_stock_daily_series(series, calendar, source_tool=...,
source_metadata_sha256=..., as_of=..., minimum_observations=201,
maximum_closed_session_lag_days=7)` reparses the original `StockSplitSeries` and
calendar bytes and checks their complete cached DTOs. Its current source
contract is the pinned official `mcp__robinhood_2__get_equity_historicals`
declaration, SHA256
`40b726da941850f2e4911f750ce67758668f9976019beab08126bc6dbdee8c36`.
Declaring that source is not independently authenticated evidence.

Admission requires explicit split/day/regular scope, midnight-UTC request
boundaries, no null/missing/extra rows, regular native sessions, positive volume,
and midnight-UTC labels whose UTC dates exactly equal the supplied calendar.
The calendar request must span start.date through (end minus one microsecond).date.
The UTC-date mapping is an explicit descriptive contract, not a claim that
midnight UTC is the exchange open or that New York conversion yields this date.
Every session must have closed by both as-of and the original source receipt;
waiting cannot turn a partially collected bar into a completed observation.
Both receipts must already exist at as-of. Minimum count and maximum lag are
caller-visible, uncalibrated hypotheses; no calendar gaps are filled.

The official source declaration says synthesized bars have zero volume.
For an omitted interpolation field, positive volume supports the separately
named `positive_volume_contract_inference`; the native field remains `None`.
Explicit native false is labeled `native_false`. Explicit true or zero volume
is ineligible. Currency stays unknown; no USD inference or dollar-volume metric
is provided. All qualification, authenticity, investment and live flags stay false.

`research.stock_daily_price_features.calculate_stock_daily_price_features`
revalidates the complete admission before use. It calculates 20/60/120-session
close-price changes, close/SMA50 or SMA200 minus one, sample standard deviation
of twenty simple returns times sqrt(252), and maximum peak-to-trough close-price
drawdown. Arithmetic uses an isolated 50-digit Decimal context; unsafe derived
values fail closed without publishing partial metrics. Short explicitly admitted
windows preserve individual missing metrics; unsupported/ineligible inputs
publish no metrics. Original bytes, hashes, receipt clocks, source metadata,
calendar interpretation, derived evidence and policy are bound in provenance.

These are split-only descriptive price features, not total returns, forecasts,
rankings, point-in-time vintage evidence, historical universe coverage or an
investment decision. [Alpaca calendar semantics](https://docs.alpaca.markets/us/v1.1/reference/getcalendar-1)
and [Nasdaq regular-hours context](https://www.nasdaq.com/docs/nasdaq-global-trading-hours-faqs)
describe the external session context. Provider-specific timestamp conventions
must not be transferred between sources.
