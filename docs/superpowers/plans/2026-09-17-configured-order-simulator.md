# Configured Order Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The operator selected inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate deterministic, accounting-consistent synthetic single-order lifecycles from canonical execution assumptions and explicit market events.

**Architecture:** Validate immutable inputs before scheduling. Select outcomes through event-keyed random streams and existing cost helpers, then replay every generated prefix through the existing lifecycle accounting authority. Keep all results synthetic and non-promotable.

**Tech Stack:** Python 3.12+, stdlib dataclasses/Decimal/Fraction/random, canonical Pydantic settings, pytest, Ruff, mypy, Bandit, uv.

**Spec:** [Approved configured simulator design](../specs/2026-09-17-configured-order-simulator-design.md).

## Global Constraints

- Authorized new spending is $0; no network, credentials, broker, production ledger, deployment, or live actions.
- Single equity/crypto LIMIT order only, GFD/GTC, long-only, synthetic fixtures.
- Canonical configuration, safety envelope, legacy fill/lifecycle interfaces, and production composition stay unchanged.
- Reject inexact money/quantity arithmetic under the lifecycle's precision-28 context.
- Both evidence flags must be false; output labels are fixed synthetic/non-promotable.
- Preserve unrelated dirty files. Primary owns every implementation and review.
- Existing linked worktree: `worktrees/robinhood-system-implementation`; branch `codex/continue-implementation-from-commit-7c4dcd1`; base `573c96bca79e0687d5e5c59869aa8b0d9518aab8`.

## File ownership and verification commands

New production files:

- `simulation/configured_models.py`: input records, safe errors, canonical settings copy.
- `simulation/configured_validation.py`: whole-stream validation and duplicate indexing.
- `simulation/configured_codec.py`: safe domain-separated hashes and keyed RNG.
- `simulation/configured_fills.py`: categorical selection, partial size, existing cost helpers.
- `simulation/configured_results.py`: immutable audit/result records and reason enums.
- `simulation/configured.py`: private virtual scheduler and public pure API.

All production paths are under `src/trading_bot/`. Tests and synthetic fixtures live under
`tests/unit/simulation/`. Update architecture, limitations, handoff, spec status, and this
plan only as relevant; do not commit pre-existing mixed dirty files wholesale.

Use the existing locked interpreter (editable installation points at another checkout):

```sh
PYTHONPATH=src /private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python -m pytest tests/unit/simulation -q
PYTHONPATH=src /private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python -m ruff check .
PYTHONPATH=src /private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python -m mypy src
PYTHONPATH=src /private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python -m pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80 -q
PYTHONPATH=src /private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/python -m bandit -c pyproject.toml -r src
uv lock --check --offline
```

Baseline and each task's verification results belong in the execution record below.
Package-index dependency audit remains unrun in this offline milestone, not a security pass.

## Task 1: Validated synthetic request and stream identity

**Files:** Create `configured_models.py`, `configured_validation.py`, `configured_codec.py`,
`tests/unit/simulation/_configured_fixtures.py`, `test_configured_models.py`.

**Interfaces:**

- Consume canonical `LifecycleRequest`, `Quote`, `MarketClock`, `SimulationSettings`, `CostSettings`.
- Produce `SyntheticBarWindow(starts_at, ends_at)`, `SyntheticMarketEvent(event_id, cursor, window, quote, clock, available_quantity)`, `SyntheticCancelRequest(event_id, cursor)`.
- Produce `ConfiguredOrderRequest(initial, simulation, costs, seed, submission_window, events, end_at, expires_at=None)`.
- `validate_stream(request) -> tuple[IndexedEvent, ...]`; each indexed unique event has its digest, delivery index, and duplicate indices.
- `configured_hash(kind: str, payload: object) -> DataHash`; `keyed_rng(base: DataHash, event: DataHash, purpose: str) -> random.Random`.

- [ ] Write input contract tests before new modules. Catch unsafe flags, forged nested types,
  nonempty initial scripts, invalid times/windows/source, identity mismatch, sequence reversal,
  duplicate conflicts, multiple distinct cancels, and early cancellation. Reuse existing
  `_lifecycle_fixtures.make_request`; keep all identities synthetic.

```python
def test_boolean_seed_is_rejected():
    with pytest.raises(ConfiguredValidationError):
        replace(request(), seed=True)

def test_duplicate_does_not_create_another_unique_opportunity():
    event = market("one", 1, 1000)
    indexed = validate_stream(request(events=(event, event)))
    assert len(indexed) == 1
    assert indexed[0].duplicate_indices == (1,)
```

- [ ] Run the new model tests and record the expected missing-module failure.
- [ ] Implement exact-type frozen records and safe validation wrappers. Use
  `localcontext(_context(exact=True))` around settings validation and arithmetic;
  `SimulationSettings.model_validate(settings.model_dump())` creates the private copy.
  Revalidate nested records and bound every numeric field before content hashing.

```python
seen: dict[str, DataHash] = {}
for index, event in enumerate(request.events):
    digest = configured_hash("input_event", event)
    prior = seen.get(event.event_id)
    if prior is not None:
        if prior != digest:
            deny(ConfiguredErrorReason.DUPLICATE)
        # Attach delivery index to the original event; no second scheduler entry.
        continue
    seen[event.event_id] = digest
```

