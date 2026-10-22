# Pure SEC companyfacts receipt and filing binding

`market_data.sec_companyfacts` retains original companyfacts bytes and binds
selected reported USD facts to the existing SEC submissions receipt. This is an
**offline declared profile**. Native SEC API compatibility remains unverified;
fictional fixtures establish local behavior, not provider compatibility or source
qualification. The [SEC API description](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes per-CIK companyfacts endpoints but does not establish every local rule
below.

This module performs no I/O, HTTP, credential operation, archive/database access,
scheduling, symbol mapping or investment decision. It changes neither `SourceFact`
nor the existing Robinhood financial periods, dossiers, strategy/risk controls,
blocked Alpaca SIP route or live authorization.

## Interface and retained evidence

```python
observation = parse_sec_companyfacts_with_filings(
    original_companyfacts_bytes,
    requested_cik="0000000001",
    expected_sha256=companyfacts_body_sha256,
    received_at=companyfacts_utc_receipt,
    submissions=submissions_observation,
)
```

The function returns a frozen/slotted, repr-safe `SecCompanyFactsObservation`:

- `original_body`, `body_sha256`, `received_at`, `requested_cik` and the reparsed
  `submissions` observation retain the two caller-declared receipts.
- `reported_cik` preserves the original integer/string representation;
  `normalized_cik` is the matching ten-digit positive issuer CIK.
- `source_url` is fixed to
  `https://data.sec.gov/api/xbrl/companyfacts/CIK{requested_cik}.json`.
- `selected_concepts` is always Assets, StockholdersEquity, NetIncomeLoss, Revenues,
  in that order. `missing_concepts` and `concepts_missing_usd` distinguish absence.
- `non_usd_units` contains `(concept, unit_names)` tuples for each present selected
  concept, including empty unit-name tuples. Concepts follow the extraction order;
  unit names retain their original order. Non-USD values remain only in raw bytes.
- `records` contains immutable `SecCompanyFact` rows in concept order and native
  USD-array order. Duplicate, comparative and amended rows are preserved.

Observation-derived fields are init-disabled and reconstructed from original
receipts. The incoming submissions observation is reparsed using its original
bytes/hash/requested CIK/receipt through `parse_sec_submissions`; caller-modified
derived fields are ignored. Original hashes establish local integrity only, not
transport authentication or authenticity of caller-declared receipt times.

Each fact retains `taxonomy="us-gaap"`, `concept`, `unit="USD"`, native
`row_index`, exact Decimal `value`, `period_start`, `period_end`,
`accession_number`, `form`, `filing_date`, optional `fiscal_year`, `fiscal_period`
and `frame`, plus the original fact `body_sha256`, `received_at` and
`submissions_received_at`. `filing` references the existing reparsed
`SecSubmissionFiling` or is `None`; `binding_status` is respectively `matched` or
`accession_not_in_recent`.

## Declared validation and binding rules

Raw input must be immutable, nonempty UTF-8 bytes no larger than 8 MiB, with a
matching lowercase SHA-256. Duplicate JSON keys and nonfinite JSON constants deny
the whole observation. Decimal JSON numbers never pass through binary float.
Receipts use the existing UTC policy and are retained with canonical UTC timezone.

Top-level `cik` and object `facts` are required. Both receipts must match the
requested issuer under existing SEC CIK normalization. Missing `us-gaap` or a
selected concept is explicit absence. A present selected concept requires object
`units`; missing USD is distinct from an empty USD array. Present null/malformed
known fields are invalid. Unknown descriptive fields, other taxonomies and
unselected concepts remain uninterpreted original data.

Each selected concept allows at most 64 unit names, each nonempty printable ASCII
up to 128 characters. Its USD array allows at most 20,000 rows; all selected arrays
together allow at most 50,000. These are local resource bounds, not provider limits.
No partial observation is returned when a later row fails.

Rows require `end`, `val`, `accn`, `form` and `filed`. Accession syntax, form and
canonical ISO date rules reuse the existing submissions validators/type. The
reported filed date cannot follow the facts receipt's UTC date. Optional `start`
must be a canonical ISO date no later than end. End remains independent of the
filing's report date and is not asserted to describe historical rather than
projected performance.

Values must be exact JSON integers or finite Decimals, excluding bools and strings,
with at most 128 coefficient digits and exponent from -1000 through +1000.
Nothing is rounded, clamped or filled. Optional `fy` is exact integer 1–9999;
`fp` and `frame` are nonempty printable ASCII up to 32 and 128 characters.
Known optional fields reject present null and retain absence as `None`.

Binding uses only the exact accession inside the reparsed same-CIK recent filings.
A matched accession must have identical reported form and filing date, otherwise
the entire observation fails. Accession prefixes are not treated as issuer CIKs.
The parser never joins by symbol, date, financial period or opaque Robinhood filing
ID. Unmatched accessions remain explicit because recent filings and uncollected
history references do not establish complete filing coverage. No row is dropped,
deduplicated, sorted, preferred or assigned an annual/quarterly interpretation.

## Availability and permanent limits

Both observation and fact-row `available_at` equal the later receipt timestamp.
A consumer must exclude the bound result at any earlier cutoff; this module adds
no backtest or dossier admission path. `publication_at` remains `None`;
filing, report and financial-period dates never backdate availability. The existing
filing's acceptance text remains uninterpreted and does not establish publication
time. SEC [access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
describes delayed dissemination and subsequent corrections/deletions.

Both types inherit init-disabled exact false flags: `qualified`,
`source_qualified`, `strategy_qualified`, `investment_eligible`, `trading_enabled`,
`live_authorized`, `provider_authenticated`, `native_api_compatibility_verified`,
`publication_verified`, `history_complete` and `acceptance_timezone_verified`.
Errors expose only `SecCompanyFactsError("sec_companyfacts_invalid")`; this module
does not print or log rejected data.

## Verification and next steps

Tests use fictional receipts and cover original-byte integrity, issuer identity,
exact matches and contradictions, missing evidence, row preservation, conservative
availability, optional fiscal fields, numeric/resource bounds and forged derived
submissions fields. This is not native provider, historical point-in-time,
out-of-sample, profitability or execution evidence.

Root must independently review/integrate the change and later verify the detailed
native profile with permitted retained public evidence. Issuer/security resolution,
historical completeness, current research/dossier integration, period/unit-aware
financial analysis, strategy validation and execution authorization remain separate
steps. No credentials or paid data are required for this pure implementation.
