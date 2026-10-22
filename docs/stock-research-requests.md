# Pure stock enrichment request planning

`research.stock_requests.enrichment_requests` creates the complete request list
for enrichment of an already chosen individual-stock research shortlist. It
performs no I/O, provider calls, credential access, runtime composition,
persistence, source interpretation, forecast, scoring or investment decision.
It imports neither broker nor runtime/persistence modules.

```python
enrichment_requests(
    *, symbols: tuple[str, ...], as_of: datetime,
    policy: StockResearchSettings,
) -> tuple[dict[str, object], ...]
```

Every row has exactly `{"tool": name, "arguments": {...}}`. The canonical
`StockResearchSettings` is revalidated using its own model, including when a
caller bypassed initial validation through model construction/copy helpers.
No competing configuration or fallback policy is introduced.

## Inputs and complete-plan denial

Symbols must be an exact nonempty tuple of unique canonical uppercase names,
bounded by `policy.shortlist_count`. The syntax matches the existing stock
research scanner: `[A-Z][A-Z0-9.\-/]{0,14}`. Class-share separators remain exact;
lowercase, whitespace, unsupported punctuation, booleans, nulls and duplicate
names reject. No case repair, symbol remapping or security identity is inferred.

`as_of` must be aware UTC. Invalid inputs, unrepresentable history windows and
plans exceeding `policy.max_calls_per_cycle` raise
`ValueError("stock_requests_invalid")` without returning any partial plan.
Nothing is truncated, deferred, retried or claimed to have been acquired.

The returned outer container is a tuple. Its dictionaries/lists are ordinary
JSON-compatible job inputs, as required by the capture-plan interface. Every
request and invocation owns its own lists; mutation cannot change another
request's symbols. The runtime owner must freeze and validate the **entire**
plan through the existing capture parser before any provider call.

## Reviewed request contract

The plan uses only this subset of the committed 13-tool profile at
`brokers/schema_snapshots/robinhood_stock_research.20261021.json`:

| Order | Tool | Fixed arguments and batch ceiling |
| --- | --- | --- |
| 1 | `get_equity_fundamentals` | `bounds="regular"`; 10 symbols |
| 2 | `get_financials` | `period="annual"`, `limit=8`; 20 symbols |
| 3 | `get_financials` | `period="quarterly"`, `limit=12`; 20 symbols |
| 4 | `get_equity_quotes` | 20 symbols; no unsupported bounds argument |
| 5 | `get_equity_historicals` | `interval="day"`, `bounds="regular"`, `adjustment_type="none"`; 10 symbols |
| 6 | `get_earnings_results` | One request per exact symbol |
| 7 | `get_sec_filing_index` | One initial-page request per exact symbol |

Order within each group follows the supplied symbol tuple. No order, account,
news, LLM, inference, scanner or filing-content tool is added.

History spans midnight UTC at `as_of.date() - 400 days` to midnight UTC at
`as_of.date()`, encoded as RFC-3339 `Z` strings. It does not request the current
UTC day's interval. The range is calendar arithmetic, including leap days;
400 days is not 400 trading sessions. Request bounds do not authenticate an
exchange calendar, prove completion, guarantee coverage or turn missing
interpolation markers into false. `"none"` is the reviewed raw-adjustment request
enum; `"raw"` is not substituted.

The reviewed SEC index input schema supports `symbol`, `cursor`, `form_type`,
`since` and `until`, but **no `limit` parameter**. The planner therefore emits
only `symbol`; it cannot guarantee ten filing rows. It invents neither a limit
nor pagination completion, and follows no cursor. The existing response and
filing normalizer bounds remain separate runtime/data safeguards. Quotes also
have no bounds parameter, so regular-session filtering is not claimed for them.

For `n` symbols, the call count is
`2 * ceil(n/10) + 3 * ceil(n/20) + 2*n`.
The default ten-symbol shortlist produces exactly 25 calls. Twelve symbols
produce 31 calls. Thirteen produce 33 and reject against the canonical maximum
of 32 even if the shortlist setting permits twenty. Daily remaining budget,
cache state and job durability belong to the runtime owner; this pure function
neither reads nor changes them.

## Verification and next steps

Fixture tests pass every successfully generated complete plan through
`runtime.stock_capture.parse_stock_capture_plan`, which checks the pinned
schemas and current local request constraints. This runtime import exists only
in tests. The research implementation reads no schema file and imports no
broker/runtime code. Tests make no external calls or private captures.

The runtime owner can integrate this planner, freeze/validate the complete plan,
reserve the appropriate cycle/daily budget and persist explicit outcomes. Cache,
receipt provenance, restart behavior, schema drift, partial acquisition and
dashboard publication need their existing runtime boundaries. Request planning
does not establish any source, strategy, investment, paper/shadow or live
qualification and confers no order authority.
