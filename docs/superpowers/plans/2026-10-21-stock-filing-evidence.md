# Native broker filing evidence in stock research

Root frozen pure-data contract and integration direction. Base d0acd2a25dd34655b3c4238f18e3b28d4643ea61.
This follows two actual authorized research calls, not invented financial input.
The catalog returned 50 concepts on its first page; ten selected exact non-text,
explicitly axis-free names returned 20 facts, with one native entity and two native
period labels. All 20 have numeric strings, units, explicit empty axes, canonical
end dates and a unique corresponding catalog period. Start dates are omitted in
both; decimals metadata is present. These are observed shapes, not complete API
semantics, unit qualification, entity-to-CIK mapping or investment evidence.
No native payload, symbol, filing ID, value or credential may enter code/fixtures.

## Ownership and interfaces

Isolated pure implementer owns only three new files:

- `src/trading_bot/market_data/stock_filing_facts.py`
- `tests/unit/market_data/test_stock_filing_facts.py`
- `docs/stock-filing-facts.md`

No I/O, SourceFact/strategy/risk/config/worker changes or new dependencies. Root owns
the later runtime/dossier integration and source/strategy acceptance. Read-only
dependencies: stock_events, stock_facts, recording/content_hash and pinned stock
schema snapshot. Reuse current validators/helpers when their exact rules fit.

Frozen public functions:

```python
normalize_filing_catalog(payload, *, received_at, observation_sha256,
                         requested_filing_id, requested_offset=0) -> StockFilingCatalog
normalize_filing_facts(payload, *, received_at, observation_sha256,
                       requested_filing_ids, requested_concepts) -> StockFilingFacts
bind_filing_evidence(index: StockFilingCollection, catalog: StockFilingCatalog,
                     facts: StockFilingFacts, *, as_of: datetime) -> StockFilingEvidence
```

Use frozen/slotted repr-safe models. Every error is fixed
`ValueError("stock_filing_facts_invalid")`, never raw source diagnostics.
All models carry init-disabled exact False qualified/source_qualified/
strategy_qualified/investment_eligible/trading_enabled/live_authorized flags.
Publication remains None; no transport/source authentication or historical
completeness follows from caller-declared observation hashes.

## Common declared profile

Payloads are exact JSON-like dicts. Validate before derivation, bounded to the
existing 8 MiB canonical JSON envelope. Reject duplicate requested identities,
unknown payload/data/row fields, wrong types and nonfinite JSON numbers. The pinned
schema has only `data` and `guide`; guide is required bounded text <=1 MiB, retained
only by the external raw archive and never used as instructions or interpreted here.
Use exact ASCII lowercase SHA-256 and canonical UTC receipt validation.

Strings: filing IDs <=512, concepts/entity/period/axis names <=512, unit text <=128;
nonempty printable text unless explicitly allowed empty below. Do not parse opaque
IDs or native entity text as SEC accessions or CIKs. No issuer/security mapping.
Retain source row indexes, raw optional-value states and null-row indexes; no row
dropping, deduplication, sorting, preferred vintage or accounting inference.

Optional known fields preserve absence versus null versus empty as allowed by the
pinned schema; use explicit `*_present` booleans plus original raw/parsed values.
Canonical dates use YYYY-MM-DD; non-null start <=end. Do not backfill omitted starts,
declare instantaneous/duration/fiscal periods, infer publication or silently repair.
Collection `available_at` is receipt time; hash properties use content_hash with
explicit versioned tags. Inputs are caller-declared provenance until runtime rehash.

## Catalog model

Closed data keys: required concepts/count, optional next_offset. Concepts is null or
a list of at most 5,000 nullable rows. Count is exact nonnegative bounded integer
<=2**63-1; do not equate it to row count or complete history. Offset is exact integer
0..2**31-1. next_offset absent/null/int remains distinct, int >=0. Completeness is
always False; never follow a cursor in this pure module.

