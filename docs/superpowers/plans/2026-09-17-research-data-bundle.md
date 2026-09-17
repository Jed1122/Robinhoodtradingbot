# Verifiable Research Data Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository ownership overrides generic worker delegation: the primary implements all production code; actual Codex Cloud workers own only the two specified synthetic test contracts.

**Goal:** Implement a private, synthetic-only, content-addressed data bundle and a conservative offline loader for the existing decision-cycle interface, without creating promotion evidence.

**Architecture:** Keep immutable bundle values, strict serialization, synthetic normalization, verification, local file I/O, and query selection in focused `market_data/` modules. Wrap the existing manifest and domain records instead of modifying their hashes or constructors. Integrate through the existing `MarketSnapshotLoader` protocol only in an offline test composition.

**Tech Stack:** Python `>=3.12,<3.15`; standard-library dataclasses, JSON, SHA-256, Decimal and POSIX file APIs; existing Pytest/pytest-asyncio, Ruff, mypy, and Bandit. No new dependency or lockfile change.

**Spec:** [Approved data-bundle design](../specs/2026-09-17-research-data-bundle-design.md), approved by the operator on 2026-09-17.

## Global Constraints

- Every result produced by this milestone remains non-promotable.
- No live/paper CLI or runtime factory is wired to it in this milestone.
- Existing public constructors, canonical serialization, hash formulas, and legacy artifact interpretation remain unchanged.
- Private data must not be copied into Git, logs, review messages, or Codex Cloud tasks.
- All instants must satisfy the repository's canonical UTC validation.
- Use service-owned directories with mode `0700` and regular files with mode `0600`, no symlink following, and digest-derived child paths only.
- Set `spread_percentage=None` in v1.
- No interpolation or corporate-action economic policy is added.
- Central baseline remains Ruff, strict mypy on `src`, full Pytest with branch measurement and the unchanged 80% coverage floor, Bandit, lock validation, and existing CI checks.
- No data acquisition, authentication, broker calls, production-ledger access, credential operations, deployment, or live operation. No strategy, exposure, risk, authorization, reconciliation, or promotion changes.

---

## Execution state and sequencing

Planning base: `0fd34b2cea0787ea33716cda11f649b88259c47a`, branch
`codex/continue-implementation-from-commit-7c4dcd1`. The bundle and loader are **not implemented**.
Existing recording/replay foundations are partial. Source authenticity and promotion remain
blocked. All task checkboxes below are intentionally unchecked.

Worktree: `/Users/jedweinstein/Documents/robinhood-multi-asset-trading-system/worktrees/robinhood-system-implementation`.
It is already a linked worktree; preserve `.coverage 2`, `.coverage 3`, `.coverage 4`, and `error.log`.
Recheck actual branch/status/base at execution; do not work in the unrelated Polymarket cwd.

Critical path: Task 1 types/codec → Task 2 normalization/build → Task 3 verification →
Task 4 loader → Task 6 integration. Task 5 private I/O follows Task 3 and can be completed
after Task 4 while the two Cloud workers add independent tests. Production work stays
sequential under the primary. No elapsed paper/shadow gate is part of this execution plan.

Commit each passing task on the integration branch after reviewing the exact staged paths.
Do not commit a stub-only production API. Cloud dispatch happens after Task 4, when callable
interfaces exist; workers strengthen tests while the primary implements private I/O and
integration. Freeze the exact post-Task-4 SHA in both prompts. Do not use the stale default branch.

## Files and responsibility

All paths below are relative to the worktree above. Unlisted source paths are read-only.

| Path | Owner and purpose |
|---|---|
| `src/trading_bot/market_data/bundle_models.py` | Primary: immutable values, limits and reason-code error; no I/O. |
| `src/trading_bot/market_data/bundle_codec.py` | Primary: bounded strict v1 JSON decoding/encoding and domain reconstruction. |
| `src/trading_bot/market_data/bundle_normalize.py` | Primary: only synthetic-v1 source normalization and package assembly. |
| `src/trading_bot/market_data/bundle_verify.py` | Primary: raw/normalized/manifest/coverage consistency; immutable verified result. |
| `src/trading_bot/market_data/snapshot_loader.py` | Primary: as-of query coverage and existing snapshot construction. |
| `src/trading_bot/market_data/bundle_store.py` | Primary: private descriptor-relative artifact I/O; no database or credentials. |
| `tests/unit/market_data/_bundle_fixtures.py` | Primary: deterministic synthetic package helper; not autouse or real data. |
| `tests/unit/market_data/test_bundle_models.py`, `test_bundle_codec.py`, `test_bundle_normalize.py`, `test_bundle_verify.py`, `test_snapshot_loader.py` | Primary: narrow TDD tests, in the same directory. |
| `tests/integration/market_data/test_bundle_store.py` | Primary: private temporary filesystem tests. |
| `tests/integration/simulation/test_bundle_decision_cycle.py` | Primary: real loader/features plus incapable test stages. |
| `tests/unit/market_data/test_bundle_contract.py`, `docs/reviews/data-bundle-tests-004.md` | DATA-BUNDLE-TESTS-004 Cloud worker only. |
| `tests/unit/market_data/test_snapshot_data_contract.py`, `docs/reviews/snapshot-data-tests-004.md` | SNAPSHOT-DATA-TESTS-004 Cloud worker only. |
| `docs/architecture.md`, `docs/strategy-research.md`, `docs/limitations.md`, `PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md` | Primary: record only completed behavior and observed verification. |

Do not re-export the new modules from `market_data/__init__.py`: `app.py` already imports
that package, and importing the application-facing loader there could create a cycle.
Do not modify `recording.py`, `replay.py`, `universe.py`, `adjustments.py`, `domain/`,
`research/report.py`, `app.py`, `strategies/`, `runtime/`, `persistence/`, configs or CI.

## Frozen v1 contract

These are new interfaces, not descriptions of currently implemented code. The following
names, signatures, wire keys, and behavior are fixed for this plan. Internal private helper
names may vary. An implementation-discovered contract change must be reviewed by the primary,
recorded here, and sent to both workers before their tests are integrated.

### Values and API

Define the following frozen, slotted dataclasses in `bundle_models.py`, with exact-field
validation in constructors. Existing domain types are imported, not duplicated.

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from trading_bot.domain import Bar, BarInterval, CorporateAction, DataHash, InstrumentId
from trading_bot.market_data.recording import ResearchDataManifest
from trading_bot.market_data.universe import UniverseMembership

type RecordKind = Literal["bar", "membership", "baseline", "corporate_action", "coverage"]
type CoverageKind = Literal["bar", "membership", "corporate_action"]
type CoverageState = Literal["complete", "gap", "unknown"]

@dataclass(frozen=True, slots=True)
class BundleLimits:
    max_envelope_bytes: int
    max_blob_bytes: int
    max_total_bytes: int
    max_records: int
    max_json_depth: int

@dataclass(frozen=True, slots=True)
class InstrumentMapping:
    instrument_id: InstrumentId
    symbol: str

