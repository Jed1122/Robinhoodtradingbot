# Native release and paused stock installation

This procedure completes project task 2 only. It does not authorize collection,
copy credentials, enable the timer, call Robinhood, or activate live trading.
The individual-stock worker remains paused. Actual 24/7 research/authentication,
restart/reboot recovery, monitoring and backup restoration are task 3.

## Source and prerequisites

Use a new root-owned clean full Git checkout at
`/opt/hybrid-stock-research/source/<exact-40-character-commit>` with no writable
ancestors, Git alternates or external worktree references. Transfer a Git bundle
containing the reviewed commit, never the developer's untracked files or OAuth
store. Use `/usr/bin/python3` for the standard-library host operations modules.
Application dependencies and Alembic run inside the produced locked image.

Check the existing fixed Engine socket and root peer, Docker 29.1.3/API1.52,
Linux amd64, cgroup v2 resource enforcement, available disk/RAM and Compose before
consuming a producer attempt. The renderer accepts only upstream `2.40.3` or the
exact observed Ubuntu rebuild `2.40.3+ds1-0ubuntu1~24.04.1`; it still compares every
resolved policy field. No global Compose replacement or arbitrary suffix fallback
is necessary. The producer build downloads public pinned dependencies/base layers;
the inert image probe has no network or application mounts.

Follow [producer operations](stock-release-producer-operations.md) to initialize
absent namespaces explicitly, capture the exact clean HEAD twice and run the
public source-SHA-only producer once. Preserve the original process result, all
bounded streams and native records. Actual exit0, complete success JSON, exact
image/config observations, finite natural exit and acknowledged non-force probe
removal are mandatory. Existing partial producer namespaces are incidents; do not
erase, reconstruct or replay them. A release loader checks consistency, not native
execution or caller success.

## Explicit private state and paused proof

Only when the dedicated stock namespaces are absent, explicitly create
`/var/lib/hybrid-stock-research/{state,archive,controls,exports,oauth}` as UID/GID
10001, mode0700. The OAuth directory remains empty. The runtime root and each
namespace must be canonical, with no symlinks. Initialize the operations store
separately with `initialize_operations()`; it is root0700 and retains its lock and
history permanently. Do not adopt or repair an existing unrelated ledger.

In a credential-free, network-disabled initialization container from the verified
image, bind only state and controls; explicitly call `migrate_sqlite_ledger` with
`/app/alembic.ini` and `/app/migrations`, and `StockResearchControls.initialize()`.
Require its actual natural exit0 and preserve its exact CID/metadata before
non-force removal. This is an operator initialization step, never worker startup.
Record SQLite integrity, migration head, all stock claim counts and the paused
control file hash/owner/mode. Files must be single-link, UID10001/mode0600.

The separate `stock_paused_profile` derives the actual worker command/resources
from the verified release, removes the OAuth bind, sets NetworkDisabled=true and
NetworkMode=none, and uses a distinct acceptance name/labels. It cannot be used to
relax the normal production verifier. An operator acceptance harness must:

1. Obtain current Engine/image observations and call `paused_request` itself.
2. Create once, retain the returned full CID, inspect it and pass the original
   bytes to `verify_paused_created` before any START.
3. Start only that verified full CID once; bound the actual process to60seconds.
   On uncertainty inspect that original CID; never retry CREATE/START blindly.
4. Require natural stopped state, PID0, no OOM/error/restart and actual exit2;
   collect bounded output showing `status=blocked`, `reason=control_denied` and
   `live_enabled=false`. Exit2 is the intended negative proof, not research success.
5. Recheck the same container lifetime, SQLite integrity/zero new claims and
   unchanged paused authority. Preserve metadata/output before acknowledged
   non-force removal. A helper timeout is not stopped-container evidence.

No provider SDK/credential or research claim may be created during this check.
Any discrepancy blocks installation; retain the incident and do not initialize
replacement controls or a replacement ledger to hide it.

## Disabled service and timer

After that proof, load the actual manifest with `load_release` and render
`stock_units.unit_files(release, exact_checkout)`. This is a pure generator, not
an automatic installer. Verify source HEAD/cleanliness, ancestor ownership and
unit destination absence independently. Exclusively create root-owned mode0644
files under `/etc/systemd/system`, flush/read back their bytes and preserve their
hashes. Run `systemd-analyze verify` before `systemctl daemon-reload`.

Never use `enable`, `start`, `restart` or `--now` during installation. Confirm the
timer is disabled/inactive and service is static/inactive. Inspect the effective
units, including absence of unexpected drop-ins. Preserve the existing legacy
containers, state, services and credentials unchanged.

The oneshot service has Restart=no, finite startup and45second shutdown budgets,
control-group helper cleanup and host resource caps. It launches the release-bound
regular coordinator. ExecStopPost invokes only the zero-argument
`infra.hybrid.stock_recover` entrypoint under the same permanent operations lock.
That path cannot load a new release, CREATE or START, including after a terminal
attempt; it reconfirms terminal state or performs bounded owned-container cleanup.
Failure remains visible and retains uncertainty. The timer is completion-relative
with the image-observed cadence, Persistent=false and no boot/calendar catch-up.
Enabling it and explicitly initiating the first cycle are separate task3 steps.

## Evidence and limits

Retain source/HEAD/tree, producer/probe terminal records, original CLI exit and
output, four release files/hashes/owners, native image IDs, paused-check lifecycle,
ledger/control before/after facts and effective systemd properties. Store only
sanitized public operational metadata; never credentials or account contents.
A disabled installation does not prove scheduled acquisition, broker permissions,
OAuth renewal, host-reboot recovery, backup restoration, market-data quality,
profitable strategies or live readiness.