Each non-null row has exactly concept/is_text_block/periods/axis_names.
is_text_block is exact bool. concept names must be unique on the observed page;
duplicate/conflicting rows deny rather than collapse. axis_names is null or a list
of <=64 unique bounded strings; None is unknown, () explicit empty. Periods is null
or a list of <=256 nullable records. Each period has required period/end_date and
optional start_date (null or canonical date). Preserve native order/null indexes;
reject duplicate complete period identities instead of selecting a vintage.
Expose `StockFilingCatalog.records`, requested_filing_id/requested_offset, count,
next_offset_present/next_offset, concepts_missing, null_row_indices, receipt,
and catalog_hash. Name each native concept `StockFilingConcept` with nested
`StockFilingPeriod` records and original indexes.

## Facts model

requested_filing_ids is a tuple of 1..3 distinct bounded IDs; requested_concepts is
a tuple of 1..10 distinct bounded names. Closed data has only required facts, null
or list of <=20,000 nullable rows. Every non-null row requires exactly the pinned
required fields: filing_id/concept/entity/period/axises/char_value/end_date, with
optional start_date/unit/value/decimals. Reject out-of-request filing IDs or concepts.
Preserve repeated rows and comparative periods; no fact deduplication.

Native `axises` maps to immutable `axes_raw`, None or tuple of <=64 unique bounded
strings; retain native spelling in documentation. char_value is exact string <=65536
and may be empty or contain whitespace/newlines; reject NUL. It stays uninterpreted,
never HTML, instructions or a numeric fallback.

Known optional fields: start_date null/date; unit null/string (empty allowed);
value null/string (empty allowed); decimals null/exact integer -1000..1000.
Preserve `value_present`, `unit_present`, `start_date_present`, `decimals_present`
and corresponding raw values. Nonempty value strings must be canonical numeric text
matching `[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?`, <=512 chars;
parse exact finite Decimal, <=128 coefficient digits, exponent -1000..1000.
Invalid nonempty numeric text denies the entire collection. Absent/null/empty values
have `numeric_value=None` with distinguishable raw state; never zero. Do not parse
char_value or multiply values by 10**decimals. Unit text is reported/unverified,
not normalized currency. Retain entity text without assuming company identity.

Expose `StockFilingFacts.records` of `StockFilingFact` with original row indexes,
all native fields/states, numeric_value, receipt, requested IDs/concepts,
facts_missing, null_row_indices, explicit missing_requested_concepts and facts_hash.

## Evidence binding

Require exact normalized collection classes; validate/reconstruct their contents
enough to reject caller-forged rows/flags/receipt identities. No caller-supplied
qualifying boolean. Require receipt times <=canonical UTC as_of; otherwise deny
this binding rather than backdate. Combined available_at is the latest of index,
catalog and facts receipt. Filing's own earlier availability stays independent.

Only one requested filing may be bound in this increment: facts requested IDs must
equal the singleton catalog requested ID, and exactly one index record must match it.
Bind on that opaque ID only. Every requested concept must be on the catalog page,
non-text and explicitly empty-axis. Every returned fact must retain explicit empty
axes and have exactly one catalog period matching period/end_date and the exact
start_date-present/raw state. Missing/ambiguous/contradictory context denies binding;
do not infer or flatten dimensions. Missing concepts or numeric values remain
explicit evidence gaps; no ratio or investment interpretation follows.

Return `StockFilingEvidence` containing the original checked index/catalog/facts,
the matched existing StockFiling, as_of, latest available_at, versioned evidence_hash
and permanent false flags. The binder must not promote or reinterpret SourceFact,
the separate SEC companyfacts path or actual broker account/order permissions.

## Verification and return

Observe missing-module RED first. Use fictional payloads only. Cover original indexes,
null/absent/empty optional states, wrong/duplicate request IDs, out-of-scope facts,
repeated comparative facts, unknown/empty/nonempty axes, period contradictions and
ambiguity, dates/offsets/counts/bounds/types, exact Decimal/negative/zero/exponent
values, decimals-not-scaling, char text-not-fallback, late receipts/as_of,
forged model/flag mutations and permanent qualification denial. Run new tests plus
existing stock facts/events, SEC parsers and dossier tests, Ruff/strict mypy/Bandit/
diff checks. Do not start full suite; primary1537 full41316 remains running.
Commit only owned paths and return exact hash, actual tests, assumptions/limitations,
READY_FOR_INTEGRATION or NOT_READY. Root independently reviews and runs actual retained
probe through the integrated runtime path before claiming connected dossier evidence.
