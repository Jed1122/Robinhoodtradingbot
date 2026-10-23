# Spent build reconciliation

Design for the existing Task 3 implementation. This document does not change
current admission, qualify an image, reconcile an incident or authorize a native
operation. Implementation and native acceptance require the checks below.

## Intent and evidence

Complete the already requested continuous stock-research deployment without
replaying a failed build or pretending it succeeded. Source `479fca6c`, archive
`a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674`,
has an actual original producer exit1 and exactly six retained build files. No
release was published. The current contract correctly blocks this partial history.

Investigation established a narrower fact that the present contract cannot
represent: the retained distinctive quiet image record is emitted after the
legacy build backend returns. Successful RUN commands have been waited for,
their builder goroutines joined, and their restart policy disabled. Private PID
namespaces contain detached descendants. This can establish backend termination
without reconstructing the client's missing transport/inspection acknowledgement.

The exact running daemon matches Ubuntu's published `docker.io` binary, SHA256
`237b0603cc24496c74433aeb32d70a16931ae7e015f183b8f3c7c7db83c72a5f`,
83879288 bytes. Its published control names source `docker.io-app`, version
`29.1.3-0ubuntu3~24.04.2`. The exact source and complete downstream patch series
were examined. Evidence is retained under
`.superpowers/sdd/2026-10-22-stock-continuous-operations/native-cpu-fix/`:

- `producer-running-daemon-package-binding.json`;
- `ubuntu-binary-research/running-binary-match.json` and
  `published-control-source-binding.json`;
- `ubuntu-source-research/source-flow-findings-v0.1-NOTADMISSION.md` and its JSON;
- `producer-causal-dispatch-audit.md` and the original producer receipts.

The original failure cause remains unconfirmed. This design does not fix an
unidentified transport error. It provides evidence-based incident classification
and bounded diagnostics for a future attempt.

## Chosen scope and alternatives

Retain the current producer namespace and every original byte. Add one explicit,
root-only, source-SHA reconciliation operation, limited to the qualified six-file
legacy-build case. It may record that this source is spent and failed and its
backend is terminal. A different source must perform a fresh full producer run.

Leaving every failed build permanently unrecoverable prevents Task 3 deployment.
Deleting/renaming the attempt, replacing the namespace, rerunning the source or
invoking private stages would discard its safety boundary and is rejected.

This is an implementation of the existing Task 3 authorization for autonomous
routine development and scoped stock operations. It grants no brokerage, live
trading, credential, paid-infrastructure or unrelated-service authority.

## Qualified profiles

The first profile is deliberately narrow:

- Linux/UID0, isolated loopback-only network namespace, fixed root Engine socket;
- Docker29.1.3/API1.52/Linuxamd64, distro GitCommit exactly
  `29.1.3-0ubuntu3~24.04.2`, and the exact published binary hash/size above;
- fresh GET peers are root on the fixed systemd-activated Docker socket. Native
  inspection observed peer PID1, not daemon PID950: the listener is inherited.
  Bind the peer/listener to the exact published service/socket units, kernel
  listener and shared PID1/daemon descriptors, and active service's actual daemon
  binary. Do not equate the listener SO_PEERCRED PID with the HTTP handler;
- original source/archive is exactly reviewed commit
  `479fca6ce789692d2a088b162fe6bcfeb2ad8336`, tree
  `98257c8083cc6395fde92c600b1683b783952955`, archive
  `a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674`.
  Checkout is clean and root-owned; seven module hashes must also match. Seven
  matching files cannot qualify another commit with changed imported helpers;
- original fixed version1/q=true request, with no remote context, tag, registry
  credentials or arbitrary arguments, and the existing strict response parser.

No upstream version string alone, arbitrary supplied observation, current image
GET or absence of a process authorizes reconciliation. Profiles are compiled,
reviewed code; there is no environment/config override or automatic profile update.

## Backend termination and cleanup

