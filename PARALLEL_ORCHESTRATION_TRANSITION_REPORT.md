# Parallel Orchestration Transition Report

Snapshot date: 2026-09-17 (UTC)

Repository: `Jed1122/Robinhoodtradingbot`

Integration branch: `codex/continue-implementation-from-commit-7c4dcd1`

Attestation and Cloud-review base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`

Verified deployed source: `32ab71fc3c845c56068179fed98cf4a9eb80461e`

Previous CI-verified integration base: `095e5c02b01aea95fd7858a549a7765e7b0488c0`

Current implementation wave: operator-approved, fail-closed membership and simulation input
validation from exact base `095e5c0`; no deployment or broker operation is part of this wave.

Release state: **NO-GO for live trading**

This implementation wave performs no new broker, ledger, credential, or host check. Operational
facts below remain the separately authorized 2026-09-15 snapshot, not a fresh deployment assertion.

This report transitions the existing system to centrally governed local and Codex Cloud orchestration. It does not restart or redesign the project. The executing-image-attestation release is committed, CI-verified, and deployed in paused mode. Two isolated Codex Cloud documentation reviews, one CI-hardening task, and two synthetic fixture tasks completed and were integrated centrally. Their point-in-time findings do not supersede the newer operational evidence recorded here. Operator-authorized workstation reauthorization and server credential rotation restored the bounded broker-read connection on 2026-09-15; live trading remains blocked.

## CURRENT SYSTEM

The repository contains a broker-neutral, fail-closed trading-system foundation with canonical configuration, pure risk and sizing, durable audit/promotion records, capability-separated broker protocols, deterministic offline tooling, a write-incapable connected-shadow probe, and a paused DigitalOcean deployment.

The public operator surface is not a live trading application. Live CLI paths remain locked, the default process exposes health/metrics only, and no provider-connected equity order adapter or complete live execution composition exists. Prediction-market live execution is explicitly unsupported. No live order has been placed by this system, and the project makes no profitability claim.

The funded Agentic brokerage account does not change the software gate state. A funded account is necessary operational context, not promotion evidence or authority to trade.

## CURRENT ARCHITECTURE

The implemented boundaries are:

- `domain/` and `config/`: canonical types, modes, instruments, and strictly validated configuration.
- `capabilities/` and `brokers/`: independently injectable read/review/place/cancel contracts and provider mappings.
- `strategies/`, `portfolio/`, and `risk/`: broker-neutral decision, allocation, sizing, loss, drawdown, and pretrade logic.
- `execution/`: broker-neutral order lifecycle, idempotency, and persisted non-live execution service.
- `reconciliation/`: comparison and drift classification without a complete provider/live composition.
- `persistence/`: Alembic-owned async SQLite schema, append-only evidence, unit-of-work boundaries, and journals.
- `research/` and `simulation/`: deterministic research/backtest foundations whose remaining bias and outcome requirements are documented.
- `authorization/` and `runtime/`: signed authorization/lease primitives, locked live factory, paused service, and bounded connected probes.
- `monitoring/` and `reporting/`: structured status, promotion preview, health, readiness denial, and live-disabled metrics.
- `infra/digitalocean/`: image deployment, rollback, backup/restore, Terraform, and cloud-init assets.

Provider transports remain outside strategy, risk, portfolio, and domain logic. Read, review, place, and cancel capabilities are separate. The only connected equity-shadow path is locally write-incapable even though its OAuth credential must be treated as trading-capable.

## COMPLETED WORK

The following are complete within the stated scope, not as proof of live readiness:

- Canonical domain and configuration graph with paused and live-disabled defaults.
- Non-reducible safety envelope and strict config validation.
- Pure Decimal-based sizing, exposure, loss, drawdown, activity, and ordered pretrade evaluation.
- Append-only persistence foundations, migrations, audit records, identity-bound observations, and submission journal.
- Broker-neutral order-state machine and durable non-live execution behavior with reconciliation requirements.
- Deterministic offline/replay foundations and local fixture-based tests.
- Seven authenticated equity read mappings and dual local/transport allowlists for the connected-shadow probe.
- Signed authorization, bounded lease, promotion-policy, and code/config identity primitives.
- Paused, health-only container profile with no credentials or host volumes by default.
- Transactional image-digest deployment and last-known-good rollback foundation on DigitalOcean.
- Root-owned, canonical, per-release executing-image attestation deployed and verified from an unprivileged container, including rejection when the artifact is absent.
- Portable paused-service denial test covering both plain and ANSI-colored diagnostics, while asserting that the server never starts without `--paused`.
- Two completed, centrally reviewed Codex Cloud audits with separate owned documentation paths and no production-code changes.
- Centrally integrated, CI-verified Cloud workflow hardening with independent security, locked-dependency, and configuration checks.
- Primary-owned corporate-action filtering correction: instrument isolation, effective-as-of UTC
  dates, and canonical UTC query validation. Regression tests first reproduced 11 failures; the
  corrected adjustment suite now has 23 passing cases, including independent late-announcement tests.
- Centrally reviewed Cloud membership tests and primary-owned strict input validation: UTC
  membership/lookup times, exact booleans and immutable tuple records, nonblank IDs, and rejection
  of contradictory same-key events. Identical duplicates and distinct-time changes remain valid;
  source provenance and interval coverage remain open.
- Centrally reviewed Cloud fill-contract tests with exact BUY/SELL accounting, forced branches,
  mixed seeded outcomes, distinct-seed control, and restored global RNG state. Full simulation
  lifecycle, calibration, and outcome evidence remain incomplete. Primary-owned fill/cost input
  validation now rejects malformed numeric/typed inputs and invalid arithmetic results without
  changing valid seeded outcomes or cost formulas.
- Operator-authorized credential rotation with account-match and private-permission verification, a retained root-private previous store, and one successful write-incapable server probe.
- Read-only health, metrics, status, live-readiness, and promotion-preview surfaces.
- CI definition for Python 3.12, 3.13, and 3.14 with Ruff, strict mypy, branch coverage, Bandit, and lock validation.

## PARTIAL WORK

- **Equity provider support:** seven reads exist; nonempty position/order mapping and provider review/place/cancel adapters do not.
- **Crypto provider support:** DTO, signing, read, and write plumbing is fixture/mock verified but not authenticated externally.
- **Research:** deterministic comparison, walk-forward, cost, benchmark, and Monte Carlo components exist; point-in-time membership, corporate-action/interpolation provenance, PBO/multiple-testing controls, realistic fill/exit outcomes, and accepted evidence remain incomplete.
- **Public backtest/simulation CLI:** current commands expose deterministic identity output rather than a complete operator composition of the deeper engines.
- **Paper runtime:** fail-closed boundaries and evidence types exist, but there is no complete, validated decision/execution/outcome cycle that can generate eligible promotion evidence.
- **Connected shadow:** a bounded, write-incapable probe exists, but current records lack validated data and complete outcomes and are therefore ineligible.
- **Execution and reconciliation:** strong broker-neutral foundations exist; provider-connected live composition, restart-safe recovery, and nonempty external shapes do not.
- **Live runtime:** preflight primitives and a locked factory exist; cycle composition and mode transition remain intentionally unavailable.
- **Scheduler and operations:** skeletons and runbooks exist; production leadership, reconciliation scheduling, and alert-operability evidence are incomplete.
- **Infrastructure as code:** Terraform and cloud-init assets exist but have not been validated end to end against the current manually created 2 GB Droplet.
- **Backup/restore:** scripts and tests exist; external storage, key custody, and an operator-observed restore drill remain prerequisites.
- **Dashboard/UI:** no separate dashboard exists; only health, readiness, metrics, and CLI status surfaces are implemented.

## CURRENT BLOCKERS

1. The broker connection is restored, but connected-shadow evidence remains non-promotable. The single post-rotation probe verified authenticated reads, broker health, executing-image identity, and zero-state reconciliation, while reporting `strategy_ineligible`, `live_data_invalid`, and `outcomes_incomplete`. No diagnostic market-history probe was requested. Repeating this probe would not resolve the missing research/data/outcome evidence.
2. Verification is complete for the paused release, not for live operation. Host hardening, infrastructure-as-code conformance, off-host backup, and a full operator-observed recovery drill still require their own evidence.
3. Research/data requirements and accepted research identity are incomplete.
4. The 2026-09-15 read-only promotion preview reported an intact ledger with five ineligible shadow observations across four separate identity series, two rejected research assessments, zero eligible observations, and zero live authorizations, live leases, execution leases, or submission attempts. Inventory totals do not combine identities for promotion.
5. Paper requires 100 eligible observations; shadow requires eligible observations on seven distinct UTC dates. These elapsed evidence gates cannot be compressed or fabricated.
6. Nonempty equity response mappings and authenticated review/place/cancel provider evidence are absent.
7. No provider-connected live adapter, complete live application, durable host leadership path, or restart-safe live recovery composition exists.
8. Current external security, manual review, and runtime-control attestations have not been assembled for live promotion.
9. Codex Cloud CLI access works. `RESEARCH-GAPS-001`, `IAC-AUDIT-001`, `CI-HARDENING-002`,
   `PIT-FIXTURES-002`, `SIM-FILL-FIXTURES-002`, `PIT-VALIDATION-003`, and `SIM-VALIDATION-003`
   returned bounded diffs and were integrated
   centrally. Remaining review findings and complete research/runtime implementation are not implied.
10. The remote default branch is materially behind the integration branch; any future Cloud task launched from the default branch would start from stale architecture.

## CURRENT GO / NO-GO STATE

| Activity | State | Reason |
|---|---|---|
| Local implementation and deterministic tests | GO | No external side effects; existing guardrails remain active. |
| Static/read-only audits and secrets-free Cloud tasks | GO | Seven Cloud tasks integrated; continue to require exact revision, isolated worktree, frozen interfaces, and bounded ownership. |
| Paused health-only service | Last verified GO on 2026-09-15 | Healthy, readiness-denied, live-disabled, and no credential/ledger mounts at that check; not rechecked by this wave. |
| Explicit bounded read-only evidence probe | Verified once; separate authority required for another run | The post-rotation probe succeeded but remained non-promotable. The local client is write-incapable, but the OAuth token remains trading-capable. No recurring job is authorized or installed. |
| Paper promotion | NO-GO | No accepted research composition or eligible 100-cycle evidence set. |
| Shadow promotion | NO-GO | No qualifying paper promotion and no eligible seven-UTC-date shadow set. |
| Micro-live | NO-GO | Provider writes/live composition and promotion/manual/runtime evidence are absent. |
| Normal-live | NO-GO | Micro-live and the larger observation/time gates are absent. |
| Prediction-market live execution | NO-GO / unsupported | No live placement capability exists. |

Funding the account does not override any NO-GO state.

## CRITICAL PATH

1. **Completed:** restore a green integration base by fixing the portable CLI test without changing production behavior.
2. **Completed for paused operation and one bounded broker-read probe:** review, test, commit, build natively for amd64, and deploy the root-attested executing-image identity change. Restore OAuth through separately authorized workstation bootstrap and server credential rotation. The successful probe added only ineligible diagnostic evidence; no preflight or promotion check was weakened.
3. Resolve point-in-time data, corporate-action/interpolation provenance, realistic fill/reject/partial-fill/latency assumptions, PBO/multiple-testing controls, and stage-independent research identity.
4. Compose a complete durable paper decision/execution/outcome cycle and collect 100 eligible observations.
5. Compose a qualifying bounded shadow cycle with validated data, complete outcomes, reconciliation, and known order state; collect evidence over seven distinct UTC dates.
6. Under one authoritative owner, add captured authenticated provider schemas, nonempty mappings, review/place/cancel evidence, adapters, host leadership, reconciliation, and cancel-only recovery.
7. Assemble current security, manual-review, and runtime-control attestations.
8. Conduct a separately authorized, tightly capped micro-live review. Normal-live remains a later promotion decision with its own observation and elapsed-time gates.

Steps 4 and 5 contain irreducible observation/time requirements. Parallelism can improve preparation and review; it cannot make missing evidence valid.

## PARALLELIZATION MAP

The primary orchestrator owns the integration branch, dependency graph, protected components, central verification, deployment, and release decision. Independent agents use exact commits and isolated worktrees.

| Workstream | Dependency | Parallel status | Owner boundary |
|---|---|---|---|
| CI portability test | Committed base | Completed centrally at `32ab71f` | Test file only; production CLI unchanged. |
| Attestation adversarial review | Current attestation commit/diff | Independent review now | Read-only or tests/docs only; deploy helper/runtime implementation protected. |
| Research-bias gap analysis | `a58f6eb` | Cloud review completed | Review/design only; strategy selection and promotion decision protected. |
| Point-in-time membership contract | `93b28f4` | Cloud fixture tests integrated and locally verified | Tests/docs only; source coverage and provenance remain unverified. |
| Corporate-action primitive filters | `93b28f4` | Primary correction locally verified | Existing interface retained; no provider/evidence integration. |
| Simulation fill-model contract | `93b28f4` | Cloud tests integrated and locally verified | Tests/docs only; no pricing, strategy, risk, or execution changes. |
| Membership and fill/cost input validation | `095e5c0` | Two Cloud test diffs centrally integrated; full local verification passed | Independent synthetic tests only; primary owns all production validation. |
| IaC drift and recovery audit | `a58f6eb` plus sanitized inventory | Cloud review completed | Read-only; no DigitalOcean or state mutation. |
| Coverage/observability gap inventory | Committed base | Independent now | Read-only report or isolated non-risk tests. |
| Paper composition | Accepted research/data interfaces | Sequential protected work | Primary owner only. |
| Broker writes and reconciliation | Captured authenticated evidence | Sequential protected work | Primary owner only. |
| Live runtime and promotion | All preceding gates | Sequential protected work | Primary owner plus explicit operator approval. |

### Completed centrally: CI-PORTABILITY-001

Completed at `32ab71fc3c845c56068179fed98cf4a9eb80461e`; GitHub Python 3.12-3.14 checks are green. Do not redispatch this completed task.

- **Objective:** make the paused-service missing-flag test portable across Python 3.12-3.14/Typer behavior without changing production code.
- **Owner:** one Cloud task.
- **Base revision:** `a63247eca2022a80adb8b76e47ac8c9d964ed827`.
- **Owned paths:** `tests/integration/cli/test_paused_service.py` only.
- **Read-only dependencies:** `src/trading_bot/cli/main.py`, `pyproject.toml`, `uv.lock`, CI workflow.
- **Frozen interfaces:** CLI flags, exit behavior, paused-service callback, dependency versions.
- **Prohibited changes:** production files, lockfile, risk/config/runtime semantics, external calls.
- **Acceptance criteria:** absent `--paused` exits nonzero, diagnostic names `--paused`, and a monkeypatched `uvicorn.run` proves the server was never started.
- **Verification:** targeted test under Python 3.12/3.13/3.14, then full CI commands.
- **Return contract:** commit SHA, exact diff, test outputs, assumptions, and blockers.

### Completed Cloud task contract: RESEARCH-GAPS-001

Task: [Document research-evidence gap review](https://chatgpt.com/codex/tasks/task_e_6aa8222d7154832da2b71b027131115b). Reviewed output: [research-gaps-001.md](docs/reviews/research-gaps-001.md). Exact dispatch base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`. Only the assigned document changed.

