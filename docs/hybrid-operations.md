# Isolated hybrid paper operations

These artifacts add a separate `hybrid-paper` service. They do not replace, restart, or use the
existing paused `trading-bot` service. The hybrid runtime is experimental, initialized paused,
and live execution is disabled. No strategy promotion or performance claim follows from deployment.

## Current feasibility and limits

A read-only host observation found one CPU, approximately 1.4 GiB available RAM, 42 GiB free disk,
Docker 29.1.3 and Compose 2.40.3. The existing container had no mounts and used loopback port 8080.
These observations are capacity evidence at one instant, not application acceptance or sustained
load qualification. The authorized SSH account has passwordless sudo and no Docker-group membership.
Use existing capacity only; do not provision resources or publish a registry image.

`compose.hybrid.yml` limits the new service to 0.5 CPU, 512 MiB and 128 processes. It runs UID/GID
10001, a read-only root filesystem, dropped capabilities, no privilege escalation, a bounded tmpfs
and bounded Docker logs. Its only bind mount is `/var/lib/hybrid-paper:/state`, separate from all
brokerage credentials and production evidence. Port 8000 publishes only as `127.0.0.1:8081`.
There is no production credential transfer or broker integration in this deployment procedure.

## Prepare the exact reviewed release

Integrate the reviewed runtime, dashboard and these operations files first. All required changes
must be committed and the source checkout clean. On the trusted workstation:

```shell
python3 infra/hybrid/prepare.py /private/operator/path/hybrid-source.tar
```

The command runs `npm ci` and `npm run build`, archives committed `HEAD`, appends the ignored freshly
built `dashboard/dist`, and prints the complete archive SHA-256. Record that hash and reviewed source
revision. The archive is source plus static UI only: inspect its file list before transferring.
The dedicated Dockerfile ignore file keeps unrelated archives, credentials, state and host files
out of the image context. The existing default Dockerfile and ignore file remain unchanged.

After review, transfer that archive to a private staging path on the existing host. Separately
transfer the reviewed `infra/hybrid/deploy-remote.sh` script (the archive has not yet been extracted).
Check its hash against the reviewed workstation copy, then invoke it explicitly as root:

```shell
sudo -n sh /private/staging/deploy-remote.sh /private/staging/hybrid-source.tar <archive-sha256>
```

This is an operator execution step, not an action performed by preparing the artifacts. No deployment
was performed when writing this runbook. Remote builds may download the digest-pinned Python base
and frozen Python dependencies; there is no registry publication. Verify existing provider transfer
allowances if operating constraints require zero transfer charges.

The script rejects unknown existing managed paths, symlinks, unsafe ownership, unrecognized archives,
and adoption of existing unknown Compose project containers. It keeps releases in
`/opt/hybrid-paper/releases/<archive-sha256>`, builds with `.docker-base-image`, records the exact local
image ID, then initializes `/var/lib/hybrid-paper` once. Initialization writes a private 0600 dashboard
token in a 0700 state directory and the independent SQLite ledger. It never prints the token.

Initial deployment failure preserves state for investigation; it does not erase or silently
reinitialize a journal. An identical archive release is also deliberately refused on retry. Inspect
failed release/state privately before deciding recovery. The installer is a root-owned operational
procedure, not a general-purpose untrusted-archive execution service.

For subsequent releases the script retains the prior release and image, and restores that service
if startup, image identity or bounded probes fail. The successful pointer records the archive hash;
`previous` records its predecessor. This rolls back code only. Review migration compatibility before
an upgrade: database downgrades and journal rollback are never automatic. Back up first.

## Acceptance and access

The startup probe verifies `/healthz` returns 200 with `healthy=true` and `live_enabled=false`,
`/readyz` returns 503, and an unauthenticated `/api/hybrid/snapshot` returns 401. The running image ID
must equal the recorded candidate image ID. Docker health alone is insufficient.

Open the dashboard privately:

```shell
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8081:127.0.0.1:8081 codex-bold-peak-34f4
```

Visit `http://127.0.0.1:8081`. Obtain the dashboard token through a private operator-controlled
credential channel and enter it only in the dashboard authentication field. Never paste it into
chat, logs, shell arguments, source control, or deployment reports. The tunnel does not replace
application authentication. Verify an authenticated dashboard session privately, confirm initialized
paused status, refresh persistence, and confirm the original paused service is unchanged.

## Backup, restore testing and retention

Before upgrades or manual recovery, stop only the isolated service with its exact recorded image
and release Compose definition. Do not stop the original paused service. Use root or UID 10001 in a
private directory; never loosen the state directory permissions. Run:

```shell
python3 /opt/hybrid-paper/releases/<release>/infra/hybrid/backup.py \
  /var/lib/hybrid-paper/ledger.db /private/backups/hybrid-ledger-<timestamp>.db
```

The utility uses SQLite's backup API, exclusively creates a 0600 backup, makes a second temporary
restored copy and requires `PRAGMA integrity_check` to succeed. It does not copy or print dashboard
tokens. This is an offline structural restore test, not a complete application recovery rehearsal.
Perform an isolated restored-runtime rehearsal separately before relying on disaster recovery.
Never overwrite the running ledger with a backup, and never restore synthetic fixtures into this state.

Backups contain private simulation/account journal data: retain them in approved private storage.
No unattended backup timer, encryption key management, off-host backup, release pruning, or disk
retention policy is installed here. Establish those within existing spending authorization, and
monitor disk/RAM under representative paper workloads before leaving the process unattended.

## Remaining project steps

Integrate and review the exact runtime/image composition, run the runtime and dashboard test suites,
prepare the clean archive, deploy only the isolated paper service, verify the authenticated dashboard
and persistence, rehearse restore, then qualify representative source-backed paper behavior. Research,
out-of-sample validation and live authorization remain separate gates. These artifacts do not enable
live execution.
