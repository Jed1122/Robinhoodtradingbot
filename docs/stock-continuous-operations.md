# Continuous individual-stock research operations

This is the Task3 implementation/runbook. Local test results, native installation,
scheduled acquisition, authentication lifetime, and restore evidence are separate
acceptance records. Until current native receipts establish otherwise, the Task2
installation remains paused. This document does not declare continuous operation,
strategy qualification or live-trading readiness. Live trading stays disabled.

## Runtime boundaries

The immutable research image remains the only provider client. Its fixed13-tool
facade excludes accounts, portfolios, orders, approvals and transfers. Research
controls authorize collection only; they never enable investment execution.
The reviewed provider contract is the official Robinhood Trading MCP. Current
tools and schemas are checked at runtime, rather than inferred from the public
[tool catalogue](https://robinhood.com/us/en/support/articles/trading-with-your-agent/).
The public [external-agent guide](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)
does not establish indefinitely renewable daemon access. Fresh public metadata
was verified on2026-10-22; it advertised no revocation endpoint. Do not invent one.

Collector, operations history and root controls retain the existing
[repeated-cycle](stock-repeated-cycle-design.md) and
[paused-installation](stock-paused-installation.md) contracts. An unresolved
attempt is recovery work, never permission to create another worker. The root
operations namespace binds filesystem inodes: copied records are forensic inputs,
not an executable namespace on a replacement host.

Maintenance uses a separate immutable root-owned Python3.12 virtual environment
under `/opt/hybrid-stock-research/maintenance/<source-commit>`. Build it without
pip using the existing distro stdlib, verify the bootstrap pip wheel against
`uv.lock`, and install the frozen hashed production requirements plus that exact
pip pin. Use only binary wheels, a scrubbed environment, explicit public PyPI and
`PIP_CONFIG_FILE=/dev/null`; disable user configuration and dependency resolution.
Preserve actual successful installer and `pip check` exits. Verify the exact
distribution inventory, interpreter/platform, disabled system-site-packages,
source/archive/config/lock/requirements identities and safe file ownership. A
receipt alone does not prove an installation occurred, nor does the research
image attestation attest this separate maintenance interpreter.

No global host package or new paid service is required. Source/runtime parents
must permit UID10001 read/traverse, remain root-owned and have no group/world
write permission. Runtime data remains UID10001/mode0700; private files0600.
Never loosen OAuth or unrelated runtime permissions to make a helper work.

## Scheduling and boot

`stock_continuous_units.unit_files` preserves the collector service/timer bytes
and adds bounded monitor/backup services and separate recovery/bootstrap gates.
Render from the exact verified release/checkout, inspect all effective unit
properties/drop-ins and run native `systemd-analyze verify` before installation.

- Collection remains completion-relative, has no restart/catch-up loop and is
  limited by its450second worker lifetime and persisted daily quota.
- Monitor cadence is five minutes. Backup cadence is24hours, with a separately
  observed initial backup. Neither timer authorizes research collection itself.
- Recovery is a different invocation with no release argument or new dispatch.
  Only after it succeeds may bootstrap inspect a terminal/empty operations store,
  current bound running control and enabled/active collector timer. It releases
  the nonblocking operations lock before one systemd queue request. The worker
  independently rechecks controls and admission. Ambiguous queue failure is not
  retried by bootstrap.
- Maintenance is network-isolated, denies OAuth filesystem access, clears helper
  groups/environment and drops to UID/GID10001 before application readers run.
  That owner has no Docker-socket permission. Only existing mutex anchors and
  named staging/spool/backup directories are writable in maintenance sandboxes.
  Monitor can write its incidents directory and receipt/control read-lock anchors;
  backup can write its receipts directory and snapshot/encryption paths. Neither
  receives the maintenance parent or the other service's store. Bootstrap receives
  only its operations and control-lock anchors.

Monitor, backup and bootstrap deliberately omit `User=` while retaining
`Group=root`: the system service manager's documented default user is root, and
the entry points still reject a nonroot caller. On the observed systemd255
host, explicit `User=root` with these seccomp restrictions removes `CAP_SETUID`
from the parent's permitted/effective sets before `setpriv` can drop to10001.
The [systemd255 execution source](https://github.com/systemd/systemd/blob/v255/src/core/exec-invoke.c#L4429-L4509)
explains that behavior; the [system service default](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml#L524-L527)
lets these three services keep the existing helper boundary without introducing
ambient capabilities. Recovery and collector units retain their existing bytes.
The sandbox, writable paths, deadlines, memory limits and no-new-privileges
settings remain unchanged. Monitor and bootstrap use a bounded 50% CPU quota,
matching the collector; backup retains 25%. Their 45-second internal deadline
and 60-second service timeout remain in force. An actual read-only bootstrap
prequeue probe reached the helper deadline at 10%; changing only its CPU quota
to 50% completed the helper in 20.425 seconds and the full probe in 20.794 seconds,
within the existing 128MiB memory limit. That probe queued no collector and
called no provider. It does not establish the monitor's native timing or replace
each installed release's runtime verification.
For each installed release, verify the actual sandboxed parent UID/GID0 and the
executed helper's real/effective/saved UID/GID10001, empty supplementary groups,
zero effective/permitted/inheritable/ambient capability sets and
`NoNewPrivs=1`; renderer tests alone do not establish this native evidence.

Paused/killed authority is never automatically resumed. Preserve control_id,
generation and predecessor hash during upgrades and recovery. No host reboot is
complete evidence until the actual post-boot identities, services, owned attempt,
ledger and unrelated service health have been independently reconciled.

## Authentication transfer and qualification

Use only the designated standalone stock-research grant, never the interactive
Codex credential or an unrelated account/client store. Hold its workstation lease
through private SSH transfer and validation. The same grant must have one owner:
disable/retire the workstation path before allowing the collector to refresh it.
Encrypted files plus their decryption key are still a sensitive credential store.
Store them only under the private host OAuth directory with correct ownership;
never include them in source, snapshots, Docker build context or command output.

The [authentication guide](stock-research-authentication.md) specifies automatic
generation fencing and owner-only offline status. Pending/denied state requires
review; never repair it by restoring an old refresh token. Actual post-expiry
renewal must happen without a browser/developer-client session and be verified
again by a later fresh scheduled process. Explicit renewal and fixtures do not
substitute for elapsed natural expiry.

The saved grant's conservative threshold is2026-10-29T18:45:38.277657Z; its full
response-time-plus-lifetime bound is2026-10-29T18:46:08.719989Z. Qualification must
observe an actual cycle after the later bound. Earlier rotation changes the
generation/deadline under test and must be recorded honestly. A separate test
grant is required for an official human revocation drill. Do not revoke the
production grant or infer remote revocation from local credential deletion.

## Coherent encrypted backups

Explicitly initialize these dedicated directories; startup never resets them:

- `/var/lib/hybrid-stock-research/maintenance`: UID/GID10001, mode0700.
- `/var/lib/hybrid-stock-maintenance`: root0700 maintenance parent.
- Its `incidents/`: root0700, explicitly initialized incident spool. This closed
  store contains only its own state and lock, never the receipts directory.
- Its sibling `receipts/`: root0700 plus permanent empty0600 `.stock-receipts.lock`.
- `/var/lib/hybrid-stock-backups`: root0700, ciphertext only.
- `/etc/hybrid-stock-research/backup-recipient.public`: root0400,32raw public-key
  bytes under a root0700 directory. Generate/retain the corresponding private key
  only on the trusted off-host receiver. Never copy it to the collector.

The backup coordinator holds the existing operations barrier, rejects unresolved
workers and validates the public recipient before creating plaintext. The reduced
owner helper locks archive, controls and export anchors in the documented order.
It copies a quiescent SQLite main/WAL input into private staging, runs SQLite's
backup API there, validates integrity/foreign keys/migration/audit guards and
replays every committed capture/report. It preserves pending charges, control
identity and original acquisition/export timestamps. No observation is refreshed
merely because it was backed up.

New claims retain their canonical configuration in the same ledger transaction.
Replay uses each claim's original configuration and the retained export's original
policy. Existing history without a saved graph is supported only when its hash
matches the current canonical configuration; unknown older policies fail closed.

The canonical snapshot contains only `state/ledger.sqlite3`, `archive/`, `exports/`,
`canonical-config.json`, `saved-control.json` and a hashed `manifest.json`.
No OAuth, unrelated ledger or executable operations namespace is included.
Packaging is a closed, uncompressed USTAR subset, with canonical headers, private
files, finite quotas and exact EOF. It does not run a general extraction API.

The parent encrypts in bounded chunks with pinned libsodium secretstream and a
fresh sealed stream key. Required FINAL/EOF and authenticated framing reject
tamper, truncation, reordering and trailing bytes. It flushes, independently reads
back and exclusively publishes ciphertext before removing exact successful
plaintext staging. Only then can it append a backup success receipt. Failed
partials/orphans remain evidence; they never advance backup freshness. A durable
pending fence blocks interrupted publication. Before a later snapshot, retained
ciphertext names, private metadata and sizes must match trusted backup receipts;
an orphan from failed staging cleanup or receipt publication also blocks admission.
This bounded admission check preserves historical releases and avoids rereading
all retained ciphertext; publication, off-host copy and restore verify full hashes.

At most four distinct plaintext staging attempts and16ciphertext generations are
admitted. No unacknowledged or sole good backup is automatically deleted. Capacity
or interrupted publication blocks further admission and requires audited retention
work. The2GiB canonical bundle limit is smaller than the configurable8GiB archive
ceiling: larger configurations fail closed and require a separately reviewed
backup-capacity change. Monitor free storage and reserve enough temporary space.
Snapshot admission counts the bounded archive/export inventory and reserves an
additional 256 inodes for records, directories, SQLite scratch and bundle overhead.

## Off-host copy and application restore

Pull ciphertext and its trusted receipt over the existing strict-host-key SSH
connection into a private receiver directory. Verify byte count and complete
ciphertext SHA256 independently after transfer. A copied receipt is consistency
metadata, not proof of an actual copy. Record `offhost` success only after that
verification; it must match a retained backup's identities. Receiver availability
must be monitored: a laptop that is off cannot promise unattended daily copying.

Run `trading_bot.runtime.stock_backup_restore` with the32byte private recipient
file, a new destination and mandatory trusted ciphertext/manifest hashes. Verify
actual decrypted SQLite/application replay and pending charges. The restored
control is always killed, preserving its saved identity and chaining generation;
without current trusted control high-water evidence this is an offline drill.
It never overwrites the live ledger, clears a later kill, restores a running grant
or launches a provider. Record `restore` only after actual completion, bound to a
previously verified off-host receipt. Never claim JSON/SQLite readability alone
is an application restore.

Public-key encryption does not authenticate the sender. Provenance depends on
the trusted root-owned receipts, strict SSH channel and retained hashes as well
as decryption/application checks. Keep private keys and raw financial payloads
out of logs, reports and Git.

## Local incidents and completion evidence

`stock_health` evaluates release/control/projection identity, actual owned worker
exit, original claim/result/source clocks, timer state, storage and verified
backup/copy/restore times. Launcher exit0 is only lifecycle completion; export
generated_at is not acquisition freshness. Empty validated rankings may be valid.
Running control grants must match the installed configuration and image-derived
code identity before an observation can resolve retained incidents.
Backup, off-host and restore freshness also require receipts bound to the current
configuration, code, release and image. Historical receipts remain retained but
cannot establish recovery coverage for an upgraded deployment.
Retained enrichment currently refreshes every6hours while source TTL is2hours;
stale dossiers remain suppressed and visible as `source_stale`, rather than
silently extending their evidence lifetime.

The initialized private incident spool deduplicates episodes, preserves unresolved
incidents after unavailable observations and bounds resolved history. Only complete
valid observations may clear incidents. Journald/spool are local operational
alerts; no email, chat message, financial action or automatic remediation is sent.
Unknown observation, malformed state and clock rollback remain visible failures.

Task3 completion requires the current full stock regression/static/coverage checks,
independent source review, exact native release/sandbox/runtime receipts, multiple
actual scheduled acquisitions, process/reboot recovery, scheduled encrypted backup,
off-host ciphertext verification, decrypted application restore, natural-expiry
renewal and separately revoked-test-grant denial. Missing evidence remains pending.
Next project work is Task4 stock-data qualification and Task5 strategy validation;
research ranking and successful deployment cannot enable real-money execution.
