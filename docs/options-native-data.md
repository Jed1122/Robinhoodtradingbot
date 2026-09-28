# Native options research data

## Implementation status

Native SPY minute-bar scanning, canonical resource controls, private bar storage
and byte-bound native bar/definition readers are implemented. Scoped source-evidence
contracts and recomputation are implemented, but no actual provider-era semantic
rule is approved. Evidence-bound regular-session and contract-chain assembly are
implemented, along with the independent imported-data shortlist and coverage planner in
the [approved integration plan](superpowers/plans/2026-09-25-native-options-data-integration.md).
The four offline commands below are implemented. There is no real-data economic result.

## Offline operator commands

Use the locked research environment from the implementation checkout. Source files,
input documents and existing output directories must be private, owner-controlled,
outside every Git checkout, and free of symlinks/hardlinks. Directories use mode 0700
and files 0600. These examples are templates, not acquisition or deployment commands:

```sh
PYTHONPATH=src uv run --project research --frozen --no-sync python -m trading_bot.cli.options_research native-bars-import /absolute/private/download --start 2023-01-01T00:00:00.000000Z --end 2026-01-01T00:00:00.000000Z --output-root /absolute/private/research
PYTHONPATH=src uv run --project research --frozen --no-sync python -m trading_bot.cli.options_research native-source-verify /absolute/private/evidence.json --as-of 2023-01-03T14:30:00.000000Z --start 2023-01-02T14:30:00.000000Z --end 2023-01-03T14:30:00.000000Z --output-root /absolute/private/research
PYTHONPATH=src uv run --project research --frozen --no-sync python -m trading_bot.cli.options_research native-options-shortlist /absolute/private/input.json --output-root /absolute/private/research
PYTHONPATH=src uv run --project research --frozen --no-sync python -m trading_bot.cli.options_research options-coverage-manifest /absolute/private/index.json --requirements /absolute/private/study.json --output-root /absolute/private/research
```

All accept `--config-dir` and load `options/native-data/simulation.yaml` with an
explicitly empty environment. UTC arguments require six fractional digits and `Z`;
conversion uses integer arithmetic. No credential, network, rule-injection, live or
purchase flags exist. Omitting `--requirements` produces a blocked diagnostic rather
than inventing a study. A source verification success is scoped only to its submitted
roles, not blanket data qualification.

Exit 0 means the named operation completed: bar **integrity**, scoped verification,
selected research pair, or structural coverage requirements. Exit 2 means semantic
denial/incompleteness or a stale index. Exit 1 means malformed input/storage failure.
None means economic acceptance or permission to buy data/trade. Console output contains
only status, fixed reasons, counts, hashes and four false authority flags; private
reports retain detailed diagnostics under `manifests/<artifact-hash>.json`.

`options-shortlist-index-v1` has exactly `schema` and `entries`; each entry has
`input: {path, sha256, byte_count}` and `expected_result_hash`. The expected hash is
SHA-256 of the exact encoded shortlist report, also printed as `artifact_hash`, not
the causal decision hash. Every referenced input is privately reread, hash checked,
decoded and recomputed. Duplicates, aggregate byte/record excess and mismatched results
deny; the latter publishes no coverage report. Source/code/rule changes therefore
require explicitly regenerating the index. No glob or saved-result trust path exists.

Publication uses the existing atomic no-overwrite store. Repeat execution reproduces
the same artifact; disk-full or interrupted publication does not replace earlier
reports. The fixed v2 code inventory includes this composition and coverage modules;
old v1 identities are unchanged.

## Verification status before final review

The complete locked research-backend selection passes 466 tests, including 17 new
command/pipeline tests. Positive cases use fabricated archives and private test-only
rules; the installed actual-provider rulebook remains empty. Mypy and Bandit pass.
Full branch coverage and independent review are pending at this checkpoint.

## Complete data-coverage planning

`options-study-coverage-v1` is an explicit private declaration, not an automatically
chosen study. It binds preregistration and selection-freeze times, exact decision
range/session IDs, canonical configuration and shortlist code, consumer identity,
contract references and phase-labelled windows. Historical market time remains
separate from registration time: registering a historical study does not claim the
plan existed before those markets traded. No actual study declaration is supplied
by this implementation.

The planner checks both selected contracts, prior initialization, entry, monitoring,
exit before trading ends, underlying quotes, expiry and settlement follow-through.
Times come from explicit requirements and hash-matched canonical contracts, never
an assumed holding period or settlement lag. Warmup is required. Qualification
coverage retains canonical history/fold/opportunity constraints; even complete
engineering-pilot coverage remains `economic_eligible=false`.

Exact source/consumer semantics must appear in each session's recomputed source
findings. Coverage outside their verified era, missing references or state, and
minute-snapshot quotes offered for event-age requirements block completion. The
planner cannot approve actual provider semantics; the shipped source rulebook is
still empty. Later audit invalidations block dependent coverage without deleting
the original as-known candidates. Missing and denied sessions stay in the report.

Compatible adjacent/overlapping per-symbol windows are unioned without clipping
exit/settlement tails at calendar year ends. Disjoint intervals remain separate.
Reverse links retain every requirement and selection. Transport-shaped diagnostic
batches contain at most 100 symbols and only identical dataset/schema/symbology/time
windows. Overlapping event/minute-resolution requests are flagged, not automatically
bought twice. No API, price filter or replacement-candidate behavior is introduced.

`options-acquisition-manifest-v1` reports `requirements_complete` or `blocked`.
Neither status authorizes spending or trading. Its requests describe complete data
obligations, not a ready-to-execute shopping cart. Before using the separately
recorded credit-only grant, the operator must:

1. Reverify existing acquired scopes and subtract already covered data; do not buy it again.
2. Price the exact customized requests for the entire dependent package, including tails
   and underlying/reference requirements. The existing diagnostic remains CBBO-only;
   CMBP descriptors do not unlock it or introduce an acquisition API.
3. Refresh applicable credits and subtract accepted/pending jobs and prior use of the
   grant. Reconcile uncertain acceptance before retries.
4. Proceed only when necessary complete coverage fits that grant without cash,
   subscriptions, a new agreement or other expanded scope. Otherwise retain a
   blocked feasibility report instead of spending on an unusable partial package.

No purchase has been made by this workflow. All production, promotion, download and
live authorization flags are immutable false.

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
