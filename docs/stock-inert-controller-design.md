# Bounded inert configuration controller

Planned root-owned continuation from `0af76874d8b57356b840ce96c29e52d5c2883c2f`.
The [pure probe profile/output checks](stock-inert-probe-verification.md) exist;
this controller, persistence and native transport are not yet implemented here.
The product goal remains continuous stock research and qualified, risk-controlled
automatic investing after separate live authorization. This path carries no OAuth,
provider, account, order, control-resume or live capability.

## Authority and scope

Use a separate `/var/lib/hybrid-stock-probes` root, explicit initialization, root UID,
checked ancestors, mode-0700 directories, mode-0600 single-link files and a permanent
nonblocking exclusive lock. Keep the production worker AttemptStore, fences, names,
release identity and paths unchanged. Reuse low-level strict JSON/filesystem/clock
and socket/framing primitives, not worker execution authority or fabricated releases.

One invocation may own one fresh probe. The opener classifies checked entry state
once under lock. An unfinished entry burns all admission/CREATE/START authority
before recovery and always ends that invocation. No recovery adopts RUN or publishes
a successful configuration observation. Valid terminal history permits a later
explicit invocation after fresh durability/resource reconfirmation. No automatic
retry, namespace repair, receipt rewrite or pruning occurs.

Retain at most 128 probes. Namespace pins root/lock device/inode and a random namespace
ID. Active head binds probe ID and intent hash. Intent links its predecessor ID and
closed-record hash (both null only for the first probe); validate one complete chain
containing every retained probe and ending at active head. Reject historical full-CID
reuse before START and when acknowledging a new CID. Unknown/torn/pre-head artifacts
are incidents. Closed history is retained; capacity maintenance is a later explicit
operator procedure. This finite inventory is appropriate for release probes, not a
research-cycle scheduler.

Supplied ImageProfile, CreatedProbe and lifecycle observations remain data. Actual
fixed transports obtain the one-use fences themselves and recheck the exact issued
object and acknowledged unchanged records immediately before sending. Reopening,
copying a fence, reading complete bytes after failed fsync, or changing clocks never
grants dispatch authority. The fixed root entry constructs its own store and transports.

## Pure lifecycle observation

Add a probe-specific supplied-observation reader, separate from strict prestart
hardening comparison. Bind full CID, immutable image ID, generated probe name, exact
probe labels, Linux platform, restart count zero, no auto-remove and restart policy no/0.
Accept only a closed exact State schema with correct scalar types and consistent
created/running/exited/dead facts, PID and lifetime timestamps. Unknown, paused,
restarting or removing states deny. Do not expose raw error text; retain error presence.
Native created status follows zero StartedAt, including a failed start with a nonzero
FinishedAt/exit/error. Running may retain an older FinishedAt. Preserve exact native
wall-clock timestamps for cleanup even if clocks step; chronological ordering belongs
to success qualification, not to minimal scoped cleanup ownership.

This minimal ownership observation supports cleanup of an owned never-started probe
even when the full prestart policy comparison failed. It never substitutes for that
strict comparison before START or for actual transport provenance. Store policy must
reject a created-state stopped acknowledgement whenever a START fence exists, since
a queued START may still execute. Only an owned running observation with a valid
matching START chain permits TERM/KILL. A signal acknowledgement is not stopped proof.

## Immutable records and artifacts

All receipts use schema 1 and unique `stock_probe_*` kinds. Common receipt fields are
schema_version/kind/namespace_id/probe_id/intent_sha256 plus boot_id/utc/monotonic_ns.
Clock integers reject booleans; timestamps retain UTC and native lifetimes. Exact
key sets and required nullable fields are validated centrally.

| Record | Additional bound fields |
| --- | --- |
| intent | profile version, image ID, Engine/image observation hashes and sizes, canonical request hash/size, fixed setup deadline, predecessor ID/closed hash |
| create | actual request hash, original dispatch deadline |
| cid | CREATE-receipt hash, full CID, original CREATE-response hash/size |
| created | CID-receipt hash, original strict prestart-inspection hash/size |
| start | created-receipt hash, full CID, original RUN deadline |
| stopped | full CID, start-receipt hash or null, original inspection hash/size, status/exit/OOM/error-presence, native StartedAt/FinishedAt |
| output | stopped hash, complete framed-log hash/size, status valid/invalid, canonical configuration hash/size or required nulls |
| removal-intent | full CID, stopped hash, fixed retirement deadline |
| removed | removal-intent hash, evidence kind delete_204/inspect_404 |
| closed | outcome succeeded/failed/abandoned_before_create, safe reason enum, output hash or null, removed hash or null |

