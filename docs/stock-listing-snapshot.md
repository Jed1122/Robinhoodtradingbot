# Retrospective provider listing observations

`market_data.stock_listing_snapshot` supplies a pure bounded Alpha Vantage
`LISTING_STATUS` CSV parser, quality profile and one frozen exploratory selector.
It fetches nothing and changes no existing universe, risk, strategy or live gate.

```python
request = StockListingRequest(requested_date, "active")
snapshot = parse_stock_listing_snapshot(
    original_csv, expected_sha256=csv_sha256,
    request=request, received_at=receipt_time,
)
quality = assess_stock_listing_snapshot(snapshot, as_of=utc_cutoff)
```

The explicit request date and state (`active` or `delisted`) are caller-bound
source-query evidence. The returned CSV does not independently echo/authenticate
that date. Retrieval availability is the aware UTC receipt time, never the requested
historical date. Historical-date support does not establish an original historical
data vintage, complete membership, or historical ticker identity. Current aliases
can appear in a retrospectively requested listing response. Source `Stock` is not
proof of ordinary common stock, permanent security identity or broker eligibility.

The parser rehashes unchanged UTF-8 bytes, requires the seven exact ordered columns
`symbol,name,exchange,assetType,ipoDate,delistingDate,status`, and accepts at most
8 MiB, 30,000 data rows and 4,096 characters per field. Malformed CSV, short/extra
rows, invalid nonmissing dates and control characters fail with the fixed error
`stock_listing_snapshot_invalid`. Header-only input is explicitly empty. Both
CRLF and LF and quoted commas are accepted. No row is silently skipped.

All decoded native fields, whitespace, row order and zero-based original indexes
are retained. Date `null` and empty date cells both parse to `None`, while their
distinct original strings and missingness counts survive. Empty identity fields,
unknown asset/status labels, future IPO dates, lifecycle contradictions and every
duplicate remain visible. Names are data, never instructions or classifications.

The quality profile counts rows, distinct native symbol strings, asset labels,
exchanges/statuses, empty fields and date missingness. Duplicate groups retain all
row indexes; `exact` requires all seven decoded fields to match, while any difference
is `conflicting`. It reports both rows within duplicate groups and extra rows beyond
the first, without deduplicating. Native labels can disagree across a symbol group.
Requested-state/date contradictions restrict the corresponding use; date-boundary
inclusion semantics remain unverified. All authenticity, source/strategy/investment,
historical-vintage, upstream-wire and live qualification flags are fixed false.

## Frozen exploratory panel

`select_stock_history_panel(snapshot, original_source_receipt=...,
expected_source_receipt_sha256=..., original_intent=...,
expected_intent_sha256=...)` revalidates the snapshot and binds the exact original
MCP receipt, request, decoded CSV and receipt clock. It accepts only the explicit
`stock-task4-historical-panel-v1` selection profile; changing a relevant parameter,
adding replacement symbols or substituting numeric values for booleans denies.
The original intent hash also binds the downstream study declaration, without
executing or qualifying that study.

The profile quarantines every row with a repeated ticker across **all asset
types**, including exact duplicates. Remaining candidates require source `Stock`,
NYSE/NASDAQ, exact `[A-Z]{1,4}`, a nonblank name and IPO no later than January 1,
2023. The frozen case-insensitive whole-word name exclusions are
`warrants?|rights?|units?|preferred|depositary|depository|ADR|ADS|ETF|fund|trust`.
These are candidate heuristics, not common-stock certification; they can exclude
operating companies and miss unmarked nonordinary securities.

Order candidates by SHA256 of UTF-8 `stock-task4-historical-panel-v1`, one literal
byte `00`, then UTF-8 symbol, breaking a hash tie by symbol. Retain the first twelve
and their original rows/indexes. Every source row retains all exclusion reasons,
and sequential filter denominators remain explicit. The selected symbol order is
independent of input row order. Fewer than twelve candidates produce an explicitly
incomplete panel; there is no fill from excluded rows. SPY is benchmark-only and
does not enter the stock candidate count. Later missing prices, identity or action
evidence must retain the original slots, with no replacement or surviving-denominator
normalization. The selector exposes no price/outcome-dependent reranking input.

Snapshot, quality and panel hashes bind their source/request/receipt identities,
parsed rows, missingness, duplicate/decision details, intent and scope restrictions.
Decoded MCP CSV is not original upstream HTTP wire. A deterministic sample from a
retrospective provider frame is not a survivorship-free historical common-stock
universe or an investment recommendation.

Next: retain the original selection manifest before additional price inspection,
verify selected issuer/share-class/ticker continuity, and bind calendar, price and
action evidence to the frozen study. Any unavailable slot remains unavailable;
source, historical-vintage, investment and live claims remain unqualified.
