# Native Options Data Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline native-data path that produces a verified, causally selected SPY option acquisition manifest, or a reproducible explanation of the missing evidence preventing it.

**Architecture:** Stream immutable native observations into private content-addressed storage, verify source-specific historical claims against reviewed evidence, then assemble bounded canonical inputs for the existing shortlist policy. Preserve every v1 evidence format and denial path; a separate v2 bridge recomputes verification before selection. Coverage assembly and offline CLI integration never receive credentials, broker clients or purchase capabilities.

**Tech Stack:** Existing Python 3.12–3.14, Decimal, frozen dataclasses, Pydantic, Typer and Pytest; research-only `databento-dbn==0.69.0`, `zstandard==0.25.0`, `duckdb==1.5.5`. No new dependencies or database migrations.

**Spec:** [Approved native-data integration design](../specs/2026-09-25-native-options-data-integration-design.md). Read both documents before execution.

## Global Constraints

- SPY only; native underlying request `XNAS.ITCH` / `ohlcv-1m` / `raw_symbol`; native definitions remain `OPRA.PILLAR` / `definition` / `parent`. Do not broaden `DefinitionRequest`.
- Preserve integer nanoseconds and fixed-point integer prices; exact Decimal scaling by `10**9`. Ceil availability at the microsecond boundary; never float timestamps or backdated retrieval.
- Preserve v1 readers, hashes, `Bar`, `OptionContract`, `OptionSession`, `OptionsDataRecord` and synthetic-only replay. New envelopes receive new schema identifiers.
- Preserve prior completed regular-session unadjusted close, 21–45 inclusive DTE, target 30 DTE, earlier-expiry/lower-strike ties, one call and one put or no pair. No quotes, returns, Greeks, liquidity or account balance enter ranking.
- Standard USD SPY, American, physical/PM, unadjusted, premium multiplier and deliverable exactly 100 SPY shares; all terms, deadlines and sessions need historical evidence.
- Keep `production_eligible=false`, `evidence_promotable=false`, `download_authorized=false`, `live_authorized=false`. Parser success and hashes grant no source, economic or trading authority.
- Retain shortlist limits: 25,000 records, 16 MiB decoded bytes, depth 16, one decision session. Keep `ChainSnapshot`'s existing 10,000-member bound; deny overflow, never truncate.
- Native stream ceilings remain 512 MiB compressed, 4 GiB expanded, 256 MiB metadata, 10,000,000 records and 1,000,000 unique symbols; retain the 128 MiB decompression window. Research runs locally, not on the production droplet.
- Native parts use at most 10,000 rows and 16 MiB per encoded part, with at most 10,000 parts and 16 MiB per manifest. Reuse existing private storage and DuckDB 64 MB/one-thread/external-access-denied settings. New ceilings enter the canonical config/envelope, not a second loader.
- Private artifacts stay outside every Git checkout, owner-only 0700/0600, no symlink/hard-link surprises, no overwrite; only synthetic fixtures enter Git or CI.
- Preserve the 3,650-calendar-day request, 750-bar minimum, five folds, 50 test bars/fold and 30 independent opportunities wherever applicable. This plan does not define a study split or weaken research requirements.
- Preserve $100 assumed capital, $150 live-equity ceiling, 0.5% per-trade risk ($0.50 at $100), $50 outer per-trade cap, $50 non-replenishing trial-loss ceiling and stricter limits.
- No broker/account call, data API, subscription, credential handling, deployment, production ledger, scheduler or live activation. Credit-only purchases remain a separate authorized workflow, not capabilities of this software.

## Review Focus

1. **Source replaced after hashing:** validation and queries must use the same immutable bytes; a well-formed replacement must not inherit the old verification. Task 2 pins this race.
2. **Equivalent-looking but different authority:** copied evidence for another source, window, config, rulebook or record cannot qualify the current selection. Task 3 and Task 6 pin substitution and stale-rule cases.
3. **Undefined prices and partial-day warnings:** equal undefined sentinels can satisfy ordinary OHLC ordering; excluding an after-hours bad row must not clear an unresolved day-wide degradation. Task 1 and Task 4 pin both cases.
4. **Nanosecond visibility and later discovery:** rounding must not expose future data; a retrospective quality invalidation must not rewrite an earlier as-known decision hash. Task 3 and Task 6 pin those boundaries.
5. **Year-end and duplicate request coverage:** entry dates, overlapping selections and 100-symbol chunks must preserve exits, initialization and unresolved obligations without counting the same request twice. Task 7 pins these cases.

---

## Execution boundary and current baseline

Planning base: `c69cc90d1a7cc4e0dbc9187ff4ecbbee55491ea6`, branch
`codex/continue-implementation-from-commit-7c4dcd1`. Work in the existing Robinhood
implementation worktree, not the unrelated Polymarket workspace. The operator's
2026-09-25 approval applies to the written specification at that base. The operator
subsequently approved this implementation plan on 2026-09-27; implementation starts
from `37a461fa0eee348e475b1b7cfe68ed9cf073d306`. **Preserve the selected Native method.**

The coordinator implements these tightly coupled interfaces sequentially. Use
`superpowers:executing-plans` after plan approval. Do not dispatch Cloud jobs or
implementation subagents. Perform the required fresh whole-branch review at the end
under that skill, respecting repository restrictions; a reviewer must not receive
licensed data or decide source authority, strategy, exposure or execution policy.

Existing native definitions/storage and synthetic shortlist are implemented. Task 1
adds native bars scanning and canonical limits; private bars storage, semantic source
verification, v2 imported shortlist and complete coverage manifests remain pending.
Source facts and study requirements remain externally
unverified. A tested denial path is useful progress, not evidence that those facts
have been obtained. No point-in-time publication rule is approved by this plan alone.

Preserve existing dirty README, architecture/research/limitations/transition documents,
tracked SBOM, general CLI, equity replay files and tests. The worktree inspection also
found **seven pre-existing tracked deletions**: the Terraform lockfile, migration
template and migrations 0001–0005. Following explicit operator approval on 2026-09-27,
those exact paths were restored from HEAD and both broken local environments were
rebuilt from their unchanged lockfiles. No production migration ran; old environments
remain recoverable in the plan workspace. Unrelated failures are not grounds to weaken gates.

Before each task: inspect HEAD, index and owned paths; stop on overlapping changes.
Use exact staging paths and path-scoped commits, never `git add .`. Protect the
existing SBOM and both lockfiles with before/after hashes. Do not push or merge as
part of this plan. Do not install tools or mutate dependencies to make tests pass.

## File map and frozen dependency chain

Source prefixes below are `src/trading_bot/`; test paths are explicit in each task.

