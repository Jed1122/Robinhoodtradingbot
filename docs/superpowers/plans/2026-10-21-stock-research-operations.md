# Isolated stock research operations implementation plan

> **For agentic workers:** Use `superpowers:executing-plans` task by task. Root owns
> configuration, runtime, credentials, deployment and all host mutations. Agents may
> review or implement only separately contracted non-overlapping, secrets-free work.

**Goal:** Run the reviewed individual-stock collector under an external supervisor,
with verified identity, explicit operator controls and observed recovery; no live trading.

**Architecture:** Reuse the existing locked Python image recipe and canonical stock
configuration. Add a separate stock Compose definition, root-owned standard-library
launcher and completion-relative systemd timer. The launcher verifies the created
container before starting it and enforces the deadline on that actual container.

**Base:** `3d32b62ce26f095cf383c693738a3020a895721f`, after local collector controls.
The primary `3cd8e8c` full suite remains frozen/running separately. Local source work
may proceed in the runtime worktree; integration waits for the terminal baseline.

**Contracts:** [worker](../../stock-research-worker.md),
[controls](../../stock-research-controls.md),
[export](../../stock-dashboard-export.md),
[overall dependency chain](2026-10-21-hybrid-stock-readiness.md).

## Boundaries and review focus

- Leave both existing paused services, `compose.hybrid.yml`, their state and credentials
  unchanged. Use sibling `/var/lib/hybrid-stock-research` and `/opt/hybrid-stock-research`
  namespaces; the dashboard mounts all of `/var/lib/hybrid-paper` and must never receive
  nested stock credentials/raw data.
- No automatic control initialization, resume, reset, retry, catch-up or live activation.
  Installation leaves controls paused and timer disabled. Preserve the ledger, archive
  and control generation across upgrades/rollback.
- Keep OAuth worker-only. Operator control containers get controls and, for resume,
  immutable release/configuration only. Dashboard may eventually receive exports RO only.
- Current control mutex opens its anchor `O_RDWR`; a wholly RO control mount denies
  admission. A trusted worker-only RW control namespace is compatible today. Any tighter
  RO-state/RW-anchor arrangement needs separate source/native verification.
- Source/config identity does not prove the executing container, authentication lifetime,
  market-data quality, strategy performance, backup restoration or continuous operation.
- A Docker CLI timeout or systemd host-process timeout does not prove the actual container
  stopped. Never remove it before collecting bounded status/exit evidence.

## Task 1: Canonical configuration-only observation

Files: extract only the shared stock configuration load from
`src/trading_bot/runtime/stock_research_worker.py`; add
`src/trading_bot/runtime/stock_research_identity.py` and focused CLI tests.

- [x] Observe failing tests for an explicit configuration-only command, exact canonical
  full hash/bounds, no code-identity/SDK/credential/ledger operation, missing/invalid config
  and unsafe environment denial with sanitized errors.
- [x] Reuse one configuration helper for worker startup, control resume and the probe.
  Output bounded canonical-policy hash, scheduling/runtime/call bounds and live=false;
  provide no caller hash, fabricated attestation, provider/session or activation option.
- [x] Verify focused tests, prior worker/control/identity regressions and static checks.
  The eventual producer runs this inside a credential-free network-disabled container
  and inspects that container's actual immutable image and absent mounts independently.

Task 1 local checkpoint: four observed RED tests became GREEN; the central
probe/worker/control/identity/architecture subset passed 285 tests with 97.77% combined
branch coverage (probe individually 85%). Ruff, strict mypy across 440 source files,
Bandit, lock and diff checks passed. Independent review is READY_FOR_INTEGRATION for
Task 1 only. The actual local command returned the unchanged canonical stock hash;
no native image probe, producer or deployment is claimed. See the
[operations status](../../stock-research-operations.md).

## Task 2: Release description, container barrier and hard deadline

