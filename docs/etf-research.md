# Offline SPY/cash ETF research commands

Status: 2026-10-01 development increment, not yet merged. Native capture PR #6
is merged at `a2b3921635fd489db87c4dd1f7451789fbdb6162`; that merge does not
qualify the captured data or approve economic results, deployment or trading.

The three runnable standalone commands use the canonical backtest configuration
and locked `spy-cash-momentum-20-100-v1` research identity. A fourth command,
`account-ledger-run`, explicitly denies before mutation. None constructs network
or broker transport, opens credentials, submits orders or enables live execution
or promotion. The existing main operator CLI is not their entry point.
See the [approved specification](superpowers/specs/2026-09-30-focused-etf-research-design.md),
[implementation plan](superpowers/plans/2026-09-30-focused-etf-research.md) and
[dated operator authority](operator-authority.md).

## Invocation and private storage

Run from the repository root in its existing locked Python environment:

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research --help
```

`account-fixture-run`, `account-checkpoint-run` and `latest-vintage-run` accept
`--config-dir` (default `configs`). They enable only the research profile inside
the canonical configuration; execution and promotability remain false. The
denied ledger command accepts only `--output-dir`, not `--config-dir`.
Do not change limits to make an example succeed.
The $500/$1,000 inputs are hypothetical starting cash, not account balances or
authority to increase sizing. The risk-equity reference remains $100; current
order/gross caps, loss gates and the non-replenishing $50 trial-loss limit remain
unchanged.

Capture, checkpoint and report roots must be existing absolute directories outside
the repository, owned by the current user with mode `0700`, with no symlink
traversal. Read input files must be owned mode `0600`. Reports are private,
content-addressed `<sha256>.etf-report.json` files for the latest-vintage command;
account reports go to stdout. Conflicting publication bytes are refused, and
identical publication is idempotent. Do not move raw licensed inputs,
credentials, account identifiers or private financial evidence into Git, logs or
Cloud agents. The archive reader never opens the credential path retained in a
capture manifest.

## Fabricated account accounting

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research account-fixture-run \
  --capital 500 --scenario completed --operating-cost .25

PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research account-fixture-run \
  --capital 1000 --scenario completed --operating-cost .25
```

This checks exact accounting for explicit fabricated order/fill/action/settlement
facts, not a strategy-selected market opportunity or executable-price replay.
The $500 example buys 0.1 shares at $100 plus $0.01 fee, credits a $0.02
distribution, then sells at $101 less $0.01 fee: final cash is exactly $500.10.
With the illustrative $0.25 operating allocation, trading P&L is $0.10 and
operating result is -$0.15. Decimal JSON strings may omit trailing zeros.
Neither this allocation nor the default zero allocation is verified cost evidence.

`--scenario open` retains shares; `--scenario pending_settlement` retains
unsettled proceeds. Neither invents a closing fill or finalized P&L.
Incomplete reports set `complete=false`, `trading_pnl=null` and
`operating_profit=null`. Every fixture is labeled
`synthetic-account-facts-v1` and remains `ECONOMIC_NO_GO`, even when complete.

## Private checkpoints and restart example

Use a new private fixture root, then retain the same root and unchanged request
for continuation:

```sh
etf_fixture_root=$(mktemp -d /private/tmp/etf-account-checkpoints.XXXXXX)

PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research account-checkpoint-run \
  --output-dir "$etf_fixture_root" --capital 500 --through-events 2 \
  --operating-cost .25

PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research account-checkpoint-run \
  --output-dir "$etf_fixture_root" --capital 500 --through-events 8 \
  --operating-cost .25
```

The first command intentionally returns incomplete status after the buy; the
second reconstructs and advances the eight-event completed fixture. Repeating
the second command does not duplicate cash flows. The command creates a private
`etf-account-checkpoints` child with an ownership marker, nonblocking writer lock
and immutable numbered prefix snapshots. Each snapshot binds the request,
source event, state hash and previous snapshot hash. Every stored prefix is
reconstructed with the same account owner and compared before continuation;
states remain paused and cannot execute trades.

Verified directory descriptors stay open for descriptor-relative reads and
no-overwrite publication. There is no SQLite database, journal or migration in
this command, and no SQLite fencing claim. Unknown entries, changed request
identity, conflicting snapshots, prefix gaps, another writer or a backward
cursor deny continuation. Use a separate root for the $1,000 tier. Do not delete
ownership/evidence files to bypass a denial. This fixture restart mechanism is
not broker authentication, recovery or real-account reconciliation evidence.

### SQLite pathname boundary

`account-ledger-run` always exits `1` with
`etf_sqlite_path_binding_unsupported` before mutation. The current macOS SQLite
stack reopens database/journal pathnames and cannot bind them to the verified
directory descriptor; this safety boundary has no waiver. The internal SQLite
history store and migration `0008_etf_replay_history.py` remain implementation
and integration-test surfaces, not an enabled path-based CLI or authority to
migrate production state. Use the checkpoint command for these offline examples.