@dataclass(frozen=True, slots=True)
class BarSlot:
    starts_at: datetime
    ends_at: datetime

@dataclass(frozen=True, slots=True)
class MembershipBaseline:
    instrument_id: InstrumentId
    coverage_start: datetime
    effective_at: datetime
    announced_at: datetime
    included: bool

@dataclass(frozen=True, slots=True)
class CoverageDeclaration:
    instrument_id: InstrumentId
    record_kind: CoverageKind
    interval: BarInterval | None
    starts_at: datetime
    ends_at: datetime
    state: CoverageState
    expected_slots: tuple[BarSlot, ...]

@dataclass(frozen=True, slots=True)
class SourceCapture:
    source_id: str
    origin: Literal["synthetic", "imported"]
    instrument_ids: tuple[InstrumentId, ...]
    record_kinds: tuple[RecordKind, ...]
    requested_start: datetime
    requested_end: datetime
    collected_at: datetime
    claimed_published_at: datetime | None
    limitation_codes: tuple[str, ...]
    raw_bytes: bytes

@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_id: str
    format_id: str
    normalizer_version: str
    origin: Literal["synthetic", "imported"]
    instrument_ids: tuple[InstrumentId, ...]
    record_kinds: tuple[RecordKind, ...]
    requested_start: datetime
    requested_end: datetime
    collected_at: datetime
    claimed_published_at: datetime | None
    limitation_codes: tuple[str, ...]
    byte_length: int
    blob_sha256: str
    descriptor_hash: DataHash

type RecordValue = Bar | UniverseMembership | MembershipBaseline | CorporateAction | CoverageDeclaration

@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    kind: RecordKind
    source_hash: DataHash
    locator: int
    available_at: datetime
    price_basis: Literal["unadjusted", "adjusted", "unknown"] | None
    value: RecordValue
    record_hash: DataHash

@dataclass(frozen=True, slots=True)
class BundleEnvelope:
    schema: Literal["research-bundle-v1"]
    instruments: tuple[InstrumentMapping, ...]
    sources: tuple[SourceDescriptor, ...]
    records: tuple[NormalizedRecord, ...]
    manifest: ResearchDataManifest
    classification: Literal["synthetic"]
    limitation_codes: tuple[str, ...]
    bundle_hash: DataHash

@dataclass(frozen=True, slots=True)
class BundlePackage:
    envelope_bytes: bytes
    blobs: tuple[tuple[str, bytes], ...]  # exact byte digest -> body, sorted by digest

@dataclass(frozen=True, slots=True)
class SnapshotSettings:
    interval: BarInterval
    history_start: datetime
    minimum_bars: int
```

`BundleLimits` has no defaults; exact positive integers only (bool is not int here), with
`max_total_bytes >= max_envelope_bytes` and `>= max_blob_bytes`. `minimum_bars` is an exact
integer at least 2. This is an offline constructor contract, not a competing config graph.
Tests use small explicit limits. Production operator defaults are not introduced.

`BundleError(ValueError)` exposes only `code: str` and `record_index: int | None`.
The constructor accepts only these registered codes, optional nonnegative exact-int index,
and sets its message to the code alone. Translate low-level exceptions with `from None`;
no raw payload, path, invalid value, `repr`, or underlying exception message is retained.

```text
bundle_limits_invalid       bundle_input_too_large     bundle_json_invalid
bundle_schema_invalid       bundle_value_invalid       bundle_source_unsupported
bundle_hash_mismatch        bundle_blob_mismatch       bundle_normalization_mismatch
bundle_manifest_mismatch    bundle_record_conflict     bundle_scope_mismatch
bundle_coverage_invalid     bundle_fixture_mismatch    bundle_path_invalid
bundle_storage_unavailable  bundle_storage_conflict    snapshot_query_invalid
snapshot_coverage_missing   snapshot_records_unavailable
snapshot_membership_missing snapshot_not_member        snapshot_history_insufficient
snapshot_interpolated      snapshot_price_basis_unsupported
snapshot_action_unsupported
```

Public functions/classes (parameter names are part of the worker contract):

```python
# bundle_codec.py
def decode_envelope(encoded: bytes, *, limits: BundleLimits) -> BundleEnvelope: ...
def encode_envelope(envelope: BundleEnvelope) -> bytes: ...

# bundle_normalize.py
def assemble_bundle(*, sources: tuple[SourceCapture, ...],
                    instruments: tuple[InstrumentMapping, ...],
                    limits: BundleLimits) -> BundlePackage: ...

# bundle_verify.py; init=False, constructed only inside verify_bundle; not a security token
@dataclass(frozen=True, slots=True, init=False)
class VerifiedBundle:
    envelope: BundleEnvelope
    limitation_codes: tuple[str, ...]

def verify_bundle(package: BundlePackage, *, limits: BundleLimits) -> VerifiedBundle: ...

# snapshot_loader.py
class BundleSnapshotLoader:
    def __init__(self, bundle: VerifiedBundle, *, settings: SnapshotSettings) -> None: ...
    @property
    def bundle_hash(self) -> DataHash: ...
    @property
    def limitation_codes(self) -> tuple[str, ...]: ...
    async def load(self, universe: tuple[InstrumentId, ...],
                   as_of: datetime) -> ValidatedMarketSnapshot: ...

# bundle_store.py; root must already exist outside repository_root
def write_bundle(root: Path, package: BundlePackage, *, repository_root: Path,
                 limits: BundleLimits) -> DataHash: ...
def read_bundle(root: Path, bundle_hash: DataHash, *, repository_root: Path,
                limits: BundleLimits) -> VerifiedBundle: ...