Add `compose.stock-research.yml`, `infra/hybrid/stock_release.py`,
`infra/hybrid/stock-runner.py`, focused deployment tests and a stock operations runbook.
Reuse `Dockerfile` and the trusted-root attestation schema. Keep the read-only release
verifier separate from actual Docker orchestration so its trust/identity contract can
be independently tested first. Public `load_release(path)` enforces the fixed production
root and UID 0; only private test helpers may inject a fictional root/owner. It performs
no Docker, credential, ledger, control mutation or activation operation.

- [x] Freeze the root-owned release manifest format, canonical resolved Compose identity,
  fixed paths, image/config identities and resource/deadline bounds before implementation.
  Avoid circular identity by using a source-release path independent of the attestation's
  image/config/Compose release key.
- [x] Implement/read-only verify the exact closed manifest, observation, resolved policy
  and attestation schemas in [the container contract](../../stock-container-contract.md).
  Require canonical bounded bytes, owner/mode/link/path checks, all companion hashes,
  exact type-sensitive worker policy and matching observed bounds. Exercise rehashed
  hostile model changes, malformed records and filesystem substitutions with fictional
  files. No trusted image/deployment proof follows from internally consistent fixtures.
- [ ] Write RED fixture tests for malformed/untrusted manifest, wrong image/config/command,
  unexpected mounts/environment/network/restart policy, unknown existing container,
  duplicate launcher, time rollback, interrupted Docker commands and orphan ownership.
- [ ] Inspect a created CID and exact image, user, command, mounts and hardening before
  start. No registry pull/publication, Docker socket in worker, ports or inherited HTTP
  healthcheck. `restart: "no"`; bounded logs, pids/CPU/memory and read-only root filesystem.
- [ ] Enforce the canonical run bound on the actual verified CID with monotonic polling,
  bounded TERM grace, KILL escalation and observed stopped state. Handle host signals and
  restart/orphan recovery without blind re-execution or deletion of unknown containers.
- [ ] Produce root-owned immutable attestation only after inert actual image/config
  observations. Verify the executing worker mount/argument/config binding separately.
  Keep installation, credential transfer and production probes as explicit operations.

Task 2 partial local checkpoint: the isolated Compose policy rendered successfully with
the local reviewed Compose tool and fictional release values, without creating/starting
a container. The read-only verifier and policy passed 102 fictional tests; verifier
branch coverage is 99%. Independent review found a descriptor-cleanup error; two RED
regressions reproduced it and passed after the fix. Launcher, producer, actual container
inspection and hard termination remain unimplemented/unverified. Task 2 is not complete.

## Task 3: Supervised timer, paused installation and native checks

Add stock-specific oneshot service/timer files, fixture tests and installation procedure.

- [ ] Use `Restart=no`, `OnUnitInactiveSec` derived from canonical cadence, `Persistent=false`,
  no overlap or wall-clock catch-up. Configure bounded unit timeouts and identity-checked
  actual-container cleanup; no automatic control changes.
- [ ] Verify unit syntax on native Linux, actual UID/mount compatibility and host capacity.
  Network-disabled paused worker without OAuth must return control_denied and append no
  claim. Keep timer disabled until its verified operating procedure is satisfied.
- [ ] Verify authorized scheduled acquisition with the development client closed, actual
  deadline/termination, reboot/orphan recovery, no replay and retained daily reservations.
  Do not claim 24/7 operation from installation or one successful local cycle.

## Task 4: Recovery and monitoring

- [ ] Freeze a coherent stock ledger/archive/control backup contract under archive/control
  ownership, preserve all source links and control continuity, exclude OAuth and encrypt
  to an approved public recipient. Do not reuse the dashboard's plaintext structural
  backup or unrelated restore checker as stock application evidence.
- [ ] Verify encrypted backup, off-host copy and decrypted application restore with source
  rehash/reconstruction and paused control continuity. Never restore an old running grant.
- [ ] Implement stock-specific freshness/failed-cycle/budget/storage incidents. Reuse bounded
  watchdog mechanics, not its dashboard-specific health assumptions. Persist command audit
  and incident state with resource limits; external delivery requires applicable authority.

Finish each source task with independent review and narrow central verification. Native
deployment evidence remains separate from fixture success. Data/strategy qualification,
nonempty broker reconciliation and explicit live authorization remain later requirements.
