# Current stock bot test scope

The operator requested removal of legacy ETF/options tests and testing only the
current individual-stock bot going forward. This supersedes the old whole-repository
test denominator. It does not authorize trading or removal of shared safety controls.

## Current boundary

Keep the stock research collector, source/filing parsers, worker and controls,
OAuth/MCP integration, scheduler, release producer/probe/lifecycle, stock dashboard,
hybrid portfolio/accounting/exits/backtesting, and reusable equity execution, risk,
authorization, reconciliation, persistence, monitoring and security tests. Keep
passive benchmark comparisons and tests rejecting unsupported assets.

Retire the separate ETF strategy/study/forward-pilot and options strategy/pricing/
native-data/expiry/monitor suites, their exclusive helpers/fixtures and options CI.
Also retire unrelated positive crypto/prediction suites and legacy native Databento
pipeline tests outside this stock bot. Preserve shared migration/schema integrity
checks even where legacy ORM types are still registered. Production legacy code is
not deleted or advertised as verified by the stock suite.

Use filename selection only as an audited retirement manifest, not an execution
filter hiding files. The core manifest is all test_*.py files with etf/options in
the filename, except the unsupported-options capability denial check, plus the
legacy capital profile/intake tests. Rename that retained denial test to an
asset-neutral name. Remove the legacy ETF cost-observer case from the mixed
execution service test while retaining the other durable execution checks.

TrialEpisode/TrialLossState are reused by equity accounting. Move these unchanged
asset-neutral types to risk/trial_losses.py, retain their former import aliases,
update the equity projection import and preserve loss-budget/finality tests under
an asset-neutral test name. No arithmetic, fields, identity semantics or risk
configuration changes are allowed.

## Verification contract

- Plain pytest and pytest tests collect only the retained stock/shared suite.
- CI uses the same suite, without installing/appending old options research tests.
- Measure entire retained stock/shared source modules, including unexecuted lines,
  and infra/hybrid/stock_*.py. Use standard coverage configuration with explicit,
  documented legacy module exclusions. Never report the new denominator as the old
  whole-repository result.
- Preserve80% aggregate coverage,90% per-file critical branch coverage for retained
  shared critical modules, and95% combined statement/branch coverage for stock host
  modules. Missing reports/modules, malformed counters and nonbranch reports fail.
- Preserve report path/duplicate/threshold/integrity checks in the coverage checker.
- Guard against reintroducing legacy test files or workflow commands, missing stock
  coverage, orphan fixture imports, or dropping current worker/risk/auth/ledger tests.
- No application mode, account, risk limit, auth permission, worker schedule,
  deployment, credentials or live-trading setting changes.

Baseline e2960a4 is retained on codex/stock-release-producer. Its original single
full run exited0:15370passed33skipped1warning,89.04%,8618.49seconds. Its terminal
receipt/log and static/review evidence remain in the original plan workspace.
The new stock-suite result must be executed and reported independently.
