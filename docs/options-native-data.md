# Native options research data

## Implementation status

Native SPY minute-bar scanning, canonical resource controls, private bar storage
and byte-bound native bar/definition readers are implemented. Scoped source-evidence
contracts and recomputation are implemented, but no actual provider-era semantic
rule is approved. Evidence-bound regular-session and contract-chain assembly are
implemented, along with the independent imported-data shortlist; complete quote coverage remains subsequent work in
the [approved integration plan](superpowers/plans/2026-09-25-native-options-data-integration.md).
There is not yet a native-bars CLI or a real-data economic result.

## Independently verified imported shortlist

`options-shortlist-input-v2` binds explicit private bar/definition manifests, source
claims and session/contract references to the canonical configuration. Every call
rehashes and reparses the required source evidence and assembles canonical inputs
again. There is no `verified=true` switch, accepted saved verification token, or
quote/return input. Closed request fields, aggregate record/byte bounds and code
identity checks stay in force. Results are path-free diagnostics, not trust tokens.

The bridge calls the unchanged v1 identity, eligibility and ranking functions:
previous regular-session close, one call and put, common expiry closest to 30 days
within 21–45, earlier-expiry and lower-strike ties. V1 imported requests still deny;
explicit original v1 wire/decision hashes are regression-tested. The synthetic-only
replay has not been opened to imported data.

All five input roles must verify independently. An unrelated quote-semantics denial
remains visible but does not block shortlisting; it still blocks dependent quote
acquisition work. Source mutation, altered canonical result hashes or a changed
rulebook forces re-evaluation. Whole-archive hashes are diagnostic: future records,
file-order changes and later audit invalidations cannot rewrite as-known candidates.
Later invalidations remain in the verification report and must block affected future
use, even when historical selection status is `selected`.

The native simulation profile explicitly enables both intake and the existing
research shortlist. Base/production defaults remain disabled; risk limits and live
locks are unchanged. This profile change invalidates older native-profile identities
and requires re-verification/restaging, not automatic reuse. Only test-private
fabricated rules currently exercise successful selections; real imports still deny.

## Regular-session inputs

`assemble_session_inputs` requires exact, hash-bound prior/current sessions,
complete intervening calendar declarations, corporate-action coverage and bar
publication facts. It does not infer holidays from weekdays. Synthetic tests cover
both DST changes, explicit exceptional closures and early closes.

Only accepted regular-session rows from one publisher/instrument series contribute
to unadjusted first/max/min/last/summed-volume aggregation. After-hours observations,
rejected observations and duplicate observations remain separately accounted for.
A degraded provider day stays denied even if an offending observation is outside
regular hours. Missing final minutes require exact verified no-trade coverage; they
are never interpolated. Dividends remain context, while splits and unsupported
deliverable/reference changes deny assembly.

The close is labelled `source_last_trade`, not an official consolidated close or an
executable quote. Availability uses the verified as-of upper bound, never an assumed
interval-end publication. Canonical fact hashes must match the actual supplied
values, and the native manifest, configuration and installed source code must still
match verification. These diagnostic records are not reusable trust certificates;
the imported-data bridge must reverify their source bundle. All authority flags
remain false, and the empty actual-source rulebook still blocks real qualification.

## As-known definition inputs

`assemble_definition_inputs` reconstructs a complete explicitly evidenced baseline
plus visible additions, modifications and deletions. Every native row needs a verified
publication instant and a unique dated publisher/instrument-to-symbol mapping. Exact
duplicates are collapsed; conflicting simultaneous revisions, unexplained deletes
and unknown update actions deny. Historical ID reuse needs non-overlapping half-open
mapping windows. Partial-symbol metadata needs explicit scoped coverage, not an
automatic pass or blanket rejection.

Independent pinned term and calendar facts must establish standard SPY/USD contracts:
100-share deliverable and premium multiplier, American exercise, physical PM
settlement, historical tick and eligible sessions, exact OCC strike/type/expiry,
last trading and expected settlement times. A native multiplier sentinel remains
unknown. Date-only midnight expiry never supplies a trading deadline. There are no
generic multiplier, settlement-delay or adjusted-contract fallbacks.

All active members are constructed before ranking. More than 10,000 contracts denies
the whole chain; nothing is silently trimmed to nearby strikes. The legacy native
manifest is unchanged and its completeness/availability flags stay false. New
derived records are labelled imported and remain research-only. Their causal hash
binds visible native rows, canonical terms and installed code/configuration/rulebook;
later native records or a one-nanosecond-late publication cannot alter that identity.
The complete source archive/claim hashes remain separately auditable.

Only fabricated, fixed-protocol source fixtures currently exercise successful
enrichment. No actual provider parser/term protocol has been approved or installed.

## Private storage and readers

`validate_bar_batch` accepts exactly the bar DBN file, `metadata.json`,
`condition.json` and `manifest.json`, with matching query, customization, size and
hash declarations. Provider URLs are inert and excluded from published reports.
Condition dates and optional last-modified dates are preserved without inventing a
publication instant. No provider request or credential is used.

