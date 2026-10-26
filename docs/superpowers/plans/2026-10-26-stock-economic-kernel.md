# Stock economic kernel and annual measurement increment

This continues the full Task 5 evaluation under the approved lean operations
scope. It adds executable accounting and financial-measurement building blocks;
it does not complete the actual monetary study or qualify a strategy.

Base code `70a87163327d1582e41d417016776a27c3198103` is integrated by PR 57 as
`dd704f8db3d3926dfea9183c9323ee445b085112`. Its 12,896-test CI result is historical
baseline evidence and does not include either new module below.

## Economic session kernel

- [x] Implement a pure, paused $1,000 session kernel around the existing account,
  fill/settlement arithmetic, exit proposals and dividend book. Support stock
  candidates, preselected long-term stocks and optional passive comparisons.
- [x] Queue close decisions for next-open modeled execution, preserve reservations,
  lot/tax history, settlement claims, ex-date rights and separate dividend-funding
  support. Apply sizing, reserve, concentration, cooldown and sticky-loss rules.
- [x] Implement the three profit models and two named controls. Resume partial
  rungs without exceeding their owned history; principal resumption additionally
  respects the current known-close surplus. Future opening gaps remain possible.
- [x] Reproduce and correct the independent review's four initial findings and
  the subsequent principal-surplus counterexample before integration.
- [x] Verify 52 fictional cases on Python 3.12/3.14, architecture and static checks;
  independently accept 71 checks on each version at source `c3796445`.

See [the kernel guide](../../stock-economic-replay.md). Actual provider admission,
seven-family selection, quality selection, complete rebalance/volatility/expense
orchestration and economic/statistical evaluation remain separate work.

## Annual financial measurement bundle

- [x] Bind original filing ID/entity, complete native source hashes/clocks,
  empty dimensions, USD units, annual durations and year-end instants without
  manufacturing an annual start for balance-sheet facts.
- [x] Implement the explicitly AXP-only as-reported financing method, typed
  defined/unavailable results, retrospective filing-date proxy and revalidation.
  Keep unavailable components absent and every qualification flag false.
- [x] Correct the independent review's quadratic full-batch hashing defect using
  invocation-local validated hashes. Preserve every reference and fresh tamper
  detection on subsequent revalidation.
- [x] Verify 56 fictional cases on Python 3.12/3.14 and 185 architecture cases on
  each; static checks pass. Independent operation-count and correctness probes
  accept source `7da566da` with no remaining findings.

See [the annual measurement guide](../../stock-annual-quality.md). Legacy
`SourceFact` and policy consumers remain unchanged. No actual financial factor
or strategy outcome was calculated by this increment.

## Root integration

- [x] Independently review both source/test pairs and preserve counterexamples,
  corrections and acceptance reports. Root's combined related selection passed
  432 tests; repository Ruff, mypy (471 source files) and expanded Bandit passed.
  Existing Bandit annotation warnings remain recorded.
- [x] Commit frozen reviewed sources and run the complete retained stock/shared
  suite with the unchanged 80% aggregate, critical-branch and stock-host gates.
- [x] Verify exact-source CI on Python 3.12/3.13/3.14, preserve terminal results and
  integrate the reviewed change. Do not substitute the earlier PR 57 result.

Source `3fc413b14576bacfbb1fc664af4629abeba3b46f` passed 13,004 tests locally
and on each CI Python version. All six CI jobs and unchanged coverage gates
passed; combined CI coverage was 91.96%, 91.96% and 91.71%. Warnings were 1, 36
and 36, with no failures or skips. PR 58 merged as
`e1d080a44260f91474c87d9afcc4265fc3f7f163`; an independent Git API read verified
the merge parents and the exact reviewed/CI tree
`12d67ee71411ab5a5443a430dde3fcd7e17cf29a`.

A separate frozen actual-source feature run produced three AXP annual rows.
Independent arithmetic from original JSON passed 1,338 checks, including all 21
raw references and nine Fraction/Decimal90 ratio comparisons. The maximum
normalized error was below the preregistered 1e-47 tolerance. Actual collection
clocks and the retrospective filing-date proxy remain distinct. This acceptance
covers financial measurements only; no portfolio return or strategy was qualified.

Next: wire the typed annual consumer without changing empty-input legacy evidence,
freeze purpose-specific actual source admission and protocols, then perform the
actual portfolio/family/exit/reinvestment comparisons and full statistical audit.
The late historical period remains reused development data. Missing required
comparisons remain incomplete. Deployment and live activation stay separate;
no mandatory prospective paper waiting period is introduced.
