# Current stock earnings and filing-index facts

`trading_bot.market_data.stock_events` provides two pure, bounded normalizers:

```python
normalize_earnings_results(
    payload: Mapping[str, object], *, received_at: datetime,
    observation_sha256: str, requested_symbol: str,
) -> StockEarningsCollection

normalize_filing_index(
    payload: Mapping[str, object], *, received_at: datetime,
    observation_sha256: str, requested_symbol: str,
) -> StockFilingCollection
```

These functions do no I/O and interpret no provider text as instructions. Inputs
are already captured structured results. The caller must separately verify the
retained observation bytes and their authenticated transport provenance. The
receipt's SHA-256 is explicitly caller-declared; normalization does not make it
authenticated evidence. Errors use `ValueError("stock_events_invalid")` without
including provider values.

The shape follows the committed
[13-tool schema snapshot](../src/trading_bot/brokers/schema_snapshots/robinhood_stock_research.20261021.json)
and the enabled official tool declarations inspected as metadata only. All tests
use fictional schema-derived fixtures. No provider response or private capture
is a test fixture.

## Receipt and availability

Every immutable record and collection retains a `StockEventReceipt` containing
the exact tool, UTC `received_at`, and observation hash. `available_at` always
equals this receipt time. Fiscal periods, scheduled report dates and SEC filing
dates remain separate facts; none becomes a historical availability timestamp.
`publication_at` remains `None`, since neither supported response supplies an
exact publication timestamp. In particular, `am`/`pm` is a scheduling category,
not an exact event time.

Collections expose `records` as a tuple, `requested_symbol`, `null_row_count`,
`response_results_missing`, `scope_verified` and a reproducible `observation_hash`
under the `stock-events-normalized-v1` namespace. Hashes bind the normalized
facts, receipts, request context and missingness; they do not assess confidence
or source authenticity. Payload mutation cannot alter an already normalized
collection. All record and collection qualification, strategy, trading and live
flags are fixed false. No forecast, strategy choice, expected move, earnings-beat
confidence, revision history, investment eligibility or order is produced.

## Earnings results

The requested ticker must already be canonical uppercase, matching the stock
scanner's ticker syntax. Each nonnull result must echo that exact symbol.
Quarter keys must be unique and strictly ascending by fiscal year and quarter,
as declared by the tool; conflicting or repeated quarters reject. At most eight
rows are accepted, including nulls.

`StockEarningsEvent` retains `fiscal_year`, `fiscal_quarter`, signed nullable
Decimal `eps_actual` and `eps_estimate`, nullable `report_date`, `report_timing`
and `report_verified`, and `report_scheduled` indicating whether the source
supplied a report block. `reported` means actual EPS was present. Missing EPS
stays `None`, including a genuine zero estimate or actual remaining distinct
from missing data. Decimal values must be finite and safely bounded.

A future scheduled date is valid when actual EPS is absent. A tentative date
keeps `report_verified=False`; even a company-confirmed future schedule does not
become a reported actual. Actual EPS alongside a future report date rejects.
An absent report block leaves scheduling unknown; it does not imply an earnings
date. Fiscal labels are not converted to calendar dates or publication times.

`not_found` can contain only the requested symbol and cannot coexist with result
rows. Null result entries are counted and leave symbol scope unverified. A null
results array remains explicitly missing. An empty array with no `not_found`
means no retained earnings entries, and supplies no independent symbol echo, so
`scope_verified=False`. A matching explicit `not_found` verifies only the symbol
scope of that absence; it does not imply available earnings or qualification.

## SEC filing-index page

The top-level echoed symbol must exactly match the canonical requested ticker.
Each immutable `StockFiling` retains the original `filing_id`, `date_filed`,
`form_type` and `description`. Dates must be valid and no later than the receipt's
UTC date. Rows must be most-recent-first by filing date; different filing IDs on
the same date are permitted. Duplicate or conflicting filing IDs reject.

The reviewed response has no URL field. `source_url` therefore remains `None`;
the normalizer never constructs a URL from a filing ID or description. Unknown
fields, including claimed source URLs, reject. Supporting a future URL field
would require a separately reviewed schema and SEC-only URL validation.

`next_cursor` retains an optional cursor. Nonempty means `has_more=True` and
`pagination_state="more"`; an explicit empty string means `"terminal"`; absence
means `"unknown"`. `history_complete` is always false, even on a terminal page:
the request may have filtered dates or forms, the response may be null, or rows
may be missing. `scope_verified=True` here means only that the page's explicit
symbol echo matched. It does not certify row coverage, pagination completion,
filing contents, acceptance/publication time or historical completeness.

Local denial bounds are 1,000 filing rows per page (including nulls), 512
characters per filing ID, 64 per form, 4,096 per description and cursor, and
65,536 per ignored guide. Null filing rows and null arrays remain explicit;
they create no records. The normalizer neither follows cursors nor retries.

## Integration and verification

The dossier owner must supply the exact requested symbol and the verified
observation's receipt time/hash. Keep estimates, missing facts, partial pages,
and exact publication-time unknowns visible to downstream readers. This layer
does not fetch SEC contents or interpret filings. Current receipt availability
cannot support a historical point-in-time backtest without separate evidence.

Run the focused fixtures first:

```sh
PYTHONPATH=src python -m pytest tests/unit/market_data/test_stock_events.py
```

Then run market-data/architecture regressions and the repository's central
integration checks. Passing these local fixtures supplies no broker-runtime,
economic, strategy, paper/shadow or live authorization evidence.
