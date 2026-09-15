# Research-data correctness implementation plan

> **For agentic workers:** use `superpowers:executing-plans` for the primary-owned work and
> `superpowers:test-driven-development` for the production correction. Independent, synthetic-only
> test contracts run in Codex Cloud as already requested by the operator.

**Goal:** correct point-in-time corporate-action filtering and independently exercise the existing
membership and simulated-fill primitives without manufacturing eligible research or trading evidence.

**Architecture:** retain the canonical domain objects, `adjust_bars`, `PointInTimeUniverse`, and
`FillModel` interfaces. The primary owns the production correction and final integration. Cloud
workers own only disjoint new test and review files. This is not a paper-runtime composition or a
release authorization.

**Tech stack:** Python 3.12–3.14, immutable domain dataclasses, exact `Decimal` values, Pytest, Ruff,
Mypy, Bandit, and the existing locked `uv` environment.

**Spec:** [strategy research](../../strategy-research.md),
[research gaps](../../reviews/research-gaps-001.md), and the effective-as-of adjustment requirement
in Task 2 of [the existing research implementation plan](2026-07-10-research-simulation-paper.md).

**Global constraints:** no broker calls, credentials, production-ledger access, deployment, live
controls, schema/config changes, provider adapters, strategy/risk decisions, or promotion relaxation.
Use synthetic fixtures only. Keep unrelated dirty and untracked files intact. The existing linked
implementation worktree already provides isolation; do not create a second worktree.

## Classification at the dispatch base and dependency chain

- Corporate-action adjustment: partial; the current function ignores instrument identity and can
  apply an announced action before its effective date. Its query time lacks the canonical UTC check.
- Point-in-time membership and simulated fills: implemented primitives with incomplete contract
  coverage, not complete research-data or execution-evidence systems.
- Accepted research and qualifying paper composition: blocked independently of these corrections.
- Live operation: blocked; no provider write adapter or live application is added by this work.

Critical path: correct primitive semantics -> verified data provenance and complete research
simulation -> accepted research identity -> paper composition and qualifying evidence -> elapsed
shadow evidence and the remaining explicit live gates. Only the first item is implemented here.
Cloud test work can run independently alongside the primary correction.

Base revision: `93b28f484f1968f415d2d765a2d50143831ad3e4` on
`codex/continue-implementation-from-commit-7c4dcd1`.

## Task 1: Reproduce and correct corporate-action filtering (primary)

**Files:**

- Modify `tests/unit/market_data/test_adjustments.py`.
- Modify `src/trading_bot/market_data/adjustments.py` only after observing regression failures.
- Modify `docs/strategy-research.md` to state the precise primitive contract and limitations.

- [x] Add real-function, hand-calculated regressions for both a 2-for-1 split and a cash dividend
  of 2. A raw bar has `(open, high, low, close, volume) = (100, 110, 90, 105, 1000)`.
  An unrelated instrument's action must leave these values unchanged. Before a known action's
  effective UTC date, these values must also remain unchanged. At its effective date, the split
  must yield `(50, 55, 45, 52.5, 2000)` and the dividend `(98, 108, 88, 103, 1000)`.
- [x] Add a mixed-instrument batch asserting each instrument receives only its own action, retain
  the announcement boundary coverage, and assert bars ending on or after effectivity remain raw.
- [x] Add rejection tests using `InvalidTimestamp` for naive and nonzero-offset `as_of` values,
  including empty input. Assert the canonical UTC input still accepts empty input.
- [x] Run the adjustment tests and inspect each failure to establish that it is a behavior defect,
  not import, fixture, or environment failure:

```shell
uv run pytest tests/unit/market_data/test_adjustments.py -q
```

- [x] Use the existing validator and add only the missing filters:

```python
as_of = require_utc(as_of)
available = tuple(
    action
    for action in actions
    if action.announced_at <= as_of and action.effective_date <= as_of.date()
)
# Inside the existing per-bar action loop:
if action.instrument_id != bar.instrument_id or action.effective_date <= bar.ends_at.date():
    continue
```

- [x] Rerun the same tests, then the market-data, simulation, and paper-runtime integration tests.
- [x] Document date-only effectivity as a UTC-date convention, not proof of exchange-session
  timestamps. Leave multi-action ordering, complete adjustment history, source provenance, and
  accepted evidence as separate unresolved requirements.

## Task 2: Point-in-time membership contract (Codex Cloud)

