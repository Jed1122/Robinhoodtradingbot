# Private hybrid host watchdog

`infra/hybrid/watchdog.py` is a host-only, standard-library observer. It checks the
existing isolated `hybrid-paper-hybrid-paper-1` container and records private local
incident/recovery transitions. It never changes the application, restarts a service,
resumes research, sends a notification, reads dashboard tokens or journal contents,
contacts a brokerage, or authorizes live operation. It does not inspect the original
paused service. This package adds no recurring paid service.

These are reviewed installation artifacts, not evidence that a timer is installed or
that unattended operation is qualified. The primary operator owns installation,
deployment identity attestation, backup production, off-host recovery and validation
on the actual Linux host. The existing application image need not change.

## Observations and boundaries

Each invocation uses one fixed `/usr/bin/docker inspect --format` call selecting
only image ID, running/status, OOM state, restart count, start time and health status.
It never collects full inspection output, environment variables, container logs or
Docker stderr. The subprocess has a five-second deadline and an 8 KiB stdout limit;
its environment is scrubbed and pins the local Unix Docker socket. Root Docker
access is inherently powerful, so the root-owned script and manifest remain trusted
operator artifacts. There is no Docker socket mount in the application.

Three unauthenticated requests target only `127.0.0.1:8081`: `/healthz` must return
200 with exact boolean healthy=true and live_enabled=false; `/readyz` must return
503; `/api/hybrid/snapshot` must return 401. Each request has a three-second total
deadline and a 4 KiB response limit. Proxies and redirects are disabled. Bodies are
discarded and never enter the spool or logs. The implementation uses POSIX signals
and runs in the main thread of the Linux oneshot process.

Host checks read only `/proc/meminfo`, filesystem free-space/inode statistics for
the watchdog and backup directories, and the approved backup success receipt plus
archive metadata. Application health performs the application's existing internal
journal verification; the watchdog itself never opens that ledger. Unknown Docker
observations do not clear existing image/container incidents. A change in start
time or restart count for the same release raises an unexpected-restart incident;
the first observation establishes the baseline. A subsequent unchanged observation
records recovery, preserving the earlier incident.

CPU, RAM, PID, filesystem and logging restrictions on the application remain those
in `compose.hybrid.yml`. The watchdog reports resource pressure; it does not change
limits or delete application data, Docker images, releases or backups.

## Deployment-owned manifest and receipt

The manifest must be a root-owned regular private file in a root-owned mode-0700
directory. It requires exactly these keys, with no credentials or delivery endpoint:

| Key | Required value |
| --- | --- |
| `schema_version` | integer `1` |
| `release_id` | reviewed source archive SHA-256, 64 lowercase hex characters |
| `expected_image` | exact reviewed immutable `sha256:` image ID |
| `deployment_config_hash` | exact existing canonical loaded configuration SHA-256 |
| `compose_sha256` | exact reviewed Compose file SHA-256 |
| `container_name` | `hybrid-paper-hybrid-paper-1` |
| `backup_receipt` | absolute path to the root-private backup success receipt |
| `backup_max_age_seconds` | positive integer derived by the owner from existing canonical backup cadence, normally twice that cadence |
| `minimum_free_bytes` | positive integer operator-reviewed free-space floor on both observed filesystems |
| `minimum_free_inodes` | positive integer operator-reviewed inode floor |
| `minimum_available_memory_bytes` | positive integer operator-reviewed host available-memory floor |

There is no expected-image default. Derive these values from the exact trusted
release and fresh host capacity evidence. This manifest contains host observations
and release bindings, not a second investment, trading authorization or backup
policy configuration system. Do not edit the application's canonical configuration
just to move an operations path: existing hybrid history is bound to its config hash.

The receipt requires exactly `schema_version`, `completed_at`, `release_id`,
`image_digest`, `deployment_config_hash`, `compose_sha256`, `archive_sha256`,
`archive_name`, `archive_bytes`, `encryption`, `structural_check`, and
`application_check`. Version is integer 1; completion is an aware UTC ISO timestamp
that is neither future nor older than the permitted age. Release/image/config/Compose
must equal the manifest. The archive hash is 64 lowercase hex characters; its name
is a safe basename ending `.db.age`; size is a positive integer; encryption must
equal `age-v1`; both check flags must be exact true booleans.

The referenced archive must be a private root-owned regular single-link file in
the receipt's own private parent directory with the recorded size. The watchdog
does not read ciphertext or recompute its hash. A receipt is trusted root operational
evidence of the backup producer's pre-encryption structural and application checks;
flags alone are not independent verification. It proves neither successful
off-host decryption nor a disaster-recovery drill, strategy qualification or live
authority. Missing encryption/receipt prerequisites produce a failed observation.

## Durable local incidents

`--state-dir` must already be a private root-owned mode-0700 directory. The script
does not create operator directories. `watchdog.lock` provides nonblocking process
exclusion; `state.json` contains bounded incident state and a local outbox. Root-owned
mode-0600 files, regular types, single links and every path component are checked;
symlinks, unknown schema fields, invalid checksums, future state and backwards clocks
are rejected. No exception text, command output, receipt body or operator path is
printed on failure.

