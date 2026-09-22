# Durable Offline Options Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently reconstructed, synthetic-only options ledger that preserves cash, obligations, trial losses and unresolved incidents across restart and supplies the existing paused reconciliation/expiry monitor.

**Architecture:** Immutable local economic facts and separately retained comparison evidence share a bounded SQLite journal, but never share authority to create ownership. A pure reducer supplies exact accounting, existing trial/loss evaluators supply their existing necessary gates, and one fenced transaction commits local and legacy-journal effects together. The separate offline CLI can rehearse, inspect and explicitly continue synthetic input; it cannot construct a broker transport or enable production entries.

**Tech Stack:** Existing Python `>=3.12,<3.15`, frozen dataclasses, Decimal, SQLAlchemy/aiosqlite, SQLite, Alembic, pytest, Ruff and Mypy. No added dependency or external service.

**Spec:** [Approved durable ledger design](../specs/2026-09-22-durable-offline-options-ledger-design.md), implementing the relevant parts of [options-only build specification](../../options-only-build-spec.md) and [migration plan](2026-09-18-options-only-migration.md).

## Global Constraints

- Native implementation is already selected: the coordinator implements the tasks, then one fresh independent reviewer reviews the complete diff. This plan is awaiting operator review; it is not implemented software.
- Planning base: `15297264838962ffcefebb70f6b0b33a6ff4582b`, branch `codex/continue-implementation-from-commit-7c4dcd1`, worktree `/Users/jedweinstein/Documents/robinhood-multi-asset-trading-system/worktrees/robinhood-system-implementation`. Record the actual approved-plan commit before execution and verify it contains this base.
- Preserve unrelated dirty work, including the main CLI, README, architecture/research documents, equity replay files and tracked SBOM. Do not stage by directory or use `git add .`. Do not edit the unrelated Polymarket repository.
- Only private temporary synthetic databases may be migrated or restored. No broker calls, credential access, production-ledger access, data acquisition, spending, Cloud dispatch, deployment, activation, exercise instructions or stock remediation.
- All public results keep `source_kind=synthetic`, `production_eligible=false`, `evidence_promotable=false`, `live_authorized=false`, and `paused=true` as non-constructor-controlled fields/properties.
- Preserve the $100 capital assumption, $150 live-equity ceiling, 0.5% per-trade limit, $50 outer per-trade ceiling and non-replenishing $50 cumulative trial-loss ceiling. Other applicable stricter controls remain unchanged.
- Single-leg standard-deliverable long calls/puts only; one complete structure unit per entry, one open strategy position, one new position per session. Abnormal multi-unit/partial/short observations are retained as incidents, not admitted positions.
- A necessary synthetic capital filter is not complete pretrade authorization. Scripted reviews and acknowledgements are synthetic events, not broker review or verified account permissions.
- Event payload bytes: `min(16_384, loaded.config.options.replay_max_bytes)`. Evidence/scenario and aggregate recovery bytes: `replay_max_bytes` (currently 4,194,304). Aggregate nested row count: `replay_max_records` (currently 5,000). Depth: `replay_max_json_depth` (currently 16). No input may increase these limits.
- Exact Decimal strings at most 512 characters; exact bounded SQLite integers, excluding bool; UTC timestamps. Monetary arithmetic uses a fixed 2,048-digit local context, traps inexact/rounded/nonfinite results, then revalidates outputs. No float conversion or implicit quantization.
- Preserve existing v1 replay, trial and risk encodings/hashes and public journal behavior. Additive schema follows `0007_options_risk_history`; never reinterpret existing account history under a new config.
- Retain 80% overall coverage and 90% per-file branch coverage for every new ledger domain, codec, reducer, projection, risk-binding, transaction, persistence, recovery and operator path. Authenticated tests remain excluded.

## Review Focus

1. The same fill delivered with two event IDs must not double charge premium/fees or create two settlement obligations; task 2 tests economic identity independently of delivery identity.
2. A fee or conflicting fill arriving after finality must be retained as an unresolved incident without silently rewriting consumed trial losses; tasks 2 and 5 test restart and halt behavior.
3. Database lock wait or commit uncertainty must not let an expired writer append or let a caller generate a replacement economic event; task 5 tests post-wait checks and original-receipt lookup.
4. A zero liquidation bid is data, but missing/stale marks or lost observation preimages must not become fabricated zero-valued clean snapshots; tasks 3 and 6 test distinct results.
5. Inspecting an active-WAL database through a symlink, case alias or repository descendant must neither mutate the source nor copy an inconsistent prefix; tasks 7 and 8 test source identity and consistent backup.

---

## 1. Starting state, dependency chain and ownership

The old replay/journals/paused monitor are implemented reuse points. Independent durable local ownership, a common accounting transaction and its offline operator composition are **partial/missing**, not proven production lifecycle support. Genuine historical normalization/economic evidence, full pretrade, broker/runtime capability verification and live authorization are **separate blocked or unverified milestones**. This plan does not mark any of them complete.

Critical path: records/codec -> exact reducer -> valuation/risk binding -> atomic schema/journal helpers -> durable vertical slice -> retained-source monitor -> private CLI -> failure/restore/release evidence. Each numbered task has a meaningful independent test cycle; task 5 is the first complete durable entry/close/settlement/restart slice.

The coordinator owns every accounting, risk, transition, schema, lease, reconciliation, recovery and integration decision. After interfaces below are frozen, isolated agents may inventory fixtures, add non-risk-sensitive parser fixtures or independently review a committed diff with exact base and file ownership. Do not delegate implementation of the protected components, do not describe local agents as Cloud execution, and do not let an agent edit this integration worktree.

Before coding, read `AGENTS.md`, `Codex.md`, the approved spec, the current versions of the reused modules and relevant repository operations/risk/incident/disaster-recovery documents. Snapshot `git status --short`, the staged diff and the tracked SBOM digest. If a planned path develops unrelated edits, stop only that overlapping change and resolve ownership; do not overwrite it.

### File map

All paths below are repository-relative; only these product files are owned by this milestone.

| Path | Responsibility / task |
| --- | --- |
| `src/trading_bot/domain/options_ledger.py` | Immutable scope, typed commands/events, independent evidence and result contracts; 1 |
| `src/trading_bot/simulation/options_ledger_codec.py` | Closed canonical v1 wire schema and shared bounds; 1 |
| `src/trading_bot/simulation/options_ledger_book.py` | Pure cash/ownership/order/episode reducer; 2 |
| `src/trading_bot/simulation/options_ledger_projection.py` | Explicit synthetic cash semantics, valuations, normalized local snapshot; 3 |
| `src/trading_bot/risk/options_ledger.py` | Bind ledger/risk points and entry necessities using canonical evaluators; 3 |
| `src/trading_bot/risk/options_economics.py` | Backward-compatible stricter risk-equity reference, no new policy; 3 |
| `src/trading_bot/persistence/options_ledger_models.py` | New exact-column ORM rows; 4 |
| `src/trading_bot/persistence/models.py` | Register new model metadata without changing old columns; 4 |
| `migrations/versions/0008_options_offline_ledger.py` | Additive tables, composite references and immutable guards; 4 |
| `src/trading_bot/persistence/options_journal_transaction.py` | Private validated fenced transaction shared by new writer and legacy helpers; 4 |
| `src/trading_bot/persistence/options_trial.py` | Private in-transaction helper; preserve public API, payload/hash; 4 |
| `src/trading_bot/persistence/options_risk.py` | Private in-transaction helper; preserve public API, payload/hash; 4 |
| `src/trading_bot/persistence/options_ledger.py` | Atomic append, retained evidence and receipt lookup; 5 |
| `src/trading_bot/persistence/options_ledger_recovery.py` | Bounded chain/effects/journal reconstruction; 5 |
| `src/trading_bot/runtime/options_ledger_monitor.py` | Independently reconstructed source, run/result linkage and paused monitor composition; 6 |
| `src/trading_bot/persistence/reconciliation.py` | Transaction-internal result append used by new run-link store; preserve legacy public persist; 6 |
| `src/trading_bot/simulation/options_ledger_scenarios.py` | Explicit synthetic scenario assembly, not historical evidence; 7 |
| `src/trading_bot/simulation/options_ledger_io.py` | Private roots, safe input/read-only snapshot and atomic report publication; 7 |
| `src/trading_bot/cli/options_ledger.py` | Separate offline module entry point; 7 |
| `scripts/check_critical_branch_coverage.py` | Include all new safety-critical ledger modules; 1–8 |
| `docs/options-ledger-rehearsal.md` | Usage, fixture semantics, limitations and operator failure meanings; 7–8 |
| `docs/options-ledger-validation.md` | Actual verification record, not anticipated results; 8 |

Test files are listed in their owning tasks. Do not alter `runtime/options_recorded_session.py`, `runtime/options_monitor.py`, the order transition table or comparator semantics to make new tests pass. A discovered need to alter those contracts requires an explicit design adjustment first.

## 2. Frozen record and API contract

The names in this section are new interfaces to implement, not current repository APIs. `AccountId`, `OptionsOrderIntent`, `OptionContract`, `OrderEvent`, `OrderState`, `OptionsAccountSnapshot`, `OwnedOptionPosition`, `OptionsLossPoint`, `TrialEpisode`, `TrialLossState`, `LoadedConfig`, `ExecutionLease`, `Clock` and `OptionExpiryCalendar` are reused existing types. Use exact-type validation at trust boundaries, not annotations alone.

### Domain records

