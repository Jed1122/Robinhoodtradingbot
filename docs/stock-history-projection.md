# Per-symbol stock-history projection and quarantine

`market_data.stock_history_projection` is a pure local wrapper around the
unchanged `stock_facts.normalize_daily_bars`. It allows a known company's
invalid series to be quarantined while preserving other companies' valid
series from the same retained observation. It performs no source acquisition,
network, credential, persistence, ranking, investment selection or trading work.
All source, strategy, trading and live qualification flags remain false.

## API and outcomes

```python
normalize_history_by_symbol(
    payload,
    *,
    received_at,
    observation_sha256,
    requested_symbols,
    request_adjustment_type=None,
    completed_before=None,
) -> StockHistoryProjectionBatch
```

The required `requested_symbols` is an immutable unique canonical ticker tuple
of one to ten names. `observation_sha256` references the original retained
observation and remains a caller declaration. `received_at` must be aware UTC.
The optional raw-basis request enum accepts only `"none"` or unknown (`None`).
The optional conservative completion cutoff must be aware UTC and no later
than receipt. Invalid caller declarations fail the entire batch.

The returned frozen batch contains its original `StockObservationReceipt`, full
request tuple, preserved raw-basis/completion declarations, and an immutable
tuple of `StockHistorySymbolOutcome` objects in request order. Every outcome
retains its symbol, immutable projection context, fixed reason codes and one of:

| Status | Meaning | Normalized collection |
| --- | --- | --- |
| `normalized` | The existing normalizer accepted at least one actual bar | Full accepted company collection |
| `unavailable` | Explicit source not-found or no actual accepted bars | Empty collection with missingness/omission evidence |
| `quarantined` | The existing normalizer raised `ValueError` | `None`; no partial company series |

The only reason codes are `symbol_history_normalized`,
`source_symbol_not_found`, `no_normalized_daily_bars` and
`daily_history_validation_failed`. Exception messages, payload excerpts and
provider text never become quarantine reasons. Unexpected programming errors
are not converted into apparently successful company outcomes.

## Whole-batch identity boundary

The entire `data.results`/`data.not_found` scope is validated before company
normalization begins. Results must be an explicit bounded list of correlated
objects with canonical requested symbols. Null or uncorrelated result rows,
duplicates, unrequested names, repeated not-found names, overlaps/conflicts,
unexplained missing symbols, unknown envelope fields and malformed envelopes
raise only `ValueError("stock_history_projection_invalid_batch")`.

History results need not have request order; original source indices retain
their actual positions. This differs from the separate positional financial
response contract. A known symbol's malformed history fields may be quarantined
only after its batch identity is established. The wrapper never assigns an
unknown row to a requested name by position.

The source envelope has at most ten total result/not-found entries. A global
30,000 raw list-entry bound applies before splitting, including null entries
and interpolated rows. The existing normalizer still enforces its 10,000-bar
per-company bound. Thus projection does not multiply the original aggregate
history allowance. A global resource-bound violation fails the whole batch.

## Local projection provenance

Each `StockHistoryProjectionContext` retains:

- the original source observation hash and complete original request tuple;
- the original result index, or explicit original not-found index;
- `source_path`, such as `("data", "results", 2)` or
  `("data", "not_found", 0)`;
- the SHA-256 of its deterministic projected payload encoding.

For a result, the projected envelope contains only that original result row
under `data.results`. For explicit not-found it contains an empty results list
and that one name under `data.not_found`. An original optional `guide` string
is preserved in the projection. No price, order, session or bar is rewritten.
The caller's input object is not mutated or retained by the returned records.

`projected_payload_sha256` hashes UTF-8 JSON with sorted keys, ASCII escaping,
compact separators and nonfinite JSON numbers prohibited. Context identifies
this encoding as `json-ascii-sorted-compact-v1`. It is a hash of a local decoded
payload projection, not a hash of the original transport bytes. Non-JSON or
nonfinite values that cannot be hashed safely fail the batch.

The normalized collection's receipt binds the **projected** hash at the original
receipt time. The context separately binds the original source hash. Both batch
and each outcome/context explicitly set `is_local_projection=True` and
`is_native_provider_payload=False`; callers must retain this context whenever
using a projected collection. The batch's `observation_hash` binds all outcomes,
context, declarations and flags under `stock-history-projection-v1`.

## Quality and availability boundaries

The unchanged normalizer checks positive consistent OHLC, finite Decimal text,
volume, chronology, duplicate timestamps, future left edges, daily/regular
bounds, explicit nonregular sessions and source field types. Any failure
quarantines the company's entire series. The wrapper neither repairs prices
nor discards a bad actual bar to produce a partial company history.

Existing explicit interpolated-bar omissions remain intact, including their
immutable symbol/left-edge provenance and count. Such rows still undergo the
normalizer's quality and chronology validation. An all-interpolated, empty or
null-only series is unavailable. Gaps are not filled, and no contiguous or full
calendar/session coverage is claimed. Raw prices are identified only by the
explicit caller request declaration; completion remains unknown without the
approved injected cutoff. Receipt time remains availability time.

## Next steps

Integrate this wrapper into the retained-observation research reader and retain
both original receipt and projection context. Report normalized, unavailable
and quarantined companies separately. Quarantined histories require a separate
source-quality investigation; valid companies still need explicit raw-basis,
completion, liquidity-window and corporate-action evidence before contributing
to qualified stock analysis. Numerical screening, deeper SEC/issuer research,
continuous scheduling and full strategy/portfolio evaluation remain separate
tasks. This projection adds no promotion or live-trading authority.
