# Robinhood options-only migration implementation

Approved source: [complete master specification](../../options-only-build-spec.md).
Baseline: `2edf4cf1b462658c6aef1e0a8dafe7432b496117`.

## Global constraints

Development and credential-free offline testing only. No broker/account calls, orders,
paid services, Cloud dispatch, production state migration, activation, or deployment.
Preserve all pre-existing staged and unstaged work. Coordinator owns canonical models,
configuration, pricing, decisions, risk, execution, reconciliation, persistence, release.
Use Decimal monetary values, integer complete package units, versioned evidence, and
the existing strict configuration loader. Synthetic runs never establish economic or
promotion eligibility. Keep all production capabilities locked.

The $100 assumption and $150 live ceiling are unverified. Retain the $50 per-trade
outer cap AND $50 non-replenishing cumulative trial-loss cap. The stricter 0.50%
trade budget applies ($0.50 at $100); profits/deposits/restarts cannot replenish trial
capacity. Initial/micro profiles permit one unit, one open position, one entry/session.
Whole-percent config values: 0.50 trade, 5 portfolio payoff risk, 2 underlying group,
80 minimum unencumbered cash, 2 daily, 5 weekly, 10 drawdown. Retain stricter limits.
Single-leg session declarations do not establish standalone runtime support; spreads
remain research-only and must never be legged into live markets.

## Task 1: Non-mutating SBOM verification

Owner: isolated credential-free implementer. Base: 2edf4cf1b462658c6aef1e0a8dafe7432b496117.
Owned paths: scripts/generate_sbom.py; tests/smoke/test_sbom_reproducible.py.
Read-only dependencies: uv.lock, pyproject.toml, docs/sbom.cdx.json.
Add optional --output destination, preserving the default. Test reproducibility at
tmp_path and assert tracked artifact bytes remain unchanged. Write a failing test
first, then minimal implementation. Do not regenerate the tracked SBOM, edit the
lockfile, invoke network, inspect secrets, or alter other paths. Verify focused pytest,
Ruff and applicable typing. Commit only owned paths and return READY/NOT_READY with
RED/GREEN evidence and commit SHA. No subagents. Coordinator reviews and integrates.

## Task 2: Migration contract and canonical options foundation

Preserve the master prompt verbatim, classify every original requirement, and update
the existing implementation plan. Add immutable contract, quote, leg, structure and
intent models with explicit effects, session/expiry identity, tick rules and adjusted
deliverable rejection. Use versioned serialization; keep legacy order records and
long-only validation unchanged. Extend canonical config/release envelope, not another
loader. Zero bids are observations; crossed/incomplete/stale execution is rejected;
locked quotes require explicit policy. No constructible production options adapter.

## Task 3: Complete offline single-leg vertical slice

Recorded synthetic point-in-time input -> existing 20/100 momentum hypothesis ->
long-option candidate -> premium/fee economic admission -> shared order transitions ->
reconciled cash-flow report. Full risk reservation persists through partial fills,
cancel-pending, unknown acceptance and unsettled obligations. Completed episode losses
never net against profits. Next-event fills, rejection/unfilled orders, cancel races,
closing/settlement and incomplete results are explicit; never force terminal exits.
Expose options replay and capital-feasibility commands; demonstrate $100 denial and
complete hypothetical research-capital lifecycle without altering live authority.

## Task 4: Historical data, pricing and economic research

Point-in-time provenance/manifests and exact partitioned Parquet/DuckDB outside ledger;
provider import contracts/fixtures and rights/cost comparison without restricted data.
Pin and validate QuantLib European analytical/American FD dividend-aware models,
Greek units/finite differences and stress. Research long options, debit verticals,
credit verticals then condors. Preregister grids, splits, effective sample and uncertainty
before holdouts. Conservative/base/optimistic fills; dependency-aware resampling;
cash/operating-cost comparisons across all master capital tiers. Insufficient evidence
is ECONOMIC_NO_GO, never an invented winner.

## Task 5: Locked official capability integration

Separate public/session/account/runtime evidence, operation-specific hashes/expiry and
negative history. Credential-free schema/parser/fake transport tests only. Independent
read/review/place/cancel capabilities under execution owner; exact review-intent binding,
fresh final checks, persist before submission, reconcile ambiguous acceptance before
retry. OPTIONS_LIVE_SUPPORTED remains false until independently authorized evidence.
Account-specific settlement/intraday restrictions cannot be inferred from public rules.

## Task 6: Durable lifecycle and continuous operation

Additive ledger migrations for legs/reservations/collateral/lifecycle/settlement/trial
history, no production migration. Reconcile orders/fills/options/unexpected shares/
cash/fees/unsettled obligations. Paused recovery, protective monitoring and fenced
single writer. Entry halts distinct from separately authorized risk reduction; manual
weekly/drawdown latches. Physically settled expiry exits by preceding eligible session.
Assignment, unmatched legs, unexpected shares and missed deadlines are incidents;
stock remediation/exercise remain unavailable. Scheduling/private status/heartbeat and
operator commands; paper credential-free and shadow order-write-incapable.

## Task 7: Deployment preparation and evidence handoff

Preserve DigitalOcean and paused startup. Benchmark before hardware proposals; separate
heavy research. Deployment-plan output, encrypted backup/restore, rollback compatibility,
resource limits/costs, security/capability/economic/operations/limitations reports. No
deployment or activation. Independent technical/economic/account/operator verdicts.

## Verification and progress