Every new record is `@dataclass(frozen=True, slots=True)`. Identity strings are nonempty ASCII allowlisted tokens up to 128 characters, hashes are lowercase SHA-256, and timestamps use `require_utc`. Enum tags below are closed string literals. No arbitrary dictionaries survive decoding.

```python
@dataclass(frozen=True, slots=True)
class OptionsLedgerScope:
    ledger_id: str
    account_id: AccountId              # reserved prefix synthetic:ledger:
    config_hash: str
    genesis_cash: Decimal
    history_start: datetime            # explicit first eligible session open
    schema: Literal["options-ledger-v1"] = field(default="options-ledger-v1", init=False)
    currency: Literal["USD"] = field(default="USD", init=False)

@dataclass(frozen=True, slots=True)
class LedgerCommand:
    event_id: str
    occurred_at: datetime
    payload: LedgerPayload
    evidence_hashes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class OptionsLedgerEvent:
    scope: OptionsLedgerScope
    command: LedgerCommand
    sequence: int
    previous_hash: str
    event_hash: str
    fencing_token: int
    producer_code_hash: str
    recorded_at: datetime
```

`LedgerPayload` is the union of these exact dataclasses, with an `init=False` `kind` literal matching the left column. The listed fields are complete constructor fields, not examples:

| Kind / class | Fields | Semantic rule |
| --- | --- | --- |
| `genesis` / `Genesis` | none | First event only; flat cash comes from scope, no imported holdings |
| `intent` / `IntentRecorded` | `episode_id: str, intent: OptionsOrderIntent, entry_fee_bound: Decimal, exit_fee_bound: Decimal, session_id: str` | Opening starts one reservation; closing binds existing episode and exact held contract; bounds cannot increase config limits |
| `order_event` / `OrderTransitioned` | `order_id: str, event: OrderEvent` | Existing `transition()` only; risk/review events explicitly synthetic |
| `fill` / `FillRecorded` | `fill: ObservedOptionFill, fee_id: str, settlement_id: str, due_at: datetime` | Full immutable fill identity; fee is already `fill.fee`; derive obligation amount, never accept caller net cash |
| `fee` / `FeeAllocated` | `order_id: str, fee_id: str, amount: Decimal, settlement_id: str, due_at: datetime` | Additional positive fee with its own payable; never repeat an embedded fill fee |
| `fees_final` / `FeesFinalized` | `order_id: str, total_fee: Decimal, allocation_ids: tuple[str, ...]` | Exact set/sum of booked allocations; empty plus zero is explicit zero finality |
| `outcome_final` / `OutcomeConfirmed` | `order_id: str` | Attributed synthetic final-outcome evidence only; order already terminal, all fills consistent |
| `settled` / `SettlementCompleted` | `settlement_id: str` | Existing obligation, full one-time settlement; amount is derived |
| `external_flow` / `ExternalFlowRecorded` | `flow_id: str, amount: Decimal` | Nonzero signed settled cash flow; not episode P&L or increased authorized risk equity |
| `evidence` / `EvidenceRetained` | `evidence_hash: str` | Preimage must be in append request or already retained under this scope |
| `valuation` / `ValuationRecorded` | `valuation_hash: str` | Derive loss point from post-event book and separate retained valuation/session input |
| `incident` / `IncidentRecorded` | `incident_id: str, reason: LedgerIncidentCode, episode_id: str \| None, evidence_hash: str` | Unresolved, append-only; no clear/repair event |

`LedgerIncidentCode` values are `unmatched_execution`, `conflicting_execution`, `unsupported_partial`, `late_economic_fact`, `fee_bound_exceeded`, `unknown_liability`, `unexpected_shares`, `assignment`, `exercise`, `expiration_unreconciled`, `broker_closeout`, `negative_cash`, `collateral_unverified`, `expiry_deadline_missed`, `comparison_mismatch`, `history_incomplete`. Malformed input is a sanitized validation failure; validly normalized but unsupported economic evidence is durably retained as an incident. Do not acknowledge an unsupported fact until its retention transaction commits.

Three retained evidence records share `account_id: AccountId`, `config_hash: str`, `evidence_hash: str`, `observed_at: datetime`, `history_start: datetime`, `history_end: datetime`, `provenance: tuple[SyntheticProvenance, ...]` and `source_kind="synthetic"` (`init=False`). `SyntheticProvenance(fixture_name: str, fixture_version: str)` is a closed immutable record containing only allowlisted fixture identity strings; its canonical content hash identifies invented inputs, not authentic market data:

- `RetainedOptionsObservation`: `snapshot: OptionsAccountSnapshot`, `calendars: tuple[OptionExpiryCalendar, ...]`. Neither changes local ownership or booked cash.
- `RetainedOptionsValuation`: `marks: tuple[LedgerMark, ...]`, `session: LedgerSession`, `complete: bool`. `LedgerMark(contract_id: str, kind: Literal["broker_comparison", "liquidation_bid"], price: Decimal, observed_at: datetime, source_hash: str)` accepts nonnegative price, distinguishes absent mark from zero. `LedgerSession(session_id: str, opens_at: datetime, closes_at: datetime, previous_session_close: datetime | None)` is explicit; only the first known session may omit its predecessor, and no weekday generator is used.
- `RetainedExecutionEvidence`: `orders: tuple[ObservedOptionOrder, ...]`, `fills: tuple[ObservedOptionFill, ...]`, `settlements: tuple[ObservedOptionSettlement, ...]`, `lifecycle: tuple[ObservedOptionLifecycle, ...]`, `shares: tuple[ObservedSharePosition, ...]`. It supplies event-level attribution or anomalies, never aggregate balance authority.

`RetainedEvidence` is their union. Hashes cover a versioned canonical envelope excluding only its own hash; every referenced source hash must resolve to retained content or a `SyntheticProvenance` record inside that content. Reject unbound source hashes. This slice has only the synthetic source label, account/config and original timestamps; it does not invent authenticated provider identity or freshness.

`LedgerAppend(command: LedgerCommand, retained: tuple[RetainedEvidence, ...])` is the sole append request. Evidence not referenced by the command is rejected. Record validators check hash syntax; canonical decoders and every ingress operation additionally verify content hashes. `LedgerState` and its child book records below are reducer outputs, not accepted as authoritative input by the durable writer. Their serialization is not a replacement journal. All tuple members are exact typed immutable records.

| Reducer record | Frozen fields / properties |
| --- | --- |
| `LedgerIdentity` | `kind: Literal["event", "fill", "fee", "settlement", "flow"], identity: str, payload_hash: str` |
| `LedgerOrderBook` | `intent: OptionsOrderIntent, episode_id: str, state: OrderState, fills: tuple[ObservedOptionFill, ...], fees_final: bool, outcome_final: bool`; local `order_id` is exactly `intent.intent_id`, never inferred from a comparison snapshot |
| `LedgerHolding` | `episode_id: str, contract: OptionContract, quantity: int, premium_basis: Decimal` |
| `LedgerObligation` | `settlement_id: str, order_id: str, episode_id: str, amount: Decimal, due_at: datetime, completed_at: datetime | None`; signed amount positive receivable, negative payable |
| `LedgerFee` | `fee_id: str, order_id: str, amount: Decimal, settlement_id: str, embedded_in_fill_id: str | None` |
| `LedgerEpisodeBook` | `episode_id: str, order_ids: tuple[str, ...], reserved_risk: Decimal, entry_fee_bound: Decimal, exit_fee_bound: Decimal, cash_commitment: Decimal, session_id: str` |
| `LedgerFlow` | `flow_id: str, amount: Decimal, occurred_at: datetime` |
| `LedgerIncident` | `incident_id: str, reason: LedgerIncidentCode, episode_id: str | None, evidence_hash: str, occurred_at: datetime` |
| `LedgerState` | `scope: OptionsLedgerScope, initialized: bool, identities: tuple[LedgerIdentity, ...], orders: tuple[LedgerOrderBook, ...], holdings: tuple[LedgerHolding, ...], obligations: tuple[LedgerObligation, ...], fee_allocations: tuple[LedgerFee, ...], episodes: tuple[LedgerEpisodeBook, ...], flows: tuple[LedgerFlow, ...], incidents: tuple[LedgerIncident, ...], retained: tuple[RetainedEvidence, ...], last_occurred_at: datetime | None, settled_cash: Decimal, trial: TrialLossState` |

`LedgerState.receivables`, `.payables` and `.cash_commitment` are exact nonnegative sum properties over unfinished obligations/episode commitments. `.entry_halted` is true when unresolved incidents exist; risk/freshness/admission remains a separate stricter decision. Session activity is counted from opening episode records, including pending/rejected attempts conservatively; this slice never clears an attempt by changing the date or retrying an intent. Keep original attributed fee/obligation facts even after completion. No mutable cache is a second source of truth.

```python
@dataclass(frozen=True, slots=True)
class OptionsLedgerProjection:
    settled_cash: Decimal
    receivables: Decimal
    payables: Decimal
    cash_commitment: Decimal
    trial: TrialLossState
    snapshot: OptionsAccountSnapshot | None
    owned_positions: tuple[OwnedOptionPosition, ...]
    liquidation_equity: Decimal | None
    reasons: tuple[str, ...]
    source_kind: Literal["synthetic"] = field(default="synthetic", init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    paused: Literal[True] = field(default=True, init=False)
```

`LedgerReceipt(event_id: str, head_hash: str, sequence: int)` contains durable identity, not authorization. `LedgerRecovery(scope: OptionsLedgerScope, head_hash: str, state: LedgerState, projection: OptionsLedgerProjection, trial_head: str, risk_head: str, pending_monitor_runs: tuple[str, ...])` reports paused recovery. `LedgerAdmission(admissible_units: int, reasons: tuple[str, ...], ledger_head: str, valuation_hash: str, risk_head: str)` is synthetic necessity evidence and carries the same immutable false eligibility fields. It is not exported as a live permit.

