# Verifiable local research data and snapshot loading

Date: 2026-09-17 (UTC)

Status: high-level architecture and written specification approved by the operator on
2026-09-17. The [implementation plan](../plans/2026-09-17-research-data-bundle.md) records the
execution sequence and Cloud test contracts. This is a design, not an implemented capability
or release approval.

Inspected implementation base: `8785266866206b1e93f1f031794703d3ab8f106e`, on
`codex/continue-implementation-from-commit-7c4dcd1`.

## 1. Outcome and authority

Add one offline subsystem that binds retained source bytes to normalized market records,
verifies that binding, and implements the existing `MarketSnapshotLoader` interface. The
first integration is a deterministic, non-promotable test composition of the existing
decision-cycle service. It must not create an alternative trading engine.

The operator approved the data-first approach instead of starting with another synthetic
paper demonstration. A synthetic demonstration alone would leave source preimages,
point-in-time coverage, and the missing concrete snapshot loader unresolved.

This milestone authorizes local source, synthetic fixtures, tests, and documentation only.
It does not authorize data acquisition, provider selection or purchase, authentication,
broker calls, production-ledger access, credential operations, deployment, live operation,
or changes to pricing, exposure, strategy selection, or promotion requirements. Private
data must not be copied into Git, logs, review messages, or Codex Cloud tasks.

Success means reproducible data integrity and conservative local replay. It does **not**
mean that a source is authentic, its history is complete, research is accepted, or trading
is ready. Every result produced by this milestone remains non-promotable.

## 2. Existing boundaries and compatibility

Reuse these existing components:

- `market_data/recording.py`: canonical JSON, canonical value hashes, and
  `ResearchDataManifest`.
- `domain/market.py`: immutable `Bar`, `CorporateAction`, and related validated values.
- `market_data/universe.py`: strict membership records and as-of membership selection.
- `strategies/protocol.py`: `HistoricalSlice`; no new strategy-facing market-data type.
- `app.py`: `ValidatedMarketSnapshot`, `MarketSnapshotLoader`, and `DecisionCycleService`.
- `research/report.py`: existing dataset/report bindings and integrity checks.

Add focused modules under `market_data/` for the versioned bundle contract, private local
artifact I/O, bundle verification, and snapshot loading. Their exact Python signatures
will be frozen in the implementation plan before any Cloud test work starts. File storage
is not a production database migration, and no promotion record is added.

Existing public constructors, canonical serialization, hash formulas, and legacy artifact
interpretation remain unchanged. In particular, do not add fields to existing dataclasses
that are hashed through `dataclasses.asdict`, reinterpret historical `raw_hashes`, or turn
`point_in_time_universe=True` into source-verification evidence. New provenance lives in a
versioned envelope around an existing manifest. Legacy artifacts without an envelope stay
readable through their existing paths, but cannot enter the new verified-bundle path by
having missing provenance filled with defaults.

`RecordedMarketDataProvider` remains an in-memory replay provider. The new loader is an
implementation of the application interface, not a new method on the provider protocol.
No live/paper CLI or runtime factory is wired to it in this milestone.

## 3. Bundle identity and record binding

The v1 package consists of one canonical UTF-8 JSON envelope and content-addressed raw
blobs. The envelope contains a schema version, existing manifest value and hash, explicit
instrument/symbol mappings, declared coverage, raw descriptors, normalized records,
collection limitations, and fixture classification. Its bundle hash is `content_hash` of
the envelope payload excluding only the bundle-hash field. A version/domain discriminator
is included in every new hash preimage.

### Raw descriptors

Each descriptor binds:

- a non-secret source identifier and format/normalizer version;
- record kind, instrument scope, UTC request start/end, and UTC collection time;
- response-body byte length and SHA-256 of the exact retained body bytes;
- any claimed source publication time, labeled as a claim rather than trusted visibility;
- synthetic-versus-imported origin and known collection/licensing limitations.

The byte digest is explicitly different from `content_hash`, which hashes canonical JSON
values. Raw blob names are derived from byte digests, never from provider-controlled paths.
For **new v1 bundles only**, manifest `raw_hashes` are the ordered canonical descriptor
hashes; each descriptor in turn binds its exact raw byte digest. Existing manifests retain
their existing semantics. A raw descriptor hash must never be compared to a byte digest.

The input format contains market data only: no request headers, tokens, authenticated
request URLs, account records, or credential-bearing error bodies. This milestone supplies
only a synthetic v1 source format and its deterministic normalizer. Other source formats
are rejected as unsupported until separately reviewed; an arbitrary imported provider
response is not accepted just because its digest matches.