Artifacts use fixed local slots only: Engine/image observations, actual canonical
request, CREATE response, prestart inspection, stopped inspection, original framed
logs and normalized configuration. No caller path is accepted. Metadata is bounded
to 4 KiB, JSON observations to 1 MiB, CREATE response to 4 KiB, framed logs to 16 KiB
and configuration to 4 KiB. Use exclusive writes, file/directory fsync, unchanged-file
checks and readback acknowledgement. Artifact hashes and sizes bind original bytes;
normalization never replaces them. Invalid complete logs may retain diagnostic output
evidence, but cannot provide normalized configuration or a successful closed result.

Validate complete lineage and artifact integrity at entry. Within the same lock,
already-validated content may be reused only while exact named-file metadata remains
unchanged; no cache crosses invocations or grants acknowledgement. Avoid repeated
large historical payload reads inside fixed dispatch/cleanup budgets.

## Fixed phases

Root freezes setup to 20 seconds, RUN to 30, TERM grace to 10, KILL to 5, final stopped
observation to 5, output retrieval to 5 and retirement to 15. Every Engine exchange
has at most five seconds, shortened by its enclosing absolute cap. Setup starts before
metadata reads. START persists its original RUN origin/deadline before dispatch;
all normal phases derive from that origin, never response times. Retirement allows
one inspect and one DELETE within one 15-second cap, including local validation.

These caps bound checks and exchanges, not uninterruptible filesystem/kernel work or
physical daemon enforcement. Late I/O must deny dispatch/publication and preserve an
unresolved incident. Intended-host termination/performance remains a separate gate.

Install shutdown handlers before admission and pass one shared requested state through
setup, CREATE, START and supervision. First shutdown initiates earlier bounded cleanup;
later signals never renew grace. Old boot, rollback or reopening enters cleanup-only
with finite current-domain caps while retaining the original START record. Check clocks
before/after fallible operations and before wire dispatch. Restore handlers on exit.

## Native operations and publication

Read actual Engine and exact local immutable image through fixed API 1.52/root-owned
socket checks, then apply existing verifiers. No image pull/build/tag fallback or daemon
upgrade. CREATE body/name derive only from the stored fixed probe profile. Persist and
acknowledge its transport fence before connecting; keep the actual response/CID before
prestart inspection. A retained CID alone grants no START. Inspect that CID and require
the full inert profile, then persist/acknowledge one START fence before sending once.

Poll actual owned state at most once per second without catch-up. Preserve the same
RUN fence after a lost START acknowledgement. On expiry/shutdown, use fresh owned
running observations before TERM/KILL; never infer termination from their responses.
Persist an actual stopped observation before output or removal. Only fresh normal
ownership, a strict prestart chain, natural clean exit within RUN, no shutdown/OOM/error,
complete valid logs and acknowledged cleanup can produce a successful closed result.

Retrieve only the exact finite full-CID logs route and framing/limits frozen in the
[probe boundary](stock-inert-probe-design.md). Status 200 does not override daemon error
frames, stderr, malformed/truncated bytes or missing final EOF. Retain original bytes
before normalized output. A copied canonical result cannot authorize publication.

Persist removal intent before fresh full-CID inspection. DELETE requires the same owned
stopped lifetime, uses force=false/v=false/link=false, and never retries within an
invocation. Closed empty 204 plus EOF acknowledges removal. A later exact singleton
`No such container: <owned-full-CID>` 404 may complete only an already stopped/removal
chain. Generic/name 404 never establishes stopped state or resolves uncertain CREATE.

## Restart outcomes

- A valid intent with no CREATE fence and no contradictory records may be abandoned
  before dispatch. Torn/malformed/contradictory state is unresolved, not abandonment.
- CREATE fenced without CID: inspect only its generated probe name to discover an
  owned resource for cleanup. Never START from that lookup. Name 404 stays unresolved.
- CID/prestart without START: freshly verify actual owned never-started state, record
  stopped evidence and clean up; never resume START after reopening.
- START exists: bounded cleanup only, original timing retained; created state cannot
  be acknowledged stopped or removed.
- Stopped exists: freshly verify the same lifetime before retirement. Lost removal
  acknowledgement follows the scoped 404/one fresh stopped-DELETE procedure above.
- Recovery closes failed/abandoned incidents only and ends the invocation. A later
  explicit fresh probe is needed for success. Complete terminal bytes left after a
  failed acknowledgement still need fresh durability/resource reconfirmation.

Successful output is a configuration observation bound to one actual inert probe.
It does not establish build/source provenance, a research worker, OAuth lifecycle,
scheduled operation, qualified market data/strategy, broker reconciliation or live
authorization. Root producer, paused installation and intended-host proof follow.

Pinned native state reference: [Moby 29 state implementation](https://github.com/moby/moby/blob/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/container/state.go).
This is source evidence, not intended-host lifecycle verification.