### Pure and persistence interfaces

- `ledger_limits(loaded: LoadedConfig) -> LedgerLimits`: canonical event/total bytes, total rows, depth. `RecoveryBudget(limits: LedgerLimits)` has `consume(*, byte_count: int, row_count: int) -> None`; it never resets during one recovery, including nested evidence/effects/legacy journals.
- `encode_ledger_append(value: LedgerAppend, loaded: LoadedConfig) -> bytes`; `decode_ledger_append(body: bytes, loaded: LoadedConfig) -> LedgerAppend`; `encode_ledger_event(value: OptionsLedgerEvent, loaded: LoadedConfig) -> bytes`; `decode_ledger_event(body: bytes, loaded: LoadedConfig) -> OptionsLedgerEvent`; `ledger_evidence_hash(value: RetainedEvidence) -> str`. Strict version/keys, canonical bytes and hash checks. Hash helpers use explicit field maps, never serialize an arbitrary Python object.
- `initial_book(scope: OptionsLedgerScope) -> LedgerState`; `reduce_ledger(state: LedgerState, request: LedgerAppend, loaded: LoadedConfig) -> LedgerState`; `project_ledger(state: LedgerState, valuation: RetainedOptionsValuation | None, *, as_of: datetime, loaded: LoadedConfig) -> OptionsLedgerProjection`.
- `derive_loss_point(state: LedgerState, valuation: RetainedOptionsValuation, *, ledger_head: str, loaded: LoadedConfig) -> OptionsLossPoint`; `evaluate_ledger_entry(state: LedgerState, intent: OptionsOrderIntent, *, valuation: RetainedOptionsValuation, points: tuple[OptionsLossPoint, ...], ledger_head: str, risk_head: str, as_of: datetime, loaded: LoadedConfig) -> LedgerAdmission`.
- `OptionsLedgerJournal(factory, clock: Clock, loaded: LoadedConfig, *, producer_code_hash: str)` uses only a branded validated factory. `initialize(lease: ExecutionLease, scope: OptionsLedgerScope, request: LedgerAppend) -> LedgerReceipt`; `append(lease: ExecutionLease, scope: OptionsLedgerScope, request: LedgerAppend, *, expected_head: str) -> LedgerReceipt`; `recover(scope: OptionsLedgerScope) -> LedgerRecovery`; `lookup_receipt(scope: OptionsLedgerScope, event_id: str) -> LedgerReceipt | None`. All four methods are async. `initialize` accepts only a Genesis request and an empty dedicated ledger/account; `append` never initializes implicitly.
- `recover_ledger(session: AsyncSession, scope: OptionsLedgerScope, loaded: LoadedConfig, *, as_of: datetime, budget: RecoveryBudget) -> LedgerRecovery` is async, read-only within the supplied transaction and does not migrate.

All implementation signatures include the type of `factory` as `async_sessionmaker[AsyncSession]`; its shortened spelling above avoids duplicating a long generic, not relaxed runtime validation.

## Task 1: Closed versioned records, canonical bounds and compatibility fixtures

**Files:** Create the domain/codec paths in the file map, `tests/unit/domain/test_options_ledger.py`, `tests/unit/simulation/test_options_ledger_codec.py`; modify `scripts/check_critical_branch_coverage.py` and `tests/smoke/test_critical_branch_coverage.py`.

**Interfaces:** Consumes canonical config/domain/Decimal/wire validators. Produces all records and codec/budget signatures in section 2, with no database or broker import.

- [ ] Capture old v1 trial/risk/replay literal encodings and digests from small existing deterministic fixtures into new test assertions. Do not regenerate expected values during test execution. Preserve those assertions through tasks 4–8.
- [ ] Add a minimal canonical roundtrip and a strict unknown-key test using the existing `tests.unit.risk.test_options_economics.config` fixture factory:

```python
def test_genesis_roundtrip_and_closed_keys():
    loaded = config()
    item = LedgerAppend(LedgerCommand("genesis-1", OPEN, Genesis(), ()), ())
    body = encode_ledger_append(item, loaded)
    assert decode_ledger_append(body, loaded) == item
    malformed = body[:-1] + b',"live_authorized":true}'
    with pytest.raises(DomainValidationError):
        decode_ledger_append(malformed, loaded)
```

Import `OPEN` from `tests.unit.risk.test_options_loss_history`; use actual `json.loads` only in tests to construct malformed variants. Parameterize duplicate JSON keys, unknown schema/tag, bool quantity, float/nonfinite Decimal, 513-character Decimal, non-UTC datetime, invalid hash, negative/overflow sequence, future recorded time, unexpected nested field, depth/row/byte overflow, and constructor attempts to set immutable result flags.

- [ ] Run `uv run --offline --no-sync pytest tests/unit/domain/test_options_ledger.py tests/unit/simulation/test_options_ledger_codec.py -q`. RED must be the missing new import/behavior, not dependency or unrelated fixture failure.
- [ ] Implement closed dataclasses and per-tag parsers. Reuse `canonical_decimal_text`, bounded Decimal validation, `require_utc`, canonical JSON and duplicate-key/depth checks; keep a separate ledger schema rather than relaxing old decoders. Arithmetic helper in `options_ledger_book.py` (task 2) is not needed for record parsing.

```python
def consume(self, *, byte_count: int, row_count: int) -> None:
    if type(byte_count) is not int or type(row_count) is not int:
        raise DomainValidationError("ledger_budget_invalid")
    if min(byte_count, row_count) < 0:
        raise DomainValidationError("ledger_budget_invalid")
    if self.bytes_used + byte_count > self.limits.total_bytes:
        raise DomainValidationError("ledger_bytes_exceeded")
    if self.rows_used + row_count > self.limits.total_rows:
        raise DomainValidationError("ledger_rows_exceeded")
    self.bytes_used += byte_count
    self.rows_used += row_count
```

`LedgerLimits(event_bytes, total_bytes, total_rows, depth)` is immutable. `RecoveryBudget` is deliberately private mutable accounting for one bounded read; initialize its counters at zero and validate exact limits from `ledger_limits`, not caller scenario fields. Account for canonical bytes once per examined representation and rows once per stored/nested row, including duplicates; declare this convention in tests so repeated small sections cannot evade the aggregate bound.

- [ ] Register explicit new paths in the critical checker, with a smoke test that enumerates the expected set. Add further planned paths as they appear. Run the narrow tests plus existing v1 wire tests and critical-checker smoke tests; expect PASS, unchanged old digests. Commit only task 1's listed files with `feat(options): add closed offline ledger records`.

## Task 2: Exact independent book and conserved episode accounting

**Files:** Create `src/trading_bot/simulation/options_ledger_book.py`, `tests/unit/simulation/test_options_ledger_book.py`, `tests/options_ledger_fixtures.py`, `tests/options_ledger_boundary.py`; extend domain state records and task 1 coverage registration.

**Interfaces:** Consumes section 2 records, existing `transition`, `TrialEpisode`/`TrialLossState`. Produces `initial_book`, `reduce_ledger`, derived balance/episode state and shared `LedgerCase` fixtures. Does not accept caller P&L/finality or borrow comparison snapshot cash.

`LedgerCase` fields: `loaded: LoadedConfig`, `scope: OptionsLedgerScope`, `opening_intent: OptionsOrderIntent`, `commands: tuple[LedgerAppend, ...]`, `phase_indexes: Mapping[str, int]`, `valuations: tuple[RetainedOptionsValuation, ...]`, `observations: tuple[RetainedOptionsObservation, ...]`. Test helper `make_ledger_case(*, capital: str = "2500", scenario: str = "gain") -> LedgerCase` accepts only `gain`, `loss`, `two_episodes`, `unfilled`, `rejected`, `unknown`, `cancel_race`, `flat_unsettled`, `late_fee`, `duplicate_delivery`, `unexpected_shares`, `missing_mark`. `book_at(case: LedgerCase, phase: str) -> LedgerState` reduces through `phase_indexes[phase]`; `case_append(case: LedgerCase, event_id: str) -> LedgerAppend` requires one exact matching command. `with_evidence_changes(value: RetainedEvidence, **changes: object) -> RetainedEvidence` is a test-only resealing helper below. No production reducer computes fixture expected values.

```python
def with_evidence_changes(value, **changes):
    changed = replace(value, **changes)
    return replace(changed, evidence_hash=ledger_evidence_hash(changed))
```

Build fixtures from the existing `synthetic_options_request` contract shape, replacing account scope with `synthetic:ledger:case-1`, explicit sessions and all linked identities together. Do not reuse the incompatible `synthetic-research` account from old observation tests. Use explicit invented sessions on September 18 and 21, 2026, 13:30–20:00 UTC; genesis is the first open. Contract eligible sessions include both. Existing legacy replay gain/loss prices differ; the new literal prices below are authoritative for these fixtures.

| Phase / event facts | Independent expected cash state |
| --- | --- |
| `genesis` | cash 2500, no obligations or risk |
| `reserved`: buy 1 at limit .10, multiplier 100, entry fee bound .50, exit fee bound .50 | commitment 11, trial reservation 11, cash 2500 |
| synthetic risk/review/submission transition chain | no cash change; no transport |
| `entry_filled`: one .10 fill, fee .50, explicit payable due | payable 10.50, remaining commitment .50, settled cash still 2500, trial reservation 11 |
| `entry_settled`: matching completion | cash 2489.50, payable 0, remaining fee commitment .50, trial reservation 11 |
| `close_filled`: sell held 1 at .16, fee .50 | receivable 15.50, cash 2489.50, quantity 0; trial reservation 11 until all finality conditions |
| `fees_and_outcomes_final` | every related order has explicit exact fee set and terminal outcome evidence; receivable remains, trial still reserved |
| `complete`: close settlement completion | cash 2505, episode +5, consumed trial loss 0, reservation 0 |
| second-session complete close at .04 | second episode −7, cash 2498, consumed loss 7, never netted to 2 |