The qualified quiet record proves scoped backend return and no remaining runnable
Dockerfile RUN commands under the trusted runtime/kernel model. It does not prove
producer success, original socket EOF/close, image inspection, all cleanup success,
or daemon-wide idleness. Cleanup failures may retain stopped containers, layers,
mounts and temporary context. Do not remove them automatically or claim a bound
on the original incident's residual bytes.

Require fresh capacity headroom of at least 5GiB and4096 free inodes on the fixed
producer/release and verified Docker data filesystems at reconciliation and before
admitting a new source after failed history. Record observed capacity, not a
fictional residue inventory. Missing data-root identity or capacity fails closed.
The profile observer obtains DockerRootDir only through a fixed, bounded GET/info
from the same root peer; paths must be canonical root-owned directories. No path
or endpoint override is exposed. Actual supported data-root identity must be
verified before native reconciliation.

## Native reconciliation

`reconcile_failed_build(source_sha256: str) -> Path` accepts only a lowercase
archive SHA256. The CLI exposes only that argument. It has a120second monotonic
budget, nonblocking permanent producer lock, bounded reads/GETs and exclusive
publication. It never builds, probes, renders, starts/stops/removes a container,
initializes a store, changes permissions, touches OAuth or changes controls/units.

Under that actual lock:

1. Validate original namespace/root/lock identity and exact inventories. Validate
   every other admitted successful or spent-failed history using fresh readback
   and durability checks. Any other partial or unknown artifact blocks closure.
2. Require the target's exact six files: `source.tar`, `source-preparation.json`,
   `engine.bin`, `build-request.http`, `dispatch.json`, `build-response.http`.
   Require its input source and no target release. No terminal/probe/render/
   publication artifact may exist. Validate all original hashes, canonical clocks,
   namespace/source links, fixed request and complete distinctive quiet record.
3. Freshly verify the qualified original-source flow, current root peer/running
   binary and capacity. The producer's actual lease and causal stage ordering
   exclude later in-process dispatch. Original caller exit1 remains separately
   retained; no current receipt claims to reconstruct an old return.
4. Recheck originals, then exclusively publish `failed-build-terminal.json`,
   mode0600, at most16384bytes. Fsync file/directory, read back and recheck original
   namespace, inodes, files and budget. Close all owning handles before CLI success.

The schema1 record has kind `stock_failed_build_terminal_facts`. It binds source,
namespace, original input/six-file SHA256s and fingerprints, directory identities,
qualified source/daemon profile observations and reconciliation clock/deadline.
It records `backend_terminal=true`, `producer_success=false`,
`release_qualified=false`, `cleanup_qualified=false`, `source_replay_permitted=false`.
It must not synthesize `build-complete.json`, `terminal.json`, `native_complete`,
a manifest, image eligibility or a prior caller acknowledgement.

### Exact record and observation contract

Top-level keys are exactly `schema_version`, `kind`, `namespace_id`,
`source_sha256`, `source_commit`, `image_digest`, `backend_terminal`,
`producer_success`, `release_qualified`, `cleanup_qualified`,
`source_replay_permitted`, `original_origin`, `original_dispatch_clock`,
`reconciler_origin`, `reconciler_deadline_ns`, `reconciled_clock`,
`daemon_profile`, `capacity`, `directories`, `files`. The negative booleans and
kind/schema are the literals above. Original fields derive from actual inputs;
source commit comes from the existing strict archive parser.

The owner supplies the encoder an observation with exactly `reconciler_origin`,
`reconciler_deadline_ns`, `reconciled_clock`, `daemon_profile`, `capacity`.
The observer supplies only the last two. All clocks use the existing exact
`boot_id`/`monotonic_ns`/`utc` clock schema. Original, observer and reconciliation
clocks share a boot for this first qualified profile. Deadline is exactly origin
plus120000000000ns; current observations are ordered and before that deadline.
Reconciliation is later than the original dispatch and need not fall inside the
old producer's window. No original terminal timestamp is invented.

