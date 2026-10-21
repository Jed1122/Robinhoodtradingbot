# Hybrid release verification — 21 October 2026

**Disposition: working experimental research/simulation release; live readiness
blocked.** No live order, transfer, credential migration or live activation occurred.
The operator removed the mandatory paper period; simulation remains available for
engineering validation. A separate explicit live authorization is still required.
No strategy has qualified and no return is promised.

## Source and scope

The isolated `codex/hybrid-equity` worktree extends base
`efaed4b494cc33e4dd547d726e5e0dcc3a137fb5`. Other dirty worktrees, retained source
archives and the completed ETF studies were preserved. Integration owns the
canonical policy, risk, accounting, execution and persistence composition.

| Delivered | Verified behavior and practical boundary |
| --- | --- |
| Opt-in canonical policy | $1,000 simulated start, 75/15/10 targets, no live setting or mandatory paper period; existing legacy envelopes unchanged |
| Accounting, tax estimates and exits | Exact Decimal lot basis, proceeds versus gains, optional tax assumptions, three tactical exit models, persisted partial-threshold progress |
| Portfolio and execution safeguards | Reservations, buying power, settlement, concentration, stop-risk sizing, fresh complete marks, loss suspension, kill control, duplicate/conflicting fill rejection |
| Experimental execution | Explicit synthetic scenarios, partial fills/cancellation/restart, FIFO disposal; no connection to a real order endpoint |
| Research connectors and policies | Bounded SEC/FRED adapters, explicit imports, evidence timestamps, seven frozen pure hypotheses; all proposals unqualified |
| Backtesting components | Next-open comparisons, explicit costs and unknown taxes, six exit references; full qualification/study limits documented separately |
| Durable state and scheduling | Configuration-bound hash-chain journal, append-only database, serialized updates and persisted deduplicated jobs/reports |
| Investor dashboard | Five responsive views, authenticated API, in-memory browser token, truthful missing values and readiness blockers |
| Deployment and operations | Isolated nonroot image, private ledger, loopback access, health checks, bounded resources/logs, code rollback helper and backup utility |
| Security and activation documentation | Capability matrix, unattended-auth limitation, credential boundaries, explicit future activation checklist |

## Checks

Counts below overlap and must not be added together. Local Python checks used
Python 3.12.13; this report does not claim execution of the hosted Python-version
matrix or a remote CI pass.

- Original config/domain/risk baseline: 600 passed.
- Migration and append-only verification: 211 passed.
- Architecture/configuration/new-core checks: 492 passed.
- Focused hybrid/research/deployment checks on deployed executable source
  `b3b7f49`: 78 passed; a subsequent test-only guard expansion passed 91 checks.
  Specific buying-power, reserve, allocation, risk-stop, precision and invalid-fill
  denials were checked without changing deployed code.
- Independent final review: no unresolved actionable finding in the reviewed changes.
  The multi-symbol restored replay defect was reproduced by failing tests, fixed,
  and independently checked with 8 passing scenario/journal tests.
- Frontend: 9 tests passed, TypeScript/Vite production build passed, npm audit
  reported zero known vulnerabilities in the complete locked dependency set.
- Real headless browser: desktop and 390px mobile login/navigation across all five
  views and research controls passed without JavaScript errors or horizontal overflow.
  The browser used fictional fixtures; it did not establish broker correctness.
- Ruff passed; strict mypy passed for 414 source files; Bandit reported zero issues.
  Frozen Python dependency audit reported no known vulnerabilities; lock check passed.
- Full Python regression: **10,869 passed, 33 skipped, one dependency deprecation
  warning**, in 4,115 seconds. The required 80% aggregate coverage check passed
  (87.53%). Its collected base is `2bb5325`; later conservative exposure, logging,
  quote-batch and pure policy changes have the separate scoped checks above.
  Interrupted earlier runs are not counted as successful runs.
- Optional native historical-episode supplement: 20 passed in the locked research
  environment; appended aggregate coverage was 91.24%. The existing per-module
  critical branch coverage gate passed. It covers its established module list;
  it does not confer a 90% coverage result on the new extension.