| Task | Main files | Responsibility |
| --- | --- | --- |
| 1 | `market_data/databento_bars.py`, `databento_bar_models.py`, `databento_native_io.py`; config/profile files | Strict bars request, decoder and resource contract; shared bounded byte primitives only |
| 2 | `market_data/databento_bar_store.py`, `databento_bar_wire.py`, `databento_native_rows.py` | Private native parts, manifests, byte-bound readers for bars and existing definitions |
| 3 | `market_data/options_source_models.py`, `options_source_wire.py`, `options_source_rules.py`, `options_source_verify.py` | Closed evidence contracts, reviewed rules and recomputed verification |
| 4 | `market_data/options_session_inputs.py` | Verified regular-session close, calendar and action assembly |
| 5 | `market_data/options_definition_inputs.py` | As-known definition state, canonical contracts and complete chain |
| 6 | `research/options_shortlist_v2.py`, `options_shortlist_v2_wire.py`; shared policy in existing selector | Separate verified entry point without relaxing v1 |
| 7 | `research/options_acquisition_models.py`, `options_acquisition.py`, `options_acquisition_wire.py` | Causal coverage plan, union/deduplication and request chunks |
| 8 | `cli/options_native.py`, `research/options_native_io.py`, existing `cli/options_research.py`, research workflow and operator guide | Offline commands, artifact composition, end-to-end validation and truthful handoff |

Tasks depend in this order: **1 → 2 → 3 → (4 then 5) → 6 → 7 → 8**.
No second risk engine, config loader, artifact store or trading-state machine is added.
Use the existing `bundle_store` private traversal/publication and `options_parquet`
DuckDB connection. If a shared extraction is needed, preserve its original callers
and their exact regression tests in the owning task.

Common vocabulary: `DataHash`, `ConfigHash`, `LoadedConfig`, `OptionSession`,
`OptionContract`, `OptionsDataRecord`, `Bar`, `ShortlistClose`, `ShortlistAction`,
`OptionsShortlistCandidate`, and `DefinitionLimits` are existing types. All new records
are frozen/slots dataclasses with exact-type checks, closed enums, UTC and bounded
container validation. No `Any` or free-form provider dictionaries cross task interfaces.
Unless stated otherwise, names ending in `_hash` use `DataHash`, names ending in
`_ns` and counts use strict `int`, reasons are sorted unique `tuple[str, ...]`, and
all four authority fields use `Literal[False]` with `init=False`. Test case fixtures
below are local arrangements, not extra production APIs: their zero-argument
`assemble`, `build` or `invoke` closures call the exact interface in their owning task.
Each test module defines its own fixtures; shared synthetic source fixtures belong
only in the explicitly listed helper modules.

## Task 1: Strict native OHLCV intake and canonical resource controls

**Files:** Create `src/trading_bot/market_data/databento_bar_models.py`,
`src/trading_bot/market_data/databento_bars.py`,
`src/trading_bot/market_data/databento_native_io.py`,
`configs/options/native-data/simulation.yaml`,
`tests/unit/market_data/_native_bars_fixtures.py`,
`tests/unit/market_data/test_databento_bars.py`,
`tests/unit/config/test_options_native_data_config.py`.
Modify `src/trading_bot/market_data/databento_definitions.py` only for shared byte-helper
extraction; `src/trading_bot/config/models.py`, `src/trading_bot/config/loader.py`,
`configs/base.yaml`, `configs/safety-envelope.yaml` for the one canonical settings graph.

**Interfaces consumed:** Current `DefinitionLimits`, strict DBN/decompression helpers,
canonical `load_config` and `DatabentoImportError` conventions. Retain old definitions
exports and error codes through wrappers if helpers move.

**Interfaces produced:**

- `NativeBarRequest(start_ns: int, end_ns: int)`: exact fixed SPY query; `.query() -> dict[str, object]`.
- `NativeBarRow`: `record_ordinal`, `dbn_version`, `publisher_id`, `instrument_id`,
  `interval_start_ns`, four
  nullable integer price fields (`open_nanos`, `high_nanos`, `low_nanos`, `close_nanos`),
  integer volume, record/raw hashes, disposition `accepted|rejected|duplicate` and
  fixed reason tuple. Preserve the original bytes in the referenced immutable archive.
- `NativeBarProfile(request: NativeBarRequest, raw_hash: DataHash, dbn_version: int,
  decoded_count: int, accepted_count: int, rejected_count: int, duplicate_count: int,
  first_interval_ns: int | None, last_interval_ns: int | None,
  mapping_counts: tuple[tuple[str, int], ...], quality_counts: tuple[tuple[str, int], ...])`.
  `historical_availability_verified` and `economic_evidence` are immutable false fields
  in addition to the four authority fields. Count labels are fixed decoder-owned codes.
- `scan_bars(source: BinaryIO, *, expected: NativeBarRequest, expected_sha256: str,
  limits: DefinitionLimits, consume: Callable[[NativeBarRow], None] | None = None)
  -> NativeBarProfile`; callbacks are provisional until successful complete EOF.
- `OptionsNativeDataSettings` under `options.native_data`: `enabled` false by default;
  the exact stream/part ceilings from Global Constraints. Values may tighten, not exceed
  the release envelope. Only explicit BACKTEST/SIMULATION compositions may enable it.
  Use the five `DefinitionLimits` field names plus `max_part_rows`, `max_part_bytes`,
  `max_parts` and `max_manifest_bytes`; the existing 128 MiB window remains fixed.
  `native_limits(loaded: LoadedConfig) -> DefinitionLimits` in `databento_bar_models.py`
  enforces enablement/mode and maps only validated canonical settings.
- Test helper `bar_fixture(*, version: int = 1, count: int = 1,
  prices: tuple[int, int, int, int] = (100000000000, 102000000000, 99000000000, 101000000000))
  -> tuple[bytes, NativeBarRequest, str]`: fabricated compressed DBN, request, SHA-256;
  timestamps are distinct minute starts in a fixed synthetic UTC query.

- [x] **1.1 Write failing decoder/config tests** with these named assertions; generate
  DBN v1/v2/v3 via the pinned SDK, not licensed examples.

```python
def test_undefined_ohlc_is_rejected_even_when_ordering_matches():
    body, request, digest = bar_fixture(prices=(2**63 - 1,) * 4)
    rows = []
    report = scan_bars(BytesIO(body), expected=request, expected_sha256=digest,
                       limits=DefinitionLimits(), consume=rows.append)
    assert (report.decoded_count, report.rejected_count) == (1, 1)
    assert rows[0].open_nanos is None
    assert report.historical_availability_verified is False

def test_native_stream_row_conservation(valid_profile):
    assert valid_profile.decoded_count == (
        valid_profile.accepted_count + valid_profile.rejected_count
        + valid_profile.duplicate_count
    )

def test_native_profile_is_research_only(load_native_config):
    loaded = load_native_config()
    assert loaded.config.options.native_data.max_records == 10_000_000
    assert loaded.config.options.live_supported is False
    assert loaded.config.options.max_per_trade_loss_usd == 50
```

