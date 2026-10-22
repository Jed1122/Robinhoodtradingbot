# Repeatable bounded stock-research invocations

Root implementation plan, not implemented behavior or deployment authority.
Base711cfb5; protected operations source remains the previously checked0914482 tree.
This follows the independent read-only protocol audit and the corrected
[handoff design](../../stock-repeated-cycle-design.md). Root owns all protected
implementation, acceptance and integrated review. Live and broker writes stay absent.

## Decisions frozen for implementation

- Keep the existing fixed operations root, root UID checks, exclusive lock, closed
  filesystem/HTTP readers, append-only receipts and fresh-session capability model.
  Explicit new initialization writes protocol2. Existing protocol1 is recognized for
  bounded cleanup/incident inspection only; every admission/CREATE/START entry denies
  v1. No receipt/version rewrite, automatic migration or namespace reset.
- A typed full historical CID404 may complete retirement ONLY with the complete
  durable owned stopped/removal-intent chain. It is not stopped proof and cannot
  resolve an uncertain CREATE from generated-name absence. This is a root recovery
  decision; native same-daemon/full-ID behavior still requires separate verification.
- A closed non-force DELETE204 with validated empty body and final EOF completes
  acknowledged retirement; a second GET404 is not required by the local protocol.
  Lost acknowledgements may recover through scoped inspect404, or one new DELETE
  after a new owned stopped observation. No retry loop. A delayed DELETE(P) remains
  scoped to historical full CID P while successor Q must have a distinct full CID.
- Reject historical CID reuse before START (and when recording a new created CID).
  Same-daemon/nonreuse and absence of out-of-band hostile root writers are explicit
  operational assumptions, not facts established by fixtures.
- Unfinished-lifecycle recovery burns all admission/dispatch authority BEFORE fallible
  validation and ends the invocation even after successful resolution. Normal terminal
  handoff may admit once. No recovery branch loops into BEGIN or renews a RUN fence.
- Pre-head/torn admission artifacts remain incident-only. No automatic repair or
  receipt pruning. Preserve the existing bounded8192-attempt inventory; warn/stop
  before exhaustion in later host monitoring, rather than promise indefinite history.

## Closed record contract

Use existing exact key sets under `schema_version=2` for namespace.json and
active.json. Namespace keys remain schema_version/kind/namespace_id/root_device/
root_inode/lock_device/lock_inode. Head keys remain schema_version/kind/namespace_id/
attempt_id/intent_sha256. Unknown/partial/wrong-version records deny.

Intent retains its existing exact fields: schema_version/kind/namespace_id/attempt_id/
release_id/image_digest/config_hash/compose_sha256/max_run_seconds/boot_id/utc/
monotonic_ns, plus these six required nullable fields:

```
predecessor_attempt_id: ID | null
predecessor_terminal_kind: "stopped" | "abandoned_before_dispatch" | null
predecessor_terminal_sha256: SHA256 | null
retirement_attempt_id: ID | null
retirement_container_id: FULL_CID | null
retirement_stopped_sha256: SHA256 | null
```

Each triple is wholly null or wholly populated. Logical predecessor is null only
for the first attempt. A stopped predecessor supplies the physical triple; an
abandoned predecessor supplies none and must already have resolved inherited
retirement. Validate one complete lineage containing every inventory attempt and
ending at active head. Never skip an abandoned attempt or fabricate its CID.

New common receipt keys R are schema_version/kind/namespace_id/attempt_id/
intent_sha256/boot_id/utc/monotonic_ns. In removal receipts, R identifies successor;
target fields identify physical predecessor. Exact additions:

| File; kind suffix | Additional fields |
| --- | --- |
| create.json; create | request_sha256, dispatch_deadline_ns |
| removal-intent.json; removal_intent | target_attempt_id, target_container_id, target_stopped_sha256 |
| removed.json; removed | same target triple, removal_intent_sha256, evidence_kind: delete_204 or inspect_404 |
| abandoned.json; abandoned_before_dispatch | removed_sha256: SHA256 or null |

Kinds use `stock_attempt_` plus suffix. Existing created/start/stopped fields remain
exact under v2: R+container_id, start adds term_deadline_ns; stopped adds status/
exit_code/oom_killed/error_present/start_fence_present/container_started_at/
container_finished_at. Preserve exact scalar/hash/UTC/boot checks, start-presence
consistency, original RUN deadline, and denial of created state after START fence.
Every created/start/stopped chain in v2 requires its valid CREATE dispatch fence.

## Task 1: Versioned store, lineage and durable dispatch fences

Files: infra/hybrid/stock_attempts.py, tests/deployment/test_stock_attempts.py and
strictly necessary existing fixture consumers. Write failing contracts before code.
Reuse current helpers and one store; do not introduce a second configuration system.

- Attempt exposes protocol version and copied lineage fields. Snapshot adds copied
  create/removal-intent/removed/abandoned hashes; copied values grant no authority.
- `recovery_snapshot() -> AttemptSnapshot | None` revokes BEGIN/CREATE/CID-recording/
  START and terminal admission acknowledgements before any validation.
