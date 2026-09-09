# Parallel Orchestration Transition Report

Snapshot date: 2026-09-09  
Repository: `Jed1122/Robinhoodtradingbot`  
Integration branch: `codex/continue-implementation-from-commit-7c4dcd1`  
Committed base audited: `a63247eca2022a80adb8b76e47ac8c9d964ed827`  
Release state: **NO-GO for live trading**

This report transitions the existing system to centrally governed local and Codex Cloud orchestration. It does not restart or redesign the project. The current uncommitted executing-image-attestation patch is intentionally identified separately from the committed base.

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

The following are complete as local foundations, not as proof of production readiness:

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
- Read-only health, metrics, status, live-readiness, and promotion-preview surfaces.
- CI definition for Python 3.12, 3.13, and 3.14 with Ruff, strict mypy, branch coverage, Bandit, and lock validation.

## PARTIAL WORK

- **Executing-image attestation:** a root-owned, canonical, per-release attestation patch is locally verified in the working tree but is not yet committed, CI-verified, or deployed.
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

1. GitHub Actions is red on the committed base for one cross-platform CLI assertion. All three Python versions report `tests/integration/cli/test_paused_service.py::test_serve_requires_explicit_paused_flag`; the working tree contains a test-only portable fix, but it must be committed, pushed, and pass the matrix.
2. The executing-image-attestation patch has passed local focused, full, security, lock, Compose, and shell checks; it still needs a clean commit, CI, immutable image build, and paused deployment verification.
3. Research/data requirements and accepted research identity are incomplete.
4. The evidence ledger has no eligible paper or shadow promotion observations. The latest verified operational snapshot contained four ineligible observations and zero live authorizations, execution leases, or submission attempts.
5. Paper requires 100 eligible observations; shadow requires eligible observations on seven distinct UTC dates. These elapsed evidence gates cannot be compressed or fabricated.
6. Nonempty equity response mappings and authenticated review/place/cancel provider evidence are absent.
7. No provider-connected live adapter, complete live application, durable host leadership path, or restart-safe live recovery composition exists.
8. Current external security, manual review, and runtime-control attestations have not been assembled for live promotion.
9. Codex Cloud task creation is unavailable from the current host because the Codex task connector reports delegation unavailable. No Cloud task has been represented as launched; the contracts below are staged for dispatch once the connector is available.
10. The remote default branch is materially behind the integration branch; any future Cloud task launched from the default branch would start from stale architecture.

## CURRENT GO / NO-GO STATE

| Activity | State | Reason |
|---|---|---|
| Local implementation and deterministic tests | GO | No external side effects; existing guardrails remain active. |
| Static/read-only audits and secrets-free Cloud tasks | GO when a task connector is available | Must use exact revision, isolated worktree, frozen interfaces, and bounded ownership. |
| Paused health-only service | GO | Current service is healthy, readiness-denied, live-disabled, and has no credential/ledger mounts. |
| Explicit bounded read-only evidence probe | GO only with existing operator authorization and all preflight checks | The capability is locally write-incapable, but the OAuth token remains trading-capable. |
| Paper promotion | NO-GO | No accepted research composition or eligible 100-cycle evidence set. |
| Shadow promotion | NO-GO | No qualifying paper promotion and no eligible seven-UTC-date shadow set. |
| Micro-live | NO-GO | Provider writes/live composition and promotion/manual/runtime evidence are absent. |
| Normal-live | NO-GO | Micro-live and the larger observation/time gates are absent. |
| Prediction-market live execution | NO-GO / unsupported | No live placement capability exists. |

Funding the account does not override any NO-GO state.

## CRITICAL PATH

1. Restore a green integration base by fixing the portable CLI test without changing production behavior.
2. Finish, independently review, test, commit, and deploy the root-attested executing-image identity change in paused mode.
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
| CI portability test | Committed base | Independent now | Test file only; production CLI frozen. |
| Attestation adversarial review | Current attestation commit/diff | Independent review now | Read-only or tests/docs only; deploy helper/runtime implementation protected. |
| Research-bias gap analysis | Committed base | Independent now | Review/design only; strategy selection and promotion decision protected. |
| Data-provenance contract | Research gap analysis | Parallel with CI/attestation review | Schema/design/fixtures only; canonical config and persistence schema frozen. |
| Simulation fill-model test design | Documented assumptions | Parallel review | Tests/design only; no claims or strategy/risk changes. |
| IaC drift and recovery audit | Committed base plus sanitized inventory | Independent now | Read-only; no DigitalOcean or state mutation. |
| Coverage/observability gap inventory | Committed base | Independent now | Read-only report or isolated non-risk tests. |
| Paper composition | Accepted research/data interfaces | Sequential protected work | Primary owner only. |
| Broker writes and reconciliation | Captured authenticated evidence | Sequential protected work | Primary owner only. |
| Live runtime and promotion | All preceding gates | Sequential protected work | Primary owner plus explicit operator approval. |