Each task: failing tests, narrow checks, broader baseline, reviewed diff. Retain overall
80% gate; add 90% branch-only gates for risk/execution-state/lifecycle-critical modules.
Run Ruff, Mypy, pytest, Bandit, locked dependency audit, SBOM/deployment checks. Offline
tests deny network/write capabilities; authenticated tests excluded from CI. Include
payoffs, exact fees/cash, whole units, trial exhaustion/profits/deposits/rolling/restarts,
quotes/calendar/DST, partial/unmatched/cancel/timeout, stale leaders/schema changes,
assignment/settlement, no-lookahead/synthetic rejection and failure/restore scenarios.

Status: initial foundation and synthetic long-call slice implemented and verified; the
complete six-milestone migration remains unfinished. See the tracked
[validation/progress report](../../options-migration-validation.md) for current scope,
commands, evidence and remaining work. The scoped SDD ledger retains review details.

## Task 8: Explicit critical branch-coverage verification

Owner: isolated credential-free CI implementer; baseline 2edf4cf1b462658c6aef1e0a8dafe7432b496117.
Owned paths: scripts/check_critical_branch_coverage.py,
tests/smoke/test_critical_branch_coverage.py, .github/workflows/ci.yml.
Add a deterministic checker consuming pytest-cov/coverage JSON; enforce at least 90%
branch-only coverage for every source module under risk/, execution/, lifecycle/,
domain/order_state_machine.py, simulation/lifecycle*.py and simulation/options_replay*.py.
Discover source paths
from the supplied repository root, require every discovered critical module in the
report, fail if branch data absent/invalid, accept zero-branch modules only with measured
branch counters. No excluded uncovered files or total-line percentage substitutes.
CI retains overall80% and emits JSON then runs the checker. Missing optional lifecycle/
or options modules at this baseline are not errors; once created they must be measured.
TDD with tmp_path synthetic report/source trees covers threshold boundary, missing
files/counters, zero branches, invalid counts, no critical modules, and correct root
path normalization. CLI required --report and optional --root default current directory.
No dependencies, network, credentials, production changes, baseline test suppression or
threshold weakening. Focused pytest/Ruff/Mypy. Commit only owned files; report RED/GREEN
and READY/NOT_READY. Coordinator reviews/integrates. No subagents.

## Task 9: Bounded recorded synthetic options replay

Coordinator-owned follow-up to Task 3 at 2bac364. Freeze a closed, versioned JSON input
containing synthetic options replay records, config identity and content digest, never
configuration overrides, filesystem references or credentials. Financial fields remain
decimal strings; counts are exact integers; unknown/duplicate keys, non-finite numbers,
oversized/deep inputs, mismatched hashes and non-synthetic claims fail closed.
Reuse existing bounded JSON and private no-follow/no-overwrite artifact storage helpers,
the existing canonical config, current domain records, risk and replay function. Do not
change monetary admission, quantity limits, production capability or old serialization.
Expose fixture export and saved-input replay/report commands within options_research.
Input parsing is not source authenticity, and all outputs remain ECONOMIC_NO_GO and
non-promotable. Saved reports must be content-addressed, private and non-overwriting;
incomplete replay still has exit code2 and saves its truthful report. No broker imports,
network, production persistence, paid dependencies, staged lockfile changes or main CLI
edits. Tests first: exact independent cash outcomes, tampering/type/provenance denial,
configuration mismatch, malformed paths, size/depth/count bounds, no overwrite and
determinism. Require90% branch coverage for new options_replay modules.

## Task 10: Official historical-data comparison, documentation only

Independent local read-only research at 2bac364 while Task9 runs. Compare Databento,
ThetaData and Massive using primary vendor documentation only, with retrieval dates
and source links. Cover quote/chain schemas, expired coverage, timestamps/availability,
corporate actions/dividends, non-display use, personal use, retention, redistribution,
free/sample path, advertised prices and all-in cost uncertainty. No API login, downloads,
restricted datasets, subscription or provider selection. Unknown rights/costs stay unknown;
do not infer automated-use rights from retail display pricing. Draft findings under this
plan's ignored workspace; coordinator verifies sources and publishes docs/data-providers.md.

## Completion sequence from dde6e46

Continue Tasks4-7 through tested slices, retaining coordinator ownership of all financial,
canonical and production-boundary code. Tasks1,8,9,10 are complete. Public documentation
and deployment reuse audits are read-only parallel work; never duplicate implementation.

1. Freeze point-in-time options data records/import contracts; exact Parquet/DuckDB
   storage in a separately locked local research environment. Synthetic tests only.
2. Validate pinned QuantLib European analytical/American finite-difference pricing,
   explicit dividend/rate/time conventions, Greek units and full-repricing stress.
3. Complete matched long/debit/credit/condor payoff economics and research candidates,
   preregistered walk-forward/cost/dependence scorecards with permanent synthetic NO_GO.
4. Add durable options trial/lifecycle tables and journals with restart reconstruction,
   idempotent events, incident detection, expiry deadlines and latched entry halts.
5. Extend existing capability evidence dimensions and credential-free official schema
   contracts; keep real adapter construction locked and submission unavailable.
6. Wire offline research/paper operator commands and bounded continuous scheduling,
   reuse paused deployment, backup/restore and monitoring facilities where applicable.
7. Review all added code, run complete validation, and report evidence blockers separately
   from engineering gaps. No external evidence is assumed or manufactured.

The additional numerical/history dependencies live in research/pyproject.toml and its own
lock, referencing the existing local Python package. This separates heavy research from
production and preserves the user's staged root lockfile. It does not create a second
trading config or risk policy. No existing dirty main CLI/docs file is overwritten; additive
operator composition remains separate until its integration can preserve existing work.
