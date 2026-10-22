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
metadata reads. START persists its original RUN origin/deadline before dispatch.
Normal STOP must be acknowledged within that RUN cap; output and entry into retirement
must occur before STOP+5seconds. No late response renews those windows. Retirement allows
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

## Store contract details frozen before implementation

The intent is the sole exception to the common `intent_sha256` field: its value is
required null because the canonical intent bytes define the digest. Later records
bind that digest. This avoids a circular self-hash. The namespace record has only
schema_version/kind/namespace_id/root_device/root_inode/lock_device/lock_inode;
active has schema_version/kind/namespace_id/probe_id/intent_sha256. Namespace kind is
stock_probe_namespace, active kind stock_probe_active. The permanent lock basename
is launcher.lock, matching the low-level convention without sharing its inode/path.

Fixed artifact basenames are engine.bin/image.bin/request.bin/create-response.bin/
prestart.bin/stopped.bin/framed-logs.bin/configuration.bin. Original finite framed
logs may be empty (then output is invalid); every other artifact is nonempty.
Artifact writes are exclusive and never overwrite even complete unacknowledged bytes.
The metadata names are intent/create/cid/created/start/stopped/output/removal-intent/
removed/closed with .json suffix. No caller-selected basename is admitted.

Filesystem primitives do not assert transport provenance or durability merely from
readable bytes. They sanitize all operational failures and never repair a partial
namespace. The namespace opener now validates complete bounded lineage and original artifacts;
setup/CREATE/CID/prestart/START and cleanup/STOP/output/retirement/closed writers
and fences are implemented locally. Fixed transport operations are implemented and
tested with socket pairs; actual native behavior remains unverified. No runnable
controller uses this store yet.

Receipt field spellings are frozen as follows (common fields above are implicit):

| .json basename | Exact additional fields |
| --- | --- |
| intent | profile_version, image_digest, engine_sha256, engine_size, image_sha256, image_size, request_sha256, request_size, setup_started_ns, setup_deadline_ns, predecessor_probe_id, predecessor_closed_sha256 |
| create | request_sha256, dispatch_deadline_ns |
| cid | create_sha256, container_id, evidence_kind, observation_sha256, observation_size |
| created | cid_sha256, prestart_sha256, prestart_size |
| start | created_sha256, container_id, run_deadline_ns |
| stopped | container_id, start_sha256, inspection_sha256, inspection_size, status, exit_code, oom_killed, error_present, container_started_at, container_finished_at |
| output | stopped_sha256, framed_sha256, framed_size, status, canonical_sha256, canonical_size |
| removal-intent | container_id, stopped_sha256, retirement_deadline_ns |
| removed | removal_intent_sha256, evidence_kind |
| closed | outcome, reason, output_sha256, removed_sha256 |

CID evidence is either create_response (original create-response.bin, at most4KiB)
or name_inspection (original discovery.bin, at most1MiB). The latter is recovery-only:
a lost CREATE response cannot be reconstructed from a name lookup, and name inspection
never permits START. Both retain the original observation and its hash/size. This
explicit variant reconciles the CID schema with the recovery row above.

Safe closed reasons are completed, abandoned_before_create, setup_failed,
prestart_failed, start_uncertain, process_failed, run_expired, shutdown,
invalid_output and recovery. Success requires reason completed and nonnull output/
removed hashes. Failed outcomes require a non-completed, non-abandonment reason and
removed hash. Abandonment has no output/removed references and its own reason only.
Individual record validity never establishes cross-record lineage, acknowledged
transport/durability, normal ownership or permission to publish success.

Historical node caches retain validated receipt/profile facts and exact named-file
fingerprints, not all original payload bytes. The temporary byte cache is cleared
after each newly validated node. Originals remain on disk and are reread when a
node fingerprint changes; this limits historical-payload memory on the small host.

## Writer and fence contract

These are internal root orchestration interfaces, not application/LLM tools. The
later fixed transport obtains and consumes its own actual issued token. Supplied
metadata and equal dataclass copies cannot reconstruct a token after reopening.

- begin_setup(image_digest) captures boot/UTC/monotonic origin before Engine/image
  reads, burns the invocation's one admission claim and returns ProbeSetup with
  generated probe ID, immutable image, original20-second setup cap and prior full
  CID or null. An unfinished entry never obtains this claim.
- check_setup(token) requires exact issued object identity, unchanged namespace and
  current original-domain time. BEGIN never restarts this cap.
