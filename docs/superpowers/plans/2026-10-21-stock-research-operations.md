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
The primary `3cd8e8c` full suite ended with 11,597 passed, 33 optional skips and two
test-context failures (88.74% coverage). Narrow RED reproductions, reviewed test-only
corrections and the final ordered 131-test regression passed; production guards remain
unchanged. Local integration and a corrected integrated full run remain required.

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
`infra/hybrid/stock_container.py`, `infra/hybrid/stock-runner.py`, focused deployment tests
and a stock operations runbook.
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
- [x] First implement data-only Engine/image observation verification. Freeze the official
  versioned API 1.52 schema, requiring a Linux daemon whose advertised API range contains
  that version, with no silent downgrade. Reject image-ID/OS/architecture mismatches,
  inherited volumes/ports or unreviewed environment keys/values, duplicates and bare keys.
  Match image-owned user/workdir and application environment to the existing Dockerfile;
  retain only a frozen public-metadata profile for the later created-container comparison.
  Bounded fictional JSON checks do not prove the pinned base's actual configuration,
  daemon compatibility, image provenance or runtime support. No Docker I/O is added here.
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

The next data-only Engine/image metadata parsers passed 67 fictional tests with 100%
branch coverage. Independent review's exponent-overflow finding was reproduced RED and
fixed for both parsers, including nested ignored metadata. The complete deployment-test
directory passed 245 tests with four optional local-age skips; no encrypted-backup or
native-image proof follows from those skips. Ruff, strict mypy (442 files), expanded
Bandit, lock and diff checks passed. Independent review is READY_FOR_INTEGRATION for
these parsers only. Actual CID inspection and the supervisor are still pending.

Host compatibility amendment: a separately authorized read-only native check observed
Docker 29.1.3 advertising API 1.44–1.52, Linux amd64 and cgroup v2. The initial fixed
1.55 source profile would deny that host. After independent versioned-schema review,
the source target was explicitly changed to 1.52 with no runtime fallback, upgrade or
policy weakening. Two version regressions were RED before the change; all 67 parser
tests passed afterward with 100% branch coverage. No image/container/service mutation
or broker operation occurred. Native image/runtime proof remains pending.

The data-only worker request and prestart comparison are now implemented locally in
`infra/hybrid/stock_prestart.py`. They derive only the closed release policy, explicit
private namespaces and complete request/resolved mount inventories, and check fresh
created state, CID/attempt/release/image/config identities, environment, command,
resources and all 69 versioned HostConfig fields. They never create or start anything.
Initial missing-implementation RED was observed; 123 fictional cases then passed with
100% branch coverage. Deployment regression passed 368 tests with four optional age
skips; Ruff, strict mypy (443 files), expanded Bandit and lock checks passed. Independent
review initially found a no-volume normalization mismatch: Docker image merge may
replace the empty request map with null. A RED regression reproduced it; the
field-specific fix and five denial cases passed, producing 129 tests at 100% branch
coverage. Independent review is READY_FOR_INTEGRATION after 374 deployment tests
with four optional age skips. Trusted production and supervisor remain pending;
the actual-CID inspection task above is not checked complete by supplied JSON tests.

The next local increment implements the fixed root/Linux Unix-socket GET-only
metadata reader, with a single absolute five-second budget, bounded HTTP/1.0
responses and fixed sanitized errors. It cannot mutate Docker or retry. Its 42
fictional/socketpair tests passed at 98.48% branch coverage; root/peer validation
is exercised with fictional system metadata. Missing peer support was observed
RED before its guard was implemented. Ruff, strict mypy (444 files) and expanded
Bandit passed. Review found the private shared transport accepted unchecked paths
despite safe public methods. A RED pre-connection regression reproduced it; the
transport now independently enforces all four exact route forms before opening a
socket. All 53 reader cases passed at 97.40% branch coverage. Independent review is
READY_FOR_INTEGRATION after 427 deployment tests and four optional age skips.
A separately authorized read-only native run of the exact reviewed reader/version
parser source completed one `/version` GET through the fixed root Unix socket,
confirming API 1.52/Linux amd64. No host installation, Docker mutation, image/CID
inspection, broker call or credential operation occurred. This is metadata transport
compatibility only; actual image/container proof and the supervisor remain pending.

