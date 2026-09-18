# Options migration: engineering checkpoint

Date: 2026-09-18. Initial baseline: `2edf4cf1b462658c6aef1e0a8dafe7432b496117`.
Saved-input continuation: `2bac364` -> `6ece50e` -> `a1afceb`; see its section below.
This is a progress report, not the final acceptance report for all six milestones.
The approved [migration plan](superpowers/plans/2026-09-18-options-only-migration.md)
and [complete master](options-only-build-spec.md) remain governing requirements.

## Initial foundation checkpoint (`2bac364`)

- Historical requirement disposition and separate traceability for all 24 master sections.
- Immutable options contracts, quotes, legs, 1:1 structure identities and whole-unit
  limit/DAY intents, with explicit effects, contract/session identity, adjusted-contract
  rejection, zero-bid observation and executable quote-quality checks.
- Versioned options intent serialization. The legacy serializer and long-only validator
  were not relaxed, and old evidence was not rewritten. New required config fields change
  config hashes; older configs missing them fail closed rather than gaining permissions.
- Options settings in the existing canonical config and release envelope, including
  whole-percent conversion: `0.005` becomes `0.50`, not `50`.
- A runnable synthetic long-call research slice using existing 20/100 momentum features
  and common order transitions, complete-unit economic admission, premium/fee reserves,
  exact cash flows, explicit settlement, completed-episode trial losses and truthful
  incomplete results. All synthetic results are permanently non-promotable.
- Credential-free `capital-feasibility` and `options-replay` module commands. See
  [commands, examples and scope](options-research.md).
- Non-mutating SBOM reproducibility testing and explicit per-file 90% branch coverage
  enforcement for risk, execution, order-state and options replay/lifecycle modules.
  The overall 80% gate is unchanged. Existing denial tests were extended, not weakened.

The coordinator implemented domain/config/risk/replay changes. Two isolated local workers
handled only SBOM/CI work; their diffs were centrally reviewed and integrated. Independent
local read-only reviews covered contract identity, replay correctness and documentation.
No Codex Cloud task was dispatched or claimed to have run.

Local session tool declarations were inspected without invoking Robinhood tools. The
visible declarations include option chains, instruments, quotes, historicals, positions,
orders, review, placement and cancellation. Review/place explicitly state single-leg-only
support. This is Codex-session metadata, not account permission, a successful API test,
standalone DigitalOcean authentication or runtime capability evidence. No schema snapshot
was promoted into the production capability manifest; that integration remains pending.

## Independent expected outcomes

The $100 assumed account has a $0.50 per-trade budget. The fixture needs $10 premium plus
$1 entry/exit fee reserve and therefore admits zero contracts. No rounding up occurs.
The $150 live ceiling and $50 cumulative non-replenishing trial ceiling are unchanged.

At an explicitly hypothetical $2,500 research tier, the completed fixture starts with
$2,500, pays $10 plus $0.50, receives $15 less $0.50, then settles to $2,504. The losing
fixture settles to $2,494 and consumes $6 of trial capacity. These are independently
calculated engineering expectations, not market observations or return forecasts.
Prior completed profits do not replenish consumed losses; incomplete episodes retain
their full reserved risk. Durable reconstruction and deposit/rolling handling are pending.

Review found and fixed three replay correctness defects using failing regressions:
re-wrapped old quotes could fill, close orders inherited entry expiry, and zero-net closing
proceeds could imply settlement. Fills now require a qualifying new quote observation,
closes have independent eligible-session deadlines, and settlement finality is explicit.

## Initial checkpoint verification

Environment: local Python 3.12.13 with the existing locked development dependencies,
`PYTHONPATH=src`; all verification artifacts were placed under a temporary directory.
Tests ran against the working tree including pre-existing local changes, not an isolated
clean-checkout CI job. No remote CI, authenticated tests or live writes were executed.

Final post-review full suite: **4,877 passed**, one existing Starlette/httpx deprecation
warning, **88.59% overall coverage**. The expanded **90% per-file branch gate passed**.
Its inventory includes `risk/`, `execution/`, `lifecycle/` when present, the domain order
state machine, `simulation/lifecycle*.py` and `simulation/options_replay*.py`.
New options economics has 100% branch coverage, replay 93.75% and replay records 96.43%.
Existing lifecycle accounting and codec denial paths now have 100% branch coverage.
Coverage is not evidence of production safety or economic validity.

