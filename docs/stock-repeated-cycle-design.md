# Repeated stock research cycles: recovery design checkpoint

This records the next root-owned protocol design. It is not implemented, approved
native behavior, a migration instruction or authority to run a timer. The current
first-attempt entry point correctly rejects every nonempty namespace. The live
trading boundary and all existing collector controls remain unchanged.

## Why a durable handoff is required

Retain the active stopped container until a later session freshly reconfirms its
owned stopped state and durably admits the successor. Remove only the predecessor,
without force or volume deletion, before the successor's CREATE. A process can die
after admission but before cleanup; the successor then has an intent without a CID.
Its intent alone cannot distinguish that case from an uncertain CREATE request.
The existing in-memory claim is intentionally insufficient after restart.

The next implementation therefore needs an explicit versioned operational protocol,
not a loop around `launch_fresh_attempt` and not a blanket retry on an exception.
Production operations have not been initialized; do not silently reinterpret any
existing version-1 receipts as containing new dispatch evidence.

## Candidate dependency chain for the next implementation plan

1. Define the versioned namespace/receipt contract and compatibility policy. Preserve
   the current store's historical integrity checks. Old nonterminal protocols remain
   cleanup/incident-only; no automatic migration grants execution authority.
2. Add a durable CREATE dispatch fence before the first byte of CREATE can be sent.
   The absence of that fence is meaningful only in the new explicitly bound protocol.
   Persistence or readback uncertainty burns dispatch; reopening never adopts START
   or CREATE authority. Preserve all existing one-use and code/release bindings.
3. Bind a successor intent to its exact predecessor attempt, full CID and immutable
   stopped-receipt hash. Retain historical identities and terminal evidence. The
   predecessor must stay active through fresh reconfirmation and durable new admission.
4. Derive retirement targets internally from that checked handoff, not caller IDs,
   labels alone, a broad daemon list or arbitrary root paths. Verify fresh full-CID
   identity and stopped facts before non-force/no-volume removal. Persist removal
   intent before dispatch and completion only after the selected protocol establishes
   it. Do not delete the active worker or any unknown container, image or volume.
5. Resolve removal uncertainty separately from creation uncertainty. A typed scoped
   historical-CID absence may be useful only after durable owned stopped/removal
   evidence. Opaque reader errors and absence of an uncertain CREATE's generated name
   are not quiescence proof and cannot admit another worker.
6. For a new-protocol successor with no CREATE dispatch fence, define an explicit
   durable abandoned-before-dispatch terminal record. It must not fabricate a CID or
   stopped-container receipt. Resolve predecessor cleanup before any later admission.
   Recovery consumes its invocation; it does not execute the reopened attempt.
7. For a created-but-unfenced worker, verify actual identity and never-started state
   before recording resolution. For a start-fenced worker, retain the existing
   bounded cleanup-only supervision. Created state after an uncertain START remains
   unresolved; no fresh fence or START retry. Partial/corrupt chains remain incidents.
8. Compose all phases under the actual operations lock with shutdown intent recorded
   before admission. Shutdown and any recovery branch end that invocation. Every
   blocking daemon operation keeps a finite absolute budget; error handling cannot
   loop into new admission, renew a RUN fence or release uncertain reservations.

Freeze exact schemas, public/internal method names, acknowledgements and per-operation
budgets in the implementation plan before editing the protected store or transports.
This checkpoint intentionally does not pretend those interfaces already exist.

## Verified official API facts and remaining native proof

The fixed [Engine API 1.52 schema](https://raw.githubusercontent.com/moby/moby/api/v1.52.0/api/swagger.yaml)
defines container inspection 200/404 and removal 204/404/409 responses. Its removal
query flags `force`, `v` and `link` default false; running removal can conflict.
The [Docker removal reference](https://docs.docker.com/reference/cli/docker/container/rm/)
distinguishes forced removal and anonymous-volume deletion. These documented
responses do not establish request quiescence after a timeout, prove that an
unobserved CREATE cannot later complete, or implement durable application recovery.
No absence/removal transport or native deletion test has been added at this checkpoint.

The later transport must accept only its closed paths/methods and checked targets,
validate status/body/EOF under one absolute budget and sanitize diagnostics. Native
permission, actual full-CID behavior, daemon compatibility, stop/removal races and
restart recovery still need separate verification on harmless owned resources.

## Required validation before repeated scheduling

Test crashes before/after each intent, dispatch-fence, CREATE, CID, START, stopped,
handoff and removal acknowledgement; torn or mismatched chains; old protocol versus
new protocol; reopened sessions; duplicate calls; changed boot/clock; lock contention;
wrong predecessor/CID/image/release; every uncertain response; unrelated containers;
delayed CREATE and START; failed flush/readback; and shutdown at each phase.

The safety invariant is one unresolved lifecycle at a time, with no inferred dispatch
authority from recovery and no promotion from lifecycle evidence to investment
eligibility. Full regression and independent integrated review remain required.
Trusted release production, the manifest-file integration fixture, inert and executing
image proof, paused installation, disabled completion-relative timer, exclusive
credential renewal, backups/restore, freshness monitoring and actual scheduled stock
collection remain later independent gates. None is supplied by this design document.