`stage_bars` partitions raw integer observations by UTC interval date in bounded
Parquet parts. Rejected and duplicate rows retain their ordinal, native record hash
and raw archive hash. The content-addressed manifest is published last, only after
full stream validation and a final source recheck. Identical repeats are idempotent;
conflicting content cannot overwrite earlier artifacts. An interrupted publication
may leave task-owned orphan parts, which are not evidence of a completed import.

Sources and destinations must be outside Git checkouts, with owner-only 0700/0600
directories/files. Symlink traversal, hard-linked files, wrong ownership and broader
permissions deny. Original source archives are not modified or deleted.

`verify_bar_stage` reconstructs row counts, quality/disposition counts and native
record hashes using the exact private snapshots it hashed. Readers validate all
parts before yielding a requested window and query those same snapshots; a later
source-path replacement cannot inherit earlier verification. Existing definition
staging remains v1; its new reader preserves all native columns and nullable terms,
including unknown multipliers. This integration remains SPY-only.

Neither schema is canonical market evidence. Source publication rules, sessions,
corporate actions and contract-term authority remain unverified.

## Historical source-evidence boundary

`options-source-evidence-v1` contains strict claims and explicit private artifact
references. The verifier rechecks file bytes, exact source/schema/era/coverage,
pinned reference-document identities, installed verifier/rulebook identities and
the canonical configuration identity. It never treats a successful download, usage
attestation, caller `verified=true`, or a current public document as a historical
publication guarantee. Unknown fields, dispatch names and substituted scopes deny.

Publication visibility is compared using native integer nanoseconds before any
datetime conversion; availability is rounded upward at a microsecond boundary.
Missing publication remains unknown. A claimed publication cannot postdate its
recorded observation. No default `available_at=interval_end` is supplied.

Parsed fact hashes are exposed for downstream value comparisons; coverage and
visible-claim hashes also bind their publication/effective-time record envelopes.
Whole-file hashes remain diagnostic, so appending a future record cannot rewrite
an earlier as-known selection. Later-discovered invalidations are reported separately
and never silently backdated. A missing rule for one role does not clear another
role's finding. A verified role alone is not a complete dataset qualification.

The installed rulebook is deliberately empty. The fixed synthetic record parser
and fabricated private test rules validate software behavior only; no CLI, profile
or environment variable can install those fixture rules as provider approvals.

| Required role | Actual evidence status |
| --- | --- |
| Calendar and exceptional sessions | No reviewed source/era rule |
| Historical bar publication and no-trade semantics | No reviewed source/era rule |
| Corporate actions, including explicit empty coverage | No reviewed source/era rule |
| Definition baseline and update/delete semantics | No reviewed source/era rule |
| Contract terms, sessions and deadlines | No reviewed source/era rule |
| Option/underlying quote semantics | No reviewed source/era rule |

This is an explicit real-data qualification blocker, not a completed economic
validation. Diagnostic verification reports have no trusted-result decoder and
retain all four false production, promotion, download and live authority flags.

## Intake boundary

`NativeBarRequest` fixes the query to `XNAS.ITCH`, `ohlcv-1m`, `SPY`, raw-symbol input
and instrument-ID output. `scan_bars` accepts only DBN versions 1–3 with the exact
request bounds and schema. It checks dated, non-overlapping symbol mappings and
monotone minute-start timestamps. This structural mapping check does not prove when
the mapping or a bar was historically available.

Prices remain nullable integer nanounits; timestamps remain integer nanoseconds.
Undefined, nonpositive and inconsistent OHLC values are retained as rejected
observations. Byte-identical same-key repeats are retained as duplicates; conflicting
repeats invalidate the entire stream. Duplicate state is limited to the current minute.
No missing bar is fabricated, and a minute bar is never an executable quote.

Callbacks are provisional until `scan_bars` returns after complete DBN and compressed
EOF, checksum and SHA-256 validation. Consumers must discard staged results on any
failure. Multiple compression frames may encode one DBN document; concatenated DBN
documents, unknown metadata extensions, truncated records and trailing garbage deny.

The existing definitions scanner shares only its byte-reading/decompression helpers;
its request policy, records, validation semantics and evidence format are unchanged.

## Configuration and authority

The one canonical `options.native_data` graph is disabled in ordinary profiles.
`configs/options/native-data/simulation.yaml` explicitly enables offline intake.
PAPER, SHADOW and live modes deny native-data activation. Strict integer ceilings in
the canonical config and safety envelope can only tighten: 512 MiB compressed,
4 GiB expanded, 256 MiB metadata, 10,000,000 records and 1,000,000 native identities.
The decompression window remains capped at 128 MiB. Part/manifest ceilings are also
declared now for the subsequent private-storage implementation.

Every intake profile has immutable false values for historical availability,
economic evidence, production eligibility, evidence promotion, download authorization
and live authorization. Integrity checks do not grant data usage rights or confirm
source semantics. No credentials, network calls, broker capabilities, purchases,
deployment or risk-limit changes are introduced.

Existing capital assumptions and safety controls remain unchanged. These synthetic
tests validate the software boundary, not an options strategy's economic performance.