- begin(token, engine_bytes, image_bytes) verifies actual supplied metadata with the
  existing pure verifiers, retains originals/request/intent and atomically advances
  the checked head. Owned admission is acknowledged only after complete durability,
  history/readback and post-operation original-cap checks. Prior closed-CID entries
  additionally require fresh scoped absence evidence; readable terminal bytes alone
  are insufficient. No controller invokes an incomplete writer surface.
- prepare_create() persists/acknowledges one original CREATE receipt and returns
  ProbeCreateFence. Its fixed deadline is the earlier of setup expiry and five
  seconds from preparation. claim_create(token) consumes the sole dispatch before
  fallible work; check_create_fence(token) rechecks actual identity, retained hash,
  request and original time before wire. create_request(token) returns only the
  retained fixed request after these checks.
- record_cid(token, original_response) separately retains the actual complete CREATE
  response/full CID. It never grants START. This one-use retention may complete after
  setup expires, but the original cap still blocks prestart/START. Boot discontinuity
  or an unacknowledged write leaves recovery-only ownership resolution.
- record_created(original_inspection) requires the normal owner and its acknowledged
  CID, then the existing full inert prestart verifier and complete original-byte/
  receipt acknowledgement. Copied CreatedProbe data does not meet this condition.
- prepare_start() requires those acknowledgements and persists the original30-second
  RUN origin/deadline before returning ProbeStartFence. Its dispatch window is also
  shortened by setup and five seconds. claim_start(token) consumes the sole dispatch;
  check_start_fence(token) checks the exact issued object and unchanged records/time.
  Lost acknowledgement retains this original RUN; no second START is issued.

Every issuance/retention flag and candidate acknowledgement is burned/cleared before
fallible validation or I/O. File/kernel delays never renew deadlines; any post-write
failure leaves readable bytes non-authoritative. Current sampled boot/monotonic and
UTC continuity is checked, including rollback relative to the last sampled clock.
A discontinuity burns admission/CREATE/START and leaves only later bounded cleanup.
Metadata receipts use the operation's pre-write timestamp, not its acknowledgement
clock. Fresh entry durability is reconfirmed explicitly; it is not inferred from a
validated content cache. The remaining writer contracts are detailed below; fixed
transports/controller must still compose them before this protocol is runnable.

## Cleanup and stopped-state writer contract

begin_cleanup() burns all admission/CREATE/START authority before inspecting state.
It returns one exact ProbeCleanup token for the known unfinished entry (or null for
an empty namespace). For an uninterrupted normal owner, cleanup starts at the earlier
of the current clock and its original RUN deadline. Reopened/changed-domain recovery
uses a fresh finite current-domain cleanup origin, preserving the original START.
TERM/KILL/final deadlines are origin+10/+15/+20 seconds. Repeated calls or later clock
changes cannot renew them. Only the initially observed entry, the acknowledged own
entry or the exact precomputed pending intent can become the cleanup target.

check_cleanup(token) and cleanup_target(token) check that exact issued object and
its original final cap; target snapshots remain copied data. record_discovered_cid
retains a fixed-name inspection only when CREATE exists and CID is absent. It binds
original discovery.bin, full CID and name_inspection receipt, rejects CID reuse and
never grants START. Name absence remains unresolved in the later actual transport.

prepare_signal(token, TERM/KILL) issues each fixed signal at most once, within its
original phase. KILL cannot issue before TERM grace ends. claim_signal(fence, raw)
consumes dispatch before fallible work and requires a fresh owned running observation,
matching retained START and full CID. check_signal_fence rechecks exact identity,
unchanged records and the fixed phase before wire. Neither ACK nor error is STOP.

record_stopped(raw, cleanup=None) writes original stopped.bin and its immutable
receipt, binding CID, START hash and exact native facts. Without cleanup, it requires
the actual normal owner's dispatched START and original RUN cap. With cleanup, it
uses the exact issued cleanup token and original final cap. A created observation
with any START fence is unresolved. Only a normal, timely, clean exited observation
can acknowledge natural completion; cleanup/recovery never can.

reconfirm_stopped(token, raw) requires an existing valid STOP chain plus fresh actual
nonrunning ownership and exactly the same StartedAt/FinishedAt strings. It freshly
flushes unchanged original STOP bytes/receipt and never rewrites them. Later native
error/OOM/exit facts or exited->dead state can be retained as current cleanup facts
without manufacturing a new lifetime; they cannot qualify normal success. This is a
cleanup-only reconfirmation, not a recovered successful run. Unknown/mismatched
identity, running/queued-created state or changed lifetime denies reconfirmation.

Every writer/reconfirmation/signal claim burns its one-use state before fallible
validation. Complete bytes after failed acknowledgement remain non-authoritative;
torn artifact/receipt inventory is an incident, never synthesized automatically.
Actual fixed transport provenance and output/removal/closed writers follow separately.