```

Signature-only ellipses above denote documentation contracts, not production stubs. All
types resolve from `bundle_models`, `bundle_verify`, `pathlib`, or the existing `app.py`.
`VerifiedBundle` carries immutable records, not raw blobs; verification copies/decodes input
before returning. There is no `trusted`, `accepted`, `eligible`, or `promotable` property.
No module can convert it to a promotion context or persist it in the evidence ledger.

### Synthetic wire format, canonical form and hashes

Raw source bodies are strict UTF-8 JSON with exactly `schema` and `records`; schema is
`synthetic-market-v1`. Each record has exactly `kind`, `available_at`, `price_basis`, `value`.
`value` has the fields of the corresponding `RecordValue` dataclass, **excluding `data_hash`**
for bars/actions. `coverage.expected_slots` is a JSON array of slot objects. Records contain
no class names or constructors. A baseline is a source assertion, not an event synthesized
by the importer. `price_basis` is required for bars and exactly null for other kinds.

Envelope JSON uses exactly the `BundleEnvelope` dataclass keys above, recursively following
the declared dataclass shapes; domain values include computed `data_hash` where present.
`NormalizedRecord.kind` discriminates its value. Decimal values are canonical fixed-form
strings through the existing `canonical_decimal_text`; UTC instants use six fractional digits
and `Z`; dates use `YYYY-MM-DD`; enums use their existing string values; tuples use arrays.
No floats, NaN, Infinity, exponent-form decimal strings, duplicate object keys, unknown
fields, coercion of bool to int, or class-directed deserialization. Require canonical scalar
spelling; JSON key order/insignificant whitespace may differ on input. Re-encoding is always
existing `canonical_json(value).encode("utf-8")`, with no final newline for these new packages.
Do not change legacy `write_jsonl` or report trailing-newline behavior.

Parse with duplicate-key detection and `parse_float`/`parse_constant` rejection. Scan depth
outside quoted strings before `json.loads`, bound bytes first, and count all raw plus
normalized records against the configured limit before domain construction. Reuse existing
UTC, finite Decimal, SHA-256, exact enum/bool and domain field constraints. Bundle IDs allow
only `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` and symbols `[A-Za-z0-9][A-Za-z0-9._-]{0,31}`;
these are new synthetic-format restrictions, not changes to existing domain constructors.
V1 source IDs, bar source labels, and limitation codes allow only
`[a-z][a-z0-9_-]{0,63}`. No URLs or arbitrary prose fields exist. Reject mismatched kind/value
types, duplicate mappings/IDs/symbols, and scope arrays with duplicate values.

All new hashing calls use existing `content_hash`; raw body hashing alone uses
`hashlib.sha256(raw_bytes).hexdigest()`. Exact preimages:

```python
descriptor_hash = content_hash({"domain": "source-descriptor-v1", "value": descriptor_without_hash})
record_hash = content_hash({
    "domain": "normalized-record-v1", "kind": kind, "source_hash": descriptor_hash,
    "locator": locator, "available_at": available_at, "price_basis": price_basis,
    "normalizer_version": "synthetic-normalizer-v1", "value": value_without_data_hash,
})
bundle_hash = content_hash(envelope_without_bundle_hash)  # includes schema discriminator
```

Source `format_id` is `synthetic-market-v1`; normalizer is `synthetic-normalizer-v1`;
origin must be synthetic. Imported origin, unknown normalizer and unknown format are
`bundle_source_unsupported`, never a fallback parser. Preserve `claimed_published_at` as a
claim only; it cannot substitute for `available_at`. A future imported normalizer must use
availability no earlier than collection time, but no such normalizer is implemented here.

Normalize raw array order into zero-based `locator`. Domain Bar/CorporateAction `data_hash`
equals the normalization `record_hash`; exclude that field from its own preimage. Sort
descriptors by descriptor hash, records by `(source_hash, locator)`, and blobs by byte digest.
Reject duplicate descriptors; identical blob bytes may be shared by distinct descriptors.
Preserve the supplied unique instrument/symbol order; within a symbol sort bars by
`(starts_at, ends_at)`. Rebuild manifest `raw_hashes` from ordered descriptor hashes and
`cleaned_hashes` with exactly `content_hash({"bars": bars, "symbol": symbol})` per mapping.
Do not add v1 discriminator keys inside those two legacy manifest/cleaned formulas.

The new manifest uses `corporate_action_coverage="declared_unverified"`,
`point_in_time_universe=False`, `survivorship_limitations=("source_history_unverified",)`,
`licensing_limitations=("source_license_unverified",)`. `known_gaps` and envelope limitation
codes are the sorted union of descriptor codes and the following mandatory classifications:
`synthetic_data`, `source_authenticity_unverified`, `source_history_unverified`,
`source_license_unverified`. Unknown/gap coverage adds `declared_coverage_gap`; interpolation
adds `interpolated_data`; adjusted/unknown price basis adds `price_basis_unsupported`.
These classifications are derived, never caller-supplied evidence that something passed.

### Structural coverage and query rules

At normalization/verification, require each record's instrument/kind to be in its descriptor
scope, and each bar's `source` to equal its descriptor's `source_id`. Bars and coverage
windows fit the descriptor request window. Membership events have
effective times inside it; announcements and availability may be later. Baseline effective
time may precede the window but must be no later than its explicit `coverage_start`, which
must equal the start of a membership-coverage segment for the same instrument. The baseline
source descriptor must cover that segment start. Never fabricate an inclusion event.
Actions must have effective UTC
dates touching the descriptor window; source dates do not prove intraday timing.

`CoverageDeclaration.interval` is non-null only for bars. Complete bar coverage declares
strictly ordered, nonoverlapping expected slots wholly inside its window and exactly matches
all retained bars for that instrument/interval/window, irrespective of availability. Gap and
unknown declarations have no expected slots. Non-bar declarations have none. Coverage
segments for the same instrument/kind/interval do not overlap; adjacent segments are allowed.
Conflicting bar identities, action identities, or membership timestamp keys are rejected.
Identical membership events remain compatible with the existing primitive; repeated source
locators are never allowed. Missing normalized entries relative to raw rows is a mismatch.

At query time, the required window is `[settings.history_start, as_of)`, with bar ends allowed
to equal `as_of`. Every requested kind must have visible complete coverage spanning that
window without gaps; adjacent complete segments may be composed. No calendar inference.
For each selected expected slot ending by `as_of`, its bar must also be available by `as_of`,
otherwise `snapshot_records_unavailable`; a declared complete source missing that bar is
already `bundle_coverage_invalid`. Unknown/gap coverage outside this window does not deny it.

For membership, select the visible baseline with latest `coverage_start` at/before history
start, then visible events at/after that coverage start, using effective time then announcement
time. Require baseline source availability and announcement at/before query. Reject multiple
baselines for the same instrument/coverage start rather than infer an authoritative revision.
Use existing `PointInTimeUniverse` to resolve the actual visible event tuple;
for IDs with no visible event, retain their explicit baseline state. Do not construct a fake
`UniverseMembership` from the baseline and do not use `eligibility_reasons` to establish trust.
Every requested instrument must end included; otherwise `snapshot_not_member`. Missing
baseline is `snapshot_membership_missing`. Do not silently shrink the request universe.

Reject selected interpolated bars and any price basis other than unadjusted. Reject any
retained action for that instrument with effective date between the selected earliest bar's
UTC start date and `as_of.date()`, inclusive, even if announced/available later; this is the
spec's conservative unsupported-history denial, never retrospective adjustment. No matching
action may be inferred merely from missing coverage. No selection/feature value includes a
future row. Select all available completed bars in the history window, not only the last N;
N is the minimum-history check. Histories preserve requested universe order.

Per-history hash preimage is `{"domain":"bundle-history-v1", "instrument_id": id,
"as_of": as_of, "settings": settings, "bars": ordered_selected_record_hashes,
"membership": ordered_selected_baseline_and_event_hashes,
"coverage": ordered_selected_coverage_hashes, "classification":"synthetic",
"limitations": selected_source_and_quality_codes}`. Selected limitations include mandatory
classification codes plus codes from source descriptors used by that query, not unrelated
descriptors elsewhere in the bundle. Coverage includes exactly intersecting segments;
membership hashes put the selected baseline first, followed by visible events in deterministic
effective/announcement/source/locator order.

Snapshot hash preimage is `{"domain":"bundle-snapshot-v1", "as_of": as_of,
"settings": settings, "universe": universe, "histories": ordered_history_hashes}`.
Do not include whole bundle hash: appending a disjoint irrelevant future source without
rewriting selected provenance/coverage must leave the earlier snapshot hash unchanged.

## Task 1: Immutable contract and strict envelope codec

**Files:** Create `bundle_models.py`, `bundle_codec.py`, and primary
`test_bundle_models.py` / `test_bundle_codec.py` in the directories listed above.

**Interfaces:** Consume existing domain types, `canonical_json`, `content_hash`, and
`ResearchDataManifest`; produce all value types plus `decode_envelope`/`encode_envelope`.
No file I/O, normalization, or application imports in these two modules.

- [x] Write exact-type/limit and duplicate-JSON-key tests first:

```python
import pytest
from trading_bot.market_data.bundle_models import BundleError, BundleLimits
from trading_bot.market_data.bundle_codec import decode_envelope

