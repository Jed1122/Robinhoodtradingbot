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
decoded and recomputed. Duplicates, index-entry/aggregate-byte excess and mismatched results
deny; the latter publishes no coverage report. Source/code/rule changes therefore
require explicitly regenerating the index. Per-input record limits still apply;
valid multi-session input is not charged against a single-session record cap.
No glob or saved-result trust path exists.

Publication uses the existing atomic no-overwrite store. Repeat execution reproduces
the same artifact; disk-full or interrupted publication does not replace earlier
reports. The fixed v2 code inventory includes this composition and coverage modules;
old v1 identities are unchanged.

## Verified implementation and remaining limits — 2026-09-28

The complete locked research-backend selection passes **480 tests**, including 17
command/pipeline cases. The main suite passes **5,804 tests**, with 29 skips and one
existing Starlette/httpx warning. Optional backend cases skipped in the main environment
execute in the mandatory research selection without skips. Four encrypted backup tests
still cannot run because `age` is absent; no extra tool was installed.

Branch-enabled overall coverage is **82.50%**, exceeding the unchanged 80% gate; the unchanged 90%
per-critical-file branch gate passes. Ruff, Mypy (261 source files), Bandit, both lock
checks, and both registry dependency advisory audits pass. The research advisory export
excludes only local editable source, which is checked locally, not a registry package.
SBOM/deployment checks: 24 passed, four missing-`age` skips. Generated SBOM stayed in a
private temporary directory; the tracked SBOM and both lockfiles are unchanged. The
generator is an empty-component lock-digest artifact, not a full dependency inventory.
All four deployment shell scripts pass syntax checks. The installed standalone
`docker-compose config --quiet` passes; the `docker compose` plugin is unavailable.
No deployment or authenticated test was run.

One fresh read-only review covered the exact committed implementation range. Its two
Important findings were fixed with seven failing-then-passing regression cases: bind
definition projections before duplicate collapse, and prevent cross-feed quote phase
substitution. The affected 124-test selection and both full suites pass afterward.
There were no Critical or deferred Minor findings in that local review.

### Decision-time mapping correction — 2026-09-29

A subsequent cloud PR review identified an additional current-membership defect.
Every surviving contract now requires exactly one matching dated instrument mapping
at the decision timestamp, in addition to historical receive-time mapping checks.
Expired, remapped and overlapping mappings deny the chain. Adjacent matching renewal
is allowed; deleted members need no active mapping. Three denial cases failed before
the fix; all five new regression cases pass afterward. The complete definition suite
passes 37 tests and the locked research selection passes 485 tests at this checkpoint.
This is a fixture-backed correction, not actual-source qualification.

### Closed source dispatch — 2026-09-29

The approved real-data plan's first task is implemented: immutable versioned parsed
facts, closed parser dispatch and a shared hash-bound artifact read. Legacy synthetic
record/claim/coverage/manifest hashes remain unchanged. Native and reviewed-reference
parser IDs are reserved but deny; the installed actual-source rulebook is still empty.
The [source protocol review](options-source-protocols.md) records the remaining gaps.

Fresh local-workspace verification (including preserved unrelated work): 5,817 main
tests passed, 29 skipped; 498 research-selection tests passed with no skips. Overall
branch-enabled coverage is 82.53%; the unchanged critical branch gate passes. Ruff,
Mypy (262 files), Bandit, both unchanged lockfiles and both locked dependency advisory
audits pass. Documentation/SBOM/deployment selection: 25 passed, four missing-`age`
skips. The four deployment shell scripts and standalone Compose validation pass.
SBOM generation uses temporary outputs; no deployment, acquisition or broker call ran.
These are local results, not a claim of current remote CI, final whole-plan review,
implemented Task 2 adapters or completed economic validation.

### Native event-quote archive — 2026-09-29

The real-data plan's Task 3 now supplies library-only `stage_quotes` and
`verify_quote_stage` in `market_data/databento_quote_store.py`. It accepts exact
`NativeQuoteRequest` scopes for `OPRA.PILLAR/cmbp-1` SPY option raw symbols and
`XNAS.ITCH/mbp-1` SPY underlying quotes. The latter is an exchange-specific feed,
**not a claim of consolidated underlying NBBO**. There is no quote CLI, purchase,
canonical quote consumer or economic evaluation in this slice.

The `native-quotes-v1` manifest binds the existing loaded configuration, complete
raw batch receipt/metadata/conditions/compressed input, and date-partitioned Parquet.
Raw inputs are preserved in private, hash-addressed chunks of at most 1 MiB. Existing
compressed/decompressed/metadata/record/part caps and the 10,000-row part ceiling
remain unchanged. Publication uses the existing no-overwrite/fsync primitives;
all inputs must be private and outside Git, with aliases and hardlinks rejected.
No source file or prior bar archive is modified. A failed publication may leave
complete unreferenced blobs; retry verifies/reuses them without publishing a partial
manifest or deleting earlier artifacts.