## Latest-vintage native-bar diagnostic

Select the already-retained native capture directory and its reviewed 64-character
manifest SHA256. Replace the two capture placeholders below; this command does
not acquire data. Keep reports in a separate private root:

```sh
etf_report_root=$(mktemp -d /private/tmp/etf-native-report.XXXXXX)

PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research latest-vintage-run \
  --capture-dir /absolute/private/native-capture \
  --manifest-hash REVIEWED_MANIFEST_SHA256 \
  --report-dir "$etf_report_root"
```

The reader verifies saved manifest/result/raw-body hashes, receipt chronology,
request/query identities, pagination and native schemas before building a
latest-vintage projection. The retained SPY SIP daily-bar capture contains 2,514
records for the requested 2016–2025 window. The October 1 saved-data diagnostic
ran with 2,012 development records and 502 retained holdout records; it did not
evaluate the holdout and returned `ECONOMIC_NO_GO`. These counts are capture and
diagnostic inventory, not proof of complete exchange-session, action, liquidity
or executable coverage.

The command publishes its bound protocol before evaluating outcomes, preserves
the 750-bar warmup and fixed 20/100-day signal, and counts five-session rebalance
candidates. It evaluates development observations before 2024 only; retained
2024–2025 holdout bars are not evaluated. Daily aggregate completion is projected
to the following New York midnight as a disclosed research assumption, not a
verified session-close or historical publication timestamp.

The October 1 waiver applies only to original publication/correction timelines
for this research identity. Retrieval time is not historical availability, and
later corrections may change earlier signals. Original versions/timestamps are
not fabricated. The report is latest-vintage exploratory research, admits zero
entries and remains `ECONOMIC_NO_GO`; no fills, trading returns, matched after-cost
benchmarks or empirical edge are established. The waiver does not qualify
execution data, calibrated costs, economics, paper/shadow promotion or live use.

## Interpreting results and readiness

Successful fixture/checkpoint command completion exits `0`; a valid incomplete
account report exits `2`. The SQLite ledger command always denies as described
above. Other input validation emits sanitized
`etf_research_input_invalid` and exits `1`; command-line usage errors are separate.
A successful latest-vintage command can exit `0` while its economic verdict is
`ECONOMIC_NO_GO`. Exit success means the diagnostic ran, not economic acceptance.
There is no `--live` or `--assumptions-validated` override.

| Independent gate | Current evidence / remaining boundary |
|---|---|
| Engineering | Runnable fixture, descriptor-bound private checkpoint/restart and latest-vintage diagnostic increment; SQLite pathname CLI denied. Independent review has no residual actionable findings; 112 final focused tests and current static/critical-coverage checks passed. Exact committed hosted regression remains required. |
| Data qualification | Receipt-verified latest-vintage native bars; `source_qualified=false`. Session/control, corporate-action/payment and executable quote/fractional-term coverage remain unqualified. |
| Economics | `ECONOMIC_NO_GO`; fixtures and signal counts cannot establish profitability. Complete actual outcomes, calibrated costs, matched benchmarks, uncertainty and canonical acceptance evidence remain separate. |
| Broker/runtime | October 1 scoped Agentic reads observed an active cash account with level-2 options permission, no equity/options position or order rows and no further pages; SPY was active, tradable and fractional-eligible. Droplet metadata returned the existing 2 GB target, but SSH authentication failed and service/image/authentication state remains unverified. These session observations do not verify standalone DigitalOcean authentication, write semantics, unattended renewal or order integration. |
| Qualifying paper/shadow | Not ready; accepted research and trusted composition plus 100 eligible paper cycles and seven distinct UTC shadow dates are still required. Fixtures do not start these clocks. |
| Live authority | `live_authorized=false`, `execution_enabled=false`, `evidence_promotable=false`; no live writes, deployment or automatic promotion. |

## Next steps

Complete integrated source/account/checkpoint/store/economics review and the current
revision's narrow tests first, then full supported-Python regression, the 80%
overall and per-critical-module 90% branch gates, Ruff, Mypy, Bandit, locked audits,
SBOM and deployment-manifest checks. Do not substitute prior pass counts for this
increment's evidence or bypass required hosted checks before integration.

Continue the approved plan's credential-free implementation while completing
the retained data and cost evidence required by each claim. Genuine qualified
market-execution replay is not implemented by these commands; there is no
conditional price-proxy study command. Genuine economic validation and later
paper/shadow composition need their own complete evidence; standalone broker/runtime
proof and explicit live authorization remain independent. No new subscription,
credential operation, deployment or real-money test is implied by these steps.