def test_boolean_is_not_a_byte_limit():
    with pytest.raises(BundleError) as caught:
        BundleLimits(True, 4096, 16384, 100, 12)
    assert caught.value.code == "bundle_limits_invalid"

def test_duplicate_key_is_rejected_before_schema_construction():
    limits = BundleLimits(4096, 4096, 16384, 100, 12)
    with pytest.raises(BundleError) as caught:
        decode_envelope(b'{"schema":"x","schema":"y"}', limits=limits)
    assert caught.value.code == "bundle_json_invalid"
```

- [x] Run `uv run pytest tests/unit/market_data/test_bundle_models.py tests/unit/market_data/test_bundle_codec.py -q`.
  Initially missing modules are expected; record that as interface absence, not proof of a
  behavioral regression. Once callable, demonstrate the malformed-value tests fail when the
  relevant new check is locally disabled, restoring it before any commit.
- [x] Implement the frozen dataclasses and bounded codec. Use explicit field allowlists per
  kind, reconstruct existing Decimal/UTC/enum/domain values, then compare canonical scalar
  spellings. Essential duplicate/type guard shape:

```python
def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("bundle_json_invalid")
        result[key] = value
    return result

def _positive_limit(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise BundleError("bundle_limits_invalid")
    return value
```

- [x] Add cases for every listed wire field/type, non-UTC time, unknown versions/keys,
  NaN/float/exponent Decimal, excessive nesting/bytes/records, invalid kind/value union,
  duplicate IDs/symbols, and safe errors. Add a fully populated codec round trip containing
  each record kind and a legacy manifest; a hash-shape-valid envelope need not be verified
  here because semantic/hash verification belongs to Task 3.
- [x] Run the two narrow files, `uv run ruff check src/trading_bot/market_data tests/unit/market_data`,
  and `uv run mypy src`; correct failures without weakening checks. Commit only these four files:
  `git commit -m "Add immutable research bundle contract and strict codec"`.

## Task 2: Synthetic normalization and package assembly

**Files:** Create `bundle_normalize.py`, `_bundle_fixtures.py`, `test_bundle_normalize.py`.
**Interfaces:** Consume Task 1 types/codec; produce `assemble_bundle` using the exact raw and
hash formulas above. No source autodetection, real imports, provider client, or I/O.

- [x] Add this complete minimal fixture helper in `_bundle_fixtures.py`. Other tests import
  this helper; Cloud workers may read it but use their own locally owned mutation fixtures.

```python
from datetime import UTC, datetime, timedelta
from trading_bot.domain import InstrumentId
from trading_bot.market_data.recording import canonical_json
from trading_bot.market_data.bundle_models import BundleLimits, InstrumentMapping, SourceCapture
from trading_bot.market_data.bundle_normalize import assemble_bundle

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=2)
ID = InstrumentId("SYNTH")
LIMITS = BundleLimits(131072, 65536, 1048576, 1000, 16)

def fixture_sources():
    slots = tuple({"starts_at": START + timedelta(days=i),
                   "ends_at": START + timedelta(days=i + 1)} for i in range(2))
    rows = [{"kind": "baseline", "available_at": START, "price_basis": None,
             "value": {"instrument_id": ID, "coverage_start": START, "effective_at": START,
                       "announced_at": START, "included": True}}]
    for slot in slots:
        rows.append({"kind": "bar", "available_at": slot["ends_at"],
                     "price_basis": "unadjusted", "value": {
                         "instrument_id": ID, "interval": "one_day", **slot,
                         "open": "10", "high": "11", "low": "9", "close": "10",
                         "volume": "100", "source": "fixture", "interpolated": False}})
    for kind in ("bar", "membership", "corporate_action"):
        rows.append({"kind": "coverage", "available_at": START, "price_basis": None,
                     "value": {"instrument_id": ID, "record_kind": kind,
                               "interval": "one_day" if kind == "bar" else None,
                               "starts_at": START, "ends_at": END, "state": "complete",
                               "expected_slots": slots if kind == "bar" else ()}})
    body = canonical_json({"schema": "synthetic-market-v1", "records": rows}).encode()
    return (SourceCapture("fixture", "synthetic", (ID,),
                          ("bar", "baseline", "coverage"), START, END, END, None, (), body),)

def fixture_package():
    return assemble_bundle(sources=fixture_sources(),
                           instruments=(InstrumentMapping(ID, "SYNTH"),), limits=LIMITS)
```

- [x] Add deterministic identity and imported-source rejection tests:

```python
from dataclasses import replace
import pytest
from tests.unit.market_data._bundle_fixtures import ID, LIMITS, fixture_package, fixture_sources
from trading_bot.market_data.bundle_models import BundleError, InstrumentMapping
from trading_bot.market_data.bundle_normalize import assemble_bundle

def test_assembly_is_deterministic():
    assert fixture_package() == fixture_package()

def test_imported_claim_does_not_reclassify_synthetic_source():
    source = replace(fixture_sources()[0], origin="imported")
    with pytest.raises(BundleError) as caught:
        assemble_bundle(sources=(source,), instruments=(InstrumentMapping(ID, "SYNTH"),),
                        limits=LIMITS)
    assert caught.value.code == "bundle_source_unsupported"
