# Trusted stock release production

This implements the already authorized stock deployment architecture, without starting
research, installing a service, changing controls, moving credentials or activating
investing. The current controller checkout remains frozen for its actual full suite.

## Owned operations

The producer owns source preparation, one causal image build, one fresh fixed probe,
one reviewed Compose render and exclusive durable publication. A caller supplies only
the source archive's SHA-256. Independent supplied image IDs, observations, receipts,
renderer output and successful old releases cannot replace those owned operations.
Use the existing `Dockerfile`, `.docker-base-image`, canonical configuration, stock
Compose policy, probe controller and release loader. No worker or broker API changes.

The fixed raw Engine path is selected over Docker CLI builds, avoiding client config,
proxy and credential-helper collection. This version pins Docker29.1.3/API1.52/Linux
amd64 and legacy builder version1, with no fallback. Public registry/base and frozen
dependency downloads are explicitly part of building the existing recipe; `pull=false`
is prefer-local, not a network prohibition. The inert probe remains network-disabled.
No registry publication, remote build context, extra build argument or registry-auth
header is allowed. Native support and capacity still require actual verification.

## Bounded source

Prepare committed clean `HEAD` using Git's tar format and `tar.umask=0022`, selecting
only `Dockerfile`, `.docker-base-image`, `pyproject.toml`, `uv.lock`, `alembic.ini`,
`compose.stock-research.yml`, `src`, `configs` and `migrations`. No npm/dashboard build,
untracked files, environment file, key, account state or provider capture is included.
The original archive bytes, including Git's commit comment, define the release hash.

The pure parser admits only uncompressed tar, at most16MiB, at most2,048 entries,
each regular file at most1MiB, UID/GID0, modes0644/0755, regular files/directories,
unique safe ASCII paths in that allowlist, and a consistent40-or64-hex Git comment.
Reject links/devices/sparse records, traversal, dot components, hidden descendants,
PAX fields other than `comment`, missing mandatory files/trees, truncation and nonzero
trailing bytes. Require two zero end blocks and512-byte alignment. Never extract to
the host. The observed4,864,000-byte/527-entry archive fits these bounds.

The base file contains exactly one newline-terminated
`python:3.12-slim-bookworm@sha256:<64 lowercase hex>` reference. Before native build,
Dockerfile/base/Compose bytes must match the reviewed producer checkout assets,
read through bounded nonsymlink trusted paths. Archive parsing establishes supplied
data consistency only; it creates no native-build authority.

## Producer lease and incidents

Use fixed `/var/lib/hybrid-stock-producer`, explicit initialization,0700 root-owned
directories,0600 single-link private files and a permanent nonblocking exclusive lock.
Inputs are `inputs/<source-sha256>.tar`; attempt directories are `attempts/<source-sha256>`.
The normal public entry never initializes, repairs, replaces or resumes a partial
namespace. Before a new attempt, reject an existing target or any unfinished producer
attempt. Bound retained attempts to128; pruning is a later explicit operator procedure.

Persist original source/intent/request identity before build dispatch. One attempt owns
one build dispatch. Complete durable old bytes never reconstruct acknowledgement or
permit replay. Any uncertain build, missed cap, shutdown, failed probe/render/write/
fsync/close or namespace substitution suppresses publication and leaves an incident.
An incident blocks subsequent production until a separately verified operator action;
do not infer daemon termination from timeout/disconnection. Successful histories permit
a different source only after their complete closure/namespace checks. No auto cleanup,
force removal, image deletion or build cancellation success claim is introduced.

Keep raw source, version/image metadata, bounded request/build response, actual probe
result, Compose version/template/raw render and terminal producer provenance outside
the four closed release schemas. Pinned file/directory identities and exact inventories
must survive readback and final context cleanup. No secrets enter these records/logs.

## Build, probe and rendering

Install shared shutdown handlers before admission. One original producer window is
1,200seconds; one build window is900seconds within it. Check boot, monotonic and UTC
continuity throughout. Build upload has at most30seconds; reads wake at most once per
second to recheck the same original window/shutdown. Read retries on the same socket
do not replay a request. Metadata/rendering each have a separate at-most5second cap
shortened by the original producer deadline. Native blocking work is not forcibly
bounded by these checks; late work denies a result.

Build only via `POST /v1.52/build`: `version=1`, `q=true`, fixed `Dockerfile`, no tags,
`pull=false`, `rm=true`, `forcerm=false`, `networkmode=bridge`, `platform=linux/amd64`,
512MiB memory and equal swap, CPU period100000/quota50000, and the sole explicit
`PYTHON_BASE_IMAGE` argument from the verified archive. Send that exact tar body with
HTTP1.0/Connection-close and no credentials. Require bounded200/application-json,
unambiguous headers, no transfer encoding, complete body/final EOF and original caps.

Quiet mode emits its full image-ID stdout record only after backend build success.
Require exactly one JSON object with the sole `stream` key and exact value
`sha256:<64 lowercase hex>\n`. Intermediate aux IDs, ordinary progress, multiple JSON
objects, streamed errors and partial output never yield an image ID. Then inspect
that exact ID and apply the existing immutable-image profile. This is not a claim
that the build is bit-for-bit reproducible.

Invoke fixed `run_probe(image_id)` once; only current `succeeded/completed`, matching
image and canonical nonnull configuration may proceed. Retain the actual call's
owned probe/CID/configuration binding. Do not reopen or accept a supplied probe result.
The controller keeps its original independent caps; producer publication has its own.

Use `/usr/bin/docker`, fixed local socket and reviewed Compose2.40.3 to render the
verified template. Use an empty private Docker config/env file and scrubbed environment
with only explicit image/attestation substitutions and a private empty executable PATH.
No interpolation input from the user's environment or default dotenv file is admitted.
Render without image resolution, canonicalize the complete model and check the existing
policy. Actual plugin availability/normalization remains a native gate, never a fallback.

## Publication

Keep the existing four exact schemas, bounds, derived paths,0444 modes and canonical
compact JSON-plus-newline identity. Create the final release directory exclusively;
never overwrite an old/partial release. Derive observation/hash/cadence/run values
from the actual probe and full resolved Compose model. Fsync each original file and
directory, read back/revalidate identities, and pass the exact manifest through the
existing production loader before a terminal producer receipt. Final success follows
terminal durability, lock/handler cleanup and original-cap/clock/shutdown checks.
The public result is the fixed manifest path; CLI formatting shares that final gate.

File verification, local fixtures and public documentation do not prove a native build,
isolation or deployment. Native producer/probe proof precedes paused installation,
OAuth ownership/lifecycle, backup restoration and actual scheduled research with the
development client closed. Market-data/strategy qualification and nonempty Robinhood
reconciliation remain independent. Live activation stays separately user-controlled.