### Normalized records

Each normalized entry binds its record kind, source descriptor and source-record locator,
normalizer version, conservative availability time, and domain value. Re-running the
allowlisted normalizer against the retained source bytes must reproduce the entry exactly.
Merely storing a caller-asserted link between raw and normalized hashes is insufficient.

For newly normalized hash-bearing domain records, compute `data_hash` from the versioned
normalization preimage containing the value's other fields and the provenance binding;
then embed that hash in the domain value. Never hash a value containing its own not-yet-
computed hash. Membership provenance is carried in its envelope entry without changing
the existing membership type. Hash the complete resulting entries into the bundle.

Preserve symbol order explicitly and compute manifest `cleaned_hashes` with the existing
`ResearchDatasetSnapshot.cleaned_hashes` formula for bars grouped by symbol. Bind membership,
actions, availability, and coverage separately in the envelope; do not pretend the legacy
bar-group hash already covers them. Reject duplicate normalized bar identities, ambiguous
instrument mappings, conflicting records, unreferenced normalized entries, and mismatched
source scopes. Deterministic ordering rules are part of the v1 format, not filesystem order.

## 4. Time, coverage, and quality semantics

All instants must satisfy the repository's canonical UTC validation. Request windows use
`[start, end)` event-time coverage; a completed bar may end exactly at the requested end.
The loader includes only bars whose starts are within the requested history window and
whose ends and conservative availability times are no later than `as_of`.

For imported data, availability is no earlier than local collection time. An unverified
provider publication timestamp cannot backdate visibility. Synthetic fixtures may declare
simulated availability, but retain synthetic classification. Supporting earlier real
historical visibility requires a separate source/availability review and is not silently
enabled by this format. Future-visible entries may be retained in a bundle for later
queries, but cannot contribute values to an earlier snapshot. The unsupported historical
action rejection below is a denial, not permission to apply future information to features.

Coverage is explicit per instrument, record kind, and interval. It distinguishes a declared
complete interval, a declared gap, and unknown coverage; each declaration is bound to source
records. Bars use an explicit expected sequence of start/end slots within the covered
window. Membership includes a declared baseline state for every instrument in scope plus
subsequent events; absence of an event alone is not a baseline or proof of exclusion. The
baseline is explicitly a source assertion at the coverage start, not a fabricated addition
event. Its effective time is no later than that start, its announcement/availability must
be visible at the query, and its descriptor explicitly scopes baseline records separately
from events inside the request window.
Corporate actions require a declared covered interval, including an explicit empty action
set when no actions are reported.

The verifier checks internal coverage consistency and exact expected-slot matching. It
does not infer missing sessions, weekends, exchange calendars, delisting history, or source
completeness. A self-consistent expected-slot list remains a source claim. No declaration,
including `history_complete`, becomes independently authenticated evidence in this milestone.
Queries requiring unknown/gapped coverage, missing baseline state, missing expected bars,
or records outside declared source boundaries fail closed rather than returning a partial
snapshot. Unrelated gaps outside the selected query remain reported bundle limitations.

No interpolation or corporate-action economic policy is added:

- Interpolated bars are preserved for inspection but rejected by the snapshot loader.
- Bars must be explicitly unadjusted in v1. Unknown or pre-adjusted price bases are rejected
  for loading; retaining split-only adjusted data does not prove dividend coverage.
- Action records are retained and validated. An effective action affecting a requested
  instrument's selected bar window prevents loading that history in v1. No-action windows
  are supported only with explicit internally consistent action-coverage declarations.
- Future announcements are not applied to earlier bars or passed to features. If retained
  records reveal a historical window requiring an unsupported adjustment, reject the query
  rather than construct a corrected history from information unavailable at that time.
- Existing adjustment functions and their unresolved combined-action chronology remain
  unchanged. Supporting adjusted histories is a separately designed extension.

These conservative exclusions deliberately limit the first loader. They must be documented
as limitations, never bypassed by calling unknown coverage complete.

## 5. Verification result and private artifact handling

Verification separates three questions:

| Question | v1 outcome |
|---|---|
| Are the bytes, descriptors, normalized records, and manifest internally consistent? | Checked; malformed or mismatched packages are rejected. |
| Can this particular as-of query be replayed under the declared coverage and v1 quality restrictions? | Checked separately for each query. |
| Is the source authentic, independently complete, and accepted for promotion? | Not established; no accepted or promotable outcome exists. |

A successfully verified immutable value contains the recomputed bundle identity, verified
records, source/coverage limitations, and synthetic classification. Do not use a generic
`trusted=True`, `data_validated=True`, or `promotable=True` flag. It cannot construct a
`PaperPromotionContext`, accepted research assessment, authorization, lease, or ledger row.
The existing runtime gates remain the authority for those concerns.