- **Objective:** produce a traceable blocker matrix and acceptance tests for point-in-time membership, corporate actions, interpolation provenance, PBO/multiple testing, and execution outcomes.
- **Owner:** one Cloud task.
- **Base revision:** current committed integration revision at dispatch time.
- **Owned paths:** a new document under `docs/reviews/` only.
- **Read-only dependencies:** `research/`, `simulation/`, configs, tests, and strategy-research documentation.
- **Frozen interfaces:** canonical config schema, research identity, promotion flags, strategy/risk behavior.
- **Prohibited changes:** code, thresholds, acceptance decisions, external data calls, credentials, claims.
- **Acceptance criteria:** every gap maps to evidence, an owner, a deterministic test, and an explicit pass/fail criterion.
- **Verification:** link/path validation and orchestrator review against current code/tests.
- **Return contract:** commit SHA, matrix summary, unresolved ambiguities, and proposed follow-on contracts.

### Completed Cloud task contract: IAC-AUDIT-001

Task: [Perform documentation-only infrastructure drift audit](https://chatgpt.com/codex/tasks/task_e_6aa822a2bfac832da021612e65a8e28f). Reviewed output: [iac-audit-001.md](docs/reviews/iac-audit-001.md). Exact dispatch base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`. Only the assigned document changed. Its pre-deployment platform and release-drift findings are resolved by the native amd64 deployment below; its unverified host/IaC/recovery findings remain open.

- **Objective:** compare Terraform/cloud-init/runbook assumptions with a sanitized description of the paused 2 GB host and report drift; make no infrastructure changes.
- **Owner:** one Cloud task.
- **Base revision:** current committed integration revision at dispatch time.
- **Owned paths:** a new document under `docs/reviews/` only.
- **Read-only dependencies:** `infra/digitalocean/`, Docker/Compose files, operations/disaster-recovery/incident docs.
- **Frozen interfaces:** live-disabled defaults, firewall policy, deployment paths, rollback model.
- **Prohibited changes:** cloud/API calls, secrets, state files, deployment, Terraform apply, production code.
- **Acceptance criteria:** prioritized drift list, safe remediation dependencies, rollback effects, and exact verification commands.
- **Verification:** static checks only; primary orchestrator validates against sanitized current host facts.
- **Return contract:** commit SHA, findings by severity, assumptions, and blocked live checks.

### Ready Cloud task contract: ATTESTATION-REVIEW-001

- **Objective:** adversarially review the committed attestation change for symlink, ownership, mode, canonicalization, digest-binding, rollback, race, and cleanup failures.
- **Owner:** one Cloud task after the patch has an exact commit.
- **Base revision:** select an exact reviewed integration SHA at dispatch; the attestation implementation is already committed in `a58f6eb`. Do not use a dirty worktree.
- **Owned paths:** new or existing attestation/deployment tests and review documentation only, as assigned explicitly.
- **Read-only dependencies:** `src/trading_bot/code_identity.py`, runtime integrations, Dockerfile, Compose, and deployment helper.
- **Frozen interfaces:** artifact schema, root ownership, immutable digest binding, paused deploy order, fail-closed behavior.
- **Prohibited changes:** deployment/runtime implementation, external host access, credentials, live settings.
- **Acceptance criteria:** adversarial cases have deterministic tests or documented blockers; no guardrail is weakened.
- **Verification:** focused identity/deployment/runtime tests, Ruff, mypy, then the full suite.
- **Return contract:** commit SHA, findings, tests added, commands/results, and residual risks.

### Completed and centrally verified Cloud task contract: CI-HARDENING-002

Task: [Improve CI workflow for Robinhood trading system](https://chatgpt.com/codex/tasks/task_e_6aa8760eafd8832dbc1ab7b5cbcb7b1e). Dispatched from exact green base `32ab71fc3c845c56068179fed98cf4a9eb80461e`. The returned diff changes only `.github/workflows/ci.yml` and was reviewed centrally. Bandit, locked-dependency validation/audit, and shell/Compose validation run independently of the unchanged Python 3.12-3.14 quality matrix. The primary review tightened shell validation to each script's POSIX `sh` contract. Integration `93b28f484f1968f415d2d765a2d50143831ad3e4` passed [pull-request CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34905338948) and [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34905334040). These workflow/documentation changes did not change or redeploy the running application image.

- **Objective:** keep security and lock checks observable when a test matrix leg fails, and add bounded secrets-free shell/Compose validation.
- **Owner:** one Cloud task after `CI-PORTABILITY-001` is integrated.
- **Base revision:** the exact green integration commit at dispatch time.
- **Owned paths:** `.github/workflows/ci.yml` only.
- **Read-only dependencies:** Makefile, Docker/Compose files, deployment scripts, `pyproject.toml`, and `uv.lock`.
- **Frozen interfaces:** application code, dependency versions, test semantics, coverage threshold, and deployment behavior.
- **Prohibited changes:** authenticated tests, secrets, broker calls, deploy jobs, coverage reductions, or ignored failures.
- **Acceptance criteria:** Bandit, lock consistency, and locked dependency audit remain visible after Pytest failure; shell and Compose checks run without external credentials.
- **Verification:** workflow syntax review plus exact local command equivalents.
- **Return contract:** commit SHA, workflow diff, local results, permissions analysis, and `READY_FOR_INTEGRATION` or `NOT_READY`.

### Research primitive wave: PIT-FIXTURES-002 and SIM-FILL-FIXTURES-002

The [bounded implementation plan](docs/superpowers/plans/2026-09-15-research-data-correctness.md)
records exact contracts for two real Codex Cloud tasks dispatched in parallel from
`93b28f484f1968f415d2d765a2d50143831ad3e4`:

- [PIT-FIXTURES-002](https://chatgpt.com/codex/tasks/task_e_6aa949d2b85c832d9b4ce34a4d41524e):
  returned only `tests/unit/market_data/test_universe_contract.py` and
  `docs/reviews/pit-fixtures-002.md`. The primary inspected the complete diff, added imports to
  make its documented conflict reproduction self-contained, and reran 18 existing/new tests and
  Ruff successfully. Its 16 new tests do not establish real historical completeness.
- [SIM-FILL-FIXTURES-002](https://chatgpt.com/codex/tasks/task_e_6aa949d36158832d8048af09453cb70d):
  returned only `tests/unit/simulation/test_fill_contract.py` and
  `docs/reviews/sim-fill-fixtures-002.md`. Central review replaced the vacuous forced-outcome RNG
  check with an independently specified mixed-outcome sequence and distinct-seed control, restored
  global RNG state in `finally`, and added a liquidity-cap/forced-partial interaction case. The
  integrated file adds 11 tests. An isolated in-memory mutation that ignored the supplied RNG failed
  the strengthened test, while the real implementation passed and preserved global RNG state.

The CLI exposed ready diffs, not complete worker command transcripts or Cloud-local commit SHAs.
The assigned exact base is recorded in both returned reviews; central integration relies on full
diff inspection and fresh local verification, not an unobserved worker verification claim.

The primary independently corrected `adjust_bars` after reproducing cross-instrument contamination,
premature future-action application, and missing UTC query validation. A separate local read-only
test review found that effectivity could mask the older announcement test; two late-announcement
cases now exercise that filter independently. No strategy, sizing, risk, config, persistence,
provider, promotion, or deployment code changed. Corporate-action sequence chronology and full
source provenance remain unresolved. These are primitive correctness changes, not accepted
research, a complete paper composition, elapsed observations, or a live release.

### Bounded input-validation wave (2026-09-16)

The affected membership and simulation primitives are **partial**, not connected research or
promotion evidence. The approved dependency chain is: independent failing regression tests →
primary-owned validation → central Cloud diff review → focused and full verification → existing
branch/PR CI. Production validation and central verification are the critical path. No new
provider, research acceptance, strategy threshold, evidence gate, deployment, or live operation
is included. The prior `095e5c0` wave passed both
[PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019194133) and
[push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019186906).

Two independent actual Codex Cloud tasks were dispatched from exact committed base
`095e5c02b01aea95fd7858a549a7765e7b0488c0` on the integration branch. Each must verify or detach
that exact revision in its isolated checkout, otherwise return `NOT_READY`.

- **PIT-VALIDATION-003**, owner: [Cloud task](https://chatgpt.com/codex/tasks/task_e_6aaae8e47a28832da3c46160f25c5a9b).
  Objective: independent synthetic membership validation tests. Owned paths only:
  `tests/unit/market_data/test_universe_validation_contract.py` and
  `docs/reviews/pit-validation-003.md`. Read-only dependencies: universe source, shared validators,
  existing membership tests, and project/research documentation. Frozen interfaces: membership
  fields, universe constructor, lookup, and eligibility reason. Acceptance: reject invalid UTC,
  blank/non-string IDs, nonboolean flags, invalid tuple/record shapes, and contradictory values
  at the same instrument/effective/announcement key; retain identical duplicates, late
  announcements, sorted outputs, and existing valid boundaries. No claim of historical completeness.
  Verification: `uv run pytest tests/unit/market_data/test_universe_validation_contract.py -q`,
  Ruff on that file, then the existing `test_universe.py` and `test_universe_contract.py` tests.
- **SIM-VALIDATION-003**, owner: [Cloud task](https://chatgpt.com/codex/tasks/task_e_6aaae8e50fa8832d833020b834350eaa).
  Objective: independent synthetic fill/cost input tests. Owned paths only:
  `tests/unit/simulation/test_input_validation_contract.py` and
  `docs/reviews/sim-validation-003.md`. Read-only dependencies: fill/cost/event sources, shared
  validators, existing simulation tests, and project/research documentation. Frozen interfaces:
  existing constructors, fill evaluation, cost helpers, arithmetic, and seeded valid outcomes.
  Acceptance: exact bounded finite Decimals, positive order quantities/prices, nonnegative
  liquidity/costs, uncrossed quotes, independent probabilities in `[0,1]`, exact cursor/cost/side/
  boolean types, and positive execution results. Zero liquidity/costs, equal quotes, and probability
  endpoints remain valid. No new fee/slippage cap, timing model, or config schema.
  Verification: `uv run pytest tests/unit/simulation/test_input_validation_contract.py -q`,
  Ruff on that file, then existing `test_fills.py` and `test_fill_contract.py` tests.

Both contracts prohibit production/config edits, external broker/data/deployment operations,
secrets, live/risk/evidence changes, skipped/xfail tests, mocks, and source-text assertions.
Their review documents must return exact base, commands/results, expected-red explanations,
assumptions, risks/blockers, and an explicit integration disposition alongside the bounded diff.
Expected-red tests against the permissive base are TDD evidence, not release approval. The primary
owns `universe.py`, `costs.py`, `fills.py`, separate core regression tests, documentation, and all
integration/release decisions. Both tasks returned only their owned two-file diffs. The primary
inspected all four files, reproduced 140 expected failures and 8 valid passes on the exact old
base, and verified all 148 originally returned Cloud cases against the patch. Redundant unrelated-RNG assertions
were removed and separate primary controls now verify each membership timestamp independently.
The original primary regression run reproduced 30 failures before implementation. Further review
strengthened the Cloud-owned files to 176 cases; 38 separate primary cases bring the added total
to 214. The final new-test set produced 202 expected failures and 12 valid-boundary passes on the
old base. The full patched suite passed locally on 2026-09-17, as recorded below.

## LOCAL-ONLY TASKS

- OAuth bootstrap, refresh-token handling, and any authenticated broker evidence capture.
- Production account inspection, even when the local client is write-incapable.
- Production ledger backup, restore, migration, inspection, or evidence attestation.
- DigitalOcean provisioning, firewall, image pull, deployment, rollback, and host verification.
- Root-owned executing-image artifact installation and verification.
- Broker review/place/cancel experiments or schema capture.
- Live authorization, lease, leadership, kill-control, reconciliation, recovery, or mode transition.
- Final integration of protected components and every release/promotion decision.

These tasks stay local because they involve credentials, production state, external side effects, or safety-critical authority.

## CLOUD-CANDIDATE TASKS

- Cross-platform CI/test portability with production behavior frozen.
- Static architecture, dependency, threat-model, and documentation review.
- Fixture-only public response parsing and schema-shape tests.
- Research-bias and data-provenance acceptance design.
- Simulation/fill-model test design using synthetic data only.
- Coverage, mutation-test, and observability gap inventories.
- Read-only IaC/recovery drift review from sanitized inputs.
- README/runbook synchronization after primary-owner behavior is frozen.

All Cloud tasks require an exact committed base, isolated worktree, path ownership, no secrets, no broker/network operations, and central diff review.

## HIGH-CONFLICT COMPONENTS

The following must not have concurrent implementation owners:

- `src/trading_bot/runtime/live.py` and mode-transition surfaces.
- `src/trading_bot/risk/`, sizing, strategy selection, and exposure logic.
- `src/trading_bot/execution/` and submission idempotency.
- `src/trading_bot/reconciliation/` and restart/cancel-only recovery.
- Provider write/review/cancel adapters and capability bindings.
- Authorization, leases, leadership locks, kill controls, and promotion decisions.
- Persistence migrations, production ledger, and evidence schemas.
- `configs/safety-envelope.yaml`, live configs, and canonical config schema.
- Credential handling and authenticated transport code.
- Docker/Compose and `infra/digitalocean/deploy-remote.sh` while release attestation is changing.

Shared interface changes in these areas require a sequential plan, explicit migration, focused tests, architecture documentation, and primary-owner integration.

## TEST STATUS

For the input-validation wave, verified on 2026-09-17:

- A fresh secrets-free archive of staged tree `fe4d74c0a66b9b1898e88b5ded328f25509fc0b9`
  passed **3,759 tests** in 137.37 seconds, with **85.64% coverage with branch measurement
  enabled**, above the unchanged 80% threshold. The existing Starlette `httpx` deprecation warning
  remains. The interrupted September 16 full run is not counted as passing.
- This wave adds 214 cases to the 3,545-test base. The expanded market-data, simulation, and
  paper/decision-cycle integration selection passed 288 tests. The final new tests independently
  produced 202 expected failures and 12 valid-boundary passes on exact base `095e5c0`.
- Fresh Ruff, strict mypy across 165 source files, Bandit, and `uv lock --check` passed on the
  archived snapshot. A fresh audit of the exact locked requirements found no known vulnerabilities.
  Existing Bandit annotation and audit invocation warnings were not suppressed.
- POSIX shell syntax checks and standalone `docker-compose config --quiet` passed. No container
  build, deployment, account access, credential operation, production-ledger access, or live check
  was performed.
- Verification used the existing clean locked Python 3.12.13 environment with `PYTHONPATH=src`
  against the archive. The final documentation-only edits record results, clarify historical
  observations, and reconcile the original and strengthened Cloud test counts; production and
  tests remain identical to the verified tree. The user's pre-existing coverage/error files are
  not included or altered.
- The verified changes are prepared for the existing branch and
  [pull request](https://github.com/Jed1122/Robinhoodtradingbot/pull/1). Exact post-push CI results
  will be reported in the subsequent task handoff; no new CI success is claimed in this pre-push
  documentation snapshot.

For the research-primitive implementation wave on 2026-09-15:

- A secrets-free archive of staged tree `93a9b8a0e817aa9a56823f38c46f3cd623d23095` passed
  **3,545 tests**, with **85.57% coverage with branch measurement enabled**, above the unchanged
  80% threshold. One existing Starlette `httpx` deprecation warning remains. This wave adds 47 cases
  to the previous 3,498-test suite. The final report and plan only record these results afterward;
  production code and tests are unchanged from the verified snapshot.
- The focused market-data, simulation, and paper-runtime integration selection passed 73 tests.
- Ruff passed; strict mypy passed across 165 source files; Bandit reported no issues;
  `uv lock --check` passed; a fresh audit of the exact locked requirements found no known
  vulnerabilities. Existing Bandit annotation warnings were not suppressed.
- POSIX shell syntax checks and Compose configuration validation passed. This workstation uses
  the standalone `docker-compose` 5.2.0 command; its `docker compose` plugin is unavailable.
- Verification used the existing clean locked Python 3.12.13 environment and `PYTHONPATH=src`
  against the archived edited source, avoiding the reusable project environment and slow source
  reads in the Documents worktree. Earlier interrupted full runs are not counted as passing.
- This prior wave was committed as `095e5c02b01aea95fd7858a549a7765e7b0488c0` and passed
  [PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019194133) and
  [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019186906).

For deployed source `32ab71fc3c845c56068179fed98cf4a9eb80461e`:

- The CI failure was reproduced with a color-capable terminal. A plain/color parametrized regression failed before ANSI normalization and passed afterward; it still requires exit code 2, the specific missing-flag diagnostic, and no server start. Production CLI code was unchanged.
- The full local suite passed: 3,498 tests, 85.45% coverage with branch measurement enabled, and one existing Starlette deprecation warning.
- Ruff passes; strict mypy passes across 165 source files; Bandit reports no issues; `uv lock --check` passes.
- A fresh audit of the exact locked requirements reports no known vulnerabilities. Stale metadata in the reusable local virtual environment is not used as the dependency inventory.
- Compose rendering, deployment-script syntax checks, and `git diff --check` pass.
- Both [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34869770386) and [pull-request CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34869775452) completed successfully on Python 3.12, 3.13, and 3.14.
- The native amd64 image build, paused-host deployment, missing-artifact denial, and mounted-artifact verification all pass.
- The two Cloud documents were reviewed against the referenced source. All 43 unique source line references resolve; the three documentation smoke checks pass.

These are snapshot facts, not completion claims.

For the operator-authorized reconnection on 2026-09-15, a clean runtime from `93b28f4` with locked dependencies passed 28 OAuth/CLI safety tests and 23 connected-shadow deployment/runtime tests. The native deployed image independently passed offline credential/configuration checks and the one authorized broker-read probe. No production application code changed during credential rotation.

## VERIFIED PAUSED DEPLOYMENT

- Source commit: `32ab71fc3c845c56068179fed98cf4a9eb80461e`.
- Immutable native image: `sha256:1a259e1a559c2ecb2ae0277e8f7fa2733e7e9f0c2b90ff418f5baa1c527e9d25` (`amd64`, `linux`).
- Resolved deployment configuration: `f617b11838362eccf5ea0e4e18e274974f347cb12f5e01006a1c1b7a3255f224`.
- Compose SHA-256: `6ad9422f7d5e10280fcccef97a6703edb6deeb422e7fcd64f9e6d3d2c5a55c54`.
- Default container: healthy; `/healthz` 200; `/readyz` 503; `trading_bot_live_enabled 0.0`; zero host mounts.
- The canonical release artifact is root-owned mode `0444`; `last-good` matches the exact image/config/Compose release key.
- A network-disabled, non-root container rejected an absent artifact and accepted the actual read-only mounted release artifact with matching configuration and Compose hashes.
- The previous image and release record were retained. Prior administrative Compose/helper files were preserved in a root-private backup. A full failure-injection/restore drill was not performed.
- A local ARM image was not deployed. The local legacy cross-platform builder failed, so the exact committed source archive was built natively on the existing amd64 host with bounded build memory and reduced CPU priority.
- Historical pre-rotation check on 2026-09-14: the broker-read probe failed closed and did not append an observation. A separately bounded schema-only handshake failed with `OAuthFlowError` before provider-tool invocation despite passing offline credential checks. Fresh authorization later restored the connection; the exact cause of the earlier OAuth failure was not established.

## VERIFIED CREDENTIAL ROTATION AND BOUNDED PROBE

On 2026-09-15, the operator separately authorized workstation browser authorization and then credential installation plus exactly one write-incapable server connection probe.

- Workstation bootstrap completed, verified the seven permitted read-tool declarations and one active individual cash Agentic account, and saved a new private encrypted store without overwriting the existing one. The new account fingerprint matched both the previous workstation store and the server store.
- The four credential files were streamed directly over host-key-verified SSH to a root-owned mode-`0700` staging parent. No credential values were put in Git, Cloud tasks, tool output, environment variables, or command arguments.
- A network-disabled, non-root container verified account-fingerprint validity, encrypted token/client validity, and configuration-to-image attestation binding before cutover.
- Under the deployment lock, the previous store was retained behind the root-private rotation parent and the new store was installed at the existing active path. Active and preserved store directories remain mode `0700`, their four regular files remain mode `0600`, and ownership is `10001:10001`. Application image, Compose, release identity, and live-disabled defaults were unchanged.
- Exactly one bounded connected-shadow invocation succeeded with `authenticated_reads=true`, `broker_health=true`, `code_identity_verified=true`, `zero_state_reconciliation=true`, `write_capabilities_present=false`, and `live_enabled=false`.
- The invocation persisted one non-promotable observation with `strategy_ineligible`, `live_data_invalid`, and `outcomes_incomplete`. Both evidence and promotion eligibility remain false; the qualifying calendar clock did not start. No diagnostic market-history read was requested.
- After the probe exited and its container was removed, the paused service still returned health `200`, readiness `503`, and live-enabled metric `0.0`, with zero host mounts. No SQLite WAL or journal sidecar remained.
- The subsequent network-disabled, read-only promotion preview verified ledger integrity, five ineligible shadow observations across four separate identity series, two rejected research assessments, and zero eligible observations, submission attempts, live authorizations, or leases. Every identity-bound promotion remained denied.
- No order review, placement, cancellation, recurring probe, live-mode activation, or application redeployment was performed. The credential remains trading-capable despite the client's local write incapability.

## SECURITY / EXECUTION RISKS

- The OAuth token is trading-capable even when application allowlists expose reads only; host or token compromise could trade outside the local client boundary.
- Any gap between requested image digest and executing image identity can invalidate promotion evidence. The deployed attestation binds those identities under a trusted-root host model; it is not remote signed attestation and does not protect against root compromise.
- Empty-only equity order/position mappings are insufficient for reconciliation or live recovery.
- Retry, lease, leadership, and reconciliation errors can duplicate or increase exposure unless kept behind fresh risk checks and idempotent journals.
- Research/data leakage, survivorship bias, unsupported interpolation, or incomplete outcomes can make promotion evidence invalid without obvious runtime failure.
- A funded account raises the impact of credential or host compromise even while the service is paused.
- Dirty worktrees and overlapping agents can silently combine unreviewed safety changes; exact commits and path ownership are mandatory.
- Terraform/cloud-init drift from the manually provisioned host can create false recovery assumptions.
- Missing elapsed evidence cannot be replaced by configuration changes, copied records, or synthetic timestamps.

## RECOMMENDED NEXT WAVE

1. The bounded broker connection was verified once on 2026-09-15 after credential rotation. Do not repeat ineligible probes as a promotion strategy or install recurring diagnostics; the critical path is validated research/data and complete outcomes.
2. Continue from the bounded research-primitive wave: define validated point-in-time coverage,
   complete corporate-action/interpolation provenance, and leakage/multiple-testing controls.
   Input and same-key conflict validation are implemented locally; primitive tests still do not
   supply authoritative source coverage or accepted evidence. Authoritative data selection
   and statistical acceptance remain primary-owner decisions.
3. Use the completed IaC review to prepare a sanitized host-hardening and recovery evidence checklist. Do not import, rebuild, replace, resize, or apply Terraform without a separately reviewed plan and authority.
4. `CI-HARDENING-002` is integrated and verified green. A bounded attestation-test review can follow under its own exact-commit contract.
5. Compose qualifying paper and shadow cycles only after their research/data/outcome interfaces and evidence are complete. Preserve all existing observation and elapsed-time gates.
6. Keep broker writes, reconciliation, live runtime, and promotion decisions sequential under the primary owner.

The immediate aim is a reproducible, green, paused release with truthful evidence and clean delegation boundaries. Beginning live trading is not an acceptable shortcut around the critical path.