Owner: `PIT-FIXTURES-002`,
[Cloud task](https://chatgpt.com/codex/tasks/task_e_6aa949d2b85c832d9b4ce34a4d41524e).

Owned paths only:

- New `tests/unit/market_data/test_universe_contract.py`.
- New `docs/reviews/pit-fixtures-002.md`.

Read-only dependencies: `universe.py`, `recording.py`, canonical identifiers and clock, existing
universe tests, strategy research, and the research-gap review. The exact base SHA above is
mandatory. Public interfaces, production code, dependencies, config, and eligibility behavior are
frozen. No broker/provider access, external writes, secrets, deployment, risk decisions, or live
operations are permitted. No mocks, source-grep assertions, skips, or expected-failure masking.

- [x] Cover announcement/effectivity boundaries, late announcements, removal/reentry, independent
  instruments, distinct-time input permutations, sorting, empty and incomplete history, and
  repeatability with independently expected membership tuples.
- [x] Document conflicting equal-time events, invalid times, and missing provenance/coverage
  contracts without changing production behavior. A synthetic `history_complete=True` flag is
  not evidence of actual historical coverage.
- [x] Review the returned ready diff, stated base, regression meaning, and unresolved boundaries.
  **Return-contract limitation:** the CLI did not expose a Cloud-local commit or full worker
  transcript. Central review and reruns below replace reliance on unseen worker results.
- [x] Primary inspects every changed line and reruns:

```shell
uv run pytest tests/unit/market_data/test_universe.py tests/unit/market_data/test_universe_contract.py -q
uv run ruff check tests/unit/market_data/test_universe_contract.py
```

## Task 3: Simulated-fill primitive contract (Codex Cloud)

Owner: `SIM-FILL-FIXTURES-002`,
[Cloud task](https://chatgpt.com/codex/tasks/task_e_6aa949d36158832d8048af09453cb70d).

Owned paths only:

- New `tests/unit/simulation/test_fill_contract.py`.
- New `docs/reviews/sim-fill-fixtures-002.md`.

Read-only dependencies: fills, costs, events, canonical side enum, existing fill/cost tests,
strategy research, and the research-gap review. The exact base, frozen interfaces, prohibitions,
verification quality, and return contract are the same as Task 2. No pricing/exposure decisions.

- [x] Exercise deterministic probability-zero/one branches: same/earlier events, closed market,
  rejection, no fill, zero liquidity, liquidity caps, stochastic partials, and full fills.
- [x] Assert BUY/SELL prices and fees with independently hand-calculated Decimal literals.
- [x] Check seeded repeatability and independence from unrelated global random use.
- [x] Document missing remainder/cancel, exit precedence, restart, calibration, and evidence
  boundaries. Report invalid-input defects without silently approving them or changing production.
- [x] Primary inspects every changed line and reruns:

```shell
uv run pytest tests/unit/simulation/test_fills.py tests/unit/simulation/test_fill_contract.py -q
uv run ruff check tests/unit/simulation/test_fill_contract.py
```

## Task 4: Primary integration, verification, and handoff

- [x] Confirm Cloud changes are within their owned paths and use no production payloads.
- [x] Record accepted changes and deferred findings in the transition report. Preserve the existing
  local report update about the previous authorized broker check; do not rerun that check.
- [x] Run the required broad checks without weakening their selection or thresholds:

```shell
uv run ruff check .
uv run mypy src
uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80
uv run bandit -c pyproject.toml -r src
uv lock --check
```

The local project environment was not reused. Verification used the existing clean locked
Python 3.12.13 environment with `PYTHONPATH=src`. Focused tests ran from this worktree; the complete
suite ran from a secrets-free archive of staged tree `93a9b8a0e817aa9a56823f38c46f3cd623d23095`
to avoid slow Documents-worktree reads. All 3,545 tests passed with 85.57% coverage and one existing
Starlette warning. Ruff, strict mypy, Bandit, lock validation, locked-dependency audit, shell syntax,
and standalone Compose validation also passed. Report/plan result recording is documentation-only.

- [x] Review the complete diff for exposure changes, guardrail weakening, secret leaks, duplicate
  schemas, and overstated readiness. No new schema, capability, risk/config changes, broker call,
  production-ledger access, deployment, or live activation was introduced.

After this pre-commit checklist snapshot, commit only this work and the prior owned report update,
push to the existing integration branch and PR, and verify fresh CI for that exact commit. Record
the commit and post-push CI results in the task handoff without implying a production deployment.
The handoff must distinguish primitive correctness/coverage from accepted research, qualifying
elapsed evidence, a live release, or permission to place orders.