Also assert schema/scope mismatch, float/bool fields, unknown metadata extension,
partial record/footer, a second concatenated DBN document, trailing garbage,
record limit+1 and decompression expansion all deny. Multiple valid Zstandard frames
encoding one valid DBN stream pass; do not conflate compression frames with DBN documents.
Duplicate keys are `(publisher, instrument, minute)`;
byte-identical repeats count once, conflicting repeats invalidate the stream. Undefined
observations cannot become valid through duplicate handling. Mapping intervals are
half-open UTC dates; ambiguous/missing mapping or regressing native time denies.
Bound same-minute duplicate state; do not retain a whole-history Python set.
`test_native_profile_denied_in_operating_modes` covers PAPER/SHADOW/MICRO_LIVE/LIVE,
including environment overrides and an envelope ceiling exceeded by one.
`valid_profile` scans the default `bar_fixture`; `load_native_config` is a test callable
that loads base/native-simulation/envelope files with an explicitly empty environment.

- [x] **1.2 Run the new tests red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/unit/market_data/test_databento_bars.py tests/unit/config/test_options_native_data_config.py -q`.
  Expected: failure for missing new interfaces, not skipped backends or credentials.
- [x] **1.3 Implement the defined models, scanner and settings.** Extract only the
  current dependency/decompression/reader helpers; the legacy OPRA metadata validator
  keeps its exact request restriction. Pin decoder versions, bound metadata before
  decoding, map sentinels before canonical arithmetic and verify the compressed digest
  at EOF. No canonical bars or historical availability are inferred here.
- [x] **1.4 Run the new tests green**, then existing
  `tests/integration/market_data/test_databento_definitions.py`,
  `tests/unit/market_data/test_databento_batch.py` and all `tests/unit/config`.
  Expected: zero failures; backend tests must run, not silently skip.
- [x] **1.5 Review/stage only Task 1 files and commit:**
  `feat(data): add bounded native SPY minute-bar intake`.

## Task 2: Immutable native bars storage and byte-bound row readers

**Files:** Create `src/trading_bot/market_data/databento_bar_store.py`,
`src/trading_bot/market_data/databento_bar_wire.py`,
`src/trading_bot/market_data/databento_native_rows.py`,
`tests/integration/market_data/test_databento_bar_store.py`,
`tests/integration/market_data/test_databento_native_rows.py`.
Extend Task 1's `databento_bar_models.py` with the batch/dataset descriptor types below.
Modify existing `databento_stage.py` only to expose a narrow verified definition-row
reader if required; do not change `databento-native-definitions-parquet-v1` semantics.

**Interfaces consumed:** Task 1 request/row/profile and canonical native settings;
existing `_open_root`, `_read`, `_publish`, `_subdirectory`, `_connection`,
`verify_staged` and native-definition column contract.

**Interfaces produced:**

- `validate_bar_batch(source: Path, *, expected: NativeBarRequest,
  loaded: LoadedConfig, repository_root: Path) -> NativeBarBatch` in `databento_bar_store.py`.
  `source` is a batch directory, not a bare DBN file. `NativeBarBatch` in
  `databento_bar_models.py` contains `request`, `files: tuple[BatchFile, ...]`,
  `bar_file: str`, and `conditions: tuple[NativeCondition, ...]`.
  `BatchFile` is the existing native-batch type; `NativeCondition` contains
  `trading_date: date`, `state: Literal["available", "degraded", "missing"]` and
  `last_modified_date: date | None`. Preserve the reported date without inventing a
  publication instant. Implement a bars-specific query validator; never widen OPRA's.
- `stage_bars(source: Path, root: Path, *, expected: NativeBarRequest,
  loaded: LoadedConfig, repository_root: Path) -> Path`.
- `verify_bar_stage(manifest_path: Path, *, loaded: LoadedConfig,
  repository_root: Path) -> NativeBarDataset`.
- `NativeBarDataset`: validated manifest identity, request/profile, immutable part
  descriptors, source file identities and provider-condition observations; not semantic authority.
- `NativeDefinitionRow`: a typed projection of the existing native staging columns;
  preserve every original field and nullable sentinel, without a premium-multiplier default.
- `read_bar_rows(dataset: NativeBarDataset, *, start_ns: int, end_ns: int,
  loaded: LoadedConfig, repository_root: Path) -> Iterator[NativeBarRow]` and
  `read_definition_rows(manifest_path: Path, *, start_ns: int, end_ns: int,
  loaded: LoadedConfig, repository_root: Path) -> Iterator[NativeDefinitionRow]`.
  Readers consume rehashed private snapshots, not later reopened mutable source paths.

- [ ] **2.1 Write failing private-store tests:**

```python
def test_failed_footer_publishes_no_success_manifest(interrupted_stage):
    assert interrupted_stage.error_code == "databento_dbn_invalid"
    assert interrupted_stage.published_manifest_count == 0

def test_reader_uses_bytes_it_verified(replacement_race):
    assert replacement_race.observed_part_hash == replacement_race.original_hash
    assert replacement_race.observed_part_hash != replacement_race.replacement_hash

def test_duplicate_stage_is_idempotent(first_stage, repeated_stage):
    assert first_stage.manifest_hash == repeated_stage.manifest_hash
```

Implement local fixture arrangements in these test modules using Task 1's `bar_fixture`
and existing `make_batch` patterns. Cover exactly three manifest-listed files plus
manifest: the `.ohlcv-1m.dbn.zst` file, `metadata.json`, `condition.json`, and
`manifest.json`. Require exact query/customization/size/hash agreement; provider URL
metadata is inert and excluded from reports. Reject extra files and URL-as-input paths.
Cover source mutation, disk-full and manifest collision;
all Git ancestor aliases, symlinks, hard links, wrong owner/mode; 10,001 rows split
deterministically; sentinels/duplicates retained; part tampering and query-window mismatch.
No provider URL is fetched. Manifest publication is last; orphan task-owned parts
after interruption are not proof of completion and cannot harm an older manifest.

- [ ] **2.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/integration/market_data/test_databento_bar_store.py tests/integration/market_data/test_databento_native_rows.py -q`.
  Expected: missing-interface failures with no network.
- [ ] **2.3 Implement these store/reader signatures.** Use schemas
  `databento-native-bars-parquet-v1` and `databento-native-bars-part-v1`; raw integer
  columns, closed manifest keys, fixed false flags. Partition by UTC interval date,
  with ordinal/hash/disposition preserved; never create `underlying_quote` records
  from bars. Reuse storage and connection primitives rather than adding a second store.
