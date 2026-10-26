# One-event stock split comparison

`market_data.stock_split_comparison` compares a single stock's retained raw and
split-adjusted daily regular-session observations. It is pure: no file, network,
credential, broker, calendar, issuer, database or technical-admission operation.
The module does not change legacy history normalizers or native missing fields.

```python
request = StockSplitRequest(symbol, start_time, end_time, adjustment_type)
series = parse_stock_split_series(
    original_content_json,
    expected_sha256=content_sha256,
    request=request,
    received_at=receipt_time,
)
comparison = compare_stock_split_series(
    raw=raw_series,
    split=split_series,
    event_date=frozen_effective_date,
    new_shares_per_old_share=Fraction(10, 1),
    as_of=decision_cutoff,
)
```

The original bytes are the UTF-8 bytes of the MCP text content's JSON object,
containing exactly `data` and `guide`. They are not re-encoded structured content,
the outer tool-result wrapper or original upstream HTTP wire. The caller must
retain and bind the actual request/receipt evidence independently. The expected
SHA-256 is checked against unchanged supplied bytes; it does not authenticate a
provider. `is_original_upstream_wire` is permanently false.

Requests fix `get_equity_historicals`, one canonical symbol, `day`, `regular`, and
explicit aware UTC start/end times. The two requests must differ only in their
`none` versus `split` adjustment. Receipts and `as_of` must be aware UTC, and both
receipts must be visible by `as_of`. Availability is the later receipt, never a
historical bar date. The caller freezes the event date and positive exact
`Fraction(new_shares, old_shares)` before inspecting results.

The parser rejects altered hashes, duplicate JSON keys, unsupported fields,
wrong symbol/interval/bounds, unsafe numbers, invalid OHLC, negative/noninteger
volume, duplicated/reversed labels and out-of-request/future labels. Each body
is at most 8 MiB, guide at most 1 MiB, and a series at most 10,000 bar slots.
Submicrosecond timestamps that the datetime model cannot retain reject rather
than truncate. Labels must be within the declared start/end range; this check
does not establish provider endpoint inclusivity or exchange-session coverage.

Missing interpolation stays `None`; explicit true with positive volume is a
source contradiction and rejects. Zero volume is retained without inferring
interpolation. Missing results, missing bar arrays, explicit not-found responses,
empty arrays and null bar-slot indices remain auditable. Unknown/empty session
markers remain unknown/empty; explicit nonregular sessions reject. Original
bytes retain every source spelling and omission.

Comparison reparses both original bodies and rejects changed derived objects,
requests or flags. Matching timestamp sets must have observations before and on
or after the declared effective date. For every OHLC field and volume, it finds
one exact `split/raw` factor on each side. The price cross-ratio must equal the
inverse share ratio and the volume cross-ratio the share ratio. This permits a
common later split scale without assuming the post-event factor is one. It uses
`Fraction` arithmetic, no fitted tolerance or caller Decimal precision.

- `sample_consistent`: all observed factors are constant and both event ratios match.
- `sample_inconsistent`: complete matching observed inputs have constant factors,
  but a predicted event ratio differs.
- `unresolved`: empty/missing/null observations, unequal timestamps, absent event
  sides, explicit interpolated rows, zero volume or varying factors.

A consistent result does not prove that the source returned every session or
that other actions are covered. The UTC date of a source label supplies the
comparison partition; it does not authenticate an exchange-session date or close.
Calendar and issuer authentication are permanently false. All source, strategy,
investment, trading and live qualification flags remain false. The deterministic
`evidence_hash` binds request/content hashes, receipts, parsed rows/missingness,
cutoff, event/ratio, exact factors, result and limitations.

Next: independently bind authentic issuer/calendar evidence and reconstruct the
actual retained pair. A separately reviewed source-neutral input contract must
decide any descriptive technical use; this comparison provides no such admission,
total-return claim, historical point-in-time availability or investment authority.
