# Fresh stock research attempt composition

> Use superpowers:executing-plans and test-driven development. Root owns all code.

**Goal:** connect already reviewed launch components into one first-attempt lifecycle,
without silently introducing repeated-cycle handoff or uncertain-creation recovery.

**Architecture:** a root-only library entry point holds the caller's existing actual
operations lock, loads a trusted retained release, observes Engine/image, durably
admits one attempt, creates once, verifies the actual CID, records it, starts once,
and delegates to the existing fixed-phase supervisor. It returns stopped lifecycle
evidence only. The broader approved operations specification remains
`docs/superpowers/plans/2026-10-21-stock-research-operations.md`.

Base: 2e5c52849718052e2b10dd46be3fc19f2c807d51. Primary is frozen at1537d7e
for actual full session41316; no primary mutation or duplicate full suite.

## Scope and explicit exclusions

Create `infra/hybrid/stock_launcher.py`, its deployment test and operational doc.
Do not change existing store, transport, supervisor, safety config or credentials.
Public function:

```python
launch_fresh_attempt(store: AttemptStore, release_path: Path) -> StockSupervisionResult
```

Require the existing production root/store guard and `store.snapshot() is None`
before any daemon or release work. This function is deliberately first-attempt-only:
all existing terminal, unstarted, pending or fenced attempts fail closed. It never
initializes a namespace, resolves an incident, deletes a container or admits a
successor. Repeated cycles require a separate durable predecessor-cleanup protocol;
no in-memory predecessor reference or 404 inference is substituted for that work.
Keep this uncomposed: no CLI, service, timer, automatic control resume or deployment.

## Task 1: TDD one-attempt lifecycle

1. Add missing-module RED cases using fictional root-boundary substitutes, actual
   temporary receipt stores and deterministic clocks. No daemon/provider operation.
2. Implement the closed sequence: production guard -> empty snapshot -> load_release
   -> reader.version/verify_engine_version -> reader.image/verify_image -> begin ->
   mutator.create_worker -> full-CID reader.inspect -> verify_created using original
   bytes and all loaded release/image/attempt/CID identities -> record_created ->
   mutator.start_worker exactly once -> supervise_active in the same open store.
3. Internally construct reader/mutator and use the real supervisor entry point;
   no injectable callbacks, raw metadata, caller image/release objects, CID, fence,
   time budget or authentication input. Preserve the existing single-use guards.
4. On a start exception, read a validated snapshot. Only the same just-admitted
   attempt with created+start receipts and a persisted start fence may proceed to
   supervision. Never retry START or prepare a new fence. If no valid fence exists,
   fail closed. An already-started first attempt that encounters an ACK exception
   retains its original owning-session RUN boundary; reopened recovery is elsewhere.
5. Any other error denies with fixed `stock_launcher_unavailable`, without private
   provider, path, socket or receipt details. Never catch a failed supervise operation
   as a reason to start/create again. Leave uncertain receipts intact for recovery.
6. Test successful order, returned actual lifecycle result, unknown/foreign CID and
   image/version/config/mount rejection before START, release/guard/state failure
   before daemon work, begin/create/inspect/created-persistence/start errors, durable
   uncertain START, malformed/fake fence, supervision failure, no retries and no
   implicit source/research-success/qualification/live authority. Ensure existing
   nonempty states are rejected, including stopped and created without a start.

Expected: RED observed before new source; all narrow cases pass afterward. Do not
relax prestart checks or fabricate raw production payloads to make tests pass.

## Task 2: Integration, review and documentation

Run launcher plus actual attempt/transport/prestart/container/supervisor tests;
deployment+architecture regression; Ruff; strict mypy including all host modules;
expanded Bandit; lock and diff checks. Expected: pass, four optional age skips
disclosed. Fresh independent review of this bounded increment is required; root
fixes substantive findings with RED/GREEN, preserving prior full run ownership.

Document that this is a locally tested first-attempt composition. Native image and
CID compatibility, mutation/physical deadlines, recovery hooks, repeated cycles,
trusted release producer, paused deployment, exclusive credential lifecycle,
backups/restore and actual scheduled research remain unverified. No full repository
readiness from focused tests; run the eventual integrated candidate separately.

## Review focus

- Caller-created/modified release or image objects must not bypass source verification.
- A lost START acknowledgement must never cause a second START or a renewed fence.
- Receipt persistence failure must not become execution or cleanup success.
- Existing attempts must never be accidentally adopted or skipped for new admission.
- Supervisor failure and shutdown before supervision must retain uncertainty, with
  no claim of installed host-death recovery or physical termination proof.