Fixture classification propagates through normalization, bundle verification, and loader
diagnostics: fixture data cannot become real data by changing a top-level flag. The v1
normalizer itself is classified synthetic, so all bundles it accepts are synthetic. Unknown
source authenticity is never upgraded by hashing, reserialization, or a caller claim.

The storage API takes an explicit private root outside the repository. Use service-owned
directories with mode `0700` and regular files with mode `0600`, no symlink following, and
digest-derived child paths only. Reuse the safety conventions in `research/artifacts.py`
without changing the report writer's API or extracting an unrelated storage framework.
Reject traversal, wrong ownership/permissions, non-regular files, digest/length mismatch,
duplicate JSON keys, unknown schema fields/versions, invalid numeric encodings, and
oversized input before constructing domain records. Parsing must not execute code or load
classes named in data.

Input byte/record limits are explicit validated constructor inputs for this offline API;
there are no hidden defaults or new YAML/env config family. A future operator composition
must bind them through the canonical config graph before becoming an operator feature.
Read and hash the same opened regular file with bounded reads; verification returns an
immutable in-memory snapshot so later file changes cannot alter a running replay.

Write content-addressed blobs first and publish the envelope last. Write and verify each
complete artifact in a private temporary file, then atomically publish without overwriting
an existing target and perform file/directory durability checks. Exact existing bytes permit
idempotent reuse; differing existing bytes are an error. A failed write must leave no
apparently complete package. Orphaned private blobs may remain after interruption; automatic
deletion or repository cleanup is outside this milestone.

Errors use stable bounded reason codes and safe record indexes, never raw values, provider
payloads, private paths, or exception strings containing them. Known limitations are
structured data, not secrets-bearing free-form logs. No raw-data upload or logging is added.

## 6. Snapshot loader

The concrete loader receives a verified bundle plus immutable query settings: bar interval,
history-window start, and required minimum bar count. These are explicit inputs from the
existing validated research configuration/test composition; no strategy window or threshold
is changed. `load(universe, as_of)` retains its existing async signature and returns exactly
`ValidatedMarketSnapshot` containing existing `HistoricalSlice` values.

For every request:

1. Require canonical UTC, a nonempty unique universe, a valid history window, and supported
   interval. Bind instrument IDs through the envelope's exact mapping.
2. Select membership using both existing effective/announcement rules and envelope
   availability. Every requested instrument must be an as-of member. Reject a request that
   includes a nonmember; do not silently shrink the universe while the decision request
   still names the excluded instrument.
3. Verify the query's bar, membership, and action coverage and the v1 quality restrictions.
   Select only completed, available bars in the configured window, in strictly increasing
   end-time order, with no duplicates and at least the required history count. Do not pad,
   interpolate, or synthesize missing bars.
4. Return histories in the caller's explicit universe order. Set `spread_percentage=None`
   in v1: historical bars do not establish an executable spread. Features or strategies may
   consequently decline to act; the loader must not manufacture a zero spread to force a
   signal.
5. Derive each history hash from selected normalized bar identities, selected membership
   provenance, relevant declared coverage, query settings, and `as_of`. Derive the snapshot
   hash from the ordered history hashes and the same query identity. Include the versioned
   loader policy and the synthetic/source limitation classification in these preimages.

Keep whole-bundle identity in loader diagnostics, not in the selected-record hash: appending
disjoint source blobs and records that are irrelevant and unavailable to an earlier query,
without changing its existing source descriptors or coverage, may change the bundle hash
but must not change that query's data/features hash. Rewriting a selected record's source
blob changes its provenance and is not this append-only case. Changes to relevant coverage or selected
records must change the snapshot hash. A future record that exposes an unsupported historical
adjustment may instead make the query fail closed as described above; it cannot change the
earlier feature values by being applied retrospectively.

The interface has no provenance-status field. Therefore this milestone does not pass its
output to a promotion composition, and does not infer acceptance from the class name
`ValidatedMarketSnapshot`. The bundle diagnostics remain available to the local integration
test harness. Changing runtime interfaces to consume provenance is later primary-owned work.

## 7. Ownership and implementation sequence

Dependency chain: approved written spec → implementation plan with frozen v1 interfaces →
primary-owned bundle/parser/verifier → snapshot loader → non-promotable decision-cycle
integration → central verification and documentation. Primary ownership includes every
production diff, private I/O boundary, and final integration decision.