- [ ] **2.4 Run green plus existing `test_databento_stage.py`, `test_options_parquet.py`
  and Task 1 tests.** Expected: exact integer/hash round trips, all failures closed.
- [ ] **2.5 Review/stage only Task 2 files and commit:**
  `feat(data): persist and reverify immutable native bar parts`.

## Task 3: Recomputed source-verification contracts and reviewed rulebook

**Files:** Create `src/trading_bot/market_data/options_source_models.py`,
`options_source_wire.py`, `options_source_rules.py`, `options_source_verify.py` in the
same directory; `tests/unit/market_data/_options_source_fixtures.py`,
`test_options_source_contracts.py`, `test_options_source_verify.py` in the matching
test directory; `docs/options-native-data.md` for contracts and actual limitations.

**Interfaces consumed:** Native datasets/readers from Task 2, source hashing/strict
codecs and `OptionsNativeDataSettings`. No transport or source-trust booleans.

**Interfaces produced:**

- `SourceClaim(role: SourceRole, source_id: str, schema: str, era_start_ns: int,
  era_end_ns: int, raw_hashes: tuple[DataHash, ...], observed_at: datetime,
  published_at_ns: int | None, effective_start_ns: int, effective_end_ns: int,
  coverage_hash: DataHash, rule_id: str)`, with `SourceRole` the closed literal union
  `calendar|bar_publication|actions|
  definition_state|contract_terms|quote_semantics`. UTC retrieval is distinct from publication.
- `PrivateArtifactRef(path: Path, sha256: DataHash, byte_count: int)` binds an explicit
  private file. Paths are only in private input/evidence envelopes, never stdout or
  causal hashes; byte identity alone does not establish provider authenticity.
- `SourceEvidenceBundle`: hash-bound tuple of claims, reference documents and exact
  source manifests; descriptors identify private files, never executable rule expressions.
  Its fields are `claims: tuple[SourceClaim, ...]`,
  `references: tuple[PrivateArtifactRef, ...]`, `manifests: tuple[PrivateArtifactRef, ...]`.
- `VerificationContext(as_of_ns: int, start_ns: int, end_ns: int,
  config_hash: ConfigHash, code_hash: DataHash, rulebook_hash: DataHash)`.
- `SourceFinding(role: SourceRole, status: Literal["verified", "denied"],
  visible_hashes: tuple[DataHash, ...], reasons: tuple[str, ...])`;
  `SourceInvalidation(affected_hash: DataHash, discovered_at: datetime, reason: str)`.
- `SourceVerification`: `context: VerificationContext`,
  `status: Literal["verified", "denied"]`, `source_hashes: tuple[DataHash, ...]`,
  `record_hashes: tuple[DataHash, ...]`, `visible_claim_hashes: tuple[DataHash, ...]`,
  `findings: tuple[SourceFinding, ...]`, `invalidations: tuple[SourceInvalidation, ...]`,
  `reasons: tuple[str, ...]` and all immutable false authority flags.
- `load_reviewed_rules() -> tuple[SourceRule, ...]`: code-owned allowlist; each
  `SourceRule` binds exact source/schema/era, required document identities and a named
  fixed verifier, not caller-provided executable behavior.
  Its fields are `rule_id: str`, `role: SourceRole`, `source_id: str`, `schema: str`,
  `era_start_ns: int`, `era_end_ns: int`, `document_hashes: tuple[DataHash, ...]` and
  `verifier_id: str` selected only from code-owned dispatch names.
  `source_code_hash() -> DataHash` and `reviewed_rulebook_hash() -> DataHash` live in
  `options_source_rules.py`; recompute and compare these plus `loaded.config_hash`
  with the context, rather than trusting supplied identity fields.
- `verify_source_bundle(bundle: SourceEvidenceBundle, *, context: VerificationContext,
  loaded: LoadedConfig, repository_root: Path) -> SourceVerification` and
  `ceil_available_at(timestamp_ns: int) -> datetime`.
- `decode_source_bundle(body: bytes, *, loaded: LoadedConfig) -> SourceEvidenceBundle`
  and `encode_source_bundle(bundle: SourceEvidenceBundle) -> bytes` use
  `options-source-evidence-v1`. Decoding never constructs a trusted verification result.
  `encode_source_verification(result: SourceVerification) -> bytes` emits the private
  `options-source-verification-v1` report; it is diagnostic output, not a trust-token decoder.

- [ ] **3.1 Write failing contract/verification tests:**

```python
def test_nanosecond_availability_is_not_rounded_into_past():
    stamp = 1704205800000000001
    assert ceil_available_at(stamp) == datetime(2024, 1, 2, 14, 30, 0, 1, tzinfo=UTC)

def test_retrieval_or_hash_does_not_prove_publication(unverified_bundle, context):
    result = verify_fixture_bundle(unverified_bundle, context)
    assert "historical_availability_unverified" in result.reasons
    assert result.production_eligible is False

def test_copying_evidence_to_other_scope_denies(substituted_context_case):
    assert substituted_context_case.result.status == "denied"
    assert substituted_context_case.result.reasons == ("source_scope_mismatch",)
```

`verify_fixture_bundle(bundle: SourceEvidenceBundle, context: VerificationContext)
-> SourceVerification` lives only in the test helper and calls the private verifier
with a fabricated rulebook; no CLI/env/profile option may select that rulebook.
Test authentic-looking but unpinned documents, unknown rules, caller `verified=true`,
altered claim/record hashes, future publications, omitted action-empty coverage,
expiry/era boundaries, whole-file future additions and post-hash mutation. Parameterize
scope substitution over source/schema/window/config/code/rulebook/record identity.
Use fixed fixture hashes; fixture success cannot satisfy a shipped provider claim.

