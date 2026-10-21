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
model for release identity. No Engine client or write operation is implemented here.
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