Assign explicit occurrence times increasing within each session. Start order chains with PROPOSED and use the exact existing event table through submitted/filled; combine fill accounting and its corresponding `OrderEvent.FILL` in the same reducer step, not an independently assertable filled state. An `OrderTransitioned` cannot independently manufacture a fill or reconciliation-filled quantity. No event may bypass required fill evidence.

- [ ] Add these literal assertion tests before the reducer:

```python
def test_entry_fill_transfers_commitment_without_debiting_cash():
    state = book_at(make_ledger_case(), "entry_filled")
    assert state.settled_cash == Decimal("2500")
    assert state.payables == Decimal("10.50")
    assert state.cash_commitment == Decimal("0.50")
    assert state.trial.reserved_risk == Decimal("11")

def test_flat_unsettled_does_not_complete_episode():
    state = book_at(make_ledger_case(), "fees_and_outcomes_final")
    assert state.receivables == Decimal("15.50")
    assert state.settled_cash == Decimal("2489.50")
    assert not state.trial.episodes[0].complete
    assert state.trial.reserved_risk == Decimal("11")

def test_prior_gain_does_not_offset_later_trial_loss():
    state = book_at(make_ledger_case(scenario="two_episodes"), "complete")
    assert state.settled_cash == Decimal("2498")
    assert state.trial.consumed_loss == Decimal("7")
    assert tuple(e.net_cash_flow for e in state.trial.episodes) == (
        Decimal("5"), Decimal("-7"),
    )
```

- [ ] Run `uv run --offline --no-sync pytest tests/unit/simulation/test_options_ledger_book.py -q`; observe RED for reducer behavior.
- [ ] Implement fixed-context addition/product and revalidate every computed value. Reset relevant context settings instead of inheriting ambient precision/traps; set precision 2048, standard exponent range, trap `Inexact`, `Rounded`, `Overflow`, `InvalidOperation`, `DivisionByZero`, and reject nonfinite output. Retain exact zeros; reject signed noncanonical Decimal input at wire boundaries.

```python
def exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    context = Context(prec=2048, Emin=-999999, Emax=999999)
    for signal in (Inexact, Rounded, Overflow, InvalidOperation, DivisionByZero):
        context.traps[signal] = True
    with localcontext(context):
        result = sum(values, Decimal(0))
    require_bounded_decimal(result, "ledger_amount")
    return result
```

Implement `exact_product(left: Decimal, right: Decimal) -> Decimal` with the same context/validation and multiplication in place of sum. No division is needed to allocate a one-unit fill. These helpers stay local to the reducer/projection, not a new money framework.

Reducer order: exact input/scope/evidence validation -> semantic duplicate lookup -> causal/quantity checks -> existing order transition -> obligation/fee/ownership effects -> derived episode finality -> canonical output bounds. A duplicate identical `fill_id` under another delivery is a retained no-economic-effect fact; conflicting same-fill content is an incident. Apply the same uniqueness to fee/settlement/flow identities. Delivery retry and economic deduplication are distinct.

Opening premium basis excludes fees; realized episode net includes every attributed cash flow exactly once. Fill fees are embedded in signed obligation amounts and also indexed as fee allocations for audit; never charge that fee row again. Additional fee events have a distinct payable. After finality, retain the new fact/incident without changing finalized episode cash flows or claiming a corrected budget. A before-finality fee exceeding its bound is retained and halts entries; do not discard known liability or silently claim all economics resolved.

For each episode derive `flat`, `orders_terminal`, reconciled outcome status, all explicit fees final, all obligations settled and no unresolved incident. Only then assign final `net_cash_flow`; otherwise it is `None`. On cancellation/rejection with no fills, explicit zero-fee finality and outcome confirmation are still required before releasing reservation. Never decrease the original `TrialEpisode.reserved_risk`; legacy state excludes it only when complete.

- [ ] Add Review Focus 1 and 2 tests:

```python
def test_same_fill_new_delivery_has_one_economic_effect():
    normal = book_at(make_ledger_case(), "complete")
    repeated = book_at(make_ledger_case(scenario="duplicate_delivery"), "complete")
    assert repeated.settled_cash == normal.settled_cash == Decimal("2505")
    assert len(repeated.obligations) == len(normal.obligations) == 2
    assert len(repeated.fee_allocations) == len(normal.fee_allocations) == 2

def test_late_fee_retained_without_rewriting_final_trial_history():
    normal = book_at(make_ledger_case(), "complete")
    late = book_at(make_ledger_case(scenario="late_fee"), "complete")
    assert late.trial == normal.trial
    assert "late_economic_fact" in tuple(i.reason for i in late.incidents)
    assert late.entry_halted
```

Add malformed/fractional fill, overfill, contract/side/effect/account substitution, close-more-than-held, terminal-cancel fill, cancel-pending whole fill, unknown acceptance, additional fee/embedded fee collision, duplicate settlement, negative cash and scope reset tests. Every anomaly retains source facts, halts admission and preserves attributable history; invalid wire data fails before append. Simulated outcomes never authorize retry.

- [ ] Implement a new explicitly imported autouse fixture `offline_ledger_boundary` in `tests/options_ledger_boundary.py`: deny `socket.create_connection`, `getaddrinfo`, `socket.socket.connect`, `connect_ex`, and subprocess creation in in-process suites; remove broker/provider credential environment keys; deny credential-store entry points. File guards deny known credential roots and private-key filenames, allow only repository source/config and test temporary roots. Do not patch away all file I/O needed by SQLite. Add import-graph checks that the new modules cannot reach broker transports or auth bootstrap. Subprocess CLI/backup tests use a controlled child environment and explicit local-tool allowlist, never the blanket subprocess deny fixture.
- [ ] GREEN: narrow book/domain/codec tests and existing economics/state-machine tests. Add an ambient context test (precision 2, changed rounding and traps) that preserves the literal expected values, and one over-bound calculation that fails rather than rounds. Commit exact task files with `feat(options): derive exact offline option cash and trial history`.

## Task 3: Independent valuation, complete snapshot semantics and bound risk history

**Files:** Create `src/trading_bot/simulation/options_ledger_projection.py`, `src/trading_bot/risk/options_ledger.py`, `tests/unit/simulation/test_options_ledger_projection.py`, `tests/unit/risk/test_options_ledger_risk.py`; modify `src/trading_bot/risk/options_economics.py`, its existing unit tests and critical path registration.

**Interfaces:** Consumes reducer/evidence from tasks 1–2. Produces `project_ledger`, `derive_loss_point`, `evaluate_ledger_entry`. Extend existing `long_option_feasibility` with keyword-only `authorized_risk_equity: Decimal | None = None`; omission preserves exact prior behavior, supplied value can only lower the risk base to `min(capital.equity, authorized_risk_equity)` and must be positive bounded Decimal. Call only in the existing offline modes.

- [ ] Write RED tests separating cash floor from risk reference:

```python
def test_risk_reference_does_not_scale_with_gains_or_funding():
    loaded = config()
    capital = OptionsCapitalState(
        Decimal("5000"), Decimal("5000"), Decimal("5000"),
        Decimal(0), Decimal(0), 0, 0,
    )
    result = long_option_feasibility(
        loaded, capital, premium=Decimal("0.10"), multiplier=Decimal(100),
        fee_reserve_per_unit=Decimal(1), trial=TrialLossState(()),
        authorized_risk_equity=Decimal("100"),
    )
    assert result.per_trade_budget == Decimal("0.50")
    assert result.admissible_units == 0
```

Also use `capital.cash=3999`, equity 5000 and authorized reference 2500: the current-equity 80% cash floor must deny; do not use the 2500 risk reference for cash floor. Assert default calls return byte-for-byte identical old feasibility reports.

- [ ] Run `uv run --offline --no-sync pytest tests/unit/risk/test_options_economics.py tests/unit/risk/test_options_ledger_risk.py tests/unit/simulation/test_options_ledger_projection.py -q`; expected RED at new keyword/interfaces.
- [ ] Apply the lesser risk base to percentage trade, portfolio/group payoff, position-notional and gross-exposure limits while cash floor uses `capital.equity`. Preserve all existing absolute caps, activity restrictions, fee/trial checks and reason names. In ledger composition the authorized research reference always equals immutable genesis cash, never caller-supplied current balance.

The synthetic cash-account projection formula is explicit fixture policy, not broker rules:

```python
base_equity = exact_sum((state.settled_cash, state.receivables, -state.payables))
broker_equity = exact_sum((base_equity, broker_mark_value))
liquidation_equity = exact_sum((base_equity, liquidation_bid_value))
buying_power = max(
    Decimal(0),
    exact_sum((state.settled_cash, -state.payables, -state.cash_commitment)),
)
```

`broker_mark_value` and `liquidation_bid_value` are separately summed per held contract using exact `quantity * multiplier * matching mark`. Empty holdings value to zero without demanding an irrelevant contract mark; nonempty holdings require both complete mark sets. Freshness and point-in-time checks use canonical settings; reject future/missing/duplicate marks, incomplete sessions or unknown account semantics. No collateral/margin netting; nonzero unexplained comparison collateral is an incident. Once all evidence is complete, construct the existing exact fields:

```python
cash = OptionsCash(
    equity=broker_equity,
    settled_cash=state.settled_cash,
    buying_power=buying_power,
    collateral=Decimal(0),
    reserved_cash=state.cash_commitment,
    unsettled_receivable=state.receivables,
    unsettled_payable=state.payables,
)
```

Zero collateral is this closed synthetic cash policy's explicit fact, not a substitution for unknown broker collateral. Populate contracts/positions/orders/fills/settlements from attributable book records and cost basis from premium basis. Empty shares/lifecycle sections are complete only in the explicit flat-genesis synthetic history with no unresolved incident; otherwise deny a complete snapshot. `data_hash` binds the local economic history and separate valuation hash. If any required field cannot be derived, set `snapshot=None` and an explicit reason, not fabricated values.

- [ ] Add Review Focus 4 assertions using `dataclasses.replace` on the fixture valuations:

```python
def test_missing_liquidation_mark_is_not_a_zero_bid():
    case = make_ledger_case()
    state = book_at(case, "entry_settled")
    valuation = case.valuations[1]
    missing = with_evidence_changes(valuation, marks=tuple(
        m for m in valuation.marks if m.kind != "liquidation_bid"
    ))
    result = project_ledger(state, missing, as_of=missing.observed_at, loaded=case.loaded)
    assert result.liquidation_equity is None
    assert result.snapshot is None
    assert "liquidation_mark_missing" in result.reasons
```

Recompute valid evidence hashes in fixture constructors after mutation, not in production to conceal invalid hashes. A separate zero-bid fixture yields actual liquidation value zero for that holding and lower equity, not `None`; it still cannot be used for a new zero-bid entry. A changed comparison mark never changes local cost basis, quantities, cash or settlement.

- [ ] Bind each loss point source hash to `(ledger_head, valuation_hash, explicit session, cumulative external flows)`. First complete point is exactly session open with zero flows and positive equity. Subsequent valuation ticks strictly increase, with an explicit prior-session close point before new-session open; missing boundary remains a permanent gap per existing evaluator. Multiple cash events at one economic timestamp precede one valuation tick; do not invent microseconds or two loss points at one time. Retaining evidence must not itself fabricate a new point.
- [ ] Entry composition reconstructs ledger and risk heads inside the transaction, requires a complete fresh risk report and usable current valuation, rejects any unresolved incident or incomplete prior episode, then calls the existing necessary feasibility filter. A fresh valuation point after all prior economic changes is required; pure evidence/run-link appends do not refresh economics. Bind admission to exact current economic prefix, intent/config/account, risk head and valuation. The report never becomes a live permit.

Construct `OptionsCapitalState` from the projection: `equity` is current broker-comparison equity; `cash` and `buying_power` are the derived unencumbered buying power above; portfolio/group risk are the outstanding full payoff reservations; position count includes existing holdings and pending opening reservation; session activity comes from opening attempts in the exact explicit session. Negative or unknown inputs deny before constructing the nonnegative legacy type. Pass `authorized_risk_equity=scope.genesis_cash`; entry fee reserve is the frozen opening intent's full entry+exit fee bounds, not a later closing order's proposed smaller bounds. Fees are explicit invented scenario inputs in this slice, not verified broker fee schedules; absent fee bounds deny the rehearsal.
- [ ] Test $100/.10/100/$1 -> per-trade .50 and zero units; $2500 complete gain/loss; deposit and profit do not enlarge risk reference or trial capacity; withdrawals/missing marks deny; same-session second entry denies; next session requires explicit closed previous session; weekly/drawdown latches survive later gains. Test all omitted/incomplete/stale/mismatched risk inputs fail closed. GREEN narrow suite plus all `tests/unit/risk/test_options_loss_history.py`. Commit `feat(options): bind ledger valuation and existing risk history`.

## Task 4: Additive guarded schema and atomic journal composition

**Files:** Create `migrations/versions/0008_options_offline_ledger.py`, `src/trading_bot/persistence/options_ledger_models.py`, `src/trading_bot/persistence/options_journal_transaction.py`, `tests/integration/persistence/test_options_ledger_migrations.py`, `tests/integration/persistence/test_options_journal_transaction.py`; modify model registration, trial/risk journals and coverage registration.

**Interfaces:** Consumes immutable records and branded `async_session_factory`. Produces `_FencedOptionsTransaction`, an async context manager yielding `session: AsyncSession`, account-bound `lease`, monotonic trusted `checked_at`, and `check_leader() -> datetime` (async reselect/check). Only its factory method can produce an active token; helpers reject unbranded factories, inactive/foreign sessions, changed account, expired token and backward clocks.

Private helpers are `OptionsTrialJournal._append_in_transaction(tx, event, *, expected_state, expected_head) -> str` and `OptionsRiskJournal._append_in_transaction(tx, point, *, expected_head) -> str`, async, no BEGIN/commit/rollback. Their inputs use the existing exact types. Public `append` signatures stay unchanged and own their original transaction through the same helper/checks. Payload encoders and row hashes are not changed.

Schema revision `0008_options_offline_ledger`, `down_revision="0007_options_risk_history"`. Every new immutable row has account/scope composite foreign keys; causal rows also reference `(account_id, ledger_id, event_id)`. Exact types come from `persistence/base.py`, not SQLite REAL or permissive INTEGER affinity. Monetary values remain canonical TEXT.

| Table / ORM class | Principal fields and uniqueness |
| --- | --- |
| `options_ledger_scopes` / `OptionsLedgerScopeRow` | account PK/FK, ledger ID unique, schema/config/genesis cash/history start/currency; one account cannot get another genesis |
| `options_ledger_events` / `OptionsLedgerEventRow` | event ID PK, scope, sequence, previous/event hashes, fencing/code/recorded time, canonical command; unique account+sequence and event hash |
| `options_ledger_intents` / `OptionsLedgerIntentRow` | intent ID, event/episode IDs, immutable intent hash/payload, opening/closing kind; unique scoped intent |
| `options_ledger_legs` / `OptionsLedgerLegRow` | scoped intent+leg index, contract ID/hash, side/effect/ratio; one standard leg for admitted local intent |
| `options_ledger_fills` / `OptionsLedgerFillRow` | scoped fill ID, order/episode/contract IDs, quantity/premium, fee reference, causal event; unique scoped fill |
| `options_ledger_reservations` / `OptionsLedgerReservationRow` | event+episode+movement kind, exact cash/trial amounts; unique scoped event+kind |
| `options_ledger_fees` / `OptionsLedgerFeeRow` | scoped fee ID, order, fill ID nullable, amount, embedding settlement ID; no duplicate allocation |
| `options_ledger_settlements` / `OptionsLedgerSettlementRow` | scoped settlement ID, origin event, episode/order, signed amount, due; completion is a separate event reference, never UPDATE |
| `options_ledger_evidence` / `OptionsLedgerEvidenceRow` | scoped content hash, kind, original times/history coverage, bounded canonical preimage; no raw provider blobs |
| `options_ledger_incidents` / `OptionsLedgerIncidentRow` | scoped incident ID, source hash, event or monitor-run cause, reason, optional episode; append-only unresolved |
| `options_ledger_monitor_links` / `OptionsLedgerMonitorLinkRow` | run ID+link kind+ordinal, local head, observation/valuation/input hashes, retry-of nullable, result ID/hash nullable, original source time; append-only input/result/failure links |

Events are authoritative; normalized rows must exactly equal their reducer-derived effects on recovery. Add `OptionsLedgerSettlementCompletionRow` / `options_ledger_settlement_completions` with scoped settlement ID, completion event ID and completion time, unique `(account_id, ledger_id, settlement_id)` and composite FKs to the obligation and causal event. Register it in migration/guard tests; do not implement mutable completion columns. No cache table in v1.

- [ ] Write RED migration/transaction tests using temporary `database_url`/`alembic_config` fixtures. Upgrade only that URL, seed `synthetic:ledger:case-1`, then check metadata, all exact CHECKs/FKs, duplicate IDs, UPDATE/DELETE/REPLACE guards, rowid collision and nonempty downgrade denial. An empty new schema may downgrade without changing preexisting 0007 rows.

```python
def test_nonempty_ledger_downgrade_preserves_evidence(ledger_database):
    before = ledger_database.table_digests()
    with pytest.raises(RuntimeError, match="nonempty"):
        command.downgrade(ledger_database.alembic_config, "0007_options_risk_history")
    assert ledger_database.table_digests() == before
```

`ledger_database` is a new task-local fixture in this test file: dataclass containing temporary path/config and `table_digests() -> tuple[tuple[str, str], ...]`, computed from deterministic sorted SELECTs over allowlisted table names. It seeds only the minimal valid genesis/scope/event with literal synthetic IDs. Never point this fixture at environment-derived URLs.

- [ ] Run `uv run --offline --no-sync pytest tests/integration/persistence/test_options_ledger_migrations.py tests/integration/persistence/test_options_journal_transaction.py -q`; RED missing revision/helper.
- [ ] Implement guard patterns from 0007, including `RAISE(ROLLBACK)` and collision guards that also work for REPLACE. Bound all inserted canonical strings and exact integer ranges. Check nonempty tables before any destructive downgrade operation. Register models without circular imports or changing existing metadata names.
- [ ] Extract the existing journal transaction bodies unchanged in semantics. The outer writer begins IMMEDIATE, validates/reselects leadership after waits, reconstructs bounded state, calls helpers, flushes, rechecks leadership and commits once. Helpers never accept a raw arbitrary session; old public APIs still enforce exact tip retries, chronological history, config identity and expected-state/CAS checks. Test a deliberately raised exception after both helper calls rolls both back.

