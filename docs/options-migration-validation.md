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
their full reserved risk. The later foundation checkpoint adds a separate durable synthetic
trial journal; replay/service integration and deposit/rolling reconciliation remain pending.

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
| 2 Complete offline single-leg slice | Working synthetic single-unit call/put path, bounded saved-input replay/report commands and explicitly stepped durable recorded sessions. Complete historical/vendor domain imports, partial/package scenarios and full common risk composition remain unfinished. |
| 3 Historical data and economic research | Provider comparison, strict six-kind point-in-time record codec, exact Parquet/DuckDB storage, pinned QuantLib pricing/Greeks/stress, terminal package payoff research and a bounded Massive REST quote-row parser implemented. Pending: complete vendor-to-domain provenance/identity mapping and licensing, economic hypotheses, package execution, full risk integration and empirical scorecards. No market data acquired. |
| 4 Official capabilities and locked integration | Dated public/session audit, version-2 scoped manifest history, four-dimensional evidence assessment and locked options declaration classification implemented. Official response schemas/fake transports, execution-owner composition and actual account/runtime evidence remain pending. No broker/account calls. |
| 5 Durable lifecycle and operation | Additive synthetic trial journal, immutable history, exact-head compare-and-append, restart reconstruction and recorded-script replay wiring implemented. Full normalized options ledger, broker reconciliation, expiry/assignment incidents, production recovery and continuous scheduling remain pending. No production migration. |
| 6 Deployment preparation and handoff | Static preparation report, research CI, dated public cost assumptions and actual local age backup/restore helper tests implemented. Full options artifact backup, runtime benchmark, off-host restore, actual costs, heartbeat and complete operator surface remain pending. Existing DigitalOcean manifests preserved. |

All other limitations in [options research](options-research.md) remain binding.
Exact terminal payoff tests for verticals/condors do not establish package execution,
native multi-leg support or account permission. Standalone `trader` integration
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

No protected production behavior, monetary limits or authorization changed. The following
foundation continuation supersedes that checkpoint's pending engineering inventory.

## Data, numerical research and durable-history foundation continuation

Baseline `dde6e4610d951502b3fc5846f4fe518a897b2dcc`; records interface checkpoint
`a7ed602d06aa390362720ccc69be2a0f9fd2da33`. Verification date: 2026-09-18.

Implemented immutable point-in-time options records, a strict versioned six-kind codec,
content-addressed exact-value Parquet storage, and a separately locked Python 3.12 research
environment with QuantLib 1.43 and DuckDB 1.5.5. Numerical research now includes bounded
European analytical and American finite-difference pricing, dividend-aware inputs, explicit
Greek units, convergence checks, full repricing stress and exact terminal structure payoffs.
These are engineering models and fabricated fixtures, not historical trading evidence.

The additive `0006_options_trial_history` migration provides an immutable, account-scoped
synthetic trial journal. Restart reconstruction preserves consumed losses; profits cannot
replenish them, incomplete reservations cannot shrink, and populated history blocks downgrade.
Lease release now preserves monotonically increasing fencing tokens. Journal writes recheck
lease freshness after acquiring the database lock and again before commit. Only temporary
test databases were migrated. Replay and production lifecycle integration remain unfinished.

Independent review and failing regressions exposed and corrected point-in-time revision
ambiguity, future nested quote availability, unresolvable numerical bumps, unstable
finite-difference outputs, stale lease timing, and compressed-dataset budget bypasses.
Publication and read validation now use symmetric record/manifest limits and a global decoded
byte budget. The architecture import guard was preserved; pricing uses explicit typed field
access rather than dynamic access. Existing append-only tests now require all 49 guards.

Also added a deterministic static deployment-plan command, a dated public/session capability
audit, and a research CI definition. The deployment report reports missing runtime evidence,
costs and authorization honestly. CI was not dispatched remotely. Three local workers
performed isolated parser, storage, CI, documentation and read-only review work; coordinator
review/integration retained ownership of numerical, economic, persistence and lease changes.

### Fresh local verification

Tests include preserved pre-existing working-tree changes, not a clean-checkout result.
The core interpreter remains Python 3.12.13 in the temporary verification environment;
the separate research interpreter is also Python 3.12.13. Python 3.13/3.14 were not tested.

