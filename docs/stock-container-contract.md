# Stock container and supervisor contract

This freezes the deployment implementation, based on source `48914f6`. The Compose
definition and read-only release verifier are implemented locally; the actual launcher,
producer and container deployment remain unverified. Existing services, broker adapters,
portfolio controls and live-disabled defaults remain unchanged.

## Release identity

Use the existing `Dockerfile`, immutable image ID and canonical attestation verifier.
The image already contains source/config/migrations and a trusted root-owned
`/run/trading-bot` directory; stock execution overrides its paused-service entrypoint
and disables the inherited HTTP healthcheck. No separate UI build is required.

The stock Compose source defines exactly one service and no build, dependency, port,
secret/environment file or additional service. Render it with the installed reviewed
Compose version, an empty env file and a scrubbed environment containing only the
explicit immutable image and trusted attestation path. Do not request image resolution
or registry access. Preserve the complete rendered model as canonical JSON using
`json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n"` encoded as UTF-8.
Its SHA-256 is `compose_sha256`; hash the whole resolved model, not the template or
Compose's implementation-specific service hash. Retain the template/source digest
and rendering version separately. Unsupported normalized fields deny admission.

The release directory is `/opt/hybrid-stock-research/releases/<source-archive-sha256>`.
It is independent of the attestation release key, avoiding a path/hash cycle. Publish
`stock-compose.resolved.json`, the existing canonical image/config/Compose attestation
and a root-owned bounded release manifest without replacing unknown files. The manifest
binds source release, immutable image, full canonical stock configuration, resolved
Compose and inert configuration-observation digests, plus the observed canonical run
bound and cadence. It contains no credential, account or raw provider information.

The exact version-1 manifest keys are `schema_version` (integer 1), `kind`
(`stock_research_release`), `release_id` (the source archive SHA-256), `image_digest`,
`config_hash`, `compose_sha256`, `configuration_observation_sha256`, `max_run_seconds`
and `scan_interval_seconds`. Digests are lowercase hex; integer fields reject booleans.
The filename is `manifest.json` under the matching release-ID directory. Derive its
three companion paths locally: `stock-compose.resolved.json`, `stock-configuration.json`
and `runtime-image-attestation.json`. No arbitrary companion path is accepted. All
records use canonical compact JSON plus newline, regular single-link root-owned mode
0444 files and no symlink traversal. Production parents are root-owned with no group or
world write permission; owner-write permission is allowed. The private filesystem-test
helper permits a fictional owner/root and begins ownership/permission checks at that
selected root, while still traversing every ancestor without following symlinks. The
public loader always enforces UID 0 and the fixed production root including its ancestors.
Manifest, observation
and attestation are each bounded to 4096 bytes; resolved Compose is bounded to 65536.
The producer normalizes the probe's parsed closed result before storing/hashing it;
its emitted whitespace is not a second identity format. Manifest run/cadence values
must equal that retained canonical policy observation, not CLI overrides.

`infra/hybrid/stock_release.py` verifies these retained records without Docker, network,
credential, ledger or control operations. It returns immutable policy bytes only after
checking file and namespace identities again. It refuses malformed or replaced artifacts
and does not create missing files, repair permissions or select an alternate production
root. Read/cleanup errors return the fixed `stock_release_unavailable` denial; ambiguous
file-descriptor closes are not retried. Internally consistent fictional records do not
prove who produced them or which container is executing.

Before attestation production, create an inert network-disabled container with no
mounts or credentials, inspect its actual image ID and exact configuration-only
entrypoint/arguments, and execute the canonical stock identity probe. Validate its
closed result schema, actual integer bounds, hash and live=false. This observation
does not itself attest the executing worker: inspect that separate container too.

## Fixed worker policy