```python
async def test_journal_helpers_cannot_escape_rollback(journal_transaction_case):
    c = journal_transaction_case
    before_trial = await c.trial.snapshot(c.account)
    before_risk = await c.risk.snapshot(c.account)
    with pytest.raises(RuntimeError, match="injected rollback"):
        async with c.transaction() as tx:
            await c.trial._append_in_transaction(
                tx, c.trial_event, expected_state=before_trial.state,
                expected_head=before_trial.head_hash,
            )
            await c.risk._append_in_transaction(tx, c.risk_point, expected_head=before_risk.head_hash)
            raise RuntimeError("injected rollback")
    assert await c.trial.snapshot(c.account) == before_trial
    assert await c.risk.snapshot(c.account) == before_risk
```

Define `journal_transaction_case` locally with real temporary migrated factory, mutable injected Clock, account, acquired lease, journal instances, one valid reservation event and one session-open risk point; `transaction()` creates `_FencedOptionsTransaction`. No mocked successful commit.
- [ ] GREEN new migration/helper tests plus existing trial/risk/recorded-session tests. Assert old v1 literal hashes and public signatures unchanged, including optional legacy trial expected-head behavior. Commit exact files with `feat(options): add guarded offline ledger transaction schema`.

## Task 5: Durable entry/close/settlement vertical slice and bounded recovery

**Files:** Create `src/trading_bot/persistence/options_ledger.py`, `src/trading_bot/persistence/options_ledger_recovery.py`, `tests/integration/persistence/test_options_ledger_journal.py`, `tests/integration/persistence/test_options_ledger_recovery.py`, `tests/chaos/runtime/test_options_ledger_failures.py`; extend shared fixtures and coverage registration.

**Interfaces:** Consumes all previous tasks. Produces the exact async journal/recovery APIs in section 2. `LedgerCommitUncertain` and `LedgerRecoveryError` contain only fixed reason codes, never DB exception payloads; original exceptions may be chained internally only if public logging cannot render them. Commit uncertainty is not an automatic retry exception.

Integration fixture `ledger_harness` provides temporary real engine/factory, `journal`, `clock`, `lease`, `case`, `async initialize() -> LedgerReceipt`, `async apply_through(phase: str) -> LedgerRecovery`, `async reopen() -> LedgerRecovery`, `async reacquire() -> None`. Use the existing execution-lease test `Clock(current=...)`, not the different risk test clock's `.value` attribute. `reopen` disposes/recreates the engine and repositories, does not append, reacquire, redate data or change the scope. `apply_through` updates the injected clock to the prescribed command time, explicitly reacquires expired test leases, and appends each command with the prior receipt head; it cannot bypass validation. Implement this helper alongside the journal tests, with cleanup in `finally`.

- [ ] Write the first actual database slice as RED:

```python
async def test_durable_flat_unsettled_then_complete_after_restart(ledger_harness):
    h = ledger_harness
    pending = await h.apply_through("fees_and_outcomes_final")
    assert pending.projection.receivables == Decimal("15.50")
    assert pending.projection.trial.reserved_risk == Decimal("11")
    recovered = await h.reopen()
    assert recovered.head_hash == pending.head_hash
    assert recovered.projection == pending.projection
    assert recovered.projection.paused
    await h.reacquire()
    final = await h.apply_through("complete")
    assert final.projection.settled_cash == Decimal("2505")
    assert final.projection.trial.consumed_loss == Decimal(0)
    assert final.projection.trial.reserved_risk == Decimal(0)
    assert not final.projection.production_eligible
```

- [ ] Run `uv run --offline --no-sync pytest tests/integration/persistence/test_options_ledger_journal.py tests/integration/persistence/test_options_ledger_recovery.py -q`; expect RED new writer/recovery, not a fake in-memory success.
- [ ] Implement one transaction with this exact ordering:

```text
validate frozen scope/request and branded factory
BEGIN IMMEDIATE; reselect account/owner/token; check trusted clock
read bounded retained history + old trial/risk journals under one snapshot
verify schema/config/account, chains, references, normalized effects and budget
check original event ID: exact current tip -> validated receipt; conflict/superseded -> deny
compare required expected head; independently evaluate any new entry
retain referenced preimages; reduce attributable facts or derived unresolved incident
append event, normalized effects and changed existing trial/risk entries in this transaction
flush; reselect/check leader and monotonic clock again; commit once
return durable receipt only after known successful commit
```

Ledger sequence/fence/recorded time come from the writer, not input. Compare against prior trusted clock and prior event; disallow lower fencing tokens, missing/reordered sequence, mismatched predecessor or account/config/code substitutions. Producer code hash remains historical evidence; a reader does not replace it with its own hash. No independent source can rewrite history by passing a new scope or configuration.

Trial append only when derived episode state changes, using deterministic event identity derived from ledger event plus episode. Risk append only for explicit valid valuation ticks, with source hash binding the newly persisted event head; do not emit a point for each fill/monitor poll. Ensure old journal prefixes and new event references reconcile on every restore. A retained late fact can extend incident history but not reopen a finalized trial episode.

Before fetching preimages, query bounded row counts and `length(CAST(payload AS BLOB))` for the selected snapshot; include all event/effect/evidence/trial/risk/link rows in one `RecoveryBudget`. Fetch with LIMIT+1, fail before excessive materialization, then strict-decode and replay in sequence. Recompute every normalized effect and evidence hash; exact comparison fails if a source preimage is missing, rows are truncated, chain/fence chronology is invalid or persisted normalized effects diverge. Do not repair/delete rows or keep only recent losses. No stored cache may override this calculation.

- [ ] Add exact-tip retry and stale/superseded tests:

```python
async def test_exact_tip_retry_has_one_receipt(ledger_harness):
    h = ledger_harness
    first = await h.initialize()
    request = h.case.commands[0]
    again = await h.journal.append(
        h.lease, h.case.scope, request, expected_head=first.head_hash,
    )
    assert again == first
    assert (await h.journal.recover(h.case.scope)).head_hash == first.head_hash
```

After another event advances the head the same append must deny, while `lookup_receipt` may still return its old receipt without authorizing action. Permit retry against either original predecessor or same current tip only if exact content/account/scope matches. Initial genesis retry must use explicit append/lookup, not silently recreate a scope.

- [ ] Review Focus 3: inject lock delay past expiry, backward clock during reconstruction, lease takeover, flush failure, disk-full error, commit-before-ack timeout and rollback-before-commit timeout. For known rollback assert no local/normalized/trial/risk side effects. For ambiguous commit raise `LedgerCommitUncertain`, then reopen and look up the original ID: receipt validates committed original or absence; neither path manufactures an ID or retries automatically. Test two concurrent writers/CAS with exactly one success.

```python
async def test_lease_expiry_during_reconstruction_denies_append(ledger_harness, monkeypatch):
    import trading_bot.persistence.options_ledger as journal_module

    h = ledger_harness
    receipt = await h.initialize()
    original = journal_module.recover_ledger

    async def slow_recovery(*args, **kwargs):
        result = await original(*args, **kwargs)
        h.clock.current = h.lease.expires_at
        return result

    monkeypatch.setattr(journal_module, "recover_ledger", slow_recovery)
    request = h.case.commands[1]
    with pytest.raises(StaleFencingToken):
        await h.journal.append(h.lease, h.case.scope, request, expected_head=receipt.head_hash)
    assert await h.journal.lookup_receipt(h.case.scope, request.command.event_id) is None
```
- [ ] Parameterize restart at every command prefix and assert identical state/head/trial amounts to uninterrupted replay. Across wall-clock advancement only freshness/paused status may become stricter, never balances or source times. Add late-fee incident restart, second episode loss7, deposit/profit/no reset, terminal-cancel fill, duplicate semantic fill under another ID, unknown outcome, schema mismatch, row tampering and aggregate capacity tests. GREEN narrow suites then all persistence/legacy recorded-session tests. Commit `feat(options): persist and recover synthetic option economics atomically`.

## Task 6: Retained independent monitor inputs, expiry and run-result links

**Files:** Create `src/trading_bot/runtime/options_ledger_monitor.py`, `tests/unit/runtime/test_options_ledger_monitor.py`, `tests/integration/persistence/test_options_ledger_monitor_links.py`; modify `src/trading_bot/persistence/reconciliation.py` narrowly and coverage registration.

**Interfaces:** Consumes journal/recovery, independent evidence and unchanged `OptionsMonitorInput`/`PausedOptionsMonitor`. Produces:

- `OfflineLedgerObservationSource(journal, scope, *, observation_hash: str, valuation_hash: str, run_id: str, retry_of: str | None, clock: Clock, lease: ExecutionLease)` with `async read(account_id: AccountId) -> OptionsMonitorInput`.
- `OfflineLedgerRunStore(journal, scope, *, run_id: str, lease: ExecutionLease)` with `async persist(result: ReconciliationResult) -> None`.
- `SqlReconciliationStore._persist_in_session(session: AsyncSession, result: ReconciliationResult) -> None` as a private async serialization/insert helper; existing public `persist` still owns its transaction and unchanged lease-revocation behavior. New composition calls it only within the fenced run-link transaction.
- `LedgerSourceIncomplete` with fixed reason text. No changed legacy monitor protocol.

