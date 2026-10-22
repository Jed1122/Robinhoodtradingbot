# Native broker filing facts and evidence binding

`market_data.stock_filing_facts` supplies pure normalizers for the pinned Robinhood
stock-research catalog/facts shapes and a single-filing evidence binder. It performs
no I/O, provider call, credential operation, acquisition, cursor following, accounting,
strategy evaluation or investment decision. Tests use fictional payloads only.
Runtime acquisition, original archive rehashing and dossier integration belong to the
integration owner. A locally valid collection is not authenticated financial evidence.

## Public interface

```python
catalog = normalize_filing_catalog(
    catalog_payload,
    received_at=catalog_receipt,
    observation_sha256=catalog_observation_hash,
    requested_filing_id=opaque_filing_id,
    requested_offset=0,
)
facts = normalize_filing_facts(
    facts_payload,
    received_at=facts_receipt,
    observation_sha256=facts_observation_hash,
    requested_filing_ids=(opaque_filing_id,),
    requested_concepts=exact_native_concept_names,
)
evidence = bind_filing_evidence(index, catalog, facts, as_of=utc_cutoff)
```

All new models are frozen, slotted and repr-safe. `StockFilingReceipt` retains the
exact tool, canonical UTC receipt and lowercase caller-declared observation hash.
It has `hash_is_caller_declared=True`; that flag does not authenticate the provider.
Collection availability is receipt time. Guide text is validated but retained only
by the external raw archive, never in these models or as instructions.

`StockFilingCatalog` retains `receipt`, `requested_filing_id`, `requested_offset`,
`records`, `count`, `next_offset_present`, `next_offset`, `concepts_missing` and
`null_row_indices`. `history_complete` is permanently false. Each
`StockFilingConcept` retains `row_index`, `concept`, `is_text_block`,
`axis_names_raw`, `periods`, `periods_missing`, `null_period_indices` and `receipt`.
Each nested `StockFilingPeriod` retains its native `row_index`, `period`, parsed
`end_date`, `start_date_present`, `start_date_raw`, parsed `start_date` and receipt.

`StockFilingFacts` retains `receipt`, `requested_filing_ids`, `requested_concepts`,
`records`, `facts_missing`, `null_row_indices` and derived
`missing_requested_concepts`. Each `StockFilingFact` retains native `row_index`,
`filing_id`, `concept`, `entity`, `period`, `axes_raw`, `char_value`, parsed
`end_date` and receipt. Optional fields have exact `*_present` flags and `*_raw`
values for `start_date`, `unit`, `value` and `decimals`. Parsed `start_date` and
`numeric_value` are init-disabled derivations.

The provider's native spelling `axises` maps to `axes_raw`. Null axes mean unknown;
an empty tuple means explicitly empty. Native entity, filing ID, concept, period
and unit strings are not interpreted as CIK, accession, fiscal period, consolidated
accounting context or verified currency. No symbol/issuer mapping is inferred.

## Closed profile and limits

Payloads must be exact JSON-like dictionaries with exactly `data` and `guide`.
Closed data/row keys follow the pinned stock schema. Unknown fields, incompatible
types and nonfinite JSON numbers reject the entire normalization. The canonical
JSON envelope uses sorted keys, ASCII escaping and compact separators, is counted
incrementally, and cannot exceed 8 MiB. Required guide text is at most 1 MiB UTF-8.

Catalog `concepts` may be null or contain at most 5,000 nullable rows. Concept
names are unique on the observed page. Period arrays may be null or contain at most
256 nullable records, with no duplicate complete period identity. Count is an exact
integer 0 through `2**63-1` and is not interpreted as returned-row count or history
completeness. Requested offset is 0 through `2**31-1`; a next pointer is absent,
null or any exact nonnegative integer accepted by the envelope. A next pointer
outside the request range remains evidence and is never automatically requested.

