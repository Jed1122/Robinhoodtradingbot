# Pure SEC submissions receipt adapter

Root task contract; base `310bb8e9e2b62cbedfbd57620682eedcaf46ca75`.
Objective: retain an issuer's original filing-metadata response and correlated rows
without losing receipt provenance or inventing historical publication availability.
This extends the stock-data layer alongside the existing Robinhood-specific models.
It performs no I/O and changes no source acceptance, strategy, risk or runtime.

## Evidence and profile limits

The [official SEC API description](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
establishes unauthenticated per-CIK submissions, compact columnar recent filings,
issuer metadata and references to older JSON files. The existing
`PublicResearchClient.sec_submissions` consumes accessionNumber/form/filingDate but
discards original bytes. Direct public JSON was inaccessible through the research
tool; do not claim native response verification or a complete current API schema.
Optional acceptanceDateTime is retained as uninterpreted native text. Never assign
timezone, publication semantics or historical availability to it. SEC notes delayed
dissemination and later corrections/deletions in its
[EDGAR access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

## Owned paths and frozen interface

The isolated implementer may add only:

- `src/trading_bot/market_data/sec_submissions.py`
- `tests/unit/market_data/test_sec_submissions.py`
- `docs/sec-submissions.md`

Read-only dependencies: existing stock_facts/events, hybrid_sources/policy, clock,
recording and decimal helpers. Do not modify them or wrap this into SourceFact yet.

Public function:

```python
parse_sec_submissions(raw: bytes, *, requested_cik: str,
                      expected_sha256: str, received_at: datetime
                      ) -> SecSubmissionsObservation
```

Use frozen/slotted types, raw-byte-containing observation `repr=False`, fixed
`SecSubmissionsError` message `sec_submissions_invalid`, no I/O/dependencies/secrets.
Bound raw bytes to 2 MiB, rows to 10,000, historical references to 100. Reject
duplicate JSON keys, nonfinite JSON numbers, malformed bytes/hash/UTC receipt,
booleans for integer identities/counts, wrong issuer and all invalid correlated rows.
No dropped, repaired or truncated records; preserve source row order.

Requested CIK is exactly ten ASCII digits and nonzero. Native reported `cik` may be
an exact positive integer <=9,999,999,999 or a 1..10 ASCII digit string; retain its
original value and compare a separate zero-padded normalized CIK to the requested
one. A match is consistency only, never issuer authentication or symbol mapping.
Retain the original bytes/hash, fixed submissions URL derived from requested CIK,
UTC receipt time, and `available_at=received_at`.

Require top-level mapping -> filings mapping -> recent mapping. Every recent entry
must be a list of the same length. Require accessionNumber, form and filingDate
columns. Accession syntax is 10digits-2digits-6digits and must be unique; form is
nonempty bounded printable ASCII <=32 characters. Filing dates are canonical ISO
dates, no later than the UTC receipt date. Preserve amendments as separate accessions;
any derived amendment flag describes only the form's `/A` suffix, not completeness.

Retain each row's zero-based index, original accession/form/filing date. Optional
reportDate and acceptanceDateTime columns may be absent; retain each item's exact
string/null and the observation's column names so absence/null/empty remain distinct.
Validate nonempty reportDate as canonical ISO; do not interpret acceptance text
beyond printable text <=128 characters. A future timestamp parser needs verified
native syntax/timezone and publication rules. Unknown columns and issuer metadata
remain available in original bytes; do not infer their semantics or reject extra
top-level metadata. Unknown recent columns still require matching list lengths.

`filings.files` absent -> None; present -> bounded tuple (including empty). Each
reference has required name, filingCount, filingFrom and filingTo. Retain a clean
nonempty ASCII name <=255 without slash/backslash or dot-only path segments, exact
nonnegative bounded integer count and canonical ordered ISO date range; require
unique names. These are untrusted references, not authorized URLs or downloaded
history. Preserve unknown reference metadata in raw bytes. Missing or empty older
references never establish a complete history.

Observation and derived filing/reference objects keep init-disabled exact false
flags for qualified, source_qualified, strategy_qualified, investment_eligible,
trading_enabled and live_authorized. Also preserve provider_authenticated=False,
publication_verified=False, history_complete=False and acceptance_timezone_verified=False;
publication_at stays None. Do not backdate availability to filing/report/acceptance
dates, claim point-in-time completeness, parse filing substance or calculate ratios.

## Verification and return

Observe missing-module RED before implementation. Exercise originals/hash/issuer,
all malformed correlated arrays and a bad final row, duplicate/conflicting
accessions, absent/null/empty optional values, amendments, partial history, UTC
availability, and no implicit source/publication/history qualification.
Run the new tests plus existing source/policy/stock-fact/event tests, Ruff, strict
mypy, Bandit and diff checks. No full suite duplicate while primary is frozen.
Commit only owned paths; return exact diff/commit and actual test results with
READY_FOR_INTEGRATION or NOT_READY. Root performs independent review and central
integration. No credentials, provider acquisition, authenticated requests, broker or
cloud operations, support, purchase, publication or live activation are authorized.