`daemon_profile` keys are exactly `profile_id`, `binary_sha256`, `binary_bytes`,
`peer_pid`, `daemon_pid`, `daemon_start_boottime_upper_ns`, `socket_activation`,
`boot_id`, `observed_clock`, `source_profile_id`, `source_tree`, `docker_root`.
Profile IDs are exactly
`ubuntu-docker-legacy-q-29.1.3-v1` and `stock-producer-causal-479-v1`.
The fixed binary digest/size and original commit/tree/archive are above. Peer PID
is exactly1 for this qualified socket-activation profile; daemon PID is a positive
integer distinct from1. Convert /proc stat starttime ticks to conservative upper
bound `ceil((ticks+1)*1000000000/HZ)`, never a floor. This is a BOOT-time bound,
not a claimed exact MONOTONIC timestamp. Require it strictly before the original
MONOTONIC origin. Linux BOOTTIME includes nonnegative suspend time, so this is
conservative with suspend; reject same-tick/clock-uncertain cases. Recheck process
lifetime, boot and inode bindings. Source tree is the actual original checkout's
exact qualified tree; commit is the exact qualified archive commit.
Docker root is the freshly verified canonical root-owned absolute path returned
by the same Engine peer. Strings/integers have exact types; booleans cannot replace
integers. No raw Engine response, command line or environment enters this record.

`socket_activation` has exactly `mode`, `service_unit_sha256`,
`socket_unit_sha256`, `listener_inode`, `socket_file_fingerprint`.
Mode is `systemd_socket_activation`. Unit hashes must match the exact published
Ubuntu package and actual root-owned unit bytes; no drop-ins/pending reload. The
active service has stable MainPID and requires docker.socket; active socket
triggers docker.service and listens only at /run/docker.sock. One corresponding
listening stream inode in the daemon's /proc/<pid>/net/unix must be held by PID1
and daemon. Both fixed GETs have peer PID1/UID0. Unit, listener/socket file,
process and binary observations stay stable across capture. No arbitrary
peer/mode fallback exists. The nine-field socket fingerprint uses the same order
as original files below, but requires a root-owned Unix socket with no public
permissions rather than a root/root regular0600 file. Its ctime must precede the
original UTC origin, using integer nanoseconds (never floating-point timestamps).
Published service hash is
`2e35580df3c26dc898440289f4abad013fbd62722f00c93f994dba002e468873`;
socket hash is
`96c04477e86bd6f724560f3a78b7c0b00b539d5254a251d247641029fc7ad92e`.
Native read-only observation `producer-inherited-socket-readonly-evidence.json`
verified these bytes, both shared descriptors and peer PID1 with actual exit0.
It did not alter admission or publish any incident facts.
The transport actually connects `/var/run/docker.sock`. Every fixed GET and
listener observation must resolve that alias to `/run/docker.sock`, require both
names' exact same fingerprint and verify that binding again after completion.
PID1 peer credentials alone cannot join two different systemd socket paths.

`capacity` has exactly `producer`, `release_root`, `docker`. Each has exactly
`path`, `device`, `inode`, `available_bytes`, `available_inodes`. Producer and
release paths are the fixed canonical roots; Docker path equals `docker_root`.
Device is a nonnegative integer, inode positive, and free-space/inode observations
meet the specified headroom. Native closure and later failed-history admission
freshly validate these paths/identities and capacity; an old observation is not
used as current free space.
`check_failed_capacity(capacity: dict[str, Any]) -> None` performs a fresh bounded
fixed GET/info through the current root Engine peer, then canonical path/identity/
headroom checks. Current DockerRootDir must equal the supported fixed
`/var/lib/docker` and recorded Docker path/identity. The old directory's existence
alone cannot prove that the current daemon uses it. This capacity check requires
neither original boot nor old processes. Historical admission uses it separately
from the same-boot first-closure observer.

`directories` has exactly `producer`, `inputs`, `attempts`, `attempt`,
`release_root`, each `[device, inode]`, matching fresh native bindings.
`files` has exactly `namespace.json`, `producer.lock`, `inputs/<source>.tar` and
`attempt/<name>` for each of the six original names. Each entry has exactly
`sha256` and `fingerprint`. Fingerprints use the existing nine-field order
device/inode/mode/uid/gid/nlink/size/mtime_ns/ctime_ns. Original files are regular,
root/root,0600, single-link; only producer.lock is empty. Namespace root/lock
identities and every original hash must agree with these bindings.