- [ ] **3.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/unit/market_data/test_options_source_contracts.py tests/unit/market_data/test_options_source_verify.py -q`.
- [ ] **3.3 Implement the closed models/codecs and verifier.** Recompute every derived
  claim from immutable bytes using reviewed schema/era rules. Missing actual publication,
  reference, baseline or term evidence denies the affected role while other diagnostics
  remain available. Preserve unknowns; no default `available_at=interval_end`.
  Public documentation currently supports structural parsing, not every historical
  claim. Ship no blanket provider approval: unsupported semantic roles remain denied
  until coordinator-reviewed evidence supplies exact applicable rules/documents.
  Record that blocker explicitly; an empty/partial rulebook is not completed real-data
  qualification. No data-purchase permission or accepted private-use attestation is
  repurposed as technical source proof.
- [ ] **3.4 Run green and the existing options-record/codec and bundle-verification
  tests.** Check raw record visibility using nanoseconds before canonical conversion.
  Invalidations live outside causal input hashes; never invent historically known warnings.
- [ ] **3.5 Update the new operator guide's evidence matrix and commit Task 3:**
  `feat(data): verify scoped source claims without caller trust flags`.

## Task 4: Calendar, corporate events and regular-session close assembly

**Files:** Create `src/trading_bot/market_data/options_session_inputs.py`,
`tests/unit/market_data/test_options_session_inputs.py`; extend only the synthetic
source fixture helper and `docs/options-native-data.md`.

**Interfaces consumed:** Task 3 verified roles, Task 2 bar reader, existing `Bar`,
`OptionSession`, `ShortlistAction`, `ShortlistCalendarDay`, `CorporateAction` and
`ShortlistDiscontinuity`. Keep existing domain serialization unchanged.

**Interfaces produced:** `SessionReferenceInput` contains explicit current/prior
regular sessions, daily calendar declarations, corporate actions and coverage claim
identities: `current: OptionSession`, `prior: OptionSession | None`,
`calendar_days: tuple[ShortlistCalendarDay, ...]`, `actions: tuple[ShortlistAction, ...]`,
`claim_hashes: tuple[DataHash, ...]`. `SessionInputs` contains those verified
calendar/actions, `bar: Bar | None`,
`available_at: datetime | None`, selected native hashes, inclusion/exclusion/rejection
counts and `reasons: tuple[str, ...]`. Neither type is a source certificate; the v2
envelope carries verified provenance without widening v1 `ShortlistEvidence` semantics.
`assemble_session_inputs(dataset: NativeBarDataset, reference: SessionReferenceInput,
*, verification: SourceVerification, loaded: LoadedConfig, repository_root: Path)
-> SessionInputs` rechecks exact scope before assembling.

- [ ] **4.1 Write failing assembly tests:**

```python
def test_regular_close_uses_exact_session_not_after_hours(regular_and_extended_case):
    result = regular_and_extended_case.assemble()
    assert result.bar.close == Decimal("101")
    assert result.bar.ends_at == regular_and_extended_case.prior.closes_at
    assert result.bar.volume == Decimal("300")

def test_after_hours_exclusion_does_not_clear_degraded_day(degraded_case):
    result = degraded_case.assemble()
    assert result.bar is None
    assert "source_coverage_degraded" in result.reasons
```

Fixtures explicitly contain two regular bars with volumes 100/200 and closes 100/101,
plus an extended-hours close 999; no actual market values. Cover holidays, exceptional
closures, early close 13:00, ordinary close 16:00, both DST boundaries, minute ending
at session close, absent final minute, undefined in-session row, missing publication,
future dividend revision, unknown/split/deliverable changes and empty action coverage.
An absent final minute does not get filled; accept an earlier last trade only with
verified no-trade coverage through the actual close, otherwise deny.

- [ ] **4.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/unit/market_data/test_options_session_inputs.py -q`.
- [ ] **4.3 Implement the specified assembler.** Exact first/max/min/last/sum within
  the regular-session interval; use `source_last_trade`, unadjusted/no interpolation.
  Reject unresolved degraded coverage even when offending rows are extended-hours.
  Verify the immediate previous eligible session rather than weekdays or UTC dates.
  Keep visible dividends as context; do not insert an adjustment policy.
- [ ] **4.4 Run green plus `tests/unit/research/test_options_shortlist.py` calendar,
  close and action regressions.** Assert each source row is included, excluded,
  duplicate or rejected exactly once in the session accounting.
- [ ] **4.5 Update the new guide and commit:**
  `feat(data): assemble evidence-bound regular-session inputs`.

## Task 5: As-known definition state, contract enrichment and whole-chain assembly

**Files:** Create `src/trading_bot/market_data/options_definition_inputs.py`,
`tests/unit/market_data/test_options_definition_inputs.py`; extend the source fixture
helper and `docs/options-native-data.md`.

**Interfaces consumed:** Typed native definitions from Task 2, reviewed definition,
calendar and contract-term roles from Task 3, existing `OptionContract`,
`OptionsDataRecord`, `ChainSnapshot`, `point_in_time` and `select_chain`.

**Interfaces produced:** `ContractReferenceInput` supplies hash-bound, historically
scoped term/session evidence for exact standardized identities; no generic multiplier
or settlement-date default. Its fields are `references: tuple[PrivateArtifactRef, ...]`
and `claim_hashes: tuple[DataHash, ...]`; Task 3's exact reviewed parsers recompute
terms from these references, not an unchecked caller-supplied contract.
`DefinitionInputs` contains `records: tuple[OptionsDataRecord, ...]`,
`contract_ids: tuple[str, ...]`, `visible_hash: DataHash`,
`visible_native_hashes: tuple[DataHash, ...]`, `baseline_verified: bool`,
`update_count: int`, `delete_count: int`, `reasons: tuple[str, ...]`.
`assemble_definition_inputs(manifest_path: Path, reference: ContractReferenceInput,
*, verification: SourceVerification, as_of: datetime, loaded: LoadedConfig,
repository_root: Path) -> DefinitionInputs`.

- [ ] **5.1 Write failing chain tests:**

```python
def test_future_definition_does_not_enter_open_chain(future_addition_case):
    result = future_addition_case.assemble()
    assert result.contract_ids == future_addition_case.baseline_contract_ids
    assert result.visible_hash == future_addition_case.before_future_hash

def test_midnight_expiry_is_not_a_trading_deadline(missing_terms_case):
    result = missing_terms_case.assemble()
    assert result.records == ()
    assert "contract_terms_unverified" in result.reasons
```

Cover historical ID reuse and half-open mappings; exact duplicate update versus
conflicting update; visible deletion; unknown baseline; partial-symbol declarations
with and without explained interval coverage; raw-symbol/strike/type mismatch; raw
multiplier sentinel; unsupported adjusted contracts; missing tick or eligible session;
whole chain of 10,001 members; a definition visible one nanosecond after the open.
Source update semantics must be evidenced; an unknown action is never treated as ADD.

