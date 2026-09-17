# Offline Order Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The operator selected inline execution; do not delegate accounting or lifecycle ownership.

**Goal:** Replay one synthetic limit order deterministically with consistent accounting and fail-closed event handling.

**Architecture:** Immutable request/events feed a synchronous pure replay function. Reuse the canonical state machine, accounting helper, Decimal validators, and content hashing without changing their behavior. No broker, persistence, runtime, or promotion composition is added.

**Tech Stack:** Python >=3.12,<3.15; frozen dataclasses, Decimal, existing domain types, Pytest, Ruff, mypy, Bandit. No new dependency.

**Spec:** [Approved design](../specs/2026-09-17-offline-order-lifecycle-design.md); read it together with this plan.

## Global Constraints

- Authorized new spending is $0.
- The default service remains paused and unable to submit orders.
- Implementation remains inline under the primary owner.
- One account, one instrument, and one order per replay; synthetic equity/crypto LIMIT orders only.
- GOOD_FOR_DAY or GOOD_TIL_CANCELED; other order/asset/TIF types fail closed.
- No retries, replacement orders, automatic expiration, account access, source capture, or deployment.
- Fixed `source_kind="synthetic-order-lifecycle-v1"` and `evidence_promotable=False`.
- No risk/config/schema/dependency changes; do not change `FakeBroker`, `FillModel`, `SimulationEngine`, or shared accounting/state-machine semantics.
- Preserve all existing dirty changes. Commits use explicit owned paths only; no push or merge.

Base: `e8939a355566a87ad24be20532f99bedd600e88a` on
`codex/continue-implementation-from-commit-7c4dcd1`, in the existing linked worktree.
Subsystem: partial. Critical path: validated records -> checked accounting/hashes -> replay -> adversarial/regression checks.

Run commands from `/Users/jedweinstein/Documents/robinhood-multi-asset-trading-system/worktrees/robinhood-system-implementation`.
Use the existing locked environment with `PYTHONPATH=src` so an older editable-install path cannot be selected:

```bash
export LIFECYCLE_PY=/private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python
```

No setup/download is needed while that environment works. Standard `uv run` commands remain the repository baseline; use the equivalent installed module entry points without changing dependencies.

## File map

| Path | Responsibility |
| --- | --- |
| `src/trading_bot/simulation/lifecycle_models.py` | Immutable records, exact input validation, safe reason-coded errors |
| `src/trading_bot/simulation/lifecycle_accounting.py` | Fixed-context exact accounting, checked reuse of `apply_fill` |
| `src/trading_bot/simulation/lifecycle_codec.py` | Domain-separated snapshot/event/result hashes |
| `src/trading_bot/simulation/lifecycle.py` | Pure ordered replay, deduplication, canonical transitions |
| `tests/unit/simulation/_lifecycle_fixtures.py` | Synthetic-only fixture builders |
| `tests/unit/simulation/test_lifecycle_models.py` | Input/record boundary tests |
| `tests/unit/simulation/test_lifecycle_accounting.py` | Independent literal accounting oracles |
| `tests/unit/simulation/test_lifecycle.py` | Replay/state/hash/duplicate contracts |
| `tests/unit/simulation/test_lifecycle_adversarial.py` | Identity, failure atomicity, type/precision/error attacks |
| `docs/architecture.md`, `docs/limitations.md`, `PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md` | Truthful implemented boundary and remaining blockers |

Read-only dependencies: `domain/orders.py`, `domain/accounts.py`, `domain/order_state_machine.py`,
`domain/decimal_utils.py`, `simulation/events.py`, `execution/partial_fills.py`,
`market_data/recording.py`, `docs/risk-policy.md`, `docs/live-activation.md`.

## Task 1: Validated immutable inputs and outputs

**Files:** Create `lifecycle_models.py`, `_lifecycle_fixtures.py`, `test_lifecycle_models.py`.

**Interfaces:** `LifecycleRequest(order, position, cash, submitted, events)`,
`LifecycleControlEvent(event_id, cursor, account_id, instrument_id, broker_order_id, event)`,
`LifecycleFillEvent(event_id, cursor, fill)`, union `LifecycleEvent`,
`LifecycleSnapshot(order, position, cash, fees, remaining_quantity, cursor, snapshot_hash)`,
`LifecycleReceipt(event_id, event_digest, applied, reason_code, snapshot_hash)`,
`LifecycleResult(snapshot, receipts, result_hash)` with derived `order_terminal` and fixed labels.
`LifecycleErrorReason` defines INPUT, IDENTITY, DUPLICATE, ORDERING, TRANSITION, ACCOUNTING, HASH;
`LifecycleValidationError(reason)` renders only the enum's fixed value.