The pinned DBN 0.69.0 backend round-trips versions 1–3, retaining every original
80-byte record (including reserved bytes), source ordinal, nanosecond timestamp,
integer price, size, flag, action and dataset-specific field. Metadata schema and
rtype are both checked. Request membership and dated raw-symbol mapping use the
native receive/index timestamp; event time remains independent. Schema/version
compatibility is not evidence that the provider supplied a historical era.

Every occurrence survives, including byte-identical observations and timestamp/
sequence ties. `adjacent_repeat_count` is diagnostic, not deduplication: one source
message can yield multiple native records. At verification, every Parquet row is
compared to a new decode of the exact preserved archive. A changed projection or
ordinal is rejected even with self-consistent replacement manifest/part hashes.
Queries use private snapshots, and DuckDB network/extension access stays disabled.

Zero bids and locked books are retained observations. Undefined/invalid/crossed
prices, missing sizes, incomplete event flags, bad timestamp/book flags and
inconsistent OPRA normalization receive fixed quality reasons. Reset actions are
retained as control records, never accepted entry quotes. `accepted_count` means
only that these conservative intake checks passed; it does not establish a usable
session, an initialized book, firm/executable prices, a fill, or a verified source.
Unknown schemas/actions, unmapped identities, contradictory dated mappings,
truncation, integrity failures and resource-limit breaches deny the entire stage.

