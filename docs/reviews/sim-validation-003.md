# SIM-VALIDATION-003 review

## Scope and repository identity

- **Objective:** add independent, synthetic-only boundary contract tests for fill and cost
  inputs; production implementation remains owned by the primary orchestrator.
- **Owner:** isolated Cloud task `SIM-VALIDATION-003`.
- **Base revision:** `095e5c02b01aea95fd7858a549a7765e7b0488c0` (verified by
  `git rev-parse HEAD` before edits). The isolated checkout was clean and already at the exact
  requested revision; its local branch name was `work`. No integration branch was checked out or
  modified.
- **Owned paths:**
  `tests/unit/simulation/test_input_validation_contract.py` and this review only.
- **Read-only dependencies inspected:** `AGENTS.md`, `Codex.md`,
  `docs/strategy-research.md`, `src/trading_bot/simulation/{fills,costs,events}.py`,
  `src/trading_bot/domain/decimal_utils.py`, `src/trading_bot/clock.py`, and existing simulation
  tests.
- **Subsystem classification:** input validation for synthetic simulation fills and costs is
  **partial**. Existing valid deterministic arithmetic and ordering behavior is implemented, but
  the public constructors and direct cost helpers are permissive at this base.

## Dependency chain and critical path

The contract fixes the interfaces in this order:

1. shared `DomainValidationError` and bounded exact-`Decimal` validation;
2. `SimulatedCosts` construction;
3. `FillRequest` construction, including cursor, side, quote, probability, and market-state
   invariants;
4. direct `execution_price` and `execution_fee` validation;
5. `FillModel.evaluate` preserving deterministic outcomes after validated construction.

The critical path is primary-owned production validation in the constructors and helpers, followed
by rerunning this contract. Constructor rejection must happen before an invalid request can reach
random draws. No API signature, configuration schema, economic threshold, timestamp/latency policy,
or production implementation was changed by this task.

## Contract coverage

The test matrix requires `trading_bot.clock.DomainValidationError` (a `ValueError` subclass) without
depending on error text. It covers:

- non-`Decimal`, nonfinite, and existing-bound-exceeding numeric values for every numeric request
  field and every cost amount;
- nonpositive quantity, negative availability and costs, nonpositive or crossed quotes, and each
  independent probability below zero or above one;
- nonexact `Side`, nonexact `bool`, non-`EventCursor` cursors, and non-`SimulatedCosts` costs;
- invalid direct-helper side, quote, quantity, price, and costs inputs;
- positive execution-price enforcement for SELL slippage of 100% and 101%, without establishing an
  arbitrary maximum for slippage or fees;
- constructor rejection before invalid inputs can reach evaluation (the worker's unrelated-RNG
  assertion was removed during central review, as detailed below);
- valid zero availability, zero costs, equal quotes, probability endpoints, same/earlier sequence
  behavior, timestamp-order neutrality, and literal exact arithmetic.

No probabilities are required to sum to one. No mock, skip, xfail, source-text assertion, secret,
account data, external service, broker call, ledger access, deployment, or live control is used.

## Verification evidence

Commands were run from `/workspace/Robinhoodtradingbot` against the exact base plus only the two
owned uncommitted files:

1. `uv run pytest tests/unit/simulation/test_input_validation_contract.py -q`
   - **Expected red:** exit 1; **111 collected, 5 passed, 106 failed**.
   - The five valid-boundary/compatibility cases pass.
   - The failures are intended evidence of the permissive base: invalid constructors either do not
     raise, while some direct helpers leak `TypeError`, `AttributeError`, or
     `decimal.InvalidOperation` instead of the required `DomainValidationError`. The SELL 100% and
     101% slippage cases also return zero/negative prices instead of rejecting them.
   - These failures were not hidden or weakened because the task explicitly requires red TDD
     evidence before the primary-owned implementation.
2. `uv run ruff check tests/unit/simulation/test_input_validation_contract.py`
   - Exit 0; **all checks passed (0 errors)**.
3. `uv run pytest tests/unit/simulation/test_fills.py tests/unit/simulation/test_fill_contract.py -q`
   - Exit 0; **13 passed, 0 failed**.

## Original Cloud disposition at frozen base (historical)

- The existing `require_bounded_decimal` limits define malformed/unbounded decimal policy; the tests
  intentionally introduce no replacement limit.
- An equal positive bid and ask is valid. Zero availability is valid and remains `no_liquidity`.
  Zero cost components and independent probability endpoints are valid.
- Market sequence, not timestamp order, continues to govern the existing same-event rule.
- Production implementation must validate each public entry point independently rather than relying
  on callers to construct a `FillRequest` first.
- At the frozen base, primary diff inspection, separate production implementation, and focused
  and broad reruns were still required. That test-only result was not a release or operational
  readiness decision; the later central integration is recorded below.

**Original disposition: READY_FOR_INTEGRATION** as expected-red test-only TDD evidence. Production
validation was incomplete at that base and remained primary-owned.

## Central integration (2026-09-16)

The primary inspected the complete two-file Cloud diff and reproduced the original contract's
**106 failures and 5 passes** within a combined Cloud run against a secrets-free archive of the
exact `095e5c0` base. The original Cloud contracts together produced **140 failures and 8 passes** on that
base, then **148 passes** against the primary-owned validation patch.

Central review removed the redundant untouched-RNG assertions: those tests call only the request
constructor, so an unrelated RNG instance cannot establish model behavior. They now assert
constructor rejection directly. The zero-liquidity test name likewise describes its actual
outcome assertion. Formatting was normalized; the original 111-test contract's numeric expectations
were retained. A second review added 25 cases: small out-of-bounds Decimals independent of quote
crossing/probability caps, exact Decimal subclasses, and cursor/cost subclasses. The integrated
Cloud-owned file now has 136 cases. Existing mixed-outcome seed and distinct-seed tests remain the model-level RNG
checks. Separate primary tests cover bounded price/fee results and arithmetic overflow with
traps enabled and disabled. No cost formula or valid fill outcome changed.

Full repository verification is recorded in the orchestration report. Input validation is not
calibration, a complete simulation lifecycle, qualifying outcomes, or live readiness.
