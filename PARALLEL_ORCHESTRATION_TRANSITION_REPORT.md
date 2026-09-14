# Parallel Orchestration Transition Report

Snapshot date: 2026-09-14

Repository: `Jed1122/Robinhoodtradingbot`

Integration branch: `codex/continue-implementation-from-commit-7c4dcd1`

Attestation and Cloud-review base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`

Verified deployed source: `32ab71fc3c845c56068179fed98cf4a9eb80461e`

Release state: **NO-GO for live trading**

This report transitions the existing system to centrally governed local and Codex Cloud orchestration. It does not restart or redesign the project. The executing-image-attestation release is now committed, CI-verified, and deployed in paused mode. Two isolated Codex Cloud documentation reviews completed and were reviewed centrally; their point-in-time findings do not supersede the newer operational evidence recorded here.

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
- Root-owned, canonical, per-release executing-image attestation deployed and verified from an unprivileged container, including rejection when the artifact is absent.
- Portable paused-service denial test covering both plain and ANSI-colored diagnostics, while asserting that the server never starts without `--paused`.
- Two completed, centrally reviewed Codex Cloud audits with separate owned documentation paths and no production-code changes.
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

1. The bounded connected-shadow probe on the attested release failed closed with `connected_shadow_not_ready`; it did not append a new observation. Offline checks verified the configuration/attestation match, account-fingerprint validity, and encrypted token/client presence and local validity. A subsequent schema-only handshake failed with `OAuthFlowError` before any provider tool invocation. Authentication must be restored; local credential validity does not prove external acceptance, and fresh browser authorization may be required.
2. Verification is complete for the paused release, not for live operation. Host hardening, infrastructure-as-code conformance, off-host backup, and a full operator-observed recovery drill still require their own evidence.
3. Research/data requirements and accepted research identity are incomplete.
4. The current read-only promotion preview reports an intact ledger with four ineligible shadow observations, two rejected research assessments, zero eligible observations, and zero live authorizations, live leases, execution leases, or submission attempts. Identity series remain separate.
5. Paper requires 100 eligible observations; shadow requires eligible observations on seven distinct UTC dates. These elapsed evidence gates cannot be compressed or fabricated.
6. Nonempty equity response mappings and authenticated review/place/cancel provider evidence are absent.
7. No provider-connected live adapter, complete live application, durable host leadership path, or restart-safe live recovery composition exists.
8. Current external security, manual review, and runtime-control attestations have not been assembled for live promotion.
9. Codex Cloud CLI access now works. `RESEARCH-GAPS-001` and `IAC-AUDIT-001` completed from the exact attestation commit. Their reviewed documents are integrated locally; implementation of their proposed follow-ons is not implied.
10. The remote default branch is materially behind the integration branch; any future Cloud task launched from the default branch would start from stale architecture.

## CURRENT GO / NO-GO STATE

| Activity | State | Reason |
|---|---|---|
| Local implementation and deterministic tests | GO | No external side effects; existing guardrails remain active. |
| Static/read-only audits and secrets-free Cloud tasks | GO | Two Cloud tasks completed; continue to require exact revision, isolated worktree, frozen interfaces, and bounded ownership. |
| Paused health-only service | GO | Current service is healthy, readiness-denied, live-disabled, and has no credential/ledger mounts. |
| Explicit bounded read-only evidence probe | BLOCKED pending connection diagnosis | The attested probe failed closed. The local client is write-incapable, but the OAuth token remains trading-capable. |
| Paper promotion | NO-GO | No accepted research composition or eligible 100-cycle evidence set. |
| Shadow promotion | NO-GO | No qualifying paper promotion and no eligible seven-UTC-date shadow set. |
| Micro-live | NO-GO | Provider writes/live composition and promotion/manual/runtime evidence are absent. |
| Normal-live | NO-GO | Micro-live and the larger observation/time gates are absent. |
| Prediction-market live execution | NO-GO / unsupported | No live placement capability exists. |

Funding the account does not override any NO-GO state.

## CRITICAL PATH

1. **Completed:** restore a green integration base by fixing the portable CLI test without changing production behavior.
2. **Completed for paused operation:** review, test, commit, build natively for amd64, and deploy the root-attested executing-image identity change. Diagnose the failed broker handshake without weakening preflight checks or creating promotion evidence.
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
| Data-provenance contract | Research gap analysis | Parallel with CI/attestation review | Schema/design/fixtures only; canonical config and persistence schema frozen. |
| Simulation fill-model test design | Documented assumptions | Parallel review | Tests/design only; no claims or strategy/risk changes. |
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

### Returned and centrally reviewed Cloud task contract: CI-HARDENING-002

Task: [Improve CI workflow for Robinhood trading system](https://chatgpt.com/codex/tasks/task_e_6aa8760eafd8832dbc1ab7b5cbcb7b1e). Dispatched from exact green base `32ab71fc3c845c56068179fed98cf4a9eb80461e`. The returned diff changes only `.github/workflows/ci.yml` and was reviewed centrally. Bandit, locked-dependency validation/audit, and shell/Compose validation run independently of the unchanged Python 3.12-3.14 quality matrix. The primary review tightened shell validation to each script's POSIX `sh` contract. Fresh CI remains the acceptance gate; these workflow/documentation changes do not change or redeploy the running application image.

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

For deployed source `32ab71fc3c845c56068179fed98cf4a9eb80461e`:

- The CI failure was reproduced with a color-capable terminal. A plain/color parametrized regression failed before ANSI normalization and passed afterward; it still requires exit code 2, the specific missing-flag diagnostic, and no server start. Production CLI code was unchanged.
- The full local suite passes: 3,498 tests, 85.45% branch coverage, and one existing Starlette deprecation warning.
- Ruff passes; strict mypy passes across 165 source files; Bandit reports no issues; `uv lock --check` passes.
- A fresh audit of the exact locked requirements reports no known vulnerabilities. Stale metadata in the reusable local virtual environment is not used as the dependency inventory.
- Compose rendering, deployment-script syntax checks, and `git diff --check` pass.
- Both [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34869770386) and [pull-request CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34869775452) completed successfully on Python 3.12, 3.13, and 3.14.
- The native amd64 image build, paused-host deployment, missing-artifact denial, and mounted-artifact verification all pass.
- The two Cloud documents were reviewed against the referenced source. All 43 unique source line references resolve; the three documentation smoke checks pass.

These are snapshot facts, not completion claims.

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
- The one-shot broker-read probe failed closed and did not advance evidence. The read-only, network-disabled promotion preview reports `ledger_integrity=ok` and `live_activation_permitted=false`.
- Offline credential/configuration prerequisites passed. A separately bounded schema-only OAuth handshake failed with `OAuthFlowError`, with zero provider-tool invocations; only exception categories were emitted, never credential values or provider payloads. No repeated monitoring job or trading process was installed.

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

1. Finish the bounded connection diagnosis. Do not assume local credential validity means external authorization; do not repeat failed probes as a promotion strategy.
2. Use the completed research review to define independent fixture/design contracts for point-in-time membership, corporate-action/interpolation provenance, and leakage/multiple-testing controls. Authoritative data selection and statistical acceptance remain primary-owner decisions.
3. Use the completed IaC review to prepare a sanitized host-hardening and recovery evidence checklist. Do not import, rebuild, replace, resize, or apply Terraform without a separately reviewed plan and authority.
4. Confirm fresh CI on the centrally reviewed `CI-HARDENING-002` change. A bounded attestation-test review can follow under its own exact-commit contract.
5. Compose qualifying paper and shadow cycles only after their research/data/outcome interfaces and evidence are complete. Preserve all existing observation and elapsed-time gates.
6. Keep broker writes, reconciliation, live runtime, and promotion decisions sequential under the primary owner.

The immediate aim is a reproducible, green, paused release with truthful evidence and clean delegation boundaries. Beginning live trading is not an acceptable shortcut around the critical path.