- [ ] Write fixture builders `make_request(events=(), *, side=Side.BUY, quantity="1", cash="1000", position_quantity="0", average_price=None)`, `control(event_id, sequence, event)`, and `execution(event_id, sequence, quantity, *, price="100", fee="0.01", side=Side.BUY)`. Use a fixed UTC origin, `synthetic-account`, `SYNTH-USD`, and `synthetic-order`; never read files/accounts.
- [ ] Add failing tests. The missing boundary must reject mutable lists, floats, unsupported controls, mismatched identities, filled initial orders, and inconsistent position averages. Example:

```python
def test_request_rejects_mutable_event_collection():
    with pytest.raises(LifecycleValidationError):
        replace(make_request(), events=[])

def test_request_rejects_cross_account_position():
    request = make_request()
    with pytest.raises(LifecycleValidationError):
        replace(request, position=replace(request.position, account_id="other-synthetic"))
```

- [ ] Run `PYTHONPATH=src "$LIFECYCLE_PY" -m pytest tests/unit/simulation/test_lifecycle_models.py -q`; confirm missing module/feature, not a test typo.
- [ ] Implement exact-type checks before attribute access; rerun canonical record/cursor validation at this boundary. Check every monetary field with `require_bounded_decimal`; reject unsupported state/order/TIF/asset and inconsistent initial position/time/identity. Validate event timestamp against fill time. Convert known domain failures to fixed lifecycle errors with `from None`. Outputs validate fields and immutable tuple contents; labels are `field(init=False)` and terminal status is derived, not supplied.

```python
@dataclass(frozen=True, slots=True)
class LifecycleRequest:
    order: BrokerOrder
    position: Position
    cash: Decimal
    submitted: EventCursor
    events: tuple[LifecycleEvent, ...]

# Revalidate at replay entry; frozen Python records are not authenticated objects.
# Use type(value) is ExpectedType before any nested validation.
```

- [ ] Rerun the model tests, existing simulation validation tests, Ruff on owned files, and mypy on `src`.
- [ ] Commit only this task's files plus the approved spec/plan: `feat: add validated synthetic lifecycle records`.

## Task 2: Exact accounting and stable encoding

**Files:** Create `lifecycle_accounting.py`, `lifecycle_codec.py`, `test_lifecycle_accounting.py`; extend replay tests for codec contracts.

**Consumes:** Task 1 records and existing `apply_fill`, `content_hash`.
**Produces:** `apply_lifecycle_fill(snapshot, fill) -> FillAccounting`, where frozen `FillAccounting` contains `position`, `filled_quantity`, `remaining_quantity`, `cash`, `fees`;
`lifecycle_hash(kind: str, payload: object) -> DataHash` for validated internal payloads.

- [ ] Write failing BUY/SELL tests with literal amounts, zero/insufficient cash, overfill, shorting, limit violation, and nonterminating average. For a BUY of 0.25 at 100 with 0.01 fee from cash 1000: quantity=0.25, cash=974.99, fees=0.01, remaining=0.75. A SELL of 0.25 at 100 with 0.01 fee closes a starting 0.25 position and adds 24.99 cash.
- [ ] Run `PYTHONPATH=src "$LIFECYCLE_PY" -m pytest tests/unit/simulation/test_lifecycle_accounting.py -q`; confirm the feature is missing.
- [ ] Implement two fresh Decimal contexts, one exact and one allowing average rounding:

```python
context = Context(prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999,
                  Emax=999999, capitals=1, clamp=0)
for signal in context.traps:
    context.traps[signal] = signal in {
        InvalidOperation, DivisionByZero, Overflow, Underflow,
    }
context.traps[Inexact] = exact
context.clear_flags()
```

In the exact context compute filled/remainder, new position quantity, gross, signed cash delta,
new cash, fee sum, and mark value. Reject negative cash/quantity/remainder and mismatched
account/instrument/side/broker ID or limit violations. Call the unchanged helper under the
rounding context; compare its cash, fee, remaining, quantity and mark fields with the exact
results, then validate its average/position. Do not duplicate its weighted-average formula.

- [ ] Encode hashes using `content_hash({"namespace": "synthetic-order-lifecycle-v1", "kind": kind, "payload": payload})`; wrap known serialization/Decimal failures as HASH, without rendering inputs. Never include a hash field in its own preimage.
- [ ] Verify changed ambient precision/rounding/traps produce identical results, while inexact monetary operations are rejected. Confirm context flags outside the function are unchanged. Verify hashes distinguish kind/payload and canonicalize equivalent Decimal notation.
- [ ] Rerun owned tests plus `tests/unit/execution/test_partial_fills.py`, Ruff, and mypy; commit owned files as `feat: add checked synthetic fill accounting`.

## Task 3: Pure lifecycle replay

**Files:** Create `lifecycle.py`, `test_lifecycle.py`.

**Consumes:** Tasks 1-2 and canonical `transition(current, event)`.
**Produces:** `replay_order_lifecycle(request: LifecycleRequest) -> LifecycleResult`.

- [ ] Add failing end-to-end tests with literal outcomes. Core example:

```python
def test_complete_buy_is_terminal_but_not_flat_or_promotable():
    result = replay_order_lifecycle(make_request((
        control("accept", 1, OrderEvent.BROKER_ACCEPTED),
        execution("fill", 2, "1"),
    )))
    assert result.snapshot.order.state is OrderState.FILLED
    assert result.snapshot.position.quantity == Decimal("1")
    assert result.snapshot.cash == Decimal("899.99")
    assert result.order_terminal
    assert not result.evidence_promotable
```

- [ ] Run the replay test file and observe RED for the missing replay function.
- [ ] Implement initial snapshot/hash, private event/fill registries, and receipt list. For each event validate identity, hash full envelope plus initial digest, and check duplicates before cursor/state/remainder. Exact duplicate adds only a duplicate receipt; conflicting event or fill ID raises DUPLICATE.
- [ ] Reject stale/equal sequence or backward UTC time; fills require time strictly after submission. Derive FILL/PARTIAL_FILL from checked cumulative accounting. Run every control/fill transition through the canonical function. Update candidate immutable records only after validation; control events do not touch position/cash/fees. Fill events bind updated order/position data hashes to their computed event digest.
- [ ] Hash snapshots with initial digest, current records/balances/cursor, and applied-event digests; hash results with initial/final snapshot digests and ordered receipts. Return no result on failure. No runtime hooks or I/O.
- [ ] Add cancellation-race, rejection, expiration, empty/pending, terminal replay and duplicate assertions:

```python
assert replay_order_lifecycle(request) == replay_order_lifecycle(request)
assert duplicated.snapshot == original.snapshot
assert duplicated.result_hash != original.result_hash
assert duplicated.receipts[-1].reason_code == "duplicate_event"
```

- [ ] Run all lifecycle tests and existing simulation/state-machine tests; Ruff/mypy; commit only owned files as `feat: replay offline synthetic order lifecycles`.

## Task 4: Adversarial verification and truthful documentation

**Files:** Create `test_lifecycle_adversarial.py`; modify architecture, limitations, handoff, and this plan.

**Interfaces:** Frozen public lifecycle API from Tasks 1-3; no expansion.

- [ ] Write parameterized behavioral attacks for account/instrument/order/side/cursor/economic/source-hash changes. Reuse event IDs with changed payload, reuse fill IDs under new envelope IDs, and replay exact events after completion. Each mutation must either be a no-op exact duplicate or raise safely before any returned result.
- [ ] Test immutable request and prior successful result after a later failing replay; no registries survive between calls. Test malformed types, booleans, non-UTC times, unsafe Decimals, unsupported initial orders/events, and altered ambient contexts. Assert errors omit a synthetic sentinel string and suppress raw chained exception display.

```python
before = replay_order_lifecycle(valid_request)
with pytest.raises(LifecycleValidationError):
    replay_order_lifecycle(invalid_request)
assert replay_order_lifecycle(valid_request) == before
```

- [ ] Run new tests before any fix. For uncovered behavior follow RED/GREEN in the owning module, never weaken an assertion to fit an implementation.
- [ ] Update docs with the isolated synthetic capability, single-order LIMIT scope, exact-money precision bound and rounded average, mark-at-last-fill, no production wiring, and unchanged source/research/promotion/live blockers. Merge only our new paragraphs into preexisting dirty docs; do not revert their previous content.
- [ ] Run narrow tests followed by the full baseline:

```bash
PYTHONPATH=src "$LIFECYCLE_PY" -m pytest tests/unit/simulation tests/unit/execution tests/property/execution tests/replay tests/smoke -q
PYTHONPATH=src "$LIFECYCLE_PY" -m ruff check .
PYTHONPATH=src "$LIFECYCLE_PY" -m mypy src
PYTHONPATH=src "$LIFECYCLE_PY" -m pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80
PYTHONPATH=src "$LIFECYCLE_PY" -m bandit -c pyproject.toml -r src
uv lock --check --offline
```

Record dependency-index audit and remote CI as not run unless separately executed; do not
claim `make security` completed from Bandit alone. No package-index request is required by
this offline milestone. Do not run CLI paper/shadow/live commands or deployment checks.

- [ ] Review diff for hidden exposure, weakened guards, credential/logging risk, duplicate config, and false completion claims. Check `git diff --check` and exact path ownership. Commit clean task-owned files only; preserve dirty preexisting documentation unstaged if separating its prior hunks is unsafe.
- [ ] Record exact counts/results and remaining blockers here, then follow verification-before-completion and finishing-a-development-branch. Keep the local branch/worktree; the approved scope excludes pushing/merging/deploying.

## Self-review mapping

Spec sections 1-2/9 -> global constraints, file map, Task 4 docs; section 3 -> Task 1;
sections 4/6 -> Task 3; section 5 -> Task 2; section 7 -> Tasks 1-4;
section 8 -> all test steps. No external dependency is needed. Inline ownership and the
existing worktree are already selected, so no new delegation/workspace choice is required.

## Execution record

Pending. Mark steps only after observed verification; do not count synthetic runs as promotion evidence.
