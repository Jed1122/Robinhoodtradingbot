# SIM-FILL-FIXTURES-002: standalone fill primitive characterization

## Scope and disposition boundary

This review characterizes the standalone fill primitive at exact base revision
`93b28f484f1968f415d2d765a2d50143831ad3e4`. The subsystem is **partial and
promotion-blocked**: these deterministic synthetic checks establish only the existing branch and
single-fill accounting behavior of `FillModel.evaluate`. They do not change execution policy,
integrate the primitive into a strategy or runtime, demonstrate a complete simulated cycle, produce
eligible trading evidence, or authorize a promotion decision. No broker/provider call, credential,
account or production-ledger access, external dataset, or production payload was used.

The dependency chain exercised here is: synthetic `EventCursor` and `FillRequest` -> caller-owned
seeded `random.Random` -> `FillModel.evaluate` -> one `FillPlan` containing zero or one
`PlannedFill` -> existing `SimulatedCosts` arithmetic. The critical path to complete outcome
evidence remains outside this task: an event-timed order lifecycle -> remainder and cancellation
handling -> position/cash accounting -> deterministic exit ordering -> restart-safe outcome records
-> independently reviewed, identity-bound evidence.

## Characterized behavior

`tests/unit/simulation/test_fill_contract.py` uses probabilities of exactly zero or one for branch
checks, an interior probability for seeded-stream checks, fresh local requests, fixed seeds, and
literal independently hand-calculated expectations. It covers:

- denial when the market cursor is the submission cursor or an earlier cursor;
- closed-market precedence, forced rejection, forced no-fill, and zero-liquidity outcomes;
- a BUY capped by available liquidity, without halving that capped amount again even when the
  stochastic partial probability is one, and the forced stochastic partial-fill branch;
- a full SELL fill, covering the opposite slippage direction;
- exact fill quantity, execution price, commission-plus-percentage fee, rejection flag, and reason;
- equivalent-seed repeatability with a literal eight-outcome sequence and a distinct-seed control,
  using partial probability `0.5` after unrelated mutation of Python's module-global random state.
  The test restores that global state in `finally` to prevent cross-test interference.

The literal BUY expectations use ask `100`, `0.1%` adverse slippage, `0.2%` fee, and `0.01`
commission: price `100.100`; four-unit fee `0.810800`; five-unit fee `1.011000`. The SELL
expectation uses bid `99`: price `98.901` and ten-unit fee `1.988020`. The full BUY in the stream
check has ten-unit fee `2.012000`. Assertions do not call the cost helpers to derive these values.

Central review strengthened the Cloud return: the original forced-partial repeatability check could
not detect an ignored RNG argument and did not restore global state. The integrated test uses mixed
outcomes and explicit state restoration. No production fill or cost implementation changed.

## Unsupported input findings

The frozen dataclass interfaces do not validate several economically meaningful inputs. These are
findings, not approved semantics, and the tests deliberately do not encode them as correct behavior:

The snippets below use `import random`, `FillModel`, and the synthetic `make_request` builder from
the companion test module; they are not commands for a connected runtime.

1. A negative requested quantity is accepted by `FillRequest` and is later reported as
   `no_liquidity`, even when available quantity is positive:

   ```python
   request = make_request(quantity="-1", available_quantity="10")
   FillModel().evaluate(request, rng=random.Random(1)).reason_code  # "no_liquidity"
   ```

2. Probabilities outside `[0, 1]` are accepted. For example, a rejection probability of `2` forces
   rejection, while a negative rejection probability can never reject:

   ```python
   FillModel().evaluate(
       make_request(rejection_probability="2"), rng=random.Random(1)
   ).reason_code  # "simulated_rejection"
   FillModel().evaluate(
       make_request(rejection_probability="-1", fill_probability="0"),
       rng=random.Random(1),
   ).reason_code  # "no_fill"
   ```

3. Negative bid/ask values and negative cost fields are accepted and can produce negative prices or
   fees. There is no representable validation evidence on these frozen primitives.

Resolving these contracts requires a separately owned production-interface decision. This task
neither changes production code nor silently xfails or asserts the unsupported behavior as valid.

## Boundaries still missing

These primitive checks do **not** cover order remainders, repeated partial fills, cancel requests or
cancel races, order terminal-state completeness, position/cash conservation across multiple events,
stop/target/maximum-holding/regime-exit precedence, gap behavior, restart/replay idempotency,
calibration against an approved external source, comparison/runtime integration, or identity-bound
eligible promotion evidence. The primitive accepts a cursor sequence but models no elapsed latency.
Its one returned plan is not a complete order lifecycle.

All data and arithmetic assumptions in this review are synthetic characterization inputs only. They
do not select external data, establish realism, make a profitability claim, or satisfy any research,
paper, shadow, or live activation gate.

## Central integration verification

The primary reviewed the full two-file Cloud diff and independently checked the arithmetic against
the existing fill/cost implementation. The returned 10 tests plus two existing tests passed before
the review corrections above; the integrated file has 11 new tests. The combined market-data,
simulation, and paper-runtime integration selection then passed all 73 tests, and Ruff passed.
An isolated in-memory mutation replacing the supplied RNG with the module-global RNG failed the
strengthened stream assertion as intended; no source file was mutated for that negative control.
The real stream test also preserved module-global RNG state exactly.

Verification used the existing clean locked Python 3.12.13 environment with `PYTHONPATH=src` from
the implementation worktree. The CLI exposed the ready diff but not the Cloud-local commit or full
worker transcript; the results above are centrally observed checks. No authenticated test ran.