## Output, retirement and terminal writer contract

prepare_output(cleanup=None) issues one exact ProbeOutputFence only after this
session has acknowledged the retained STOP. Normal output ends at STOP+5seconds;
cleanup output has one fresh five-second window shortened by its original final cap.
claim_output consumes the one retrieval attempt before wire. record_output persists
the entire original finite framed body before decoding and before its valid/invalid
receipt. Valid canonical bytes are separately retained. A failed durability or late
acknowledgement cannot recreate output authority. The actual transport must establish
complete HTTP framing and EOF before calling this writer; transport failure is not
an invalid complete body. Recovery may retain output diagnostics but cannot succeed.

prepare_removal(cleanup=None) persists the immutable full-CID/STOP removal intent
before any retirement GET. Normal mode requires current STOP and output acknowledgements;
cleanup may use a valid retained STOP chain. ProbeRemovalFence has one nonrenewing
15second cap, shortened by cleanup's original final cap. Existing removal intents
remain unchanged: a later explicit recovery invocation receives one fresh bounded
cleanup cap, never a new START or successful RUN.

Normal retirement must enter before the original STOP+5second output deadline;
then its15second cap includes persistence. Thus timely output followed by an arbitrary
pause cannot create a new normal completion window. A retained recovery removal
intent is freshly fsynced/read back before a retirement fence can permit its GET.

claim_retirement consumes the one full-CID inspection attempt. A complete owned
nonrunning inspection with exactly the retained lifetime permits claim_removal once,
which freshly flushes STOP and intent before the non-force DELETE. Current diagnostic
changes disable natural success. Already-recorded removed plus a present resource is
contradictory and unresolved. There is no second GET/DELETE attempt in this invocation.

Only the fixed transport calls _retirement_evidence after complete scoped 404 or
closed empty204 EOF. This registers one exact private evidence object bound to the
issued fence and current clock. record_removed consumes that same registered object,
not an equal copy or supplied dataclass. New removed receipts are exclusive writes;
existing complete unacknowledged receipts require fresh exact404 plus fresh unchanged
fsync/readback. Generic/name/wrong-CID404 and incomplete HTTP cannot mint evidence.
These private interfaces define composition, not a sandbox against arbitrary root code.

close_success requires current normal ownership, actual START dispatch, a clean natural
STOP, timely complete valid output and this session's acknowledged resource removal.
It persists/revalidates closed success and checks the original retirement deadline
before returning canonical bytes. Any recovery/shutdown/signal/clock change blocks it.
close_failed requires current removal acknowledgement and a documented safe reason;
abandon requires cleanup ownership of a valid no-CREATE intent only. All terminal
writers consume their one attempt before fallible validation. Complete terminal bytes
after a failed acknowledgement remain data, never returned successful output.

For a closed predecessor CID, only the fixed transport calls _entry_absence_evidence
following its complete exact full-CID404. record_entry_absence consumes that exact
registered object, freshly flushes unchanged complete history and binds it to this
setup's original20second cap. begin requires that current acknowledgement for the same
closed entry. Copying tokens/evidence, reading old closed records or generic404 cannot
admit a successor; no setup deadline is renewed. A closed no-CID abandonment requires
fresh history durability but no daemon absence observation.

## Fixed transport composition contract

StockProbeEngine.begin_probe(store, image_digest, shutdown=None) owns one setup
claim before its bounded actual version/image reads and, when required, one exact
full-predecessor-CID404 observation. It persists original metadata through begin.
create_probe owns prepare/claim/recheck, derives exact name/body from that stored
intent, requires complete bounded201/EOF and retains actual original CREATE bytes.
verify_created owns the full-CID GET and strict prestart acknowledgement. start_probe
owns prepare/claim/recheck and sends one bodyless START, requiring closed empty204.
All methods use fixed root store/socket/API checks, current shutdown state and
original caps. Ambiguous transport never retries CREATE/START or manufactures ACK.
The transport instance burns its one metadata/prestart read before connection;
durable store flags separately prevent recreated instances from repeating writes.

The private HTTP parser admits only exact expected status, unique valid ASCII headers,
no transfer encoding, at most8KiB header, a route-specific body bound and final EOF.
CREATE bodies are at most4KiB; metadata/inspection at most1MiB. The later finite
logs path uses16KiB and requires multiplexed content type, including valid empty HTTP
bodies which are then invalid probe output. Shared production-worker defaults and
routes are unchanged; this dedicated parser composes only shared bounded socket/time
primitives, avoiding expanded authority on existing worker transports.