The next local source increment adds the explicit root operations namespace,
permanent independent host flock, exclusive durable intent/CID/start/stop records
and atomic active pointer in `infra/hybrid/stock_attempts.py`. A reopened session
cannot adopt an unfinished attempt for execution. Stopped observations are scoped
to the owned image/name/labels/CID and require non-running, non-paused,
non-restarting state, PID zero and no restart/removal policy. No Docker/provider or
control operation is performed. Two root self-review regressions were observed RED
and fixed: preparing a start after a terminal receipt, and returning a start fence
whose deadline expired during persistence. The store passed 58 fictional/local-FS
tests at 98.74% combined statement/branch coverage and 485 deployment regression
tests with four optional age skips. Ruff, strict mypy (445 files), expanded Bandit
and lock checks passed. Independent review then reproduced three gaps: readable CID
bytes after failed fsync could fence a start, a missing created receipt could relax a
persisted start CID, and readable terminal bytes after failed fsync could admit another
attempt. Four RED regressions reproduced those cases. Root added same-session CID
acknowledgement/hash checks, validated created/start CID/clock linkage, and mandatory
fresh stopped reconfirmation plus durability acknowledgement after reopen. Terminal
receipts now retain container lifetime timestamps and reject changed lifetimes. The
corrected tests and regression pass. Follow-up review confirmed those fixes and found
an entry-order gap: failure of the first filesystem validation preserved prior session
acknowledgements. Two additional regressions failed before moving all stop-related
latch invalidation before validation. The corrected store passes 72 local filesystem
tests and 499 deployment regressions with four optional age skips. Independent review
cleared the final entry-order correction at e485be8.
Production initialization,
write transport, controller/deadline handling and native recovery remain pending.

Task 2 next increment: add a separate fixed-socket mutation library, without a CLI
or service composition. Its closed shared exchange owns both entry sequences:
`create_worker(store, release, image)` consumes a fresh create claim in the still-open
owning store, then derives the fixed name/body; `start_worker(store)` itself invokes
the existing durable `prepare_start()` and derives its CID. Neither accepts a caller
route, body, CID or start fence. A second transport cannot renew either store latch.
Recheck namespace, active identity, unchanged acknowledged receipts, boot and deadline
immediately before sending. Keep the GET-only reader unchanged. Use separate strict
201/complete-JSON create and 204/empty-body start parsing with one absolute I/O budget;
unexpected status, partial send, timeout or malformed response never refunds a claim.
No claim, acknowledgement or internally consistent fixture establishes native
provenance, stopped state, research success or authority to launch a production worker.
Root implements and reviews the store and transport; only fictional sockets/files
are used until supervision, release production and native checks are complete.

This increment is now local source: 17 store-dispatch regressions were observed RED
before adding the fresh create claim and final receipt/fence checks; the missing
mutation implementation was separately observed RED. The corrected store/transport
passed 144 fictional filesystem/socket tests, with 100% combined statement/branch
coverage over the mutation library and 98.93% across both modules. All 571 deployment
regressions passed with four optional age skips. The combined deployment/architecture
check passed 756 tests with those same four skips. Independent store and transport
reviews cleared 7af0a33, including direct shared-exchange replay, post-connect boot
drift, failed stop validation and segmented-response probes. Ruff, strict mypy
(446 files), expanded Bandit and lock checks passed. No native mutation or launcher
composition is established.

For supervisor recovery, retain the active stopped CID until the next session has
freshly reconfirmed it and durably begun the next attempt. Remove only older completed
CIDs after exact fresh inspection; preserve receipts and block new creation when
cleanup is unresolved. Missing active-container lookup must remain an incident,
not substitute for stopped evidence. Define never-dispatched/absent recovery explicitly
before enabling unattended creation; do not infer absence from the current reader's
opaque error. The contract records versioned source facts and their kernel/native
limitations. This sequencing decision is not an implemented supervisor.

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