- [ ] Validate unique ordering/windows and acknowledgement/expiry bounds before any draw.
  Generate no external actions; hashing errors use value-free reasons.
- [ ] Run model tests, legacy simulation tests, targeted Ruff and mypy. Commit only new
  modules/tests and approved spec/plan updates after green checks.

## Task 2: Seeded outcomes and cost adaptation

**Files:** Create `configured_fills.py`, `test_configured_fills.py`.

**Interfaces:** Consume Task 1 keyed RNG and canonical settings. Produce
`chance(percent: Decimal, rng: random.Random) -> bool`,
`select_outcome(settings, rng) -> SimulatedOutcome`,
`partial_percentage(settings, rng) -> Decimal`,
`costs_for(asset_class, settings) -> SimulatedCosts`, and
`plan_fill(request, event, remaining, base_hash, event_hash) -> ConfiguredFillPlan`.
`ConfiguredFillPlan` contains outcome, percentage, and optional existing `PlannedFill`.

- [ ] Write boundary tests against a test-only fixed-bit RNG, plus real seeded replay tests.
  Catch wrong normalization, inclusive-boundary mistakes, fixed-half partials, liquidity
  overfill, incorrect fee mapping, and ambient-context dependence.

```python
def test_crypto_costs_charge_fee_on_slipped_price():
    costs = costs_for(AssetClass.CRYPTO, cost_settings())
    price = execution_price(side=Side.BUY, bid=D("98"), ask=D("99"), costs=costs)
    assert price == D("99.2475")
    assert execution_fee(D("1"), price, costs) == D("0.4962375")
```

- [ ] Run new fill tests and record missing implementation failure.
- [ ] Implement exact `Fraction(rng.getrandbits(53), 2**53)` comparisons; accepted outcome
  intervals are N/(100-R), then (N+F)/(100-R), then partial. R=100 never enters this path.

```python
percentage = minimum + (maximum - minimum) * Decimal(rng.randrange(10001)) / Decimal(10000)
target = remaining if outcome is SimulatedOutcome.FULL else remaining * percentage / Decimal(100)
quantity = min(target, event.available_quantity)
```

- [ ] Reuse existing price/fee helpers under fixed exact context. No spread duplication,
  stress simulation, price clamping, affordability resizing, or legacy FillModel changes.
- [ ] Run new/legacy fill tests, Ruff and mypy; commit the green isolated adapter.

## Task 3: Virtual scheduler, lifecycle composition, and auditable results

**Files:** Create `configured_results.py`, `configured.py`, `test_configured.py`,
`test_configured_adversarial.py`; update architecture, limitations, handoff, and plan.

**Interfaces:** Consume Tasks 1-2 and `replay_order_lifecycle`. Produce
`simulate_configured_order(request: ConfiguredOrderRequest) -> ConfiguredOrderResult`.
Result carries lifecycle, generated events, decisions, settings/input/result hashes,
fixed source kind and false evidence/assumptions flags. Audit decisions retain source
digest/ID, time, reason, nominal/realized outcome, percentage, emitted IDs, snapshot hash,
delivery index, and original decision reference for duplicates.

- [ ] Write tests proving ack latency, no same-bar fills, all session guards, BUY/SELL
  limits, partial/full accounting, no-fill, nonterminal horizon, GFD expiry, race allowance
  0/100, first eligible no-fill consumption, and deterministic tie priority.

```python
def test_cancel_acknowledgement_wins_at_equal_timestamp():
    result = simulate_configured_order(request(events=(cancel("cancel", 1, 1000), market("quote", 2, 1500))))
    assert result.lifecycle.snapshot.order.state is OrderState.CANCELED
    assert result.lifecycle.snapshot.order.filled_quantity == D("0")
```

- [ ] Run scheduler tests and record missing implementation failure.
- [ ] Schedule using `(UTC time, priority, input sequence)`; priorities are expiry=0,
  submission ack=1, cancel request=2, cancel ack=3, market=4. Filter generated actions by
  horizon. Assign consecutive lifecycle cursors only to emitted events.

```python
candidate = (*generated, event)
lifecycle = replay_order_lifecycle(replace(request.initial, events=candidate))
generated = candidate  # publish only after authoritative replay succeeds
```

- [ ] Implement ordered guards and one pending-cancel allowance. No outcome draw on failed
  guards; consume allowance on first fully eligible opportunity even if no-fill. Terminal
  control events become audit-only no-ops; no reopening or synthetic forced completion.
- [ ] Add adversarial tests for duplicate/conflict identity, future-suffix causality,
  context/trap preservation, safe error wrapping, all output labels, no external side effects,
  generated script replay equivalence, and input/result hash binding. Observe a red test
  before each additional guard or error-path implementation.
- [ ] Run all simulation tests, Ruff, mypy, full branch-coverage suite, Bandit, offline lock
  check. Perform focused in-memory mutation checks on timing/session/duplicate/limit guards.
- [ ] Update docs with actual implemented boundaries and remaining strategy/research/live
  blockers; preserve older dirty hunks. Self-review all new code against spec sections 1-9.
- [ ] Commit verified task-owned files locally. No push, merge, deployment, or broker action.

## Execution record

Pending execution. Tasks above map to spec sections 3-4/7 (Task 1), 5 (Task 2),
and 6-9 (Task 3). No spec requirements are intentionally deferred within this milestone.