The worker uses UID/GID `10001:10001`, a read-only root filesystem, dropped capabilities,
no-new-privileges, init forwarding, 128 pids, 0.5 CPU and 512 MiB memory. It has no
published/exposed ports, Docker socket, explicit host network/PID/IPC/UTS/cgroup sharing,
extra devices, privileged
mode, automatic removal, restart or registry pull. Explicit bridge networking is
used for the reviewed fixed-host official client. Limits require native capacity
verification; their presence is not evidence that the host can sustain them.

The current Compose source does not explicitly set IPC or cgroup namespace mode;
omission cannot prove private namespaces. The future prestart barrier must require
actual IPC and cgroup modes `private`, PID/UTS modes empty and no `host` override.
Docker's empty user-namespace mode uses daemon policy; it does not establish UID
remapping. Do not claim user-namespace isolation from an empty field. A native host
that cannot meet the frozen profile is denied; no automatic daemon upgrade follows.

Bind only these existing canonical paths, with host-path creation disabled:

| Host source | Container destination | Access |
| --- | --- | --- |
| `/var/lib/hybrid-stock-research/state` | `/stock-state` | RW |
| `/var/lib/hybrid-stock-research/archive` | `/stock-archive` | RW |
| `/var/lib/hybrid-stock-research/controls` | `/stock-controls` | RW for current mutex |
| `/var/lib/hybrid-stock-research/exports` | `/stock-exports` | RW |
| `/var/lib/hybrid-stock-research/oauth` | `/stock-oauth` | Worker-only RW renewal |
| Trusted release attestation file | `/run/trading-bot/stock-image-attestation.json` | RO |

The runtime directories are owned by 10001 with mode 0700 and their private files
remain mode 0600. The trusted attestation is root-owned and immutable. Validate
existing path components and identities rather than creating or repairing missing
state during acquisition. Keep this namespace outside `/var/lib/hybrid-paper`.

Run only `python -m trading_bot.runtime.stock_research_worker`, with canonical
`/app/configs`, fixed ledger/archive/OAuth/control/export destinations and paired
expected image / mounted attestation. Environment changes are limited to explicit
live=false flags; no credential, proxy, alternate broker or config override is added.
Actual container environment must equal the inspected immutable image's inherited
environment plus those two overrides; it must not be compared only to the two YAML
keys. Reject unreviewed inherited credential/proxy/config variables rather than
retaining arbitrary environment values in a release record.
The only additional application scratch mount configured by this policy is a bounded
`/tmp` tmpfs. Docker-managed mounts such as private IPC's `/dev/shm` require separate
actual-container inspection. Logs use a bounded local driver.

