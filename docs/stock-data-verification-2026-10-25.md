# Stock-data qualification verification — October 25, 2026

The first stock-study input stage is complete for the declared retrospective
price-only use. It delivers executable source checks and an authentic,
independently reconstructed historical stock-cohort handoff. It does not qualify
total-return economics, a strategy for capital or live execution.

## Implemented behavior

- Original-content-bound raw/split parsing and exact rational adjustment checks.
- Calendar/session admission, completed-bar checks and seven dimensionless daily
  features. Missing native interpolation markers remain unknown; positive-volume
  inference is separately documented.
- Dossier source/observation freshness, missingness, quarantine and receipt-origin
  diagnostics. Opt-in `--data-quality` reports add schema 4; default report bytes
  independently match the previous compiler on the preserved archive.
- Historical listing parsing, conflicting-identity diagnostics and reproducible
  panel selection with complete rejection denominators and no replacement.
- Exact Decimal corporate-action parsing, unsupported-group rejection and
  explicit unknown currency/completeness/publication states.

No broker writer, authentication scope, risk configuration, scheduled worker or
deployed release changed. No account values, orders, credentials or subscriptions
were requested or modified for this increment.

## Actual source evidence

The [source matrix](stock-data-qualification.md) distinguishes actual retained
data from fixtures. The historical-listing probe remains a negative result:
10,580 rows include 64 duplicate ticker groups and 65 extra rows; later ticker
aliases and an inactive-instrument denial prevent a completed twelve-slot study.
All failed and unattempted slots remain visible.

A separate [primary-source contract](stock-first-study-inputs.md) supplies eight
original disclosed common-stock groups from a pre-existing SEC filing, with SPY
as benchmark. All 138 original rendered table rows and 41 CUSIP/class groups were
independently reconstructed. Tool-rendered official-source text is retained;
the direct XML denial is preserved, with no XML/HTTP-wire claim.

The accepted handoff contains nine raw/split pairs and a 706-session calendar:
6,354 raw and 6,354 split rows. Original requests, hashes, receipts and native
unknowns remain bound. All 63 feature values were independently checked with exact
rational arithmetic and a separate 90-digit calculation within a predeclared
rounding bound. All nine admission and feature evidence hashes were reproduced.

All 706 observations supply history; 31 pre-disclosure sessions serve only as
warm-up, leaving 675 post-disclosure decision dates. The first complete
200-session prefix closes October 16, 2024; the next execution session is
October 17. Training has 438 history sessions, 407 post-disclosure dates and 239
possible complete-prefix decision closes; the holdout has 268 sessions.
No strategy signals or performance were simulated.

Independent review caught the initial binder's unnecessary exclusion of
pre-disclosure warm-up prices. That artifact is preserved; corrected v3 separates
history from decision eligibility. Original input bindings, nine evidence hashes
and 63 numerical checks stayed unchanged. The corrected binder and independent
verifier both actually exited zero with terminal receipts.

Event/source checks preserve 25 unequal closes among 1,323 overlaps, 11 unequal
dividend comparisons among 100, and two weekly-only events. No tolerance was
fitted and no value/date was repaired. The whole action response correctly fails
the strict parser because it contains two unsupported stock-merger rows. Cash-row
CUSIP corroboration is separate from action-book admission.

## Local verification

The full default stock-bot/shared-safety regression actually terminated with
**12,420 passed, 36 warnings, exit 0**. Its 1,254-file inventory was byte-identical
before and after. Combined coverage was **91.55%**; the existing critical-branch
gate passed against that exact coverage file. No selected test skipped or failed.
Existing configuration excludes authenticated tests and retired legacy ETF/options
strategy/native-data suites; exclusions are not reported as new passing tests.

All **228 new critical tests** passed. A later Ruff-only formatting correction was
followed by the same 228 passing tests. Initial CI then caught a test expectation
that differs by Python version: `dataclasses.replace` rejects `init=False` fields with `ValueError`
on Python 3.12 and `TypeError` on newer versions. Both prevent promotion. The test
now accepts those two rejection types and explicitly verifies the original safety
flag remains false. All 228 tests subsequently passed on Python 3.12 and 3.14.
Application source did not change after the full run.

Ruff lint, changed-file formatting, strict mypy across 462 source modules and
Bandit on changed modules passed. Remote CI for the final commit is recorded
separately; this record does not invent that result.

The 36 warnings comprise SQLite resource warnings and a Starlette test-client
deprecation warning. They remain disclosed. Local checks establish software
behavior, not economic merit, continuous operation or deployment success.

## Evidence identities and remaining limits

Private data remains excluded from Git under
`.superpowers/sdd/2026-10-25-task4-data/` in the Task 4 worktree.

| Artifact | SHA-256 |
| --- | --- |
| Full regression `integrated-regression-20261026/result.json` | `4866ec26b912300f5b628eb3d3e43747c6bb5946503b57b668f498f70a2fd5ba` |
| Handoff `primary-common-actual-inputs-20261026/corrected-v3-run/manifest.json` | `07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3` |
| Independent corrected-handoff acceptance | `78de84b9b52a6a2c494c8b0e92d969ee0b250407573a15a2faf12f9cbab9e1f7` |
| Corrected restored-archive quality report | `f5ecb9388ffaa4c260d2cffe4681ebd6e4698e6e9f78a270276e28b192237e4a` |

Native bar currency stays unknown. Current AXP/USD context cannot fill other
instruments or historical observations. Unavailable overview/search routes,
financial comparisons, exact source vintages, complete action books, total-return
and after-tax cash wealth remain restricted where evidence is missing. No current
financial data enters past decisions. The first ablation cannot promote a
strategy or authorize capital even if its price-only result looks favorable.

Next, Task 5 implements and evaluates the frozen stock policy against passive
comparisons and costs, reports uncertainty/insufficient evidence, and resolves
data needed for broader economic claims. Preserve the final holdout and failed
source evidence. Live trading remains disabled; activation and deployment require
their own verified scope and user control.