| Executed check | Result |
| --- | --- |
| `pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80` with temporary JSON output | 4,877 passed, 88.59%, 258.28 seconds. |
| `python scripts/check_critical_branch_coverage.py --report <temporary coverage JSON>` | Passed after all review fixes and expanded lifecycle discovery. |
| Focused replay/CLI tests | 27 passed; deterministic, network-denied CLI scenarios. |
| Lifecycle accounting/codec and denial tests | 21 passed; both modules 100% branches. |
| Coverage checker and SBOM smoke tests | 15 passed. |
| `ruff check .` | Passed. |
| `mypy src` and separate coverage-checker typing | Passed; 206 source files plus checker. |
| `bandit -r src -q` | Passed, no findings; existing `nosec` comment warnings remain. |
| `uv lock --check` | Passed. |
| Locked all-groups requirements export and `pip-audit --no-deps --disable-pip` | No known vulnerabilities found; no-deps recommendation warnings remain. |
| Temporary CycloneDX dependency inventory with validation | Passed; 104 components, schema 1.6. |
| `uv build` to a temporary destination | Source distribution and wheel built successfully. |
| `git diff --check` | Passed. |

The full-suite interpreter was
`/private/tmp/robinhood-anyio-verification.5rJfWx/.venv/bin/python`.
Coverage, dependency inventory, requirements export and build outputs were placed under
`/private/tmp/robinhood-options-validation.CQNldJ`, not in tracked artifact destinations.
The locked audit result is not proof of vulnerability-free software.

The original tracked SBOM and pre-existing staged `uv.lock` bytes were preserved. Routine
reproducibility tests now write only to temporary destinations. The project's existing
SBOM generator remains a lock-hash manifest, not a complete dependency inventory; the
separate temporary CycloneDX report does not silently replace that tracked artifact.

All 23 existing deployment tests passed; DigitalOcean shell syntax also passed. These
are local static/unit checks, not options deployment certification. The local
Docker installation could not run `docker compose config --quiet` (Compose unavailable),
so Compose's own rendered-manifest validation is not claimed. No deployment, daemon
restart, production schema migration or production-state inspection occurred.

## Milestone status and remaining work

| Approved milestone | Current checkpoint |
| --- | --- |
| 1 Migration contract and foundation | Initial foundation implemented and tested; not evidence that all downstream use is ready. |
| 2 Complete offline single-leg slice | Working synthetic single-unit long-call path and bounded saved-input replay/report commands. Historical/vendor imports, puts, partial/package scenarios and complete common risk composition remain unfinished. |
| 3 Historical data and economic research | Public provider documentation comparison delivered; actual rights and total costs unverified. Pending: import contracts, provenance/storage, QuantLib compatibility, Greeks/stress, research families, preregistration and empirical scorecards. No data purchased/acquired. |
| 4 Official capabilities and locked integration | Pending: four evidence dimensions, options schemas/fake contracts, operation-specific capability composition and standalone runtime authentication evidence. No broker/account calls. |
| 5 Durable lifecycle and operation | Pending: additive options ledger migrations, durable trial history, restart/lease integration, reconciliation, expiry/assignment incidents and continuous options scheduling. No production migration. |
| 6 Deployment preparation and handoff | Pending: options-specific benchmark, encrypted restore/rollback validation, deployment-plan output, current costs, heartbeat and complete operational reports. Existing DigitalOcean files preserved. |

All other limitations in [options research](options-research.md) remain binding.
Identity records for verticals/condors do not establish payoff-model validation, package
execution, native multi-leg support or account permission. Standalone `trader` integration
is pending to avoid overwriting the pre-existing unfinished main CLI changes.

## Separate readiness verdicts

| Dimension | Verdict |
| --- | --- |
| Synthetic engineering slice | Working; post-review tests, scoped branch gate and independent review passed. |
| Full technical/operational readiness | NOT_READY; milestones above incomplete. |
| Economic readiness | `ECONOMIC_NO_GO`; fabricated inputs provide no empirical trading-edge evidence. |
| Account/interface/runtime capability | NOT_VERIFIED; no new authenticated evidence, options production capability remains disabled. |
| Live authorization | NOT_AUTHORIZED; this change is development only. |