| Check | Result |
| --- | --- |
| Full suite, branch measurement and unchanged 80% gate | **5,008 passed, 11 skipped**, **86.80%** overall, 284.47 seconds. |
| Explicit per-file critical branch gate | Passed; inventory now includes execution leases and the durable trial journal. |
| Mandatory isolated QuantLib/DuckDB research tests | **92 passed**, with both pinned backends available; no backend skips. |
| Focused lease/journal branch run | 13 passed; lease 100% branches, trial journal 41/42 branches. |
| Architecture checks after explicit-field pricing correction | 168 passed. |
| Append-only migration checks | 53 passed. |
| Deployment and non-mutating SBOM checks | 24 passed. |
| Ruff and Mypy | Passed; 216 source files. |
| Bandit | No findings; existing `nosec` comment warnings remain. |
| Root and research locked dependency audits | No known vulnerabilities; this is not a vulnerability-free guarantee. |
| Temporary root/research CycloneDX validation | Both schema 1.6 inventories valid; incomplete-root-graph warnings remain. |
| Source distribution and wheel | Built to a temporary destination. |
| Diff whitespace and preserved artifact hashes | Passed; staged root lockfile and dirty tracked SBOM unchanged. |

The 11 core-suite skips are the deliberately optional DuckDB storage module and QuantLib
numerical cases; the research suite separately executes them. The existing Starlette/httpx
deprecation warning remains. Verification artifacts reside in
`/private/tmp/robinhood-options-foundations.tUIbHH`. No tracked SBOM was regenerated.
`age` is unavailable locally, so an end-to-end encrypted backup/restore drill is not claimed.
Prior Docker Compose availability limitations remain; static tests are not deployment proof.

All six milestone status rows and separate readiness verdicts above remain binding. No broker
or account calls, orders, paid services, Cloud jobs, infrastructure changes, production-state
inspection, deployment or production migrations occurred.

## Scoped capability-evidence continuation from `cf09c6d`

The existing capability manifest and loader now support version-2 verification history,
without changing version-1 artifacts or the legacy order validator. Public, session, account
and runtime witnesses are independent and operation-specific. Schema and opaque identity
bindings, expiry, historical denials and synthetic status are enforced. No current authenticated
account/runtime witness was acquired or asserted.

Known options declarations now receive an explicit metadata-only options classification and
remain locked. The legacy single-category capability gate cannot unlock options. The new
assessment's production-eligibility property is permanently false, including when test
witnesses satisfy all dimensions. A review-found duplicate-dimension reporting defect was
reproduced with a failing test and fixed; exact types and all four distinct dimensions are
required. Scoped re-review confirmed both this fix and the legacy-gate denial.

See [scope, semantics and remaining integration](options-capability-verification.md).
This completes the evidence-model slice, not the broker-integration milestone or live readiness.

Final refreshed full suite: **5,068 passed, 11 optional-backend skips**, **86.90%** overall
coverage, 284.50 seconds. The expanded **90% per-file critical branch gate passed**;
`capabilities/verification.py` has **18/18 branches covered**. The separate pinned research
selection again passed **92 tests with no skips**. Its independent CI review also ran that
selection under a global Python socket-denial harness and confirmed 92 passes.

Ruff, Mypy (217 source files), Bandit, both offline lock checks, final wheel/source build and
diff checks passed. The previously recorded locked dependency audits and temporary SBOM
validation apply unchanged; no dependencies changed in this evidence slice. Existing Bandit
comment warnings and the Starlette/httpx warning remain. The final coverage artifact is
`/private/tmp/robinhood-options-foundations.tUIbHH/verified-final-coverage.json`.

Standalone deployment-plan and capital-feasibility commands were exercised locally. For the
fabricated $0.10 premium, 100 multiplier and $1 bounded fee reserve, the $100 capital tier
admits zero units under its $0.50 per-trade budget. This is a necessary filter, not a final
pretrade check, observed market opportunity or recommendation to add capital. All tiers
remain production-ineligible and the economic verdict remains `ECONOMIC_NO_GO`.

Existing staged root `uv.lock`, the dirty tracked SBOM and all unrelated working-tree files
were preserved. Local checkpoints were not pushed. No external account/broker activity,
Cloud jobs, deployment, production migrations or real-money actions occurred.

## Call/put and durable recorded-session continuation

Baseline `7155612d708ab59642791adfc827bb088e8c9c42`; local verification 2026-09-18.
This continuation is still partial implementation, not completion of all six milestones.

- Long puts now use the common underlying features and purchased-option lifecycle. All
  three bearish conditions are required; invalid, missing, mixed and flat signals hold.
  `options-replay` and `export-options-fixture` accept `--option-kind call|put`. Eighteen
  independent golden tests retain the original call result hashes across nine scenarios
  and two research-capital tiers.
