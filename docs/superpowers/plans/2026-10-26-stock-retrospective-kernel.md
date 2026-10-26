# Distinct retrospective stock portfolio boundary

## Goal and scope

Connect source-bound stock observations to the existing account, tax-lot,
dividend, expense and execution simulator. Reuse one ledger and keep the public
fictional interfaces and literal evidence hashes compatible. This increment uses
fictional test originals. Actual financial comparisons require a later frozen
source, code and experiment registration.

The input profile is a named conditional retrospective reference. Missing sector,
market-cap, earnings-risk, spread, historical tradability and lifecycle evidence
remains explicit. All 56 fully constrained stock/family cases and eight
long-term quality slots remain represented and unavailable. Accepted annual
evidence supplements the original preparation without rewriting it. AXP annual
coverage cannot imply coverage of the other seven issuers.

## Implementation ownership

One engine worker owns two new research modules:
`stock_retrospective_replay_inputs.py` and `stock_retrospective_replay.py`, and
three new tests for inputs, policy context and replay. The same worker makes
narrow shared-core changes in `stock_economic_replay.py`,
`stock_economic_policies.py` and `hybrid_policies.py`. Root owns documentation,
integration, commits, actual invocations and final acceptance. Independent review
follows the implementation. Existing tests, monetary admission, annual
measurement, calendar schedules, cost and dividend-book implementations remain
unchanged unless a concrete dependency blocker receives a reviewed scope change.

Use a separate worktree based on `79dfb581e2fcfc1b3147439f5ea116794b64d47c` so the
calendar regression can finish against immutable source.

## Shared architecture

- Revalidate complete retained observations at source preparation, begin,
  explicit resume and final boundaries. Compile one local immutable panel for
  independent registered cases. No public trusted flag, global identity cache
  or serialized active-cache admission is allowed.
- Keep raw accounting bars, split signal bars and exact native integer volume
  separate, binding each symbol/index/date/value to its original source. The
  currently admitted equal-unit profile does not implement split conversion.
- Retrospective assets have no scripted signals, fabricated sector, earnings
  clearance or synthetic provider-availability timestamp. Label the conservative
  date-only membership proxy and retain original current receipt clocks.
- Use completed prior-close history for the frozen price and liquidity screens:
  minimum price USD10 and a 20-session mean close-times-native-volume proxy of
  USD20million. Label the dollar-volume proxy and account-currency assumption;
  never use the uncompleted entry session's volume.
- Extract private account/session accessors and shared planning/execution cores.
  The old public fictional wrappers keep exact type gates and output preimages.
  Actual observations never instantiate fictional input or asset classes.
- Build each policy prefix and filled holdings from its own account. Reuse the
  existing quantitative rules, latest annual selection and unavailable behavior.
  A narrow private validated policy context avoids reparsing complete annual
  originals at every close; the public evaluator retains fresh validation.
- Preserve company/sleeve/cash/risk limits, overlap, cooldown, sticky suspensions,
  actual modeled fills, tax basis and owned exit-rung/cost history. A conditional
  omitted screen never becomes production risk approval. Unknown sectors cannot
  silently become an invented shared sector.
- Use the accepted finite schedule's compact date commitments. Padding locates
  claims only; price count bounds all decisions, executions and return marks.
- Keep an inert checkpoint. Resume uses freshly validated originals and
  deterministic consumed-prefix reconstruction through the same core before
  accepting its full projection. Final likewise checks fresh source identities.

## Test-driven increments

A measured validation bottleneck justifies the separate
[owned validation transaction increment](2026-10-26-stock-replay-validation-transaction.md).
That plan permits narrow private book/cost extraction after the current
correctness fixes are accepted; it preserves public freshness and ledger math.

- [x] Input views: source/clock/unused-byte mutation, raw/split/volume/calendar
  alignment, explicit unknowns, no cross-profile admission and complete missing
  case inventories.
- [x] Policy context: measure public annual source work, then verify private
  per-step source-work bounds, identical old hashes, AXP-only coverage, latest
  unavailable, ties and future evidence restrictions.
- [x] Shared replay: exact old compatibility, independent stock-family cases,
  all three profit methods, fill/basis/tax/cash conservation, explicit expense
  plans, repeated signals, held-state unknowns and no padded executions.
- [x] Recovery and work: altered ledger/risk/prefix/lookup rejection, unchanged
  uninterrupted versus resumed state, continuous cutoff carry and source parser
  counts tied to owning boundaries rather than session or case count.
- [x] Run relevant new and unchanged tests on Python 3.12 and 3.14, architecture
  and configured static checks, then independently review the frozen increment.

The final scoped suite passed 417 tests on each Python version, with the existing
long horizon test deliberately reserved for the combined regression. Architecture
passed 168 tests. Whole-repository Ruff, mypy over 477 source files and configured
Bandit passed. Independent review corrected metadata/calendar binding and
Decimal-context findings, then separately accepted the validation transaction.
All tests in this implementation slice use fictional observations; actual
financial comparisons remain a separate registered experiment.

Live trading stays disabled. No account, credential, provider, deployment or
real-money action belongs to this implementation. Full source qualification,
long-term stock selection, remaining family evidence, exit/benchmark controls,
actual outcome execution and statistical evaluation remain required later work.