The journal gains async `link_monitor_input(lease: ExecutionLease, scope: OptionsLedgerScope, *, run_id: str, local_head: str, observation_hash: str, valuation_hash: str, input_hash: str, retry_of: str | None) -> None` and `link_monitor_result(lease: ExecutionLease, scope: OptionsLedgerScope, *, run_id: str, result: ReconciliationResult) -> None`. These audit operations use the same fenced transaction and bounded recovery checks but do not append economic effects. Results and derived incident links are reconstructed into `state.incidents`; they are included in recovery limits and entry denial. An exact already-written link is idempotent; a conflicting link is denied.

Pending links add `monitor_run_pending` to recovered projection reasons and deny a complete rehearsal or new entry. Link recovery verifies each result preimage/hash, original input hash and all source references, not just existence of a foreign key. Input/result links do not change the economic head, so entry validation must reconstruct and check them within its own current transaction instead of trusting an old clean result with the same economic head.

Source and store share immutable scope/run identity, not a mutable global “last run.” A run input link binds current local head, original observation/valuation hashes and `content_hash(OptionsMonitorInput)` before returning the input. Missing snapshot/mark/window/coverage raises sanitized incomplete-source error; persist failure/pending linkage where possible without fabricating a result. Do not acquire execution exclusivity inside the legacy monitor: the offline coordinator supplies a ledger writer lease solely for audit persistence, not execution permission.

- [ ] Write RED comparison-independence and pending-run tests:

```python
async def test_changed_comparison_cannot_repair_local_book(ledger_monitor_case):
    c = ledger_monitor_case
    before = await c.journal.recover(c.scope)
    status = await c.mismatched_monitor.cycle()
    after = await c.journal.recover(c.scope)
    assert not status.reconciliation_clean
    assert after.projection.settled_cash == before.projection.settled_cash
    assert after.projection.owned_positions == before.projection.owned_positions
    assert status.paused and not status.entry_enabled
```

`ledger_monitor_case` seeds a completed real temporary ledger, retains a separate synthetic snapshot with cash off by exactly 1, supplies complete unchanged calendars/valuation and matching account/config/history, and constructs source/store/monitor plus stub local AlertSink. It must not derive comparison balances by calling `project_ledger`; expected snapshot fields come from literal fixture expectations.

- [ ] Run `uv run --offline --no-sync pytest tests/unit/runtime/test_options_ledger_monitor.py tests/integration/persistence/test_options_ledger_monitor_links.py -q`; RED absent source/link behavior.
- [ ] Build source from independent reconstruction, never `local=broker`. Validate evidence prefix/history window and as-of identities before comparing. Old retained inputs preserve their original time after reload. A source cannot select future head evidence or a different account/config. Persist input link before monitor evaluates. Store checks the actual result ID uses the existing `options-observation-v1-{input_hash}-...` binding and checks scope/time; do not assume the monitor accepts a supplied run ID.
- [ ] Within one fenced transaction write result via `_persist_in_session` and append result link/derived incident rows. Support the monitor's possible second clock-fault result as a new ordinal link for the same run; no result overwrite. Atomic result+link failure remains pending, not clean. A crash between input and result leaves a pending run; explicit retry references it with a new run ID and original input hashes. Monitor links/incident evidence do not charge premium, repeat a fill, reset losses or refresh data.
- [ ] Feed retained calendars to existing `assess_option_expiry`; test preceding eligible session close, holiday/nonconsecutive sessions, DST timestamp boundaries, missing calendar, deadline reached, last-trading cutoff and unsettled expiry. Never implement a weekday approximation or close/exercise action. Assignment/exercise/broker-closeout/short/unmatched shares are retained unresolved incidents; do not guess option or stock effects.
- [ ] Test source missing preimage/mark vs zero, stale after restart, incomplete required sections, exact mark/cost-basis/buying-power mismatch, pending-run restart, retry result identity, storage error, expired audit lease and alert failure. Monitoring may continue to report an entry halt; it must not become healthy because persistence/alerts failed. GREEN new and all existing monitor/reconciliation/expiry tests. Commit `feat(options): connect retained ledger evidence to paused monitoring`.

## Task 7: Private synthetic rehearsal, read-only inspection and explicit prefix continuation

**Files:** Create scenario/IO/CLI paths in file map, `docs/options-ledger-rehearsal.md`, `tests/integration/cli/test_options_ledger.py`, `tests/unit/simulation/test_options_ledger_io.py`; modify coverage registration only outside those paths. Do not edit the dirty main CLI.

**Interfaces:** `build_ledger_scenario(loaded: LoadedConfig, *, name: str, capital: Decimal) -> LedgerScenario`; frozen `LedgerScenario(scope: OptionsLedgerScope, commands: tuple[LedgerAppend, ...], prefix_hashes: tuple[str, ...], input_hash: str)`. Prefix hash zero is the canonical scope hash; each next hash binds previous prefix plus next canonical command/evidence, so the tuple has `len(commands)+1` members. `read_ledger_scenario(path: Path, loaded: LoadedConfig) -> LedgerScenario`; `inspect_ledger_root(root: Path, loaded: LoadedConfig) -> LedgerRecovery` (async); `main(argv: list[str] | None = None) -> int`. Runtime uses the same journal/reducer/monitor, not test fixture imports.

Closed built-in scenarios: `gain`, `loss`, `two-episodes`, `flat-unsettled`, `unknown`, `cancel-race`, `unfilled`. Implement their literal event/price tables from task 2 in production fixture assembly, with clear synthetic labels and source manifests. Price/fee constants are invented fixtures, not strategy thresholds. No scenario-specific risk override. User-supplied synthetic scenario schema uses only task 1 records and canonical limits.

CLI flags:

```text
rehearse --config-dir DIRECTORY --scenario NAME --capital DECIMAL --output-root NEW_PRIVATE_ROOT
inspect --config-dir DIRECTORY --output-root EXISTING_PRIVATE_ROOT
resume-rehearsal --config-dir DIRECTORY --output-root EXISTING_PRIVATE_ROOT
                 --scenario-file PRIVATE_SYNTHETIC_FILE --expected-head SHA256
                 --expected-prefix SHA256
```

`--capital` is explicitly hypothetical fixture genesis and cannot alter loaded config/live equity. A new root has one fixed `ledger.sqlite3`, `scenario.json` and bounded private report; no arbitrary DB path/account flag. `resume-rehearsal` requires existing scenario's exact committed prefix and unchanged scope/config; future continuation may be appended only if prefix hash, durable head and canonical scope match. It does not truncate history, accept a replacement scenario, clear incidents or auto-resume entries. Inspection/continuation with an existing empty but unrelated DB is denied before migration.

- [ ] RED CLI test:

```python
def test_small_capital_rehearsal_is_truthfully_denied(tmp_path, options_config_dir):
    root = tmp_path / "private-ledger"
    status = main([
        "rehearse", "--config-dir", str(options_config_dir), "--scenario", "gain",
        "--capital", "100", "--output-root", str(root),
    ])
    assert status == 2
    report = json.loads((root / "report.json").read_text())
    assert report["admissible_units"] == 0
    assert report["paused"] is True
    assert report["live_authorized"] is False
    assert "per_trade_risk" in report["reason_codes"]
```

`options_config_dir` is `Path(__file__).resolve().parents[3] / "configs"` in this CLI integration test. Match `cli/options_research.py` and `cli/options_risk_history.py` with this exact loader; do not inherit environment credentials or live flags:

```python
def _load(config_dir: Path) -> LoadedConfig:
    return load_config(
        config_dir / "base.yaml",
        config_dir / "options/simulation.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )
```

Keep Typer's exception-local display disabled. Expose the testable `main(argv) -> int` wrapper around the Typer command, translate successful/denied command exits to 0/2, sanitize parsing errors, and use `raise SystemExit(main())` only in the module entry block. Document, for example, `uv run --offline --no-sync python -m trading_bot.cli.options_ledger rehearse --config-dir configs --scenario gain --capital 2500 --output-root /private/tmp/options-ledger-example` with a new root, no command substitution or implicit production target.

- [ ] Run `uv run --offline --no-sync pytest tests/integration/cli/test_options_ledger.py tests/unit/simulation/test_options_ledger_io.py -q`; RED missing module/path contract.
- [ ] Implement descriptor-relative directory creation/open with no-follow checks and inode ancestry; reject repository descendants, symlink parents, case-insensitive aliases, hardlink file aliases and unexpected root contents. Use 0700 roots/0600 artifacts, safe exclusive creation and atomic report rename/fsync. Validate canonical scenario bytes before any persistence write. Do not render paths/account IDs/payloads/exceptions on stdout; only fixed reasons, hashes/counts and immutable false flags.
- [ ] Inspection opens source SQLite in `mode=ro`, starts a consistent read/online-backup snapshot into a private temporary database and validates that snapshot; never call the writer engine factory on the source, change its PRAGMAs, migrate it, copy raw WAL files or fall back to `immutable=1` on active WAL. Fail closed on missing/unreadable required WAL state or source identity changes. Use file-descriptor/inode identity checks around SQLite opening; if the platform cannot guarantee protected-root identity, deny rather than assume.
- [ ] Exercise the real writer on the copied temporary snapshot only for connection-policy validation; reconstruction itself stays read-only. Never renew lease/observation times in inspection. For resume, recover paused first, require explicit prefix/head, then reacquire a synthetic writer lease with the current clock before any append. Persistent uncertainty/incident remains visible and blocks admission.
- [ ] Add the Review Focus 5 source-identity tests. `ledger_inspection_case` creates a private root through the real rehearsal command, keeps a source connection open so a committed WAL remains active, and exposes `root: Path`, `loaded: LoadedConfig` and `source_digests() -> tuple[tuple[str, str], ...]` for the DB and WAL bytes. Do not compare shared-memory lock bytes or checkpoint/close the final source connection between the before/after measurements.