```

- [x] Run `uv run pytest tests/unit/market_data/test_bundle_normalize.py -q` and record the
  failing test outcome before production normalization exists.
- [x] Implement canonical descriptor construction, strict raw decoding, kind-specific
  normalization, legacy bar-group manifest construction, envelope identity and sorted blobs.
  Use these core operations after field validation, without modifying legacy helpers:

```python
blob_sha256 = hashlib.sha256(capture.raw_bytes).hexdigest()
descriptor_hash = content_hash({"domain": "source-descriptor-v1", "value": descriptor_body})
row_hash = content_hash(normalization_preimage)
domain_value = Bar(**validated_bar_fields, data_hash=row_hash)  # bar branch only
cleaned_hash = content_hash({"bars": ordered_bars_for_symbol, "symbol": mapping.symbol})
```

  `descriptor_body`, `normalization_preimage`, and `validated_bar_fields` are the explicit
  fields/preimages in the frozen contract, not arbitrary input dictionaries. Use separate
  branches for all five kinds. All branches bind source scope, normalizer version, locator
  and availability. No domain constructor is selected by data-supplied class names.
- [x] Add source/body key-order equivalence controls, exact raw-byte-versus-canonical-hash
  distinction, record-hash self-exclusion, all five record kinds, adjusted/interpolated
  classification, symbol order, multiple sources and raw-blob deduplication tests. Changing
  exact source bytes may change provenance even when decoded prices are unchanged.
- [x] Run Task 1–2 tests, `uv run pytest tests/unit/research/test_report.py tests/unit/research/test_validation.py tests/integration/market_data/test_recording_replay.py -q`,
  Ruff and mypy. Commit only this task's three files:
  `git commit -m "Build deterministic synthetic research data bundles"`.

## Task 3: Verify bindings and declared coverage

**Files:** Create `bundle_verify.py`, `test_bundle_verify.py`.
**Interfaces:** Consume `BundlePackage`, codec, synthetic normalizer and legacy manifest;
produce `verify_bundle` and factory-created immutable `VerifiedBundle`. The verifier does
not read files, query providers, accept research, or write observations.

- [x] Write one valid-bundle and one same-length byte-tamper test:

```python
from dataclasses import replace
import pytest
from tests.unit.market_data._bundle_fixtures import LIMITS, fixture_package
from trading_bot.market_data.bundle_models import BundleError
from trading_bot.market_data.bundle_verify import verify_bundle

def test_complete_fixture_verifies_without_becoming_real_evidence():
    result = verify_bundle(fixture_package(), limits=LIMITS)
    assert result.envelope.classification == "synthetic"
    assert "source_authenticity_unverified" in result.limitation_codes
    assert result.envelope.manifest.point_in_time_universe is False

def test_raw_byte_tamper_rejected():
    package = fixture_package()
    digest, body = package.blobs[0]
    changed = body.replace(b'"close":"10"', b'"close":"99"', 1)
    assert changed != body
    with pytest.raises(BundleError) as caught:
        verify_bundle(replace(package, blobs=((digest, changed),)), limits=LIMITS)
    assert caught.value.code == "bundle_blob_mismatch"
```

- [x] Run `uv run pytest tests/unit/market_data/test_bundle_verify.py -q` before the verifier
  exists; after it exists, confirm deliberate local bypass of the byte-hash comparison makes
  the tamper case fail, then restore. Do not retain bypasses or weakened asserts.
- [x] Implement verification in this order: limits/shape → envelope decode → referenced blob
  set/byte lengths/digests → descriptor and outer hash → exact normalizer replay → manifest
  equality → derived classification → cross-record scope/conflicts/coverage. Each error code
  corresponds to this stage; malformed constructor values use `bundle_value_invalid`.
  Normalizer replay may call a shared private function from `bundle_normalize`, never trust
  the serialized normalized entries. The mandatory byte comparison is:

```python
if len(body) != descriptor.byte_length or hashlib.sha256(body).hexdigest() != descriptor.blob_sha256:
    raise BundleError("bundle_blob_mismatch")
```

  Compare complete ordered normalized values, including computed domain hashes, against the
  replay. Compare manifest through `ResearchDataManifest.create(...)` and expected bar-group
  hashes, not a caller's manifest-hash string. Reject extra/unreferenced blobs and normalized
  entries; every descriptor must resolve exactly one blob, and every raw locator exactly one
  normalized entry. Sharing identical blob bytes does not permit duplicate descriptors.
- [x] Implement complete-slot equality and nonoverlap checks from the frozen contract; raw
  gap/unknown declarations are retained limitations, while contradictory complete declarations
  are rejected. Count equality is insufficient: compare exact instrument/interval/start/end
  keys and source scopes. Retain immutable records even when a query will later be denied.
- [x] Add a mutation matrix changing one layer at a time: raw bytes; digest/length; descriptor;
  normalized value/locator/source hash; stored domain hash; manifest body/hash; fixture flag;
  coverage slots; baseline conflicts; same-key conflicting memberships; duplicate bars/actions;
  deleted/extra rows/blobs; ordering and unknown fields. Rehash the outer envelope in selected
  cases to prove it does not mask a deeper mismatch. Include adjacent valid coverage segments
  and identical-event positive controls. Assert safe reason codes, not original values.
- [x] Run Task 1–3 tests and existing `test_universe.py`, `test_universe_contract.py`,
  `test_universe_validation.py`, `test_universe_validation_contract.py` plus research artifact
  tests; run Ruff/mypy. Commit the two new files with
  `git commit -m "Verify research bundle provenance and declared coverage"`.

## Task 4: Existing-interface snapshot loader

**Files:** Create `snapshot_loader.py`, `test_snapshot_loader.py`.
**Interfaces:** Consume Task 3 `VerifiedBundle`, Task 1 `SnapshotSettings`, existing
`PointInTimeUniverse`, `HistoricalSlice`, and `ValidatedMarketSnapshot`; produce
`BundleSnapshotLoader` exactly as specified. No strategy, runtime, config or promotion edits.

- [x] Write a successful load with exact values and the insufficient-history denial:

```python
import pytest
from tests.unit.market_data._bundle_fixtures import START, END, ID, LIMITS, fixture_package
from trading_bot.domain import BarInterval
from trading_bot.market_data.bundle_models import BundleError, SnapshotSettings
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.snapshot_loader import BundleSnapshotLoader

@pytest.mark.asyncio
async def test_verified_fixture_loads_completed_ordered_bars():
    bundle = verify_bundle(fixture_package(), limits=LIMITS)
    loader = BundleSnapshotLoader(bundle, settings=SnapshotSettings(BarInterval.ONE_DAY, START, 2))
    first = await loader.load((ID,), END)
    assert first == await loader.load((ID,), END)
    assert first.as_of == END
    assert tuple(h.instrument_id for h in first.histories) == (ID,)
    assert len(first.histories[0].bars) == 2
    assert first.histories[0].spread_percentage is None

@pytest.mark.asyncio
async def test_minimum_history_is_not_padded():
    bundle = verify_bundle(fixture_package(), limits=LIMITS)
    loader = BundleSnapshotLoader(bundle, settings=SnapshotSettings(BarInterval.ONE_DAY, START, 3))
    with pytest.raises(BundleError) as caught:
        await loader.load((ID,), END)
    assert caught.value.code == "snapshot_history_insufficient"