Partial publication stays blocked. An existing record denies repeating this
operation. Intact complete facts after a lost caller acknowledgement may be
recognized historically only through fresh full validation/durability checks,
matching the existing distinction between facts and caller success.

## Historical admission

Successful histories retain their existing exact chain. Spent-failed histories
have exactly the six originals and the one new facts file, no release/render
directory, and a complete validated negative chain. All other histories deny
admission. An attempt cannot contain both terminal families.

The release-parent inventory contains successful histories only; attempt history
contains both admitted families. Construction/classification is data only:
validation of every history still precedes any new mutable operation. Same-source
admission remains permanently denied. No old image/probe/result can satisfy the
different source's normal build, fresh probe, render, publication and cleanup.

## Future diagnostics

Record first failing build phase and allowlisted exception family/numeric errno in
memory before sanitization. Record secondary cleanup failures separately. On CLI
failure emit one bounded canonical stderr diagnostic (at most1024bytes); success
stderr remains empty and stdout unchanged. Never emit exception messages, args,
paths, responses, locals, environment or secrets. Sink/diagnostic failure cannot
advance the producer, mask its denial, trigger a retry or alter old evidence.

## Validation and acceptance

RED/GREEN tests must cover complete quiet witness versus prefixes/errors/extra
frames; original hash/clock/source mismatches; daemon/source/peer/binary mismatch;
capacity uncertainty; both terminal families; unknown/partial history; no original
file overwrite; lock contention, shutdown, timeout and durability failures;
same-source denial; and different-source full fresh pipeline after failed facts.
Same-boot/old-process qualification applies only to first native closure and the
stored observation's internal proof. Later historical admission validates stored
facts and fresh capacity after reboot without old processes. Include a later-boot
mixed-history/new-source regression so reboot cannot strand builds, and reject a
changed current DockerRootDir even when the old path still has free space.
Fault fixtures must demonstrate first errno survival through close/retention
failures, bounded redaction, no downstream dispatch and no retry.

Require independent whole-change review, exact frozen current-stock regression,
Ruff/mypy/Bandit/lock and unchanged coverage gates. Native qualification first
uses the read-only observer against preserved originals. Only an actually
qualified profile may publish one failure record. Retain its original handle,
actual exit and complete receipts. Then stage a different clean source and invoke
the public producer once; current success still requires its actual exit0 and all
native stages. No current unit/control/runtime upgrade precedes that qualification.

Task 3 still requires actual scheduled stock jobs, monitoring, encrypted backup,
off-host verification/application restore, restart/reboot, natural-expiry renewal
and separate official revoked-test-grant denial. This incident work does not
complete those gates or enable live trading.

### Original causal source profile

These are SHA256s of full files under `infra/hybrid/` at source479; future source
flows are unsupported until independently reviewed and versioned.

| File | SHA256 |
| --- | --- |
| stock_build_engine.py | 9ad12baf09172fbd485b08b2ec1df3ca76119ecf34ec452759f3ba5782e12064 |
| stock_compose_render.py | fbaba8973249e0b9afecab75c6c5a02868a68821e41639e1a51d11af00cc6d13 |
| stock_probe_controller.py | 40929e4f45c695b0429373fea2e77e32ba1d4ec15c9e2b0fefed3db144b5a3f8 |
| stock_producer.py | 8729100585927dd9588bd02fa6ef488e08202e8c5f4089987a7f16c7e85576dc |
| stock_release_producer.py | 2ff1bee7bc22173a61f27c8f4ae14254bd9723bed417a14e7efaf9e53746d6fa |
| stock_release_publication.py | 5a1dd309a61226df3dfae6403b19653a96147bf2496076b527e99144f409d1e7 |
| stock_source_prepare.py | 10d3fba54190e9861eac997bf7990a17f78194dc627482254a1379a7b5f8803c |