Docker documents create-without-start and init/signal, pull, healthcheck and read-only
controls. These must be checked against the actual container, not inferred from YAML.
[Create reference](https://docs.docker.com/reference/cli/docker/container/create/),
[Compose service reference](https://docs.docker.com/reference/compose-file/services/).

## Data-only Engine and image observations

`infra/hybrid/stock_container.py` checks supplied bounded JSON metadata, without any
daemon connection. It is a precondition for future create/inspect work, not that work
or authentication of supplied metadata. The fixed Engine API profile is `/v1.52`:
require a Linux amd64/arm64 daemon whose advertised `MinAPIVersion <= 1.52 <= ApiVersion`,
comparing integer version components with no silent downgrade. A read-only October 21
host check observed a compatible advertised API range/platform; actual worker/image
and hardening compatibility remain unverified. The official versioned schema supports exact
`Entrypoint`/`Cmd` arrays and create followed by inspect; an accepted create or ignored
request property is not hardening evidence. A future launcher may use that documented
Engine API over the fixed local Unix socket while retaining Compose's whole resolved
model for release identity. The separate bounded GET-only reader below implements
metadata transport; the separate scoped mutation library below is not a launcher.
[Official API 1.52 schema](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/api/swagger.yaml).

The initial local source profile required API 1.55 and correctly rejected the observed
host's 1.52 maximum. Source and tests were deliberately revised after independent review
of the versioned 1.52 schema, retaining every safety requirement. The fixed client target
is not selected dynamically from daemon capabilities, and no daemon upgrade occurred.
For API 1.52 specifically, require the entire `PortBindings` map to be empty: nonempty
maps with empty/null lists can create unspecified published bindings. Reject nonempty
create warnings. These remain requirements for the future create/inspect barrier.
[Versioned port-binding behavior](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/daemon/server/router/container/container_routes.go).

Before even an inert configuration probe is created, verify the supplied image's local
`Id` (not `RepoDigests`), Linux OS, matching architecture, recipe user and `/app` workdir.
Reject inherited volumes and exposed ports: Docker can union those with image values
despite empty request overrides. Reject nonempty labels, shell/ONBUILD metadata and
escaped-argument mode in this bounded recipe profile. Omitted/null/empty map metadata
is permitted only for the documented optional maps, not as a general missing-data rule.
[Image configuration](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/api/types/container/config.go),
[Docker 29.1.3 merge implementation](https://raw.githubusercontent.com/moby/moby/docker-v29.1.3/daemon/commit.go).

Require exactly `PATH`, `LANG`, `GPG_KEY`, `PYTHON_VERSION`, `PYTHON_SHA256`, `PYTHONPATH`,
`PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `LIVE_TRADING_ENABLED` and
`PREDICTION_LIVE_ENABLED`. Entries are case-sensitive explicit `KEY=value` strings;
duplicates, bare removals, proxies, credentials and arbitrary config overrides deny.
Application values match the Dockerfile and both live flags are already false. PATH
starts with `/app/.venv/bin` and contains only reviewed absolute system directories;
the supplied order is retained for exact created-container comparison. Python 3.12
version/archive digest and public GPG fingerprint syntax are checked. This bounded
value profile does not authenticate the repository's pinned base digest or establish
its actual patch/version/path values; those still require native image observation.
[Current official Python recipe](https://raw.githubusercontent.com/docker-library/python/2a3b794c223ab067d122719541cdd54a068732a5/3.12/slim-bookworm/Dockerfile).

Require the existing Dockerfile's healthcheck test, interval, timeout, start period and
retry values, allowing the versioned optional zero `StartInterval`. Retain a derived
disabled healthcheck with `Test=["NONE"]` and reviewed timing metadata, since Docker
may preserve inherited timing fields when disabling it. Profiles are immutable and
exclude the environment/healthcheck from their repr; malformed metadata returns only
`stock_container_unavailable`. Unknown or inconsistent native behavior needs an explicit
reviewed profile change, not an unsafe fallback.

## Launcher and deadline

### Local Engine metadata reader

`infra/hybrid/stock_engine.py` implements GET-only version, immutable-image and
full-CID/generated-attempt inspection routes. It has no Docker mutation, retry,
CLI, remote context, endpoint override or configuration/credential operation.
The production connector requires Linux UID 0, a root-owned non-world-accessible
socket at `/var/run/docker.sock`, and a positive-PID UID-0 Unix peer. Missing peer
credential support denies. This does not prove how the daemon is configured or
make any returned container owned by the launcher.

Each new connection has one five-second monotonic operation deadline, including
connect/send/headers/body. Repeated reads cannot reset it. Requests use HTTP/1.0
and `Connection: close`; only a 200 response with explicit length or EOF framing
is accepted. Headers are bounded to 8192 bytes and body to 1 MiB. Duplicate or
malformed headers, transfer encoding, truncation, excess bytes already buffered,
non-success status and read/connection failures return the fixed
`stock_engine_unavailable` error without response text. Response JSON and policy
identity still require the separate Engine/image/prestart verifiers. Native
HTTP/socket compatibility is not established by socketpair fixtures. A separately
authorized October 21 read-only host check executed the reviewed source in memory
and performed one `/version` GET. Fixed-socket/root-peer/HTTP observation and the
version parser succeeded with API 1.52/Linux amd64. No host file was installed and no
Docker mutation, image/container inspection or broker call occurred. This bounded
proof does not establish worker/image compatibility, ownership or applied hardening.

### Source profile for created-container admission

`infra/hybrid/stock_prestart.py` implements a data-only API 1.52 request and inspection gate. Its
inputs must come from the root release loader and separately observed image; none
of its returned values grants execution authority. It performs no Docker operation.
The root launcher must later obtain fresh observations itself while holding its
host lock, and retain the exact attempt/CID relationship before any start request.

Use a fresh 32-character lowercase hexadecimal attempt ID, a generated
`hybrid-stock-research-<attempt>` name, and exactly three ownership labels:
`org.hybrid.stock.managed=stock-research`, `org.hybrid.stock.release=<release ID>` and
`org.hybrid.stock.attempt=<attempt>`. Compare the complete 64-character CID, not a
name or prefix. Require the actual immutable image, generated name/labels, exact
worker command, image environment, user/workdir, disabled healthcheck, no interactive
streams, SIGTERM and ten-second stop timeout. A fresh `created` state must also have
all inactive flags, zero PID/exit/restart values, empty error and zero start/finish
timestamps. Reject nonempty create warnings and unknown creation-response fields.

Construct the raw API request from the already verified complete Compose model;
never accept caller-supplied container options. Explicitly request private IPC and
cgroup namespaces, runc, a 64 MiB private IPC shared-memory segment, the fixed memory,
swap/CPU/PID limits, and private propagation on all six structured binds. These
make existing isolation requirements explicit rather than relying on daemon defaults.
No host directory creation is permitted. Request and resolved mount inventories
must agree exactly, ignoring only array order; the attestation alone is read-only.
The string-form `/tmp` tmpfs is separate from the six reported binds.
Docker's image merge can replace the empty request `Config.Volumes` map with a
null image value. Created inspection accepts only `{}` or `null` on that required
field; missing, nonempty and mistyped values still deny. This does not permit an
inherited image volume or an additional resolved mount.
[Versioned image merge](https://raw.githubusercontent.com/moby/moby/docker-v29.1.3/daemon/commit.go).

Inspect all 69 versioned HostConfig fields with exact JSON types, allowing omission
only for the seven fields marked optional by that schema. Reject extra fields,
nonempty raw binds, ports, capabilities, devices, groups, annotations, storage/sysctl
overrides, alternate namespaces, auto-removal and restart. Nil and empty collections
are equivalent only on named fields whose empty values have the same disabled
semantics. Require Docker's twelve fixed masked paths plus at most 4096 unique
CPU thermal-throttle paths, and its five readonly paths. Explicit empty masks deny.
Unknown daemon-added ulimits or logging options deny rather than being silently
adopted. The initial implementation accepts only the two explicit bounded logging
options; additional daemon cache options need an explicit reviewed profile change. Native proof
must establish the actual daemon profile before installation.

Created-stage AppArmor metadata is expected to be empty for this request; it is not
proof of an applied security profile. Network metadata must describe a single
uninitialized bridge endpoint, no published ports or active sandbox. Driver/storage
metadata is informational and cannot substitute for any mount, namespace, image or
resource check. Applied security, cgroup enforcement and filesystem/credential
ownership still need separate native verification after an authorized inert start.
[Versioned configuration types](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/api/types/container/config.go),
[HostConfig types](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/api/types/container/hostconfig.go),
[inspect types](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/api/types/container/container.go).

### Durable attempt protocol

`infra/hybrid/stock_attempts.py` implements a root-private operations store at
`/var/lib/hybrid-stock-operations`, separate from worker-writable state. This is
local source with fictional-filesystem evidence; no production namespace has been
initialized by this work. It makes no Docker, broker or control call. Inputs must
come from the trusted release loader and actual observation pipeline.
Initialization is explicit and refuses existing/partial namespaces. Acquisition
never creates or repairs the namespace or its permanent `launcher.lock`. The
root-owned mode-0700 directory and mode-0600 single-link files are traversed without
symlinks. A canonical namespace record binds a random namespace ID plus the actual
root and lock device/inode identities. Hold the same nonblocking flock throughout
the attempt, including observed termination; cleanup must release all handles.

Each fresh random 32-hex attempt has its own mode-0700 directory. Protocol-immutable
canonical records are written exclusively, bounded to 4096 bytes, fsynced and read
back. The intent binds namespace, attempt, release/image/config/Compose identities,
canonical duration, actual boot ID, UTC and monotonic timestamp. Publish an atomic
`active.json` pointer to its hash and fsync the parent before returning admission.
Unknown files, lost anchors, altered identities or ambiguous writes deny admission.
Unfinished attempts prevent new ones; completed receipts are retained.

Persist the verified full CID separately before start. Write an exclusive start
fence before the single start request, including boot/clock domain and the absolute
monotonic TERM deadline derived from canonical duration. Persistence overhead counts
against that bound. Start also requires the same owner session's successful CID
durability acknowledgement and the exact acknowledged receipt hash. Readable bytes
after a failed file/directory flush never supply that acknowledgement. Fencing is
one-use even following an uncertain local write.
Only the store session that acknowledged a fresh intent can prepare a start;
reopening the store never adopts an unfinished attempt for execution. Recovery may
only inspect and stop the owned container, including lookup by the generated name
when create acknowledgement was lost.

A retained start fence requires a valid created receipt with matching CID and
ordered same-boot monotonic timestamps; loss or corruption of that anchor denies.
Generated-name recovery is available only when no persisted start identifies a CID.
A terminal receipt requires supplied actual inspection to match the owned identity,
image/name/labels, no restart/removal policy, non-running/non-paused/non-restarting
state and zero PID. Preserve exit/OOM/error-presence and separate local observation
time, plus Docker's start/finish timestamps; do not retain diagnostic text or infer
successful research from exit code zero. A reopened session requires a fresh actual
stopped observation and successful explicit durability reconfirmation of the unchanged
terminal receipt before admitting a later attempt. Readable terminal bytes alone
cannot grant admission after a failed flush. A changed CID/lifetime, unsafe state or
uncertain reconfirmation denies and clears the session's acknowledgement. Reconfirmation
does not rewrite, repair or initialize records.
Stop processing revokes prior CID/start/terminal acknowledgements before its first
filesystem validation, so even an entry-validation failure cannot preserve an earlier
permission to start or admit a later attempt.
This store is sequencing/consistency evidence, not a substitute for native
observations, control authority, authentication or the process supervisor.
Each opened owner session admits at most one fresh attempt. At most 8192 retained
attempt directories fit the bounded inventory; an explicit completed-receipt
retention procedure is required before that limit, without deleting active receipts
or replacing namespace/lock anchors. Public functions fix root UID and production
path; only private filesystem-test helpers accept a fictional root/owner.

### Scoped create/start transport

`infra/hybrid/stock_engine_mutation.py` is an uncomposed root-only library, with no
CLI, scheduler or service caller. Production operations require the fixed Linux
UID-0 operations store and the existing fixed-socket/root-peer connector. The
GET-only reader retains its separate closed routes and 200-response policy.

`create_worker(store, release, image)` consumes the still-open owning store's one-use
fresh create claim, matches retained release/image/config/Compose/duration identities
and derives the name and request through `worker_request`. Recovered, closed or
terminal attempts cannot create; constructing another transport does not reset the
store latch. A valid 201 response returns only a checked CID acknowledgement. It
does not record a verified CID or start anything. Actual inspection and
`record_created` remain separate mandatory steps for the future supervisor.

`start_worker(store)` invokes `prepare_start()` itself and derives the CID from its
local result. There is no input route, body, CID or caller-created start fence. The
closed shared exchange owns those same sequences even if called directly. Immediately
before sending it rechecks the namespace, active identity, issued object, exact
acknowledged receipt hashes, boot and unexpired monotonic deadline. A successful 204
returns the fence for supervision; it does not mean the process exited or produced
research. A second start preparation remains denied across transport objects.

Each exchange has one absolute five-second I/O budget, including local preflight,
connect, send and response. HTTP/1.0 close framing, 8192-byte headers and 1-MiB body
caps are fixed. Create requires a complete bounded 201 JSON acknowledgement without
warnings; start requires 204 with no response bytes, including a delayed extra byte.
Duplicate/malformed headers, transfer encoding, unexpected statuses, partial sends
and timeouts deny with `stock_engine_mutation_unavailable`, without daemon diagnostics.
No outcome refunds a consumed claim or retries a request. In particular, 304 is not
a fresh-start acknowledgement and a reader error is not proof of 404 absence.

No native mutation has been exercised. Signal/stop/removal, ambiguous-outcome recovery,
actual ownership observations, the trusted release producer, deadline supervisor and
paused timer are still required before this library can be composed into a worker.

Use a root-owned standard-library launcher, fixed local Docker Unix socket and
scrubbed environment; do not inherit a remote context, proxy, user env file or shell
expansion. The launcher holds a separate stable host flock across creation through
observed termination. Before creating, durably record an attempt identity and unique
stock container name/ownership labels under the root-private operations namespace.

Create without starting. Capture the CID, inspect actual image, command/arguments,
user, mounts, network, restart/removal/healthcheck policy, environment and resource
hardening against the complete frozen release policy. Persist the verified CID and
release/attempt relationship before start. Unknown collisions or mismatches deny
start; they cannot be adopted or deleted as if owned. The launcher's known generated
name and attempt labels are execution receipt fields, not mutable release parameters.

The active run's monotonic deadline starts immediately before the single start
request and lasts no more than the observed canonical `max_run_seconds` (maximum
450). Record that TERM deadline separately from the at-most-ten-second shutdown grace
and the final observed-stop timestamp; termination at the deadline does not mean the
container was already stopped then. All Docker operations are individually bounded. Ambiguous create/start/wait
outcomes are reconciled by inspection; never retry a start or run blindly. Poll the
verified CID. On deadline/signal, send TERM with at most ten seconds' grace, then KILL
if needed, and inspect stopped state with bounded cleanup. A Docker CLI timeout alone
is not a stopped-container result. Collect bounded status/exit/OOM evidence before
removal, without collecting provider payloads or arbitrary logs.

Persist boot/clock domain and owned CID receipt for signal, host-process death and
reboot recovery. An unfinished attempt must be inspected and safely stopped before
any new creation; never restart it. Unknown container ownership blocks with an incident.
Future retries use a new eligible worker cycle, preserve the ledger/reservation and
cannot replay an old slot. Loss of a terminal acknowledgment is not a refunded call.

## Installation, timer and rollback

Installation requires an explicitly initialized paused collector, intact dedicated
ledger and no unknown active stock attempt. It never initializes or resumes controls
implicitly. Prove a network-disabled paused worker invocation with no OAuth mount
returns control_denied and appends no claims before installing any scheduled path.

The oneshot timer is completion-relative (`OnUnitInactiveSec` from canonical cadence),
`Persistent=false`, `Restart=no`, with no overlap/catch-up. Installation leaves it
disabled and controls paused. Unit limits must allow the finite host cleanup budget
and have identity-checked post-stop recovery of the actual container; killing only
the host helper is insufficient.

Upgrade or rollback stops only the stock timer/owned worker, acknowledges paused
authority, switches the stock release and preserves ledger/archive/control continuity.
Do not restore an old running control record or automatically resume a prior image.
Native Linux image/mount/unit/deadline/reboot checks, credential-exclusive-use procedure,
backup/off-host restoration and stock monitoring remain required separate evidence.