```python
async def test_inspection_is_repeatable_without_changing_db_or_wal(ledger_inspection_case):
    c = ledger_inspection_case
    before = c.source_digests()
    first = await inspect_ledger_root(c.root, c.loaded)
    second = await inspect_ledger_root(c.root, c.loaded)
    assert first.head_hash == second.head_hash
    assert first.state == second.state
    assert c.source_digests() == before
    assert first.projection.paused and second.projection.paused

async def test_inspection_rejects_root_alias(ledger_inspection_case, tmp_path):
    c = ledger_inspection_case
    alias = tmp_path / "ledger-alias"
    alias.symlink_to(c.root, target_is_directory=True)
    with pytest.raises(DomainValidationError, match="ledger_source_unsafe"):
        await inspect_ledger_root(alias, c.loaded)
```

`source_digests` also detects a disappearing or newly created DB/WAL file, not just modified content. Add equivalent repository-ancestor/case-alias checks using inode identity, with an explicit filesystem-capability skip only for case-insensitive alias creation on a case-sensitive test filesystem; the general inode guard must still be exercised.
- [ ] Add repeat-inspection byte/state identity, live/auth/reset/DB-path flag rejection, private permissions, malicious scenario/deep JSON, stdout redaction, input outside private root, root alias substitution, complete0/incomplete2, no forced closing fill, and wrong-prefix/head/config tests. Use the offline boundary fixture and static import denial; separate subprocess smoke invokes only local Python with a stripped environment.
- [ ] GREEN new CLI/IO plus old options replay CLI and recorded-session tests. Operator guide explains cash policy, premium basis, explicit settlement, zero-vs-missing marks, paused restart, fee incidents, no live permit, exact commands and all remaining external/economic gates. Commit `feat(options): add private offline ledger rehearsal commands`.

## Task 8: Failure matrix, restore/rollback compatibility and honest validation handoff

**Files:** Create `tests/deployment/test_options_ledger_backup_restore.py`, `tests/integration/persistence/test_options_ledger_compatibility.py`, `docs/options-ledger-validation.md`; extend chaos/CLI/codec/new critical-checker tests only where this milestone owns the behavior.

**Interfaces:** Consumes final APIs and existing online backup/encrypted restore scripts. Produces reproducible local verification evidence; no new trading capability or deployment output. Existing backup tests create a toy table, so passing them alone is not options-ledger restore evidence.

- [ ] Add RED real-schema backup test: seed a migrated synthetic ledger with a completed loss, a new unresolved obligation and an incident; take an online SQLite backup while WAL has committed data; restore into a different new private root. Recovery must reproduce economic heads/balances, consumed loss, reservation, original source times and unresolved incidents. New runtime stays paused and cannot use an expired restored lease.

```python
async def test_restored_economics_do_not_restore_authority(ledger_backup_case):
    c = ledger_backup_case
    before = await c.original.recover(c.scope)
    after = await c.restored.recover(c.scope)
    assert after.head_hash == before.head_hash
    assert after.projection.trial == before.projection.trial
    assert after.projection.settled_cash == before.projection.settled_cash
    assert after.state.incidents == before.state.incidents
    assert after.projection.paused and not after.projection.live_authorized
    with pytest.raises(StaleFencingToken):
        await c.restored.append(c.old_lease, c.scope, c.next_request, expected_head=after.head_hash)
```

`ledger_backup_case` uses the same real fixture database pattern, `sqlite3.Connection.backup`, independent temporary root, and a clock advanced past stored lease expiry. Encryption variant uses the existing actual backup/restore shell scripts and temporary age identities, not a mocked encryption pass. If `age`/`age-keygen` are absent, report explicit skip; do not install/download or claim encrypted validation.
- [ ] Run narrow backup/compatibility/chaos tests; RED must identify new coverage or missing behavior. Complete only scoped fixes, rerun the owning task's tests first.
- [ ] Pin an old-reader compatibility fixture to supported 0007 snapshots: unchanged reader behavior/hashes remain supported, while a 0008 ledger opened by a runtime/schema gate that does not declare 0008 support fails before writes. Do not patch old history or downgrade nonempty data to “prove” compatibility. Test that downgrade raises before deleting any new row and leaves old tables untouched.
- [ ] Finish the acceptance matrix below with actual test names/results. Include corrupt chain/reference/evidence, record-size/count aggregate exhaustion, malicious ambient Decimal context, duplicate economic facts, late fees, finality conflicts, lock/flush/disk/commit failure, concurrent writer, stale source/lease, bounded scheduler cancellation, result persistence and failed alerts. No skipped critical case can be called PASS.
- [ ] Run Ruff/Mypy/narrow tests and then the full locked non-authenticated suite. Use temporary coverage/SBOM outputs, never tracked artifact destinations:

```bash
uv run --offline --no-sync ruff check .
uv run --offline --no-sync mypy src
ledger_checks_dir=$(mktemp -d /private/tmp/options-ledger-checks.XXXXXX)
COVERAGE_FILE="$ledger_checks_dir/.coverage" uv run --offline --no-sync pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80 --cov-report="json:$ledger_checks_dir/coverage.json"
uv run --offline --no-sync python scripts/check_critical_branch_coverage.py --report "$ledger_checks_dir/coverage.json"
uv run --offline --no-sync bandit -c pyproject.toml -r src
uv lock --check --offline
uv run --offline --no-sync pytest tests/smoke/test_sbom_reproducible.py tests/deployment -q
```

Use a single shell/session for commands that use `ledger_checks_dir`, or record its resolved absolute path and use it explicitly in later calls. At the planning base, `test_sbom_reproducible.py` already writes two outputs under `tmp_path` and asserts the tracked artifact is unchanged; preserve that behavior. Do not run the SBOM generator against its default tracked output. Verify tracked SBOM and lockfile digests are unchanged.

Render only the default existing manifest: `docker-compose -f docker-compose.yml config --quiet` (installed standalone executable; use `docker compose` only if that plugin is actually available). The checked-in manifest supplies defaults; do not source a credentials file or inspect mounted production paths. No container/service start or infrastructure mutation. Locked audit against public advisories is allowed only under separately applicable authorization; otherwise mark unrun/blocked, not clean. Optional QuantLib/DuckDB/DBN research checks are separate environment checks; state absent tools/skips honestly. Do not network-install dependencies as part of these commands.
- [ ] Obtain one fresh whole-diff review under the preserved Native method, on the most capable available reviewer model as required by the chosen skill, with exact committed base and no raw/private data. Coordinator reviews every finding, fixes in-scope defects with RED/GREEN tests, reruns affected/full checks, and records unresolved findings. No per-task implementation delegation or Cloud claim.
- [ ] Write the actual validation report, commit only owned files, and hand off separate verdicts: offline technical result, remaining production technical gaps, economic evidence unavailable/unqualified, account/runtime verification unchanged, live authorization false. Do not push, merge, deploy or activate as an incidental verification step. Describe what was actually tested and any skips; do not reuse an earlier branch's test counts as current results.

## 3. Specification-to-test coverage map

| Approved spec sections | Owning task / required evidence |
| --- | --- |
| 1–4 scope, authorities, unchanged defaults | 1 records/false flags; 6 independent-source comparison; 7 import/CLI boundary |
| 5 schema, UTC, Decimal, limits, evidence identity, old v1 | 1 codec/aggregate bound/literal compatibility; 4 guarded rows; 5 recovery integrity |
| 6 ownership, full reservation, fill/payable/settlement, fee attribution | 2 exact cash tests; 5 durable vertical slice and rollback |
| 6 non-replenishing trial, roll/restart/finality/late facts | 2 two-episode and late-fee tests; 3 risk reference; 5 restart every prefix |
| 6 cancel/unknown/partial/unmatched | 2 state-machine/anomaly tests; 5 durable incident and no-retry tests |
| 7 independent marks, mandatory fields, synthetic cash policy | 3 zero/missing projection and lower risk reference with current-equity cash floor |
| 7 explicit sessions/flows/risk latches | 3 boundary/gap/latch tests; 5 atomic risk-journal linkage |
| 8 normalized schema, fenced atomic journals, CAS/uncertain commit | 4 schema/helper tests; 5 lock expiry/concurrency/unknown receipt tests |
| 8 bounded restore, no destructive downgrade, no privileged-rewrite claim | 5 corruption/overflow; 8 real backup/rollback tests and limitations |
| 9 pending runs, retention, incidents, expiry, failed alerts | 6 real source/store/run tests and unchanged expiry engine |
| 10 private root, read-only inspection, explicit resume, status codes | 7 alias/WAL/read-only/privacy/prefix tests; 8 live-WAL restore |
| 11 numerical acceptance, broad failure and quality gates | 2–3 literal arithmetic; 5 durable arithmetic; 8 fresh whole suite and coverage |
| 12 Native ownership and truthful deferred gates | all tasks; final independent review and separate readiness verdicts |

## 4. Plan review and execution handoff

Main-agent self-review checked this map against all twelve approved spec sections, reconciled cash-field/config-loader names against the current code, defined shared helper signatures and pinned the five Review Focus items to their owning tests. The code snippets are implementation/test instructions, not executed tests or existing features. Implementation may split long modules by responsibility only while preserving these frozen public interfaces and updating the file map/critical-coverage list in the same change.

Approval of this plan permits the described **Native, credential-free implementation and local tests**. It does not authorize external account access, production changes or live trading. Complete this ledger milestone before resuming the separately scoped native historical-data normalization milestone; neither synthetic ledger success nor clean reconciliation establishes economic viability.