- `prepare_create(claim: Attempt, request_sha256: str,
  dispatch_deadline_ns: int) -> CreateFence` persists/fsyncs/readback-acknowledges the
  fence. `check_create_fence(fence: CreateFence) -> None` checks the exact issued object,
  retained bytes, boot and nonrenewed five-second deadline. Reopening grants no fence.
- `begin(release)` derives predecessor/physical target internally. Fresh stopped
  admission reuses actual raw stopped reconfirmation; new
  `acknowledge_abandoned_terminal() -> None` durably rechecks an already abandoned
  active terminal in a later fresh invocation. No admission follows recovery.
- `prepare_removal() -> RemovalFence` derives and durably acknowledges one target;
  `check_removal_fence(fence) -> None` checks its exact issued authority. Both support
  a fresh owner or a consumed recovery invocation, without allowing recovery CREATE.
- `record_removed(fence: RemovalFence, proof: RetirementProof) -> None` accepts only
  the scoped closed-transport result with target/fence identity and fresh timing.
- `record_abandoned_before_dispatch() -> None` itself burns recovery authority first,
  requires complete v2 history, no CREATE/created/start/stopped contradiction and
  resolved inherited retirement; no CID or stopped receipt is invented.

Expected: P(stopped)->S(admitted/no CREATE)->P(retired)->S(abandoned)->T preserves
logical S and admits no unresolved physical resource. Wrong/old/torn/forged chains,
CID reuse and readback/fsync/clock/lock failures deny. Existing v1 cleanup stays bounded.

## Task 2: Closed retirement and transport-owned CREATE fencing

Files: new infra/hybrid/stock_engine_retirement.py, existing stock_engine_mutation.py,
shared reader/framing helpers only where needed, and focused deployment tests.

The actual CREATE transport obtains/acknowledges prepare_create and rechecks its
exact fence immediately before sendall. Request hash binds actual canonical worker
body; route/name derive from the same stored attempt. No composer-only fence or
caller route/body/ID override. Every exchange retains its original absolute budget.

Retirement derives target only from store. Persist removal intent before inspection;
DELETE needs fresh full-CID owned stopped facts matching the retained stopped
lifetime. Only fixed Engine API paths and `force=false&v=false&link=false` are allowed.
Inspect and DELETE each have an absolute five-second budget. A typed404 requires
closed status/body/EOF validation for that exact historical CID. Opaque errors,
wrong identity/lifetime, running/conflicting state, timeout or malformed responses
remain unresolved; never infer absence from a generic exception.

Expected: bounded fictional socket tests for204/404/409, framing/delayed bytes,
wrong target, deadlines, lost acknowledgement, DELETE(P) versus Q, and no accidental
force/volume/name paths. No native Docker or broker operation in tests.

## Task 3: One repeated-cycle composition and fixed-root CLI

Files: stock_launcher.py, stock_supervisor.py only if required, focused deployment
fixtures and operational docs. Use the actual release manifest-file loader in the
new composition tests; resolve the deferred launcher fixture/input mismatch here.

`run_research_cycle(store: AttemptStore, release_path: Path) -> StockCycleResult`
installs shutdown handling before admission, checks protocol, and dispatches once:
normal fresh/terminal handoff -> BEGIN -> predecessor retirement -> fenced CREATE ->
existing prestart verification -> one START -> existing bounded supervision.
An unfinished recovery consumes authority, resolves only what is justified, then
returns `recovery_only`; ordinary completion returns `completed`. Neither status is
research success, strategy qualification or live authorization. Never create/start
again after an ambiguous response. No active/unknown container deletion.

The CLI constructs actual operations()/store, fixed transports and loader internally.
No dependency/socket/UID/CID/clock override. Timer/service installation stays disabled.
Expected: multi-invocation fictional end-to-end P->S->T, all crash windows, old and
new protocol, wrong release, shutdown, recovery and lock races with one unresolved
lifecycle at a time. Preserve collector budgets/sticky controls and all existing caps.

## Task 4: Independent integrated review and acceptance

Root reviews every protected diff, runs focused deployment+stock worker+architecture
checks and statics, and obtains one fresh whole-increment review. Fix Important/
Critical findings with RED/GREEN and integrated regression; disclose deferred minors.
Do not run another backend full suite while primary1537 full41316 remains active.
A later reviewed integrated candidate receives revision-specific required checks.

Native inert lifecycle tests, release production/attestation, credential ownership,
actual research execution, disabled-timer installation, monitoring/backups/restore,
capacity thresholds and verified repeated scheduling remain explicit later gates.
This implementation must not claim24/7 operation until actual external runs prove it.

## Review focus

- No version reinterpretation, skipped lineage, copied-capability adoption or unknown
  receipt absence creates dispatch authority.
- Every recovery path consumes invocation before fallible work; no new RUN budget.
- Old DELETE(P) cannot target Q, even on timeout, delayed responses or CID collision.
- An uncertain CREATE/name404 never becomes abandoned-before-dispatch.
- Shutdown, corrupt/torn records and changed clocks cannot fall through to launch.
