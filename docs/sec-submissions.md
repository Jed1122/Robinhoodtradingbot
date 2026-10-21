# Pure SEC submissions receipt adapter

`market_data.sec_submissions` preserves original response bytes and correlated
filing metadata under an explicit **offline declared profile**. Native SEC API
compatibility has not been verified. Fictional fixtures prove this local profile;
they are not captured provider data or source qualification.

The [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes unauthenticated per-CIK submissions, columnar recent filings and
references to older JSON files. It does not enumerate the complete field profile
used here. The existing `PublicResearchClient.sec_submissions` consumes the same
three required recent-column names, but that consumer is not provider-schema proof.

This module performs no I/O, HTTP, credential operation, archive/database access,
scheduling, investment decision, strategy/risk change or source promotion. It
does not change the existing Robinhood models, `SourceFact`, policy/backtest
interfaces or the blocked Alpaca SIP route.

## Interface and local integrity

```python
observation = parse_sec_submissions(
    raw,
    requested_cik="0000000001",
    expected_sha256=original_body_sha256,
    received_at=utc_receipt,
)
```

The function returns a frozen/slotted `SecSubmissionsObservation` with suppressed
field representation. It retains `original_body`, `body_sha256`, `requested_cik`,
original `reported_cik`, separate `normalized_cik`, UTC `received_at`, source-order
`recent_columns`, `records` and `history_references`. Derived fields are constructed
from the original bytes, rather than accepted as caller-provided parsed results.
`source_url` is the fixed submissions URL derived only from the requested CIK.
`available_at` always equals `received_at`.

Raw input must be immutable UTF-8 JSON bytes, nonempty and at most 2 MiB, matching
the declared lowercase SHA-256. Duplicate JSON keys, nonfinite numeric constants,
malformed input and missing required mappings reject. Unknown issuer metadata
and unknown reference metadata remain available in the original bytes without
interpretation. JSON decimal lexemes use exact Decimal decoding so ignored finite
metadata cannot overflow to a binary-float infinity.

Requested CIK is ten ASCII digits and nonzero. Reported CIK may be an exact positive
integer through 9,999,999,999 or a nonzero one-to-ten-digit ASCII string. Its exact
original value/type is preserved; zero-padding is used only for a separate identity
comparison. Equality establishes consistency, not issuer authentication, historical
ticker mapping or a stable security identity.

## Correlated filing records

The declared profile requires a top-level mapping with `cik` and `filings`, then
`filings.recent` as a mapping. Recent columns `accessionNumber`, `form` and
`filingDate` are required. Every recent entry, including unknown columns, must be a
list with the same length, up to 10,000 rows. Zero rows remain explicit. A malformed
final row rejects the entire observation; rows are not dropped, repaired, sorted
or truncated.

Each immutable `SecSubmissionFiling` retains response hash, receipt, zero-based
`row_index`, `accession_number`, `form`, canonical `filing_date`, `report_date_raw`
and `acceptance_datetime_raw`. Accessions have the declared
`10digits-2digits-6digits` syntax and are unique. Their prefix is not assumed to be
the issuer CIK. Forms are nonempty printable ASCII of at most 32 characters;
`is_amendment` describes only the literal `/A` suffix. Separate amendments remain
separate accessions. Filing dates cannot exceed the UTC receipt date.

Optional `reportDate` and `acceptanceDateTime` columns may be absent. When present,
each value retains its exact string or null. Column names distinguish absence from
null, while empty strings remain empty strings. Nonempty report dates must be
canonical ISO dates. Acceptance text is only validated as printable text of at
most 128 characters, including empty text; it is not parsed as a datetime. Even
a timestamp-looking value supplies no timezone or publication claim.

## Older-file references and fixed limits

Absent `filings.files` becomes `history_references=None`; an explicit empty list
becomes `()`. Present lists have at most 100 unique references. Each immutable
`SecHistoryReference` retains response hash, receipt, source index, `name`,
`filing_count`, `filing_from` and `filing_to`. Names are nonempty visible ASCII up
to 255 characters, with no whitespace, slash, backslash or dot-only name. Counts
are exact integers from zero through `2**63 - 1`, excluding booleans; this is the
root-approved local resource bound, not a verified provider count limit. Date
ranges must be canonical ISO and ordered. Unknown reference metadata remains in
the original bytes. References are untrusted data, not authorized URLs or already
downloaded history. Missing, empty and nonempty references all leave history
completeness unverified.

All three types keep init-disabled exact false flags for `qualified`,
`source_qualified`, `strategy_qualified`, `investment_eligible`, `trading_enabled`,
`live_authorized`, `provider_authenticated`, `publication_verified`,
`history_complete`, `acceptance_timezone_verified` and
`native_api_compatibility_verified`. `publication_at` remains `None`; each object's
`available_at` is its receipt. Validation errors expose only
`SecSubmissionsError("sec_submissions_invalid")`. No body or rejected diagnostic
is printed or logged by this module.

## Next steps

Root must verify the detailed native profile and obtain permitted retained public
source evidence before claiming provider compatibility. Acceptance is not assumed
to be dissemination: SEC documents delayed dissemination and later corrections or
deletions in its [EDGAR access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
Original-byte integrity and current receipt availability cannot backfill historical
point-in-time decisions. Further work includes issuer/security resolution,
exact-filing financial-fact joins, period/unit matching and substantive company
research. Source acceptance, historical completeness, strategy/out-of-sample
cost/tax evidence and execution authorization remain separate root-owned decisions.