- [ ] **5.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/unit/market_data/test_options_definition_inputs.py -q`.
- [ ] **5.3 Implement as-known membership and term enrichment.** Use explicit verified
  baseline plus visible update/delete state, never the daily union or current IDs.
  Build the complete declared chain before existing eligibility/ranking; no nearby-strike
  truncation. Require multiplier/deliverable 100, USD, American/physical/PM, unadjusted,
  exact OCC identity, historical tick, last-trading and settlement reference times.
  Unknown or conflicting facts yield no canonical chain and fixed reasons.
- [ ] **5.4 Run green plus `test_options_records.py`, `test_options_data_codec.py`,
  and native-definition regressions.** Existing staging's false verification flags
  remain false; enrichment is a new derived artifact, not a rewritten manifest.
- [ ] **5.5 Update the guide and commit:**
  `feat(data): reconstruct scoped point-in-time option chains`.

## Task 6: Verified v2 shortlist bridge with unchanged v1 behavior

**Files:** Create `src/trading_bot/research/options_shortlist_v2.py`,
`src/trading_bot/research/options_shortlist_v2_wire.py`,
`tests/unit/research/test_options_shortlist_v2.py`,
`tests/unit/research/test_options_shortlist_v2_wire.py`.
Modify `src/trading_bot/research/options_shortlist.py` only for shared pure-policy
extraction; keep existing public v1 types/codecs/guards. Extend the new operator guide.

**Interfaces consumed:** Tasks 3–5 verification/session/definition inputs, existing
`OptionsShortlistCandidate`, policy/config, exact Decimal bounds and canonical hashes.
Reuse the existing `_contract_identities(contracts)`, `_eligible(contract, as_of)`
and `_rank(contracts, close, day, settings)` signatures directly. Do not construct a
synthetic `ShortlistSessionInput` or `ShortlistEvidence` to reach them; v1 `_selection`
retains its source guard and historical behavior.

**Interfaces produced:** `VerifiedShortlistInput` binds source-bundle identity,
source manifest identities, reference inputs, the decision session and canonical
config; fields are `bundle: SourceEvidenceBundle`, `bars: PrivateArtifactRef`,
`definitions: PrivateArtifactRef`, `session: SessionReferenceInput`,
`contracts: ContractReferenceInput`, `config_hash: ConfigHash`.
It never deserializes a trusted `SourceVerification`. `VerifiedShortlistResult`
has schema `options-shortlist-result-v2`, fixed policy version
`spy-prior-close-atm-30d-v1`, `source_kind: Literal["imported"]`,
`status: Literal["selected", "no_candidate"]`,
`candidates: tuple[OptionsShortlistCandidate, ...]`, `reasons: tuple[str, ...]`,
`decision_hash: DataHash`, `input_hash: DataHash`, `verification: SourceVerification`,
`session_id: str`, `as_of: datetime`, `config_hash: ConfigHash`, `code_hash: DataHash`,
`input_record_count: int`,
and the four immutable false authority flags.
`select_verified_shortlist(request: VerifiedShortlistInput, *, loaded: LoadedConfig,
repository_root: Path) -> VerifiedShortlistResult` always reruns source verification
and canonical assembly. `decode_verified_shortlist_input(body: bytes, *,
loaded: LoadedConfig) -> VerifiedShortlistInput` uses `options-shortlist-input-v2`;
`encode_verified_shortlist_input(request: VerifiedShortlistInput) -> bytes` is its inverse.
`encode_verified_shortlist_result(result: VerifiedShortlistResult) -> bytes` emits
the result schema; no public decoder turns a saved result into trusted selection evidence.
`verified_shortlist_code_hash() -> DataHash` in `options_shortlist_v2.py` binds the
fixed installed inventory, including Task 3's source-rule identity and shared policy;
Task 8 adds its composition modules to that inventory. V1's stored identities remain intact.

- [ ] **6.1 Write failing bridge and compatibility tests:**

```python
def test_v1_imported_input_stays_denied(loaded):
    case = imported_case()
    result = select_options_shortlist(
        case, settings=loaded.config.options.shortlist,
        config_hash=loaded.config_hash, code_hash=content_hash("fixture-code"),
        input_hash=content_hash(case),
    )
    assert result.reasons == ("source_evidence_unverified",)

def test_future_append_preserves_causal_hash(verified_fixture_pair):
    before, after = verified_fixture_pair.run_private_test_composition()
    assert before.candidates == after.candidates
    assert before.decision_hash == after.decision_hash
    assert before.input_hash != after.input_hash

def test_all_authority_flags_remain_false(v2_fixture_result):
    assert not any((v2_fixture_result.production_eligible,
                    v2_fixture_result.evidence_promotable,
                    v2_fixture_result.download_authorized,
                    v2_fixture_result.live_authorized))
```

Before any shared-policy refactor, capture explicit synthetic v1 wire/decision golden
assertions with fixed supplied config/code hashes; old archived hashes do not regenerate.
Test 21/30/45 DTE, 29/31 tie, lower-strike tie, one missing side, permutation, complete
record/byte limit+1, forged/copy-pasted verification, changed rulebook and returned
canonical records with altered source hashes. Later audit invalidation changes usability
but not stored as-known candidates/hash. No request accepts quote/outcome fields.
Test-only positive compositions use fabricated rulebooks from Task 3; shipped CLI has
no switch to enable them. Production semantic blockers remain visible, not fixture-cleared.

- [ ] **6.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/unit/research/test_options_shortlist_v2.py tests/unit/research/test_options_shortlist_v2_wire.py -q`.
- [ ] **6.3 Implement the bridge and closed v2 codecs.** Share ranking/identity checks
  without routing imported data through a synthetic label or loosening v1 validators.
  Recompute evidence from exact inputs, not caller verification objects. V1 decision
  hashes are preserved for identical supplied identities; installed-code hashes may
  change normally. V2 causal hashes exclude irrelevant future/full-archive integrity.
- [ ] **6.4 Run green and all existing `tests/unit/research/test_options_shortlist*`
  plus `tests/integration/cli/test_options_shortlist.py`.** Snapshot false live locks
  and unchanged synthetic replay source rejection.
- [ ] **6.5 Update the guide and commit:**
  `feat(research): add independently verified imported shortlist bridge`.

## Task 7: Complete quote-coverage manifest and purchase handoff

**Files:** Create `src/trading_bot/research/options_acquisition_models.py`,
`options_acquisition.py`, `options_acquisition_wire.py` in the same directory;
`tests/unit/research/test_options_acquisition.py`,
`tests/unit/research/test_options_acquisition_wire.py`; extend the operator guide.

**Interfaces consumed:** V2 shortlist results and verification/audit identities,
existing canonical hashes and native resource limits. No cost/data HTTP client.

**Interfaces produced:**

- `CoverageWindow(dataset: str, schema: str, symbol: str, stype_in: str,
  start_ns: int, end_ns: int,
  requirement_ids: tuple[str, ...], selection_hashes: tuple[DataHash, ...])`.
- `StudyCoverageRequirements`: immutable preregistration identity/time, exact requested
  decision range/session IDs and windows for initialization, entry/monitoring/exits,
  underlying observations, expiries and settlement follow-through; explicit consumer
  and source-semantics identities. No default splits, holding period or settlement lag.
- `CoverageManifest`: all selected/denied sessions, unioned requests, reverse coverage
  links, missing dependencies, incomplete obligations, hash and the four false flags.
  `status` is `requirements_complete|blocked`, not authorization or economic acceptance.
  `requests: tuple[CoverageWindow, ...]`, `reasons: tuple[str, ...]` and
  `incomplete_obligations: tuple[str, ...]` are the fields asserted below. Batched API
  groups are separate from this per-symbol canonical coverage, never a symbol-list string.