### Ready Cloud task contract: CI-PORTABILITY-001

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

### Ready Cloud task contract: RESEARCH-GAPS-001

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

### Ready Cloud task contract: IAC-AUDIT-001

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
- **Base revision:** the future attestation commit SHA; do not use the dirty worktree.
- **Owned paths:** new or existing attestation/deployment tests and review documentation only, as assigned explicitly.
- **Read-only dependencies:** `src/trading_bot/code_identity.py`, runtime integrations, Dockerfile, Compose, and deployment helper.
- **Frozen interfaces:** artifact schema, root ownership, immutable digest binding, paused deploy order, fail-closed behavior.
- **Prohibited changes:** deployment/runtime implementation, external host access, credentials, live settings.
- **Acceptance criteria:** adversarial cases have deterministic tests or documented blockers; no guardrail is weakened.
- **Verification:** focused identity/deployment/runtime tests, Ruff, mypy, then the full suite.
- **Return contract:** commit SHA, findings, tests added, commands/results, and residual risks.

### Ready Cloud task contract: CI-HARDENING-002

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

At committed base `a63247e`:

- Local baseline previously passed 3,486 tests.
- Current GitHub Actions is **RED** on Python 3.12, 3.13, and 3.14 with one failure and 3,485 passes per job.
- The failure is the portable assertion described under CURRENT BLOCKERS; it is not evidence that live behavior became enabled, but red CI still blocks integration.
- CI Ruff and strict mypy stages passed before the test stage. Bandit and lock validation were skipped by job sequencing after the test failure.

For the current working tree:

- The portable paused-flag regression test passes locally and proves the server never starts.
- All 76 focused identity/runtime/CLI/deployment tests pass.
- Ruff passes across the repository.
- Strict mypy passes across 165 source files.
- The full suite passes: 3,497 tests with 85.45% branch coverage.
- Bandit reports no issues; `uv lock --check` passes.
- Auditing a locked requirements export reports no known dependency vulnerabilities. A stale reusable local virtual environment initially reported old `cryptography 49.0.0` metadata, but `uv.lock` resolves `50.0.1` and the isolated lock-based audit is clean.
- Compose rendering, both deployment-script syntax checks, and `git diff --check` pass.
- Immutable image build, container-level attestation exercise, paused-host deployment, and GitHub's Python 3.12-3.14 matrix are still required.

These are snapshot facts, not completion claims.

## SECURITY / EXECUTION RISKS

- The OAuth token is trading-capable even when application allowlists expose reads only; host or token compromise could trade outside the local client boundary.
- Any gap between requested image digest and executing image identity can invalidate promotion evidence; the attestation patch addresses this but is not integrated yet.
- Empty-only equity order/position mappings are insufficient for reconciliation or live recovery.
- Retry, lease, leadership, and reconciliation errors can duplicate or increase exposure unless kept behind fresh risk checks and idempotent journals.
- Research/data leakage, survivorship bias, unsupported interpolation, or incomplete outcomes can make promotion evidence invalid without obvious runtime failure.
- A funded account raises the impact of credential or host compromise even while the service is paused.
- Dirty worktrees and overlapping agents can silently combine unreviewed safety changes; exact commits and path ownership are mandatory.
- Terraform/cloud-init drift from the manually provisioned host can create false recovery assumptions.
- Missing elapsed evidence cannot be replaced by configuration changes, copied records, or synthetic timestamps.

## RECOMMENDED NEXT WAVE

1. Review and commit this orchestration contract, portable CI test, documentation, and verified attestation work as one coherent release candidate.
2. Push the release candidate and restore green CI across Python 3.12-3.14.
3. Build the immutable image, exercise the mounted attestation boundary at container level, and complete paused deployment verification.
4. Run one explicitly authorized, bounded, read-only connected observation to confirm the attested release records the executing image and remains ineligible for honest documented reasons.
5. Refresh promotion status and preserve the NO-GO result.
6. When Codex Cloud task creation becomes available, dispatch `RESEARCH-GAPS-001` and `IAC-AUDIT-001` from the exact green commit. Dispatch `ATTESTATION-REVIEW-001` only after the patch has a commit SHA.
7. Keep paper composition, broker writes, reconciliation, live runtime, and promotion decisions sequential under the primary owner.

The immediate aim is a reproducible, green, paused release with truthful evidence and clean delegation boundaries. Beginning live trading is not an acceptable shortcut around the critical path.
