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
published/exposed ports, Docker socket, host namespaces, extra devices, privileged
mode, automatic removal, restart or registry pull. Explicit bridge networking is
used for the reviewed fixed-host official client. Limits require native capacity
verification; their presence is not evidence that the host can sustain them.

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
The only writable scratch is a bounded `/tmp` tmpfs. Logs use a bounded local driver.

Docker documents create-without-start and init/signal, pull, healthcheck and read-only
controls. These must be checked against the actual container, not inferred from YAML.
[Create reference](https://docs.docker.com/reference/cli/docker/container/create/),
[Compose service reference](https://docs.docker.com/reference/compose-file/services/).

## Launcher and deadline

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