- `build_coverage_manifest(results: tuple[VerifiedShortlistResult, ...], *,
  requirements: StudyCoverageRequirements | None, loaded: LoadedConfig) -> CoverageManifest`.
- `decode_coverage_requirements(body: bytes, *, loaded: LoadedConfig)
  -> StudyCoverageRequirements`; `encode_coverage_manifest(manifest: CoverageManifest)
  -> bytes`, with schemas `options-study-coverage-v1` and `options-acquisition-manifest-v1`.

- [ ] **7.1 Write failing union/coverage tests:**

```python
def test_missing_preregistration_cannot_create_purchase_ready_list(shortlists, loaded):
    result = build_coverage_manifest(shortlists, requirements=None, loaded=loaded)
    assert result.status == "blocked"
    assert "coverage_requirements_missing" in result.reasons
    assert result.download_authorized is False

def test_year_end_does_not_cut_required_exit_tail(year_end_case):
    manifest = year_end_case.build()
    assert manifest.requests[-1].end_ns == year_end_case.required_january_end_ns
    assert manifest.incomplete_obligations == year_end_case.missing_tail_dependencies

def test_duplicates_preserve_reverse_links_without_double_request(overlap_case):
    manifest = overlap_case.build()
    assert len(manifest.requests) == 1
    assert manifest.requests[0].selection_hashes == overlap_case.both_selection_hashes
```

Add missing session/pair, mismatched preregistration/config/consumer, future-selected
requirements, disjoint versus overlapping windows, absent warmup, 101-symbol request
chunking, exact nanosecond boundaries, missing underlying quote requirements, unsupported
pre-feed-change event schema and selected-but-unquoted contracts. Minute-sampled CBBO
must not satisfy an event-age requirement. An unavailable candidate remains selected
in the record; it is not replaced. Cover missing initialization state before first quote.

- [ ] **7.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/unit/research/test_options_acquisition.py tests/unit/research/test_options_acquisition_wire.py -q`.
- [ ] **7.3 Implement deterministic exact-window union.** Group only compatible
  dataset/schema/symbology/symbol requirements; merge overlapping/adjacent coverage,
  retain disjoint intervals, sort stable and preserve all reverse links. Batch at most
  100 symbols only when their exact windows/schema agree. Keep required tail/reference
  gaps explicit and preserve every denial. Do not create duplicate minute and event
  purchases by default or infer consumer requirements from prices/outcomes.
- [ ] **7.4 Run green plus Task 6 tests and existing cost-request tests.** Confirm
  CMBP-1 coverage descriptors do not broaden the CBBO-only diagnostic or enable a data API.
- [ ] **7.5 Document the separate credit handoff and commit:**
  `feat(research): freeze complete deduplicated data coverage requests`.
  The handoff must compare exact customized-request costs for the entire dependent
  package, using fresh applicable credits less pending accepted costs and prior use
  of the grant. Existing acquired scopes are not bought again. Reconcile uncertain
  accepted jobs before retries. No source/manifest `true` flag or local estimate
  authorizes a purchase. No further user approval is required when an actual necessary
  purchase meets the recorded credit-only authority; stop on cash/subscription/new
  agreement/over-budget exposure. This is an operator procedure, not new purchasing code.

## Task 8: Offline commands, regression gates and evidence-based handoff

**Files:** Create `src/trading_bot/cli/options_native.py`,
`src/trading_bot/research/options_native_io.py`,
`tests/integration/cli/test_options_native.py`,
`tests/integration/research/test_native_options_pipeline.py`.
Modify only `src/trading_bot/cli/options_research.py` for four command registrations,
`.github/workflows/options-research.yml` to run the new research suites without skips,
`tests/integration/cli/test_options_research_cli.py` for import-boundary coverage,
and `docs/options-native-data.md` for actual usage/results/limitations.

**Interfaces consumed:** Tasks 1–7. Four command callbacks live in `options_native.py`
and load the canonical native simulation profile with an explicitly empty environment:

- `native-bars-import SOURCE --start UTC --end UTC --output-root PRIVATE_ROOT`.
- `native-source-verify EVIDENCE --as-of UTC --start UTC --end UTC --output-root PRIVATE_ROOT`.
- `native-options-shortlist INPUT --output-root PRIVATE_ROOT`.
- `options-coverage-manifest RESULTS --requirements FILE --output-root PRIVATE_ROOT`.

`RESULTS` is a bounded private `options-shortlist-index-v1` index of
`(input: PrivateArtifactRef, expected_result_hash: DataHash)` entries, not a directory
glob or trusted result cache. Re-run Task 6 for each exact input and require its
encoded result to match before passing results to Task 7; source/rule changes deny
the old index until explicitly regenerated. Never qualify a forged saved result.
Support
`--config-dir` consistently with existing options commands; no flag for keys, network,
rulebook injection, trading modes, forced trust or purchase execution. Source and all
reference paths must pass the private-root checks. Standard output is only status,
counts, reason codes and artifact hashes. Semantic denial returns exit 2, malformed
input/storage failure exit 1, verified completion exit 0; document those distinctions.

**Interfaces produced:** Command callbacks are `native_bars_import`,
`native_source_verify`, `native_options_shortlist` and `options_coverage_manifest`,
all returning `None`; explicit input/output/config paths use `Path`, time arguments
use strict UTC strings converted without floats. In `options_native_io.py`, provide:

- `read_native_document(path: Path, *, loaded: LoadedConfig, repository_root: Path)
  -> bytes`: bounded private read using the existing store primitives.
- `write_native_report(root: Path, result: SourceVerification | VerifiedShortlistResult
  | CoverageManifest, *, loaded: LoadedConfig, repository_root: Path) -> DataHash`:
  validate and dispatch to the corresponding closed encoder, then atomically publish
  under `manifests/<sha256>.json` with the existing no-overwrite implementation.
- `ShortlistIndexEntry(input: PrivateArtifactRef, expected_result_hash: DataHash)` and
  `decode_shortlist_index(body: bytes, *, loaded: LoadedConfig)
  -> tuple[ShortlistIndexEntry, ...]`; reject duplicate identities and bound index size
  by the existing shortlist record/byte ceilings. Iterate sessions, not all native history.

- [ ] **8.1 Write failing end-to-end and capability-denial tests:**

```python
def test_real_source_without_publication_evidence_stays_blocked(cli_denial_case):
    result = cli_denial_case.invoke()
    assert result.exit_code == 2
    assert result.json["production_eligible"] is False
    assert "historical_availability_unverified" in result.json["reasons"]

def test_offline_composition_cannot_read_credentials_or_send_network(offline_probe):
    offline_probe.invoke_all_four_commands()
    assert offline_probe.credential_reads == 0
    assert offline_probe.network_calls == 0
    assert offline_probe.broker_constructions == 0