Once interfaces are committed, two independent actual Codex Cloud tasks can add synthetic
tests while the primary implements the contract. Neither task is dispatched by this spec:

| Contract | Sole owned paths | Objective |
|---|---|---|
| DATA-BUNDLE-TESTS-004 | `tests/unit/market_data/test_bundle_contract.py`, `docs/reviews/data-bundle-tests-004.md` | Inline synthetic fixtures; byte/descriptor/normalized mismatch, malformed input, deterministic hash, and fixture-classification tests. |
| SNAPSHOT-DATA-TESTS-004 | `tests/unit/market_data/test_snapshot_data_contract.py`, `docs/reviews/snapshot-data-tests-004.md` | Inline synthetic fixtures; as-of visibility, requested universe, coverage, completed bars, ordering, and deterministic snapshot contract tests. |

Each dispatch must include the exact committed SHA on the integration branch after interface
freeze, owner, isolated checkout, complete frozen signatures/schema/error codes, read-only
dependencies, exact test commands, and prohibited operations. Do not dispatch with a symbolic
default-branch assumption or an unresolved base. Shared fixtures and production files are
read-only to both workers; fixture helpers stay local to their owned test files.

Workers may not change strategies, pricing, fills, risk, promotion, runtime composition,
production persistence, brokers, reconciliation, config, credentials, deployment, or other
tests. No network data acquisition, secrets, private artifacts, or account state are sent to
Cloud. Require a review document containing observed base, commands/results, assumptions,
remaining blockers, and `READY_FOR_INTEGRATION` or `NOT_READY`. The primary inspects complete
diffs, demonstrates meaningful failing tests before implementation, and reruns integrated
tests. These contracts are preparation, not claims that tasks have run.

## 8. Acceptance and verification

Required tests include positive controls, not only rejection cases:

- A minimal all-synthetic, no-action, explicitly covered bundle verifies and loads; the
  existing feature/decision-cycle integration can consume it without any external client.
- Mutating raw bytes, descriptor fields, normalized prices, membership, manifest contents,
  or relevant coverage without the corresponding binding fails verification. Recomputing
  only the outer hash cannot hide a normalization mismatch.
- Unsupported versions/normalizers, wrong field types, duplicate JSON keys, symlinks,
  permissions, traversal, oversized inputs, interrupted writes, and conflicting existing
  artifacts fail without leaking payloads. Exact-byte repeat writes are idempotent.
- Missing baseline/coverage/expected bars, too little history, mixed instruments/intervals,
  interpolated or pre-adjusted bars, and effective action windows deny loading. A valid
  no-action window passes; a gap outside the selected window remains a reported limitation.
- Future bar ends, late membership announcements, and late availability never enter an
  earlier snapshot. Imported collection time cannot be replaced by a claimed earlier source
  timestamp. Appending disjoint irrelevant future source records without changing selected
  provenance or coverage leaves snapshot hashes unchanged.
- Repeated runs and equivalent serialization reproduce hashes; changing selected inputs or
  loader query settings changes them. Explicit universe order is stable and hash-bound.
- Existing legacy manifest/report hash fixtures and constructor call sites remain unchanged.
  Missing new provenance is rejected by the new path, not silently migrated.
- Synthetic classification cannot be erased. Tests cannot manufacture accepted research,
  a promotion observation, an authorization, or broker execution through the new subsystem.
  Existing no-live-write and missing-promotion-composition denials continue to pass.

Run narrow bundle/loader tests first, then existing market-data, research, features,
decision-cycle, and paper-boundary tests. The implementation plan will list verified test
paths; planned new test files above do not exist yet. Central baseline remains Ruff, strict
mypy on `src`, full Pytest with branch measurement and the unchanged 80% coverage floor,
Bandit, lock validation, and existing CI checks. Report external or environment-blocked
checks explicitly. Design-only verification is documentation smoke testing and diff review;
it is not a new execution of the full implementation suite.

## 9. Remaining path to live readiness

This milestone addresses structural data provenance and a missing loader, not the whole
critical path. Source authenticity/licensing, independently supported historical coverage
and availability, corporate-action policy, research bias/multiple-testing controls,
realistic fill/exit outcomes, and accepted code/config-bound research remain prerequisites.

The primary must later build the trusted durable paper composition and collect 100 eligible
observations, then qualifying shadow observations across seven distinct UTC dates. Provider
execution/reconciliation, host/runtime controls, recovery, security, manual review, and
separate live authority remain required. Existing additional normal-live requirements are
unchanged. No repeated diagnostic probe or added account funding substitutes for this work.

Written-spec approval is complete. The implementation plan freezes task contracts; production
implementation has not started in this design/planning pass.