```

- [x] Run `uv run pytest tests/unit/market_data/test_snapshot_loader.py -q`; record the red
  result before loader implementation. Add tests that observe selected bar identities, not
  only total counts, so a future bar substituted for a missing past bar cannot pass.
- [x] Implement query validation, visible coverage union, explicit baseline/event selection,
  conservative action denial, available completed bar selection, ordered existing histories,
  and exact hash preimages. The only application output construction is:

```python
history = HistoricalSlice(instrument_id, selected_bars, None, selected_history_hash)
snapshot = ValidatedMarketSnapshot(as_of, ordered_histories, str(snapshot_hash))
```

  `selected_bars`, `selected_history_hash`, `ordered_histories`, and `snapshot_hash` are
  derived by the frozen query rules, not passed in by the caller. Keep diagnostics at
  `loader.bundle_hash`/`loader.limitation_codes`; no mutable last-query state. Restrict imports
  to application value contracts and public data/domain helpers; no runtime factory imports.
- [x] Add two-instrument order/membership controls; baseline-only inclusion; removal and
  re-inclusion; late announcements/availability; missing baselines; gap/unknown segments;
  adjacent complete windows; future bar ends; delayed bars; interval mismatch; interpolation;
  unknown/adjusted prices; effective split/dividend denial; no-action success; exact boundary
  times. For future-action denial use a separate test so it cannot be confused with the
  future-record invariance control.
- [x] Add a future-source invariance control by appending a **new separate capture** outside
  the selected window with no changed earlier source/coverage. Assert different bundle hash,
  identical earlier snapshot and feature hashes, and changed later snapshot where that source
  becomes relevant. Mutating selected coverage/provenance must instead change identity or deny.
- [x] Run Task 1–4 tests, existing features/property-determinism and recording/replay tests;
  run Ruff/mypy. Commit the two files with
  `git commit -m "Load conservative synthetic snapshots through existing interface"`.
- [x] Resolve, record and push the exact passing Task-4 commit on the existing branch before
  dispatching the two Cloud contracts below. Confirm the remote branch tip is that SHA.
  Do not restart tasks already completed in earlier waves. Primary proceeds with Task 5
  while both independent workers execute; no worker owns loader or verifier production code.

## Task 5: Private content-addressed local artifact I/O

**Files:** Create `bundle_store.py` and `tests/integration/market_data/test_bundle_store.py`.
**Interfaces:** Consume `BundlePackage`, `verify_bundle`, `BundleLimits`; produce
`write_bundle`/`read_bundle`. `read_bundle` returns verified immutable values, never unverified
records. `write_bundle` verifies the whole in-memory package before creating artifacts.

The explicit root must already exist, be owned by the current effective UID, mode exactly
`0700`, and lie outside explicit `repository_root`. Do not create/chmod a caller's root.
Reject symlink components and repository-contained roots before opening any artifact.
Walk path components with directory descriptors and no-follow flags; validate each opened
component is a directory. System ancestors need not be owned by the service UID; exact
private ownership/mode requirements apply to root and its descendants. Require absolute
paths and reject `..` components. Within root create only `blobs/` and `bundles/`, both
`0700` current-owner; filenames
are `<blob_sha256>.raw` and `<bundle_hash>.json`. No arbitrary relative paths are accepted.
Supported platforms are the existing macOS development and Linux runtime; missing required
no-follow, directory-descriptor or atomic no-overwrite capability must fail closed.

- [x] Write the complete private-directory round-trip test:

```python
from pathlib import Path
from tests.unit.market_data._bundle_fixtures import LIMITS, fixture_package
from trading_bot.market_data.bundle_store import read_bundle, write_bundle