Current public [OPRA normalization](https://databento.com/docs/venues-and-datasets/opra-pillar),
[MBP/CMBP layouts](https://databento.com/docs/schemas-and-data-formats/mbp-1), and
[version-pinned publisher definitions](https://github.com/databento/dbn/blob/v0.69.0/rust/dbn/src/publishers.rs)
inform these parser checks. They do not install Task 2 historical semantic rules.
All production, promotion, download, live, historical-availability and economic
eligibility remain false. Testing uses fabricated records only; no actual quote
purchase or intake was performed, and Databento support was not contacted.

Fresh local-workspace verification: 82 new quote cases pass; the mandatory locked
research selection passes 580 tests without skips. The main suite passes 5,817 tests
with 31 skips and one existing warning; 80.39% branch-enabled overall coverage and
the unchanged 90% critical-module branch gate pass. Ruff, Mypy (268 files), Bandit,
both unchanged lockfile checks and both registry dependency audits pass. The research
registry audit excludes only the local editable project, which is tested and scanned
locally. Documentation/SBOM/deployment checks pass 27 tests, with four encrypted-backup
tests skipped because `age` is unavailable. Shell syntax and standalone Compose checks
pass. These are local results including preserved unrelated workspace changes, not
a claim of current remote CI or economic readiness.

Next: complete provider/reference source qualification without support outreach;
build the causal quote stream and freeze the study/coverage requirements; then verify
fresh credits and complete costs before any authorized purchase. Historical
after-cost accounting and uncertainty evaluation follow. Live trading remains blocked.

### Previously acquired bar/definition intake

After code review and the targeted fix pass, the new CLI imported the already-acquired
`XNAS.ITCH` SPY minute bars for `[2018-05-01, 2026-01-01)` UTC:

- 1,421,744 decoded records; 1,421,742 structurally accepted, two undefined-OHLC rows
  retained as rejected observations, zero duplicate rows.
- 1,929 private Parquet parts, 81,704,154 bytes. These date partitions are not proof of
  complete trading sessions. Provider declarations remain 1,999 available / three degraded
  dates, not an exchange calendar or an overall clean-data verdict.
- Aggregate counts agree with the earlier independent native profile. No original archive,
  receipt or downloaded file was changed, and no record was repaired or fabricated.
- Local import plus reverification took 62.69 seconds with 85 MiB peak resident memory.
  This was a local development run alongside other checks, not a production resource
  benchmark or justification for changing DigitalOcean hardware.

The existing staged definitions archive was reverified locally: 6,821,768 records,
1.79 seconds, 54.5 MiB peak resident memory. This verifies the existing archive snapshot,
not native-to-projection semantics or account/executable contract eligibility. All new
private files/directories passed 0600/0700 permission checks. Licensed rows, private paths,
provider request identifiers and detailed receipts remain outside Git and reviewer context.

A source-verification command bound both current manifests but supplied no invented
source claims. It returned exit 2, `historical_availability_unverified`, with all authority
flags false. Missing dependencies remain explicit:

1. Reviewed provider-era publication/revision and definition-update/mapping protocols,
   including exact native/projection bindings and partial-chain coverage.
2. Verified session/holiday/early-close and corporate-action/dividend coverage, resolution
   of degraded dates, and explicit missing/no-trade interval treatment.
3. Canonical contract/deliverable/exercise/expiry/settlement reference facts.
4. Genuine option bid/ask and matching underlying quote coverage through initialization,
   entry, monitoring, exits and settlement, with independently verified source semantics.
5. An approved preregistered study/consumer and complete session/window requirements,
   followed by actual history/sample adequacy and after-cost uncertainty testing.

**Disposition:** native engineering milestone implemented and fixture-tested; actual
archive integrity verified; real-source qualification blocked; no acquisition-ready
study or genuine economic result; broker/runtime/live eligibility unchanged. No credits
were spent, and no account, broker, deployment or risk setting was changed. A structural
`requirements_complete` fixture is not economic acceptance or a promise of returns.

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
Option quote phases must use one dataset/schema/symbology/symbol stream for each
selected contract. An unrelated feed cannot initialize it or fill its coverage gaps;
no cross-feed compatibility rule is currently approved. Existing consumer and source
semantics checks remain independently required.
Times come from explicit requirements and hash-matched canonical contracts, never
an assumed holding period or settlement lag. Warmup must cover the declared history
continuously through the decision boundary; an old window or an interior gap cannot
satisfy it. Qualification remains blocked with `research_history_insufficient` because
v1 carries declared windows/session IDs, not independently verified observed history
counts and fold/opportunity evidence. It cannot establish the retained 750-bar minimum
by counting planned sessions. Even complete engineering-pilot coverage remains
`economic_eligible=false`.

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

Publication evidence must also bind `projection_hash`, the canonical
`native-definition-projection-v1` identity of every projected field except the
ordering-only `record_ordinal`. This is checked for every row before deduplication or
membership changes, including deletions. Rehashing a changed Parquet file cannot
reuse unchanged publication evidence. The legacy archive remains readable but its
stored native digest does not by itself prove the meaning of projected columns:
omitted native bytes cannot be reconstructed. Missing projection evidence denies
assembly. A future real-provider verifier must derive both identities from native
source bytes; the installed rulebook remains empty. Exact duplicate and file-order
invariance are preserved, and no historical archive hash is rewritten.

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

The 2026-09-28 economic-path audit confirmed this is also an implementation gap:
`_verify_with_rules` currently dispatches only to `_fixture_records`, which rejects
real-provider identities. Adding reference documents or rulebook entries alone
cannot qualify Databento data. A separately reviewed provider parser must derive
the required facts from the preserved source bytes, with era-specific semantics.

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

## Economic-validation continuation checkpoint (2026-09-28)

Standing automatic-merge and remaining-credit acquisition authority is recorded
in [Operator authority](operator-authority.md). Missing purchase permission is
not the blocker. After the operator restored the portal session, authenticated
Billing showed **$112.68 remaining credits and $0.00 due** around 04:31 UTC.
The download center showed the existing SPY bars and definitions jobs ready,
plus provider examples, with no pending job visible. No new request was submitted.
[Billing](https://databento.com/portal/billing),
[download center](https://databento.com/portal/download-center).

The credit-details panel still displayed the original $125 historical credit
grant, whereas Data usage displayed $12.33 of usage and the Billing summary showed
$112.68 remaining. Do not count the original grant as available again. Preserve
the one-cent display/rounding difference and use the lesser conservative balance
after reconciling exact costs before any submission; neither display alone is a
hard cash-charge cap. No billing, subscription, or account setting changed.

Code inspection at `591715a01072318d77520701c2a30d74befe0147` establishes this
remaining dependency chain:

1. Implement real-source semantic verification and supply reviewed calendar,
   publication/revision, corporate-action, definition and contract-term evidence.
2. Freeze a study and its complete quote-consumer requirements, then produce the
   existing causal call/put shortlist and deduplicated acquisition manifest.
3. Reconcile existing acquisitions, price the entire missing package, and purchase
   only within freshly verified remaining credits. Normalize actual option bid/ask
   and matching underlying observations, with initialization, coverage and tails.
4. Compose imported-data historical options evaluation and quote-bound reports.
   The existing `OptionsReplayRequest` deliberately rejects imported records;
   it must not be weakened or given relabelled data to bypass that boundary.
5. Evaluate actual after-cost outcomes, incomplete episodes, operating costs,
   cash/no-trade baselines, dependent-outcome uncertainty and untouched tests.
   Reusable generic metrics do not supply those missing options compositions.

Current public Databento documentation describes minute-bar timestamps as interval
starts, and explicitly notes that vendor aggregation and retroactive trade handling
can differ. It does not establish the original publication time of these private
historical bars. [OHLCV documentation](https://databento.com/docs/schemas-and-data-formats/ohlcv).
Databento's consolidated OPRA quote announcement states CMBP-1/TCBBO history starts
on March 28, 2023; the earlier portion of the purchased definition range must not
be assumed to have matching consolidated quotes.
[OPRA migration](https://databento.com/blog/opra-migration).

The coverage planner's qualification-history check compares the requested study
end to the earliest declared warmup start; it is not proof of actual usable bars
or ten years of option quotes. The canonical 3,650-day history request, 750 daily
observations, five folds, 50 test observations per fold and 30 independent
opportunities remain unchanged. The already acquired underlying range alone is
shorter than that history request. No shorter pilot can be relabelled as accepted
economic evidence. Economic readiness remains **ECONOMIC_NO_GO**.

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