- Pure replay can evaluate an immutable script prefix without consuming future events or
  changing its v1 identity. The new recorded-session API connects that same replay to the
  existing journal, reserving risk before simulated acceptance and reconstructing exact
  cash/order state after restart. Every checkpoint is paused; explicit resume and expected
  count are required for one next event. One script per isolated account is intentional.
- Journal snapshots bind verified events, trial state and exact head hash. Compare-and-append
  is atomic under the existing execution lease. Independent review found and reproduced a
  state-preserving-writer race and cross-account checkpoint-ID collision; test-first fixes
  bind the exact journal head and account identity. Reviewers rechecked both corrections.
  No historical replay hashes, journal payload schemas, ledger migrations or risk limits changed.
- Added a strict fixture-only [Massive REST row parser](options-import-contracts.md). It
  preserves Decimal prices and raw provider size units and nanosecond integers. It neither
  converts ambiguous sizes to contracts nor fabricates contract/availability context.
  Direct construction's Decimal invariant was corrected after a failing review regression.
- Added [dated public cost assumptions](options-operating-costs.md) and real local
  [encrypted helper tests](options-backup-validation.md). The latter uses an official,
  digest-verified age v1.3.2 binary in a temporary directory, ephemeral keys and synthetic
  SQLite/research artifacts. Independent decryption checks recovered data, while wrong-key
  and damaged-ciphertext tests deny restoration. No installed service or host was changed.

The coordinator owns every strategy, risk, persistence and runtime change. Local workers
handled only provider parsing, docs, isolated tests and independent review; no Cloud job ran.
Failed tests preceded core put/prefix/session implementation and the two concurrency/identity
corrections. The additional adversarial/golden tests are explicitly post-implementation
acceptance tests, not misrepresented as the original red phase.

### Verification for this continuation

Selected independent review suite: 127 passed. Initial focused branch run: 139 passed.
Final full core suite: **5,211 passed, 11 optional-backend skips**, **87.02% overall
coverage**, 324.59 seconds. The expanded **90% per-file critical branch gate passed**:
recorded-session runtime **26/26**, trial journal **51/52**, and replay **45/48** branches.
The socket-denied runtime/parser/CLI selection subsequently passed **65 tests**.
Ruff, Mypy (221 source modules plus the branch checker) and Bandit pass, with the existing
Bandit comment warnings. Both locked dependency audits report no known vulnerabilities;
both offline lock checks pass. Separate pinned QuantLib/DuckDB research: 92 passed without
skips. Actual encryption plus deployment/SBOM checks: 28 passed. DigitalOcean shell syntax
passes; installed Docker still lacks usable Compose, so rendered Compose verification is
not claimed. Both temporary CycloneDX 1.6 inventories validate (104 core, 58 research
components); the final source distribution and wheel build passed. Inventories are not
claimed to establish a complete dependency graph. Working-tree results include preserved
pre-existing changes; no remote CI or clean-checkout run is claimed. The existing
Starlette/httpx warning remains. Coverage artifacts are `full.json` and `full-pytest.log`
under the temporary directory below. User lock/SBOM hashes remain unchanged.

A separate-process saved put export/replay settles the fabricated $2,500 fixture to $2,504,
with $1 fees and false production/promotion flags. These are exact engineering expectations,
not actual or expected trading returns. Artifacts are under
`/private/tmp/robinhood-options-completion.5UUs9v`, not tracked evidence destinations.

### Remaining engineering versus external evidence

Still unfinished credential-free engineering: complete options pretrade composition and
multi-episode portfolio accounting; normalized legs/collateral/settlement persistence;
expiry, assignment and unexpected-share incidents; full options reconciliation; official
response parsers/fake execution transports; continuous scheduling/monitoring/operator CLI;
complete options artifact backup/rollback; package execution; preregistered research and
uncertainty scorecards. This is not an assertion that only permissions remain.

Separately unresolved external evidence: approved/licensed point-in-time market history,
empirical economic validity, account-specific official capability and deployed authentication,
real calendars/fees/restrictions, actual runtime benchmark, off-host recovery and alert delivery.
Their absence cannot be repaired by fabricated fixtures, extra capital, a plugin, or passing CI.
No broker/account calls, paid data, purchases, Cloud dispatch, deployment, production migration
or live activation was authorized or performed. Technical readiness remains NOT_READY;
economic readiness ECONOMIC_NO_GO; account/runtime capability UNVERIFIED; live NOT_AUTHORIZED.

## Databento credential and metadata preflight — 2026-09-18