def test_private_bundle_round_trip(tmp_path: Path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    repository = Path.cwd().resolve()
    package = fixture_package()
    digest = write_bundle(root, package, repository_root=repository, limits=LIMITS)
    assert write_bundle(root, package, repository_root=repository, limits=LIMITS) == digest
    result = read_bundle(root, digest, repository_root=repository, limits=LIMITS)
    assert result.envelope.bundle_hash == digest
    assert (root / "bundles" / f"{digest}.json").stat().st_mode & 0o777 == 0o600
    assert result.envelope.classification == "synthetic"
```

- [x] Run `uv run pytest tests/integration/market_data/test_bundle_store.py -q` and observe
  failure before implementation. Reuse the existing report test's short-write technique,
  not its fixture that declares accepted research. New bundle I/O must remain separate.
- [x] Implement bounded same-file-descriptor reads with `O_NOFOLLOW`, `O_NONBLOCK` and regular
  file/owner/mode checks on `fstat`; use `O_NONBLOCK` so a FIFO cannot hang before rejection.
  Account cumulative bytes across envelope and distinct blobs, cap each read at its limit
  plus one, then pass only captured bytes to verification. Do not `lstat` and later read the
  same child by an unbound path. Do not retain raw bytes in the returned `VerifiedBundle`.
- [x] Implement publication using a private random-named temporary file inside the opened
  destination directory. Loop short writes, `fchmod(0600)`, `fsync` and verify the temp file;
  publish with a same-directory hard link that fails if the target exists, not overwrite-
  capable rename. Unlink only the exact temporary file created by this invocation. The
  essential publish operation is:

```python
os.link(temp_name, final_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
        follow_symlinks=False)
os.fsync(directory_fd)
```

  Validate final regular-file ownership/mode and exact existing bytes for idempotent reuse;
  different existing content is `bundle_storage_conflict`. Publish/finalize blobs first and
  envelope last. Injected failures before envelope publication must leave no complete bundle
  discoverable by its final name. A directory-fsync error after publication returns
  `bundle_storage_unavailable` (durability uncertain), not a success or destructive rollback;
  the complete artifact may exist, and a later explicit read/retry must reverify it. This is
  distinct from exposing a partially written envelope. No garbage collection is introduced.
- [x] Add tests for nonexistent/inside-repo/wrong-mode roots; symlink ancestor/root/subdir/file;
  invalid digest/traversal; wrong-owner simulated metadata; FIFO/nonregular files; oversized
  envelope/blob/total bytes; exact repeated writes; conflicting existing content; short writes;
  write returning zero; write/fsync/link failure before publication; post-publication durability
  uncertainty; reading a retained verified object after on-disk replacement. Assert failure
  messages contain only registered codes, not temp paths or payload markers.
- [x] Run the new I/O test, Task 1–4 tests, existing report-artifact tests, Ruff/mypy/Bandit.
  Commit only this task's two files with
  `git commit -m "Persist research bundles with private atomic local I/O"`.

## Task 6: Non-promotable integration, compatibility, and central verification

**Files:** Create `tests/integration/simulation/test_bundle_decision_cycle.py`; modify only
the four documentation paths in the file map, and integrate reviewed Cloud-owned tests/docs.
**Interfaces:** Consume the real loader, real `FeaturePipeline`, and existing
`DecisionCycleService`; no production interface changes. Primary owns integration.

- [x] Add a legacy identity test with these exact pre-change values, captured from the
  existing complete synthetic report fixture at planning base `0fd34b2`:

```python
from tests.unit.research.test_validation import report
from trading_bot.market_data.recording import content_hash
from trading_bot.research.report import render_json

def test_existing_report_identity_is_unchanged():
    value = report()  # construction only; never run acceptance or persist this fixture
    assert value.report_hash == "2a63011d5965cdd6826116f3ca2ee1532d2c98058c480b3c45256d0dd3d54781"
    assert value.run.data_manifest.manifest_hash == "08ecc519c3085798817cf57cb60f0bd7e1c1df8bdbcade4ae512d5d3cd5c451d"
    assert content_hash(render_json(value)) == "6e71bb1d6d1fb30977851d5f78cbae488767e44c09f26620069075598ef3d6ba"
```

  These are value-hash compatibility controls, not proof of a legacy deserializer (none is
  introduced). Also assert an old manifest alone is rejected by the new envelope decoder.
- [x] Build a test-only feature adapter and incapable execution stage:

```python
from trading_bot.app import ValidatedMarketSnapshot
from trading_bot.strategies import FeatureSnapshot
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.market_data.recording import content_hash

class BundleFeatures:
    def __init__(self):
        self.pipeline = FeaturePipeline(short_window=2, long_window=3)

    def compute(self, market: ValidatedMarketSnapshot, *, as_of):
        vectors = tuple(self.pipeline.compute(history, as_of=as_of)
                        for history in market.histories)
        return FeatureSnapshot(as_of, vectors, content_hash({"as_of": as_of, "vectors": vectors}))

class NoExecution:
    async def execute(self, intent):
        raise AssertionError("synthetic data integration must not create an execution intent")
```

  Use `dataclasses.replace` on the existing synthetic `request()` helper to set `universe=(ID,)`
  and `as_of=END`, updating the synthetic portfolio timestamp as well. The existing test's
  `Planner` intentionally emits an order, so **do not reuse it**. Define a test planner whose
  `plan` returns `()`, a portfolio stub constructing a zero-weight `TargetPortfolio` with the
  passed `as_of`/config hash, no strategies (`strategies=()`), and an in-memory journal that
  captures the payload and returns a fixed synthetic audit ID. No real broker or database is
  instantiated. This proves data reaches the existing cycle, not profitable strategy behavior.
- [x] Write an async integration test constructing `DecisionCycleService` with the real
  verified fixture loader, adapter and incapable test stages. Assert one history, the exact
  two selected closes, `spread_pct is None`, no decisions/intents/outcomes, fixed audit ID,
  captured `market_hash == result.market.data_hash`, and stable result hash across repeated
  identical runs. A tampered package must fail before cycle construction. A query-denied
  package must fail before feature/journal calls; use call counters to prove that ordering.

```python
from dataclasses import replace
from decimal import Decimal
import pytest
from tests.integration.simulation.test_decision_cycle import request
from tests.unit.market_data._bundle_fixtures import START, END, ID, LIMITS, fixture_package
from trading_bot.app import DecisionCycleService
from trading_bot.domain import BarInterval, DataHash
from trading_bot.market_data.bundle_models import SnapshotSettings
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.snapshot_loader import BundleSnapshotLoader
from trading_bot.portfolio import TargetPortfolio

class NoPlanner:
    def plan(self, target, context):
        return ()

class EmptyPortfolio:
    def construct(self, decisions, snapshot, *, as_of, config_hash, exposure_multiplier, exit_policy):
        assert decisions == ()
        return TargetPortfolio(as_of, (), snapshot.cash, config_hash, DataHash("d" * 64))

class MemoryJournal:
    def __init__(self):
        self.payloads = []

    async def finalize(self, payload):
        self.payloads.append(payload)
        return ("synthetic-bundle-cycle",)

@pytest.mark.asyncio
async def test_real_loader_and_features_feed_existing_cycle_without_execution():
    original = request()
    portfolio = replace(original.portfolio, observed_at=END)
    cycle_request = replace(original, universe=(ID,), as_of=END, portfolio=portfolio,
                            intent_context=replace(original.intent_context, portfolio=portfolio))
    loader = BundleSnapshotLoader(verify_bundle(fixture_package(), limits=LIMITS),
                                 settings=SnapshotSettings(BarInterval.ONE_DAY, START, 2))
    journal = MemoryJournal()
    service = DecisionCycleService(snapshot_loader=loader, features=BundleFeatures(),
                                   strategies=(), portfolio=EmptyPortfolio(),
                                   intent_planner=NoPlanner(), execution=NoExecution(), journal=journal)
    result = await service.run_cycle(cycle_request)
    again = await service.run_cycle(cycle_request)
    assert tuple(bar.close for bar in result.market.histories[0].bars) == (Decimal("10"),) * 2
    assert dict(result.features.vectors[0].values)["spread_pct"] is None
    assert result.decisions == result.intents == result.order_outcomes == ()
    assert result.audit_event_ids == ("synthetic-bundle-cycle",)
    assert journal.payloads[0]["market_hash"] == result.market.data_hash
    assert result.result_hash == again.result_hash
```

  The `portfolio` field used here is verified in existing `portfolio/intents.py`; the example
  does not modify that dataclass. Keep test stages local to this new integration file.
- [x] Run the new integration file first. Existing green compatibility assertions are
  expected; new integration must fail if the real loader is replaced with an empty snapshot
  or the feature adapter is not called. Restore deliberate fault injection before committing.
- [x] Integrate each Cloud diff only after verifying the exact base, path ownership, full
  content and synthetic-only fixtures. Resolve mismatched expected behavior against this
  plan; workers cannot decide new semantics. Run each returned file independently and both
  together; no skipped tests, blanket xfails, or changes to primary/shared fixtures.
- [x] Run this focused selection with the unchanged default non-authenticated marker filter:

```shell
uv run pytest tests/unit/market_data tests/integration/market_data/test_bundle_store.py tests/integration/market_data/test_recording_replay.py tests/unit/research tests/unit/strategies tests/property/strategies/test_feature_determinism.py tests/integration/simulation/test_bundle_decision_cycle.py tests/integration/simulation/test_decision_cycle.py tests/integration/runtime/test_paper.py tests/integration/runtime/test_promotion_wiring.py tests/integration/runtime/test_no_live_writes.py -q
```

- [x] Update architecture/research/limitations/handoff docs with implemented module paths,
  synthetic-only classification, no-action/unadjusted loader limit, new private storage
  contract, exact observed tests, Cloud task IDs/dispositions, and remaining live blockers.
  Do not remove static research blockers, amend operational observations to look current,
  claim accepted data, or describe a running paper/live application.
- [x] Run the complete baseline and existing CI-equivalent checks, without altering thresholds:

```shell
uv run ruff check .
uv run mypy src
uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80
uv run bandit -c pyproject.toml -r src
uv lock --check
```

  Run the existing CI recipes below from a secrets-free archive/isolated environment so
  their generated requirements file does not pollute the user worktree:

```shell
uv export --locked --all-groups --no-emit-project --output-file locked-requirements.txt > /dev/null
uv run pip-audit --requirement locked-requirements.txt --no-deps --disable-pip
for script in infra/digitalocean/*.sh; do
    sh -n "$script"
done
docker compose config --quiet
```

  If the local Docker Compose plugin is absent, the previously verified standalone
  `docker-compose config --quiet` is the local equivalent; report the difference and rely
  on exact-commit CI for its native command. Do not silently omit an unavailable tool or
  network-dependent audit. On this workstation the verified clean environment is
  `/private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/`; check it still exists and matches
  the lock before use. When using it, set `PYTHONPATH=src` from the intended worktree/archive
  because its editable installation points elsewhere. Use a clean staged-tree archive for
  the full suite if Documents filesystem delays recur; bind results to its exact tree hash.
- [x] Stage only intended source/tests/docs, review `git diff --cached --check` and the full
  diff, commit, then push the existing branch and observe exact-commit CI. Do not merge,
  deploy, read an account, or enable live mode. Finish with actual test counts, identities,
  remaining blockers, and the next primary-owned dependency (real-source contract review),
  not a claim that this milestone completes live readiness.

## Actual Codex Cloud contracts

The operator already requested actual parallel Codex Cloud work. These are prepared task
contracts, not completed or dispatched tasks. Use the installed Codex Cloud CLI, not local
subagents relabeled as Cloud. Environment identity previously observed:
`6a59814f60d881918365cedc8b3ed261` for `Jed1122/Robinhoodtradingbot`; verify availability at
dispatch without opening credentials. Do not create duplicate app tasks for these workers.

Both start from the same exact pushed Task-4 SHA, resolved at execution and written verbatim
into their prompts and review documents. Read-only dependencies: repository `AGENTS.md`,
`Codex.md`, approved spec, this plan, the five new production modules completed by Task 4
(the store module is not required at dispatch), existing public domain/recording/universe/application
interfaces, `_bundle_fixtures.py`, `pyproject.toml`, and `uv.lock`. They must not inspect
private local data, another task's output, production ledgers or credentials.

Common prohibitions: production edits, shared fixtures, configs, risk/pricing/exposure,
provider/broker code or calls, promotion/persistence/reconciliation/runtime changes,
deployment, external data acquisition, network requests from tests, Git pushes or PR
changes, and touching any paths outside the worker's two owned files. Use isolated Cloud
checkouts. If checkout HEAD differs, detach exact base only on a clean checkout; otherwise
return `NOT_READY`. Do not rebase or alter the primary branch.

### DATA-BUNDLE-TESTS-004

- **Owner/objective:** one Cloud worker; independently challenge v1 package integrity with
  synthetic tests, including positive controls and targeted mutation cases.
- **Owned paths:** `tests/unit/market_data/test_bundle_contract.py` and
  `docs/reviews/data-bundle-tests-004.md` only.
- **Frozen interfaces:** models, codec, assembler, verifier, complete wire/hash contract,
  and registered error codes above. Private implementation helpers are not test contracts.
- **Acceptance:** deterministic valid package; exact-byte hash distinction; outer-only rehash
  cannot conceal raw/normalized/manifest mismatch; raw locator/source scope binding; strict
  malformed input/depth/size rejection; synthetic origin cannot be relabeled; derived unknown
  coverage limitations remain. Use inline worker-owned fixture/mutation helpers and inspect
  actual selected values, not only the presence of a hash.
- **Verification:** `uv run pytest tests/unit/market_data/test_bundle_contract.py -q`, then
  `uv run ruff check tests/unit/market_data/test_bundle_contract.py`; run the existing primary
  bundle models/codec/normalize/verify files to distinguish baseline failures from new tests.
- **Return:** review document with exact base, file diff, commands/results, case count,
  assumptions, identified production defects if any, and `READY_FOR_INTEGRATION` for a
  scoped reviewed test proposal or `NOT_READY` if contract/base is unresolved. A valid test
  revealing a production defect must report red status precisely; the primary fixes it.

### SNAPSHOT-DATA-TESTS-004

- **Owner/objective:** a different Cloud worker; test offline snapshot selection against
  frozen as-of, coverage and membership rules without choosing a trading strategy.
- **Owned paths:** `tests/unit/market_data/test_snapshot_data_contract.py` and
  `docs/reviews/snapshot-data-tests-004.md` only.
- **Frozen interfaces:** verified bundle, settings, loader async signature/properties,
  existing snapshot/history shapes, reason codes and hash preimages above.
- **Acceptance:** two-instrument ordering; baseline/event visibility; explicit exclusion
  denial; missing/late/insufficient bars; gap/unknown coverage; no-action valid control;
  interpolation/price-basis/action denials; disjoint future-source identity invariance and a
  selected-source change control. No source/promotion trust inference and no broker fixtures.
- **Verification:** `uv run pytest tests/unit/market_data/test_snapshot_data_contract.py -q`,
  then `uv run ruff check tests/unit/market_data/test_snapshot_data_contract.py`; run the
  primary loader test file to separate baseline problems from independent findings.
- **Return:** the same exact-base/diff/results/assumptions/defects/disposition contract,
  recorded only in this worker's owned review document.

Primary checks status without repeated unchanged polling, reads complete returned diffs,
and integrates via `apply_patch`. A Cloud task being marked ready does not certify CI or
release safety. Only central checks and observed exact-commit CI close implementation work.

## Plan self-review and execution handoff

Primary coverage map (planning checks only; not implementation completion):

| Spec requirement | Implementation task |
|---|---|
| Existing constructors/hashes and dependency direction | 1, 2, 6 |
| Raw preimages, normalization replay, fixture classification | 2, 3 |
| Membership baseline, coverage slots, UTC visibility | 3, 4 |
| No interpolation/adjustment policy and no fabricated spread | 4 |
| Bounded strict parsing, safe errors, private atomic I/O | 1, 3, 5 |
| Existing-interface snapshots and future-source identity | 4, 6 |
| Non-promotable integration and unchanged runtime denials | 6 |
| Disjoint actual Cloud tests and primary-owned integration | Task 4 dispatch, contracts, Task 6 |

After writing, the primary checks the complete plan against the approved spec, confirms all
types/signatures/path references agree, checks example fixture wire shapes, scans for vague
steps, and fixes inconsistencies before committing this documentation. Do not ask a worker
to substitute for this self-review. The read-only fixture inventory is supporting evidence
only, not a spec/plan approval.

Execution choice after this planning handoff: primary inline execution with the two actual
Cloud test workers (recommended, consistent with the operator's parallel-work preference),
or entirely local inline execution if the operator no longer wants Cloud tasks. Generic
fresh-subagent-per-production-task execution is not appropriate for this repository's
primary-owned integration boundary. Begin execution only after that handoff is accepted.

## Execution completion — 2026-09-17 UTC

The operator approved primary-led execution with actual parallel Cloud test workers.
All six tasks are complete at implementation commit `14c29e26b760d6fb59a4514ae3f5b50f9e921d1d`.
Tasks 1-5 were separately committed as `e090b2f`, `59d3e73`, `d425152`, `5178406`, and `313f54e`.
Both Cloud workers used exact base `5178406cdd65fc4f03f37fdafd8d857116d58075`; their two-file
proposals were reviewed in full and applied centrally, yielding 42 additional passing cases.
The final local baseline passed 4,073 tests with 86.38% coverage with branch measurement;
the focused integration selection passed 463 tests. Ruff, mypy (171 source files), Bandit,
lock validation, exact locked-dependency audit, shell syntax, and standalone Compose checks
passed. Exact-commit PR CI `35264185795` and push CI `35264174224` passed all six jobs each.
Detailed results and remaining live blockers are recorded in the transition report.
No broker, credential, ledger, deployment, live-mode, or risk/configuration changes were made.
Real-source contract review remains the next primary-owned dependency, not part of this wave.