```

Use synthetic bytes for both cases despite the test's imported-source claim. Block
socket/HTTP, ambient credential/env reads, subprocess escapes, DuckDB external access
and broker imports in the fixture. The positive whole-pipeline test uses only the
private fabricated-rule composition, never a shipped CLI trust switch. Verify stable
hashes/counts across replay, truthful incomplete status, private file modes, sanitized
errors and preservation after disk exhaustion/interrupted publication. Any CLI result
containing private paths, provider payload, raw symbol/price or exception text fails.
`test_saved_result_index_is_recomputed_before_coverage` substitutes a fabricated
result hash and asserts exit 2 with no `requirements_complete` report.

- [ ] **8.2 Run red:**
  `PYTHONPATH=src uv run --project research --frozen pytest tests/integration/cli/test_options_native.py tests/integration/research/test_native_options_pipeline.py -q`.
- [ ] **8.3 Implement the four callback registrations and private artifact composition.**
  Bind code inventories to all new/verifier modules without rewriting historical
  hashes. Update the research workflow's explicit test list; native backend tests
  must execute. Keep general CLI, runtime, deployment and all live locks untouched.
- [ ] **8.4 Run narrow suites green, then the verification matrix below.** Record
  failures with provenance, including baseline missing files, rather than suppressing
  tests. No fresh baseline claim is made in this planning document.
- [ ] **8.5 Privately run the actual acquired-data intake after code review.** Preserve
  immutable archives and receipts. Compare current observations to the prior profile
  without treating that profile as an immutable expectation if source identity changed.
  Emit the exact missing semantic/reference/study dependencies. Do not evaluate returns,
  fabricate point-in-time claims or publish licensed rows. Benchmark peak memory and
  runtime locally, without hardware purchases or deployment changes.
- [ ] **8.6 Complete the Native whole-branch review, address findings and rerun affected
  checks.** Reviewer receives only code and fabricated fixtures on exact committed base,
  never the real archives or account records. Primary agent owns final integration.
- [ ] **8.7 Update the new guide with actual outcomes and commit owned Task 8 files:**
  `feat(cli): expose fail-closed native options research workflow`.

## Verification matrix and safe commands

Run from the Robinhood implementation worktree. Use a task-specific private temporary
directory for coverage, audit exports and generated SBOM; do not overwrite tracked or
unrelated artifacts. These are **planned commands**, not executed results.

```sh
umask 077
options_native_checks_dir=$(mktemp -d /private/tmp/options-native-checks.XXXXXX)
uv run --frozen ruff check .
uv run --frozen mypy src
COVERAGE_FILE="$options_native_checks_dir/.coverage" uv run --frozen pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80 --cov-report="json:$options_native_checks_dir/coverage.json"
uv run --frozen python scripts/check_critical_branch_coverage.py --report "$options_native_checks_dir/coverage.json"
uv run --frozen bandit -c pyproject.toml -r src
uv lock --check
uv lock --project research --check
uv export --locked --all-groups --no-emit-project --output-file "$options_native_checks_dir/locked-requirements.txt"
uv run --frozen pip-audit --requirement "$options_native_checks_dir/locked-requirements.txt" --no-deps --disable-pip
uv export --project research --locked --all-groups --no-emit-project --output-file "$options_native_checks_dir/research-requirements.txt"
uv run --frozen pip-audit --requirement "$options_native_checks_dir/research-requirements.txt" --no-deps --disable-pip
uv run --frozen pytest tests/smoke/test_sbom_reproducible.py tests/deployment -q
uv run --frozen python scripts/generate_sbom.py --output "$options_native_checks_dir/sbom.cdx.json"
docker compose config --quiet
```

Retain the existing 90% per-critical-file branch gate. Run these new research paths
together in addition to the existing workflow's regression list:

```sh
PYTHONPATH=src uv run --project research --frozen pytest \
  tests/unit/market_data/test_databento_bars.py \
  tests/unit/config/test_options_native_data_config.py \
  tests/integration/market_data/test_databento_bar_store.py \
  tests/integration/market_data/test_databento_native_rows.py \
  tests/unit/market_data/test_options_source_contracts.py \
  tests/unit/market_data/test_options_source_verify.py \
  tests/unit/market_data/test_options_session_inputs.py \
  tests/unit/market_data/test_options_definition_inputs.py \
  tests/unit/research/test_options_shortlist_v2.py \
  tests/unit/research/test_options_shortlist_v2_wire.py \
  tests/unit/research/test_options_acquisition.py \
  tests/unit/research/test_options_acquisition_wire.py \
  tests/integration/cli/test_options_native.py \
  tests/integration/research/test_native_options_pipeline.py -q
sh -n infra/digitalocean/deploy.sh
sh -n infra/digitalocean/deploy-remote.sh
sh -n infra/digitalocean/backup.sh
sh -n infra/digitalocean/restore.sh
```

Existing research backends must be present at pinned versions; a skipped decoder suite
does not qualify. The `sh -n` checks parse the current tracked scripts without running
them. Add any new tracked shell script to this list after read-only discovery.

The public-advisory audit has prior operator authority for package names/versions only.
If unavailable or requiring a new disclosure, report the specific block. Do not run
authenticated tests; Pytest's existing default exclusion remains. No CI push, Cloud
job, Docker deployment or broker call is authorized by these local checks. Generated
SBOM is a reproducibility/lock-digest artifact with an empty component list in the
current generator, not a complete inventory; do not overstate its security coverage.

## Spec coverage and final disposition

| Spec section | Owning tasks |
| --- | --- |
| 1–3 Intent, authority, architecture, current boundary | All tasks; Task 8 composition and guide |
| 4 Native precision, row accounting and immutable storage | Tasks 1–2 |
| 5 Source claims, calendars/actions, definitions/terms | Tasks 3–5 |
| 6 Versioned verified bridge and causal hashes | Task 6 |
| 7 Coverage completeness and credit handoff | Task 7 |
| 8 CLI, privacy and partial/failure status | Tasks 2 and 8 |
| 9 Failure scenarios, regressions and real-input limitations | Every task's red/green tests and Task 8 verification |
| 10 Review gate and preserved risk restrictions | Global Constraints and execution boundary |

Report separately: implementation/test status, real-source qualification, acquisition
manifest readiness, economic evidence, and broker/runtime/live authorization. A fixture-
verified implementation with missing real source facts is **not** qualified historical
research. A complete quote request with adequate credits is **not** economic acceptance.
This milestone must not claim genuine economic testing or live readiness is complete.

Planning self-review covers spec mapping, exact interfaces, v1 compatibility, five
Review Focus cases, scope and task size. All implementation checkboxes remain unchecked.
Next gate: operator reviews this plan; after approval, execute using the preserved
Native method. No product implementation or new data purchase occurred while writing it.
