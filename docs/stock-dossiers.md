# Receipt-visible stock research dossiers

`research.stock_dossiers.build_stock_dossiers` joins already normalized stock
observations into immutable company dossiers. It performs no I/O, source
acquisition, broker calls, persistence, text interpretation or investment
selection. It imports only the pure market-data types and shared clock/hash
utilities. Every dossier fixes qualification, source/strategy qualification,
trading, live authorization and `investment_eligible` to false.

```python
build_stock_dossiers(
    *,
    as_of: datetime,
    facts: tuple[StockFactCollection[StockFundamentals]
                 | StockFactCollection[StockFinancialPeriod], ...],
    history: tuple[StockHistoryProjectionBatch, ...],
    earnings: tuple[StockEarningsCollection, ...],
    filings: tuple[StockFilingCollection, ...],
) -> tuple[StockDossier, ...]
```

## Visibility, identity and duplicate policy

`as_of` must be aware UTC. Only collections whose receipt is at or before that
cutoff contribute data, provenance or company membership. Future-only symbols
do not appear in the output. Fiscal period ends, price-bar left edges, SEC filing
dates and scheduled earnings dates are not availability timestamps. A known
future earnings schedule can remain visible when its source receipt is already
visible; this does not create an actual earnings result.

Companies join by exact canonical ticker strings. No case repair, issuer-name
matching or permanent security identifier is inferred. Records must match their
collection's symbol scope and receipt. Projection outcomes must match the
original batch request, source hash and projected normalized receipt. Requested
or explicitly unavailable/not-found names remain in the visible universe, even
when all their facts are unknown. An observation without any known company
identity cannot create a guessed company dossier.

The assembler rejects repeated visible observations for the same company and
fundamental tool, history tool, earnings tool or filing-index tool. Financial
observations can contain one annual and one quarterly collection per company;
repeated known company/tool/period observations reject, as do repeated period
rows inside a collection. A later receipt is not selected silently. For filing
pages, no automatic pagination merge or overwrite occurs.

A null/empty financial result has no per-company annual/quarterly label in the
upstream immutable type. Distinct original hashes for these unknown-period
absence observations are retained separately. Their period is not inferred from
other companies' records, and `financial_period_unknown` remains explicit.
Repeated original hashes for the same company/tool reject even for unknown
periods. This permits separate retained annual/quarterly null observations
without inventing which one supplied a company-specific period label.

All four input groups must be exact tuples of their declared collection family.
Local denial bounds are 256 total input collections, 1,000 visible companies and
100,000 visible records, including retained history omissions. Invalid inputs
raise `ValueError("stock_dossiers_invalid")`; no partially assembled result is
returned. Source normalization remains an upstream requirement; this join does
not independently authenticate observations or replace their validators.

## Structured output and provenance

Dossiers are sorted by symbol. Each frozen `StockDossier` retains:

- its symbol and canonical UTC `as_of`;
- the optional `StockFundamentals` and annual/quarterly `financial_periods`;
- optional `StockDossierHistory` with the original immutable projection outcome,
  status and counts;
- the original typed `earnings` and `filing_index` records;
- immutable `StockDossierSource` references and collection-level missingness;
- deterministic gap codes and fixed `StockResearchQuestion` objects.

`StockDossierSource` retains the exact tool receipt and original observation
hash, normalized collection hash, request/reported/not-found/unavailable symbol
tuples, null count, missing-results flag, scope flag and source limitations.
These missingness counts refer to the source collection;
they are not silently assigned to one company's metrics. Financial period
identity and filing pagination state remain separate optional fields.

History source references retain the complete `StockHistoryProjectionContext`,
the original batch hash and the projected normalized hash where available.
`is_local_projection` identifies this provenance. The original batch receipt
hash and the projected payload hash remain distinct. A quarantined history has
no normalized collection or normalized observation hash. History references
retain the full original request tuple; their reported/not-found/unavailable
fields and missingness describe the one-symbol local normalized projection.

History counts include actual bars, interpolated omissions, null bars, unknown
completion and unknown price basis. Quarantined-series counts remain `None`;
they do not become zero. Empty/unavailable validated collections can report
actual zero counts. The original outcome retains omission symbol/left-edge
provenance and source reason codes. No partial quarantined series is returned.

Financial periods and source references have deterministic ordering, independent
of input collection order. Price bars and source event records retain their
existing order and values. `dossier_hash` binds the complete dossier under the
`stock-dossier-v1` namespace. It supplies reproducible identity, not source
authenticity or a confidence assessment.

## Questions and research gaps

Questions are fixed source-independent text about financial reconciliation,
history quality, earnings publication, filing contents and source coverage.
Filing descriptions and other source text remain data and cannot become prompts
or instructions. No bullish/bearish claim, score, expected return, potential,
probability, order eligibility or invented source URL is emitted.

Gap codes retain absent fundamentals/financials/events, unknown financial
currency/periods, missing metrics, quarantined/unavailable history, unknown or
caller-declared completion/raw basis, unknown calendar coverage and exact
publication times, source null/missing/unverified scope, unreviewed filing
contents and incomplete pagination. Exact bar-completion time remains unknown
even when an upstream conservative cutoff declares completion. A terminal
filing page removes the incomplete-pagination gap but never certifies complete
filing history; `filing_history_completeness_unknown` remains.

## Next steps

The integration owner can bind verified retained receipts to these pure inputs
and persist a separate dashboard report. Keep original receipt and projection
context alongside each dossier. Resolve data-quality quarantines, verify period
units/currency and source coverage, follow reviewed filing pagination, and review
SEC/issuer contents before drawing company conclusions. Continuous stock
research, numerical screening, model calibration, strategy/portfolio evaluation
and paper/live progression require their own evidence and remain separate work.