Condition identity is stable across process restarts: SHA-256 of release identity
and reason code. Repeated failure updates first/last observations and count without
creating another event. Recovery and a later recurrence each create one new event.
First/last/count cover failed observations across the condition's lifetime. Prior
release incidents stay recorded and are not cleared by a later release.

State is committed by exclusive temporary creation, file fsync, atomic replacement
and directory fsync while holding the lock. A private bounded interrupted temporary
write can be discarded on the next invocation because it was never authoritative.
The initialization marker in the lock prevents silent reset when an established
`state.json` disappears. Neither this marker nor the checksum resists root compromise
or complete filesystem rollback. A post-rename fsync failure returns failure even
if the replacement exists; the next invocation verifies the resulting state.

The limit is 256 total condition/event records and 256 KiB encoded state. Capacity
exhaustion, unsafe paths, corruption and write failure preserve the last committed
file and exit nonzero. Undelivered records are never automatically discarded.
Every outbox event remains `pending_local`; there is no delivery acknowledgement,
external sink or notification promise. Operators must review the private outbox
and establish a reviewed archival/acknowledgement process before it approaches
capacity. Do not delete state or the lock to make an error disappear.

The schema preserves the existing `Alert` concepts of type, reason_code,
observed_at and sanitized details. This host record uses explicit
`host_operational_failure` / `host_operational_recovery` types rather than pretending
those host conditions are broker incidents. Importing the application alert module
would require `httpx` on the host and its current `AlertService` deduplication is
in-memory; this package requires only Python's standard library and leaves that
application API unchanged.

Exit 0 means all observations passed, even if old local events await operator
review; exit 1 means one or more observations failed/are unknown, after a durable
record update; exit 2 means evidence could not be safely read or committed. The
oneshot prints only a bounded sanitized summary. A full disk can also prevent a
durable outbox update: it must not be reported as successful. Systemd failure status
and operator inspection remain necessary; a local watcher cannot report total host
loss without an independently authorized external observation channel.

## Review and installation boundary

Before installing, the primary operator must verify exact executing image and
release metadata, available capacity, directory ownership/modes, public backup
encryption prerequisites, successful backup receipt and the untouched original
service. No private decryption identity belongs on the host. Review the complete
script and both units and verify their hashes after transfer.

The supplied service expects the reviewed script at
`/opt/hybrid-paper-operations/watchdog.py` and manifest at
`/etc/hybrid-paper-operations/watchdog.json`. Its `StateDirectory` creates the
root-private `/var/lib/hybrid-paper-operations/watchdog` namespace. The oneshot
has a 30-second service timeout, 96 MiB RAM, 10% CPU, 32 tasks, read-only system
paths, no capabilities, and loopback-only IP access. It does not start Docker.
The timer begins two minutes after boot, then five minutes after each activation,
within its 15-second timer accuracy. Nothing here enables or installs those units.

On the target Linux system, validate the reviewed copies before installation:

```shell
systemd-analyze verify infra/hybrid/hybrid-watchdog.service infra/hybrid/hybrid-watchdog.timer
```

After separately authorized installation, run one observed invocation using the
exact reviewed manifest; inspect its exit code/private outbox and systemd status.
Exercise failure and recovery with fictional fixtures in a separate local namespace,
without stopping, modifying or resuming either deployed service. Validate timer
sandbox compatibility on the real host before treating scheduled checks as present.

## Verification and remaining work

Local fixture verification:

```shell
uv run pytest tests/deployment/test_hybrid_watchdog.py tests/deployment/test_hybrid_deployment.py -q
uv run ruff check infra/hybrid/watchdog.py tests/deployment/test_hybrid_watchdog.py
```

On 21 October 2026 the watchdog suite passed 50 tests. The broader command
`PYTHONPATH=src uv run pytest tests/deployment -q` passed 76 tests and skipped four
existing encrypted-backup tests because the local `age` executable was unavailable.
The first broader invocation omitted `PYTHONPATH=src` and failed collection with a
`trading_bot` import error; the corrected invocation above passed. Repository Ruff,
strict mypy for 414 unchanged application source files, the required application
Bandit scan and lock check also passed. Native `systemd-analyze` was unavailable on
this macOS workstation; no native unit or deployed timer result is claimed.

An additional Bandit scan of this host helper reports the low-severity generic
`B404` subprocess-import diagnostic. The helper deliberately needs the fixed local
Docker observation subprocess described above; it accepts no free-form command
from the manifest and never enables a shell. That diagnostic was retained. Full
application regression remains the primary integrator's central verification step.

The initial entry-point test failed before implementation. Follow-up tests exposed
missing-history reset and a stalled-body total-deadline gap before those fixes.
Fixtures cover private durable transitions, identity drift, unknown state, restart,
OOM, HTTP denials, receipt freshness/bindings, resource pressure, unsafe paths,
corruption, clock rollback, lock contention, interrupted writes, full-disk publication
failure and record/byte limits. No actual Docker, network, ledger or host observation
is needed for these tests.

Next steps are integrated review with the backup and attestation producer, native
Linux unit validation, authorized installation, a recorded first backup/application
restore drill and watchdog failure/recovery rehearsal, and sustained bounded
resource observations. External delivery and off-host decrypted recovery require
their own explicit setup. These operations artifacts do not complete investment
evidence, broker correctness or live authorization.
