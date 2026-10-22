# SEC companyfacts to exact filing binding

> Use the test-driven workflow in an isolated worktree. Root retains acceptance,
> strategy, runtime, persistence and integration decisions.

Base: 1537d7efadc426ecaad57cd4460a3dd0c252d19e. This is the next pure data step in
the approved individual-stock research plan, not source qualification or deployment.

## Objective and boundaries

Retain original SEC companyfacts bytes and link selected reported USD facts to the
existing submissions receipt by normalized issuer CIK and exact accession. Existing
Robinhood financial periods have no accession; opaque SourceFact event identifiers
and Robinhood filing IDs must not be split or guessed into stronger identities.

The official SEC API description establishes per-CIK companyfacts endpoints, but
native compatibility of this declared profile remains unverified. No HTTP, credential,
private payload, provider, archive, worker, SourceFact or dossier integration occurs.

Owned new paths only:

- `src/trading_bot/market_data/sec_companyfacts.py`
- `tests/unit/market_data/test_sec_companyfacts.py`
- `docs/sec-companyfacts.md`

Frozen public function:

```python
parse_sec_companyfacts_with_filings(
    raw: bytes, *, requested_cik: str, expected_sha256: str,
    received_at: datetime, submissions: SecSubmissionsObservation,
) -> SecCompanyFactsObservation
```

Use frozen/slotted repr-safe observations and fact rows, fixed sanitized
`SecCompanyFactsError("sec_companyfacts_invalid")`, no new dependencies or I/O.
Reparse submissions from original bytes/hash/requested CIK/receipt with the existing
parser, ignoring caller-modified derived values. Reuse its existing filing type and
CIK rules rather than inventing symbol mapping. Companyfacts URL is fixed to
`https://data.sec.gov/api/xbrl/companyfacts/CIK{requested_cik}.json`.

## Declared profile

1. Raw input: immutable bytes, nonempty, at most 8 MiB, valid UTF-8, matching lowercase
   SHA-256, duplicate-key and nonfinite JSON constant denial. Parse decimal JSON values
   as Decimal, never binary float. Receipt is canonical UTC using existing policy.
2. Require top-level object, `cik` and object `facts`. Apply the existing native CIK
   int/string normalization and require both receipts to match the requested CIK.
   Keep original reported CIK type/value. Unknown descriptive metadata stays in bytes.
3. Select exactly `us-gaap` concepts in this order: `Assets`, `StockholdersEquity`,
   `NetIncomeLoss`, `Revenues`. This is an explicit extraction profile, not all financial
   evidence or an investment model. No alternative revenue concept substitution.
   Missing `us-gaap` or missing selected concepts remains explicit absence.
4. Present selected concept must be an object containing object `units`. Only its
   `USD` array is parsed. A missing USD array remains explicit missing USD evidence;
   other unit names are retained in bounded metadata and their values remain only
   in original bytes. Do not normalize units or treat non-USD values as dollars.
   Limit units to 64 per selected concept, names to printable nonempty ASCII <=128.
5. Each selected USD array has at most 20,000 rows, and all four together <=50,000.
   No row dropping, repair, deduplication, sorting, preferred-vintage selection or
   annual/quarterly inference. Preserve repeated/comparative rows at native indexes.
6. Each row is an object requiring `end`, `val`, `accn`, `form`, `filed`. Validate
   accession using existing syntax, canonical ISO dates and form rules. Filed date
   cannot follow the UTC receipt date. Optional `start` must be canonical ISO and
   <=end; absence is None, present null is invalid in this declared profile.
   Do not equate a fact period end with the filing report date. Retain end independently
   without asserting it is historical reported performance rather than a projection.
7. `val` is an exact integer or finite Decimal, excluding booleans/strings/floats.
   Selected numeric values allow <=128 coefficient digits and Decimal exponent
   between -1000 and +1000. Do not round, clamp or fabricate missing values.
8. Optional `fy` is exact integer 1..9999; optional `fp` is nonempty printable ASCII
   <=32; optional `frame` is nonempty printable ASCII <=128. Present null is invalid
   for these known fields in this declared profile. Retain absent states as None.
   Unknown row fields remain in original bytes without invented semantics.
9. Bind only exact accession within reparsed same-CIK recent filings. A matched
   row must have exactly matching reported form and filing date; contradiction
   rejects the whole observation. Do not compare accession prefix to CIK, join by
   date/symbol, or collapse amendments. Unmatched accession is explicitly
   `accession_not_in_recent`, never silently discarded or treated as complete history.

## Output and availability

Observation retains original bytes/hash/receipt/normalized CIK/reported CIK/source
URL and the reparsed submissions observation. All derived fields are init-disabled
and reconstructed from original receipts, following the existing submissions model.
Include selected concept order, explicit missing concepts, concepts missing USD,
and non-USD unit names. Preserve a tuple of fact rows with taxonomy/concept/unit,
native unit-array index, exact Decimal value, period start/end, accession/form/filed,
optional fy/fp/frame, original fact hash/receipt and existing filing object or None.

Every row and observation has `available_at=max(facts receipt, submissions receipt)`
and `publication_at=None`. Receipt binding is conservative local visibility, not
proof of SEC publication time, historical completeness or provider authentication.
Acceptance text remains uninterpreted. Qualification, source/strategy qualification,
investment eligibility, trading/live authorization, provider authentication, native
API compatibility, publication verification and history completeness are init-disabled
exact False flags. No financial ratios, expected return or trade proposals.

## RED/GREEN and return contract

Watch missing-module RED before implementation. Exercise both receipt orderings,
equal receipts and early-cutoff visibility; all CIK representations/wrong issuers;
exact and unmatched accession, amendment and comparative periods; absent concepts/
USD versus null/malformed data; metadata contradiction; duplicate JSON keys, hashes,
nonfinite/bool/string values, numeric limits, malformed final rows, optional fiscal
fields, repeated rows, row/unit/byte limits, forged derived submissions fields and
false flags. No fixtures copied from private provider data.

Run new tests plus SEC submissions, existing stock facts/events and hybrid source/
policy tests. Run Ruff, strict mypy, Bandit and diff checks. Do not start a full suite
while primary is frozen. Commit only owned paths. Return exact revision, diffstat,
actual commands/results, assumptions and unresolved native limits, with
READY_FOR_INTEGRATION or NOT_READY. Root reviews and verifies centrally.
