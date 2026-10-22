# Stock bot verification

The default suite verifies the individual-stock collector, source and filing parsers,
scheduled worker, controls, release/launcher/probe recovery, dashboard exports, hybrid
portfolio/accounting/exits/backtests and shared equity authorization, risk, execution,
reconciliation, persistence and security. It uses local/fake inputs; authenticated
tests remain excluded by default. Local test success does not establish a trading
edge, broker fill semantics, deployment or continuous operation.

## Commands

```sh
uv sync --locked --all-groups
make test
uv run ruff check .
uv run mypy src
uv run bandit -c pyproject.toml -r src infra/hybrid/stock_*.py scripts/check_critical_branch_coverage.py
uv lock --check --offline
```

`make test` runs the same commands as CI:

```sh
uv run pytest tests --cov --cov-branch --cov-fail-under=80 --cov-report=json:coverage.json
uv run python scripts/check_critical_branch_coverage.py --report coverage.json
```

Plain `pytest` and `pytest tests` collect the same retained tests without a coverage
report. For a narrow edit, run its relevant tests first; run the full retained suite
for integration. The dashboard's existing npm test/build workflow remains separate.

## Coverage and retirement boundary

Standard coverage configuration in `pyproject.toml` measures complete retained
`src/trading_bot` modules and `infra/hybrid`, including unexecuted files. `--cov`
uses that configuration; `--cov=trading_bot` overrides it and misses host coverage.
Do not use the latter for acceptance.

The gates remain 80% aggregate coverage, 90% per-file branches for retained shared
critical modules, and 95% combined statements/branches across all stock host modules.
The checker also requires current stock/hybrid modules to appear and rejects missing
or nonbranch reports, malformed counters and duplicate normalized report paths.

Legacy ETF/options strategy, historical study, native-data, pricing, expiry and
monitor tests are physically removed. Their dedicated options workflow and native
research coverage supplement are removed. Unrelated positive crypto/prediction
tests, Databento pipelines, the predecessor four-ETF comparison/collector and root
deployment tests outside the current hybrid stock composition are also retired.
Exclusive fixtures and orphan imports are removed. These changes retire 236 test
modules and 13 helper/fixture files; the unsupported-options denial test is retained
under an asset-neutral filename. Mixed files retain their applicable safety cases.

The production legacy modules remain in the repository. Explicit coverage omissions
identify those modules; the stock result makes no claim about their correctness.
Shared config/schema migrations, passive benchmark comparisons and unsupported-asset
rejection remain tested even when they mention ETF/options/crypto names. Shared
loss-budget/finality calculations moved unchanged to `risk/trial_losses.py`; former
imports remain identical aliases.

The pre-retirement run at `e2960a4` exited 0 with 15,370 passed, 33 skipped,
one warning and 89.04% coverage in 8,618.49 seconds. That is a historical full-repository
result with a different denominator. It must not be presented as the current stock
suite result. Current verification is recorded separately after execution.

The broader scan of all `infra/hybrid` helpers reported 12 pre-existing Low
subprocess notices in `prepare.py` and `watchdog.py` (exit 1, no Medium/High
findings). Those unchanged utilities were not remediated or suppressed by this
cleanup. The application/current-stock-host command above exited 0 with no findings.

## Remaining release work

After local verification and review, validate the native stock release/probe and
paused installation, then observe unattended scheduled stock research and auth/restart
recovery on the intended host. Qualify real stock data and strategy evidence, finish
the research-to-risk-to-official-order/reconciliation bridge, and verify nonempty
broker fill/fee/lot behavior. Live activation remains a separate user decision and
is disabled by default. No fixed 60-day paper wait is imposed.