No real-money orders, connectivity-test trades, transfers, account upgrades, subscriptions,
infrastructure purchases, deployment actions or account inspections occurred in this change.

## Saved-input continuation (`6ece50e`, `a1afceb`)

Tasks 9 and 10 extend the existing synthetic slice without changing its economic admission
or live capability. `export-options-fixture` writes closed versioned inputs;
`replay-file` parses them, invokes the same replay and optionally persists an exact report.
Config identity and content hashes, Decimal strings, UTC timestamps, strict schemas and
release-bounded byte/depth/array-item limits are enforced. Existing bounded JSON and
private no-follow, no-overwrite file primitives are reused. No embedded configuration,
broker adapter, credentials, historical claims or external file references are accepted.

Reports remain synthetic, `ECONOMIC_NO_GO`, non-promotable and production-ineligible.
Incomplete outcomes still save reports and return exit code 2. Hashes are content checks,
not authenticity evidence; caller-supplied trial history is never live-budget authority.
See [commands and security boundaries](options-research.md).

The coordinator checked and integrated a local worker's official-provider documentation
research into [data-providers.md](data-providers.md). It compares schema/coverage, time and
availability, corporate actions, prices, private/non-display rights and retention.
There was no vendor selection, account login, market-data acquisition or Cloud dispatch.
All-in costs and this system's actual rights remain unverified. This is documentation,
not completion of historical import contracts, numerical pricing or economic validation.

Test-first evidence: seven expected command/config failures preceded implementation;
49 focused tests then passed, followed by 60 expanded input/config/filesystem/CLI tests.
Independent review found no production-code issue. It required coverage of oversized
engine output: a fault-injection regression now checks sanitized denial before report
directory creation, and the 12-test filesystem suite passes. Scoped re-review approved
that fix. Production code was unchanged by the test-only correction.

Separate process CLI runs saved and replayed both the $100 denial fixture and the
hypothetical $2,500 completed fixture. Results retained $100 and $2,504 cash respectively,
with false production/promotion flags. These are fabricated engineering expectations,
not a trading return forecast or recommendation to increase capital.

Validation artifacts and synthetic input/report files are under
`/private/tmp/robinhood-options-files.Sm12uE`. The pre-existing staged `uv.lock`, tracked
SBOM and unrelated dirty/untracked work were preserved. Local commits were not pushed.

### Continuation verification

Final post-review full suite at `a1afceb`: **4,919 passed**, **88.66% overall coverage**,
251.61 seconds; the explicit **90% per-file critical branch gate passed**. Both new
wire and I/O modules have **100% line and branch coverage** (8/8 and 6/6 branches).
The existing Starlette/httpx deprecation warning remains. These are local working-tree
results, including preserved pre-existing work, not remote CI or a clean-checkout run.

| Refreshed check | Result |
| --- | --- |
| Full `pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80` | 4,919 passed; temporary `coverage-final.json`. |
| `check_critical_branch_coverage.py --report <coverage-final.json>` | Passed. |
| Focused saved-input tests with branch measurement | 39 passed; both new modules 100%. |
| `ruff check .`; `mypy src` | Passed; 208 source files. |
| `bandit -c pyproject.toml -r src -q` | No findings; pre-existing `nosec` comment warnings remain. |
| `uv lock --check`; all-groups locked export and `pip-audit --no-deps --disable-pip` | Passed; no known vulnerabilities; audit's existing no-deps recommendation warnings remain. |
| Temporary CycloneDX requirements inventory with schema validation | Valid 1.6 inventory, 104 components. Tool warns its root dependency graph is incomplete; not claimed as a complete dependency graph. |
| `uv build --out-dir <temporary directory>` | Source distribution and wheel built. |
| Deployment tests plus non-mutating SBOM smoke test | 24 passed. |
| `sh -n` for every DigitalOcean shell script | Passed. |
| `docker compose config --quiet` | Unavailable in installed Docker CLI; rendered Compose validation not claimed. |
| `git diff --check`; preserved lock/SBOM SHA256 checks | Passed; original staged/dirty artifacts unchanged. |

No protected production behavior, monetary limits or authorization changed. Historical
import contracts/fixtures are the next credential-free work item; numerical pricing,
empirical research, durable options lifecycle and live capability evidence remain pending.
