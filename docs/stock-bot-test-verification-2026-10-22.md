# Stock bot test retirement verification

Tested commit: `0bfab5b79331dc9ecc74a4f107ed96ce91659ee0` on `codex/stock-bot-test-suite`.
Local Python 3.12.13. Actual original session 92157 exited **0**.

| Check | Observed result |
| --- | --- |
| Retained stock/shared suite | 10,298 passed; 0 failed; 0 skipped; 1 warning |
| Runtime | 830.97 seconds |
| Whole retained-module combined coverage | 90.69% (80% gate) |
| Retained critical per-file branches | Every required module passed 90% gate |
| 25 stock host modules combined | 5762/5883, 97.94% (95% gate) |
| Scope/fixture/CI guards | Passed within the full retained suite |
| Ruff | Passed, including the final corrected assertions |
| Strict mypy | Passed across 445 application source files |
| Offline lock | Passed, 106 packages |
| Bandit application + all stock hosts + checker | Exit 0, no findings in 100,982 source lines |
| Current deployment shell syntax | Passed |
| Fresh independent review | gpt-6-astra/high, no blocking source/scope/coverage finding |

The warning is the existing Starlette/httpx TestClient deprecation. No skip was
silently converted into success. CI configuration and workflow guards were checked
locally; hosted CI, other Python matrix interpreters, native Docker and deployment
were not run in this wave.

## Scope and accounting preservation

Removed 236 legacy test modules and 13 exclusive helpers/fixtures; 286 test modules
remain. This physically retires the ETF/options strategy, study, native-data,
pricing, expiry and monitor suites, unrelated positive crypto/prediction tests,
Databento pipelines, the predecessor four-ETF collector/comparison and superseded
root deployment checks. The options workflow and native coverage append are gone.
`pytest`, `pytest tests`, `make test` and CI now share the retained stock/shared
scope. No coverage gate was lowered.

Shared risk, auth, accounting, persistence, execution/reconciliation, passive
benchmarks and unsupported-asset rejection remain. The two shared loss-state
class bodies are AST-identical to e2960a4; old imports remain identical aliases.
Legacy production modules were not deleted and are explicitly outside the new
suite's verification claims. See [active testing commands](stock-bot-testing.md).

The historical whole-repository result at e2960a4 was 15,370 passed, 33 skipped,
89.04%, 8,618.49 seconds. The new denominator differs and is not a coverage gain
claim against that old scope. The first retained run exposed two old workflow
assertions in the logging test module: 10,296 passed, 2 failed, exit 1. Both guards
were retained and corrected for configured coverage, report and checker use; 65
focused checks then passed, followed by the successful integrated run above.
No logging/application behavior or risk setting changed in that correction.

## Review decisions and limits

- Retired native pipelines and old root deployment checks lie outside the current
  stock graph; the cost of this boundary is that their legacy behavior is unverified.
- Kept shared equity and benchmark/asset-denial tests despite older asset names;
  this intentionally leaves a larger retained safety suite.
- The sole fresh review ran read-only against the integrated pinned revision while
  regression ran. Root retained terminal-result authority, preventing a progress
  count from becoming acceptance. Only two stale test assertions and documentation
  changed after review; their RED/GREEN and integrated regression are recorded.
- The reviewer called the non-reproducible documented Bandit command Minor. Root
  treated reproducible verification guidance as required and corrected the command
  using observed broader-scan RED/current-stock-scan GREEN evidence. The broader
  all-hybrid scan still has 12 pre-existing Low subprocess notices in prepare.py
  and watchdog.py (exit 1, no Medium/High); none was suppressed or called passing.
- Native Docker, deployment/unattended operation, broker/provider/credentials/live
  readiness, strategy profitability/data qualification, retired implementations,
  remediation of unchanged helper notices and a comprehensive audit of unchanged
  application code remain outside this cleanup. The cost of confusing those with
  local regression is a false readiness claim; none is made. No deferred review
  item remains in this cleanup; broader helper remediation is separate work.

## Next project steps

Verify the native stock release/probe and paused installation, then demonstrate
unattended scheduled research with auth-expiry and restart/recovery monitoring.
Qualify real stock data and strategy evidence, finish the research-to-eligibility-
to-portfolio/risk-to-official-order/reconciliation bridge, and verify nonempty
fill/fee/lot behavior. No existing Alpaca credential JSON is assumed; acquisition
using it remains unconfigured. No fixed 60-day paper wait is imposed.

Live execution remains disabled. No credentials, provider/broker calls, money
movements, native Docker, deployment or live-setting changes occurred in this wave.
The branch is retained locally; no push/PR or remote CI execution is claimed.

Raw terminal receipts, both regression logs, final coverage, audit decisions,
retirement manifest, review and static results are preserved locally under
`reports/verification/2026-10-22-stock-bot-test-suite/`. The final result JSON records
SHA-256 identities for primary evidence.