- Separate latest hybrid component coverage was 77.65%, including 84.35% for
  experimental execution. This is measured test coverage, not a live-readiness
  verdict; further adversarial coverage remains part of future live qualification.
- The main run's skips include optional Databento/Parquet/DuckDB/QuantLib inputs
  and the local `age` backup executable. The native supplement covers its stated
  episode suite, not every optional skipped suite. The warning is the installed
  Starlette TestClient/httpx deprecation. No skip or warning was hidden or repaired
  by changing unrelated dependencies. The new CI no-live-secrets check also passed.

Bounded logs, browser fixture screenshots and a hash manifest are retained privately
in `~/.local/share/hybrid-equity-verification-20261021/`. These records contain no
brokerage tokens or customer account payloads.

The new dashboard workflow repeats install/test/build/audit on changes. No hosted
CI result is claimed by adding a workflow file. Source-policy fixture checks are
not statistical or market-data qualification.

## Actual isolated deployment

A bounded deployment and recovery rehearsal used existing authorized host capacity;
no new droplet, subscription or recurring service was purchased. The existing
paused `trading-bot` service was left separate. The new service is `hybrid-paper`,
listening only on host `127.0.0.1:8081`. The name denotes experimental execution,
not a waiting-period requirement.

Deployed executable source: `b3b7f49`. Later test/documentation-only commits do
not change that running executable image.

Archive SHA-256:
`437bd68c259062e382d0d5eebfd2223072ca6917a380a8e05b13395185dc2b8d`

Verified running image:
`sha256:39721c03805f8e25bd2a764f92bd83746c42d995edd0a4e465ae9870f6e5364d`

The deployment helper checked image identity and health=200/live-disabled,
readiness=503, and unauthenticated API=401. A separate authenticated request
verified paused state, $1,000 simulated starting capital, live disabled and no paper
period requirement. Actual Docker inspection confirmed UID/GID 10001, read-only
root, all capabilities dropped, 512 MiB / 0.5 CPU, loopback publishing and only the
private simulation-state mount. No brokerage credentials were mounted.

A restart of the final immutable image preserved the same cash, paused controls,
jobs and reports; the original service identity/start time was unchanged.
Before the final code update, the same isolated journal was exercised through
research resume, four durable job records, a daily report and pause. Container
restart preserved state. SQLite backup plus a separate offline restored copy passed
integrity checks; a restored application journal also verified configuration and
hash-chain identity, paused controls and retained reports. This is bounded recovery
evidence, not a sustained operation or disaster-recovery service-level guarantee.
The backup remains private on the host; no unattended off-host backup/alert service
has been established. Private access instructions are in
[hybrid-operations.md](hybrid-operations.md).

## Economic evidence and remaining work

[hybrid-strategy-comparison.md](hybrid-strategy-comparison.md) records the actual
715-session, five-ETF, 90-result component comparison and its input/result hashes.
All results remain unqualified and after-tax results unknown. It uses already
inspected development data and does not supersede the earlier ETF cost rejection.
The $12/month existing host cost alone is 14.4% annually of $1,000 starting capital.

The complete investment project is **not complete or ready for real capital**.
Remaining work is substantive:

1. Qualify permitted point-in-time data, corporate actions/distributions, universe,
   estimates/events, session calendars and total-return benchmarks.
2. Freeze and evaluate complete portfolio/strategy cycles, capital recycling,
   execution/cost/tax sensitivities, untouched out-of-sample data and statistical
   uncertainty. No automatic strategy promotion is implemented.
3. Verify official Robinhood background authentication/expiry/revocation and exact
   intended-account review/order/fill/cancel/lot/reconciliation contracts. The
   interactive connection does not establish unattended service authorization.
4. Complete the broker adapter/runtime only from those verified contracts, then
   test reconciliation and failures without making unauthorized live transactions.
5. Establish sustained monitoring, external alerts, backup retention/off-host recovery
   and exact-release readiness. Finally present the account, capital, strategy and
   risk settings for separate explicit user-controlled live authorization.

If the missing evidence does not support active trading over passive alternatives,
the correct result is rejection or no action. Removing a paper waiting period does
not turn synthetic tests or deployment success into investment evidence.
