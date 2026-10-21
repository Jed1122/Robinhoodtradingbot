# Individual-stock fact normalization

`market_data.stock_facts` supplies three pure normalization functions for the
reviewed Robinhood stock-research response shapes. It performs no I/O, broker
calls, ranking, investment selection, average-dollar-volume calculation or order
generation. Source, strategy, trading and live qualification remain false.

The governing declarations are the committed
`brokers/schema_snapshots/robinhood_stock_research.20261021.json` profile.
Fixtures are fictional. No provider responses, credentials or private captures
are bundled or accessed by these normalizers or their tests.

## APIs and receipts

- `normalize_fundamentals(payload, *, received_at, observation_sha256,
  requested_symbols=None)` returns `StockFactCollection[StockFundamentals]`.
- `normalize_financials(...)` accepts those same keywords and returns
  `StockFactCollection[StockFinancialPeriod]`.
- `normalize_daily_bars(...)` additionally accepts
  `request_adjustment_type="none" | None` and `completed_before=UTC | None`,
  returning `StockFactCollection[StockDailyBar]`.

`payload` is the decoded tool envelope containing `data.results`; an optional
`guide` is type/size checked and discarded. Only declared field names are
accepted. All collections and records are frozen dataclasses with immutable
tuples. Each record retains its `StockObservationReceipt`: tool name, canonical
UTC receipt time and lowercase SHA-256 observation reference. That digest is a
caller declaration; normalization does not authenticate a provider or rehash
unavailable original transport bytes. Every `available_at` is receipt time,
never a historical financial period end or a bar's left edge.

Collections retain reported, not-found and unavailable symbols, null-row counts,
and whether the entire results array was missing. Optional `requested_symbols`
must be an immutable, unique, canonical ticker tuple. Response/not-found symbols
must match it exactly, without overlap or duplicates. Without it, scope remains
unverified; null rows also prevent a verified scope claim. Batches are bounded
to 10 fundamentals/history symbols and 20 financial symbols. An unexplained
missing requested symbol denies normalization rather than shrinking the scope.

`observation_hash` binds the normalized collection, receipts, explicit request
context, missingness and false qualification flags under a distinct namespace.
It is reproducible evidence identity, not an authenticity or confidence score.

## Decimal metrics and financial periods

Fundamentals and financial periods expose `metrics` as a tuple of
`StockDecimalMetric(name, value)` and `missing_metrics` as an explicit tuple of
names. Missing and null metrics are absent from `metrics`; neither becomes zero.
Only finite bounded base-10 text is accepted for source Decimal values. Binary
floats, booleans, nonfinite values and unsafe magnitudes deny. No display-string
number repair, price-times-average-volume proxy or inferred ratio is introduced.

Fundamentals retain their declared `market_date`, bounds, sector and industry.
Missing dates stay unknown. Future snapshot/52-week observation dates reject;
upcoming dividend schedule dates may legitimately be future dates. Known partial
price ranges must be mutually consistent and prices must be positive. Share
counts, volumes and market capitalization must be nonnegative. Valuation ratios
may be signed. A market date provides day-level source context, not an exact
fundamental publication timestamp.

Financials preserve annual/quarterly mode, fiscal year, nullable fiscal quarter
and `period_end`. Annual records must have no fiscal quarter; quarterly records
may preserve an unknown quarter. Rows must retain the source's newest-first
order; duplicate dates, conflicting fiscal periods and future period ends
reject. A missing quarter is not invented. Revenue, gross profit, net income
and net margin may legitimately be negative; they are not clamped or subjected
to a positive-earnings screen. The source provides no period start, filing/publication timestamp or
currency here, so `period_start` and `currency` stay unknown. Historical or
cross-company comparisons require separately verified units and filing periods.

## Daily bars and explicit evidence

History must declare `interval="day"` and `bounds="regular"`. Bars retain
strictly increasing UTC `begins_at`, positive consistent Decimal OHLC and exact
nonnegative integer share volume converted to Decimal. Duplicate/conflicting
timestamps, reverse order, future left edges, interpolated bars and explicit
nonregular sessions reject. An absent interpolation or session marker remains
unknown rather than becoming a verified false/regular declaration. Null bars
are counted; missing sessions are never interpolated or calendar-certified.
The output retains the UTC `left_edge_date`, not an inferred exchange-session
date. Bounds are at most 10,000 rows per symbol and 30,000 total.

The response does not echo adjustment type. Without caller request evidence,
`price_basis="unknown"`. Only the explicit reviewed request enum `"none"`
produces `price_basis="raw"`, with `raw_basis_caller_declared=True`. The request
enums `"split"`, `"all"` and `"raw"` are not accepted by this raw-data seam.
No total return or action adjustment is inferred or performed.

No completion timestamp is manufactured by adding 24 hours. `completed_at`
always stays unknown. An owner may inject a conservative UTC `completed_before`
cutoff, no later than receipt time, declaring that daily bars whose left edges
precede it were already complete. Such rows receive
`completion_status="caller_declared_complete"` and an upper bound `completed_by`;
this is a caller declaration, not calendar authentication. Other rows remain
`completion_status="unknown"`. The collection preserves the injected cutoff
even when empty or when no row precedes it. The integrating owner must establish
calendar/session evidence before supplying that cutoff.

## Next steps

Connect the separately reviewed research-only transport receipts and exact
request context to these normalizers, then use verified completed-session data
for the canonical numerical stock screen. Compute dollar-volume history from
the appropriate individual completed-session price and volume observations,
with explicit window/feed/basis evidence. Run deeper SEC and issuer research
only after numerical screening, retaining period matching, missingness and
receipt-time visibility. Continuous scheduling, source acquisition, calibrated
models, full stock strategy/portfolio evaluation and any execution authorization
remain separate integration tasks; this module adds none of those capabilities.