User created a Databento account, rotated a key that had been shared in chat, and
entered the replacement through a hidden native local dialog. The replacement was
never placed in commands, chat output, Git, configuration snapshots or Cloud tasks.
It is a restricted plaintext credential file outside Git, not an encrypted vault.
The old exposed key was not used. The operator reports $125 unused credit; no API
balance verification is claimed.

Added an isolated credential helper and CLI with default-off network access. Only
one fixed official free `metadata.get_cost` GET is exposed per explicit invocation;
no time-series, batch, live-data, account-management or broker operation exists in
the helper. Requests require explicit symbols, schema and UTC dates. Responses are
bounded, Decimal-parsed and stripped to safe fields. No redirects, environment
proxies, retries, raw responses or exception details cross the boundary.

Test-first coverage established missing APIs/CLI before implementation. Independent
read-only review found main/sibling Git checkout exclusion and hard-linked-key
retry defects; six new failing regressions reproduced them before fixes. Both
findings were re-reviewed as resolved. A native-dialog syntax failure was caught
by actual macOS compilation, reproduced in a new failing compiler test, fixed,
and followed by successful local credential entry. Mocks alone did not establish
that native UI integration worked.

Final targeted suite: 68 passed. Broader diagnostics/CLI/architecture selection:
392 passed. Full suite (collected before adding the last compiler regression):
5278 passed, 11 optional-backend skips, one existing Starlette/httpx warning,
87.09% overall coverage, 392.97 seconds. The critical 90% per-file branch gate passed.
Full Ruff and Mypy (223 source files) pass. Scoped Bandit is clean; full Bandit
passes with the pre-existing suppression-comment warnings. Dependencies and root
lockfile were not changed; no new dependency audit/SBOM regeneration is claimed.
Artifacts: `/private/tmp/databento-preflight.oFsjrD`.

Four real, non-billable metadata estimates established authentication and scoped
prices only. [Exact scopes and estimates](databento-preflight.md) include $141.8456
for 2025 SPY.OPT minute quotes and $396.3368 for 2023–2025, both above reported
credits before other inputs. No market history was downloaded and no credit use
or purchase was authorized. Retention/non-display/Cloud rights, entitlements,
research selection, genuine economic evidence, remaining operational engineering
and live readiness remain unresolved. Existing staged `uv.lock`, dirty SBOM and
unrelated work were preserved unchanged. These results are local, not Cloud CI.

## Options observation, expiry and paused monitoring — 2026-09-18

Continuation from `690a591`, still a partial implementation of the migration.
Added immutable normalized account observations, exact cash/position/order/fill/
share/settlement/lifecycle comparisons, complete-package ownership checks, explicit
complete-calendar expiry deadlines and a bounded continuous read-only observer.
The observer uses the existing canonical configuration, scheduler, alerts and
append-only reconciliation store. Legacy schemas, historical hashes and risk
limits were not changed. See [scope and remaining work](options-operational-monitor.md).

Failing tests preceded each new core module. Independent review reproduced two
important false-clean cases: clock rollback above the source timestamp and fills
on pre-submission order states. Seven failing regressions preceded the fixes;
scoped re-review confirmed both were addressed. Additional post-implementation
acceptance tests cover partial complete packages/missing protective legs and DST.
All new observations use synthetic inputs; socket/DNS denial protects their tests.
Real temporary SQLite tests verify persistence, append-only results and paused restart.

Final full suite: **5,399 passed, 11 optional-backend skips**, one existing
Starlette/httpx warning, **87.68% overall coverage**, 342.05 seconds. The **90%
per-file critical branch gate passed**, including the new modules: account records
34/34, expiry 44/44, reconciliation 97/98 and monitor 42/42 branches. Separate pinned
QuantLib/DuckDB research selection: **38 passed**. Full Ruff and Mypy (228 source
files) pass; Bandit passes with existing suppression-comment warnings. Root locked
dependency audit reports no known vulnerabilities, `uv lock --check` passes and
DigitalOcean shell syntax passes. Existing manifest/SBOM tests passed in the full
suite; tracked SBOM was not regenerated. Docker Compose rendering remains unverified
because the installed CLI does not provide usable Compose. No clean-checkout or
remote CI result is claimed. Artifacts: `/private/tmp/options-operational.70j5uy`,
especially `pytest-final.log` and `final.json`.

The main agent owns all reconciliation/lifecycle/runtime changes; local delegated
work was limited to documentation, coverage discovery checks and read-only review.
Existing staged `uv.lock`, dirty SBOM and unrelated work were preserved. Their lock
and SBOM hashes match the baseline. No production state was migrated and no service
was installed or started.