Fact requests use an exact tuple of 1–3 unique filing IDs and 1–10 unique concepts.
The facts array may be null or contain at most 20,000 nullable rows. Every returned
filing ID/concept must be in scope. Repeated and comparative rows retain their
native indexes; no row is deduplicated, sorted, selected or repaired. Null indexes
and whole-array null states remain explicit. Source row and period indexes must
exactly account for every normalized slot.

Filing IDs, concept/entity/period/axis names are nonempty printable text up to 512
characters. Axis arrays contain at most 64 unique names. Units are reported text
up to 128 characters, allowing empty. Dates are canonical `YYYY-MM-DD`; non-null
starts cannot follow ends. Omitted starts remain omitted. No instantaneous,
duration, fiscal or publication semantics are invented from dates or native labels.

Character values are uninterpreted exact strings up to 65,536 characters, allow
whitespace/newlines and reject NUL. They are never rendered as HTML, followed as
instructions or used as numeric fallback. Optional numeric `value` may be absent,
null or empty, each preserving its distinct state and yielding `numeric_value=None`.
Nonempty values must match the frozen decimal grammar, fit 512 characters, and
parse to an exact finite Decimal with at most 128 coefficient digits and exponent
from -1000 through +1000. Booleans, binary floats, noncanonical numeric text and
invalid values reject. Negative values and explicit zero remain their actual values.

Optional `decimals` is null or an exact integer -1000 through +1000. It is retained
as metadata: the normalizer never multiplies a value by `10**decimals`. No ratios,
tax values or missing financial metrics are fabricated.

## Binding, hashes and provenance boundaries

Binding accepts exact normalized collection classes, validates permanent flags and
receipt consistency, and reconstructs checked index/catalog/facts collections. It
returns fresh objects with numeric values derived again from native strings. The
legacy index is reconstructed through its existing normalizer; catalog/facts use
closed native-state projections with an empty guide placeholder. The original
guide and original HTTP bytes cannot be reconstructed from normalized objects.
The runtime must independently rehash all contributing capture archives.

Facts must request precisely the catalog's one opaque filing ID, with exactly one
matching index record. Every requested concept must exist on that page, be non-text
and have explicitly empty axes. Every returned fact must have explicitly empty axes
and exactly one catalog period matching native period, end date and the exact start
presence/raw state. Absent start and explicit null start are distinct identities.
Unknown/dimensional context, missing or contradictory periods and late receipts
deny binding. Missing fact concepts or numeric values remain explicit evidence gaps.

`StockFilingEvidence` retains the reconstructed `index`, `catalog`, `facts`, matched
existing `filing` and canonical `as_of`. Its `available_at` is the latest of the
three receipts, all of which must be no later than `as_of`. The filing's own
availability remains independent. `publication_at` remains `None` in every new
model; no filed date or receipt is relabeled as historical publication.

`catalog_hash`, `facts_hash` and `evidence_hash` use shared `content_hash` with
`stock-filing-catalog-v1`, `stock-filing-facts-v1` and `stock-filing-evidence-v1` tags.
The facts preimage binds native raw optional states/strings and source identities,
including lexically distinct equal numbers; redundant parsed Decimal values are
excluded so the full native exponent range does not inherit the narrower trading
Decimal codec. The binder still validates the exact parsed Decimal representation.

All new models have init-disabled exact false `qualified`, `source_qualified`,
`strategy_qualified`, `investment_eligible`, `trading_enabled` and `live_authorized`
flags. Validation errors expose only `ValueError("stock_filing_facts_invalid")`.
No input or diagnostic is printed or logged. Checks establish internal consistency,
not sealed provenance: a fully consistent replacement model with caller-declared
hashes cannot authenticate a source. No historical completeness, source acceptance,
financial interpretation, strategy promotion or order permission follows.

## Next steps

Root must independently review and integrate the exact change, bind rehashed actual
index/catalog/facts captures through the runtime consumer, and report explicit
native scope and remaining gaps. Unit/entity semantics, issuer/security identity,
financial-period comparisons, source acceptance, point-in-time history and strategy
validation remain separate work. This adapter does not reinterpret the separate
SEC companyfacts path or remove the stock price-history qualification blocker.