The user attested historical OPRA private automated-use/local-retention permissions,
then supplied general Website Terms of Use. Public agreement review does not verify
the account's OPRA-specific terms; the public Exchange Data Policy addresses CME.
[Acquisition notes](databento-acquisition-next-steps.md) distinguish the attestation,
supplied document, unresolved rights and missing spending authorization. No credentials
were read, authenticated calls made, market history downloaded, credits spent, Cloud
jobs dispatched, broker orders placed or deployment changes made in this continuation.

This observer is not full cash-flow/reservation reconstruction or pretrade risk
admission, and a clean result grants no execution authority. Engineering still includes
complete risk/loss-latch composition, normalized lifecycle-ledger recovery, official
broker parsing and locked execution integration, service/operator composition and the
preregistered economic-evidence pipeline. Technical readiness remains **NOT_READY**;
economic readiness **ECONOMIC_NO_GO**; account/runtime capability **UNVERIFIED**;
live **NOT_AUTHORIZED**. Every observer status remains paused and live-unsupported.

## Supplied Databento definitions and native staging — 2026-09-22

The operator supplied the approved definitions-only download. All provider-listed sizes
and SHA-256 hashes match; the original Downloads folder is unchanged and a verified private
no-overwrite raw copy is retained outside Git. Full streaming decode, independent byte-count
arithmetic and private Parquet verification agree on **6,821,768 definition records**,
**224,696 distinct raw symbols**, **752 receive dates** and **1,433 Parquet parts**. Counts
include repeated definition updates, not trades or permanently unique contract identities.
The corrected verifier passed on the complete real staged archive, not only fixtures.

The existing separately locked research environment now pins `databento-dbn==0.69.0` and
`zstandard==0.25.0`; the root dependency lock and executable trading configuration are
unchanged. The standalone local importer does not touch the user's pre-existing CLI edits.
Native staging preserves integer prices, nanosecond timestamps, record order and unknown
values. It does not construct executable canonical option contracts. No actual records,
provider URLs, keys or account identifiers are added to Git, CI or Cloud tasks.

Test-first implementation covered batch scope/hashes, bounded metadata and full DBN/Zstd
EOF validation, private all-or-incomplete publication, CLI behavior and no-network boundaries.
Independent source-format audit informed version/framing rules. The final fresh-context
review found JSON hash/parse and Parquet hash/query races; seven new regressions failed before
fixes and the full focused importer selection then passed **70 tests**. The implementation
now parses/hashes one JSON snapshot and queries the exact hashed Parquet snapshot. Nested
manifest/profile/provenance schemas and false eligibility flags are also strictly checked.
This review covered the local importer change, not the entire unfinished trading platform.

### Decisions and remaining limits

- Retain native research staging, not relaxed executable records; explicit enrichment is
  still required. The cost of this boundary is additional downstream normalization work.
- Retain provider partial-symbol declarations as limitations, not rejection or complete-chain
  proof. Affected periods cannot be trusted without later coverage/mapping checks.
- File hashes establish internal byte consistency, not independent provider authenticity.
  Forged but self-consistent upstream files are outside that guarantee.
- The coordinator re-graded malformed nested manifests from Minor to Important because
  a positive verification verdict must not carry arbitrary historical-availability claims.
- Deferred minor: an early destination-open failure in `preserve_batch` can leave its source
  descriptor open until process exit. Repeated failed calls in a persistent process could
  exhaust descriptors; this does not grant data eligibility or trading authority.

The archive contains **definitions, not bid/ask quotes, underlying prices or strategy returns**.
Its metadata lists217,732 partial symbols; conditions list779 available,2 degraded,3 missing
dates. Mapping conflict resolution, eligible-session coverage, historical availability and
canonical contract enrichment remain unverified. Quotes, underlying/event inputs and any
additional data spending need their own scope, estimates and approval; no further purchase
was made. The earlier $11.44 portal price is not a verified final bill.

Full risk/loss-latch composition, lifecycle/reservation/collateral/settlement recovery, official
broker parsing and locked execution integration, continuous service/operator composition,
package execution and preregistered economic research remain unfinished. The existing
evidence-duration/sample requirements are not waived by a three-year definitions download.
Technical readiness **NOT_READY**; economics **ECONOMIC_NO_GO**; account/runtime capability
**UNVERIFIED**; live **NOT_AUTHORIZED**. No broker calls, credentials, Cloud execution,
production migration, deployment, live activation or changed risk limits in this continuation.

Verification artifacts: `/private/tmp/options-definition-validation.RauLUe`.
Full-suite and final gate results are recorded below when complete.
