# Scoped stock-worker recovery and termination library

Root-owned continuation of Task 2 in the approved
[operations plan](2026-10-21-stock-research-operations.md).
Base: `63a988e1708240b1f545bfe46916523f6922afd7`.
Status before implementation: create/start transport and durable sequencing are
locally reviewed; actual supervision, termination and deployment are unverified.

## Boundary and dependency chain

Validated durable active receipts -> immutable inspection snapshot -> fresh owned
running-container inspection -> unchanged receipt-chain recheck -> one fixed
TERM/KILL request -> acknowledgement only. Actual stopped observation and explicit
`record_stopped` remain separate. No CLI, timer, service, Docker operation, provider
call, credential operation, installation or live activation is part of this change.
Root owns all implementation and integration. Parallel agents review only.

The primary f04a63f worktree remains frozen for its real full-suite process. Develop
and verify here, then integrate only after that process is terminal. The reviewed
pure stock manifest merged at 63a988e passed 956 central tests with four optional
age skips; Ruff, strict mypy (447 files), expanded Bandit and lock checks passed.
The first central command named a nonexistent screen test and collected no tests;
the corrected run is the evidence, not that initial invocation.

## Store contract

Add frozen, slotted `AttemptSnapshot` with:

- `attempt: Attempt`
- `container_id: str | None`: validated created CID, otherwise stopped CID if present
- `start_fence: StartFence | None`: reconstructed persisted values, never the issued object
- `created_sha256`, `start_sha256`, `stopped_sha256`: optional canonical receipt hashes

`AttemptStore.snapshot() -> AttemptSnapshot | None` is read-only. Validate the
namespace/active intent and complete existing receipt chain, including ordered
created/start clock/CID bindings and stopped CID/start-presence agreement. Recheck
namespace and active identity before returning. Do not fsync, set an acknowledgement,
renew a deadline, initialize/repair records, or admit/start an attempt. Empty stores
return None. Malformed or partial chains fail with the existing sanitized error.

`AttemptStore.cleanup_target() -> AttemptSnapshot` first revokes fresh create,
created/start and terminal acknowledgements, even if entry validation then fails.
Require a nonterminal active snapshot with both validated created and start receipts
and a full CID. It works after reopening and after boot change or deadline expiry;
it cannot restore start authority. Reconstructed fences are data, not issued tokens.
No new on-disk record/schema or recovery adoption for execution is introduced.

## Signal contract

Add `infra/hybrid/stock_engine_termination.py` with
`StockEngineTerminator.signal_active(store: AttemptStore, signal: str) -> None`.
Only exact strings TERM and KILL are supported. Its closed private exchange must
perform the same sequence even if directly invoked; no route, CID, body, socket,
caller observation, release or start-fence override is accepted.

Require the actual fixed production root store and existing Linux root socket/peer
connector. Obtain `cleanup_target` internally, GET the full CID through the fixed
API 1.52 route, parse the original bounded bytes, and require exact CID/image/name/
three labels/Linux/no-restart/no-auto-removal ownership. Admit only ordinary first
running state: running true, nonpaused/nonrestarting/nondead, positive integer PID,
zero exit/restart count, no OOM/error, nonzero valid start timestamp and zero finish
timestamp. Unknown, stopped, missing, paused or drifted observations deny; they do
not become stopped receipts. This is a deliberately narrow initial cleanup profile.

Immediately before signal send require the current validated snapshot to equal the
obtained one. Derive only `POST /v1.52/containers/<fullCID>/kill?signal=TERM|KILL`.
Use one absolute five-second monotonic budget spanning store work, both connections,
inspection and signal response. Reuse bounded HTTP parsing; accept only complete
200 inspection and empty 204 signal acknowledgement followed by EOF. Reject every
other status, malformed/extra/truncated/streamed response, timeout or disconnect
with fixed `stock_engine_termination_unavailable`. No retry or silent fallback.

Signals may deliberately abort a research worker before its trading-independent
deadline (host shutdown/emergency). A past deadline or different retained boot never
prevents scoped cleanup and never renews the original deadline. This library does
not decide when TERM/KILL should occur, wait for exit, handle paused workers, prove
quiescence, remove containers, grant a later attempt, or implement the supervisor.
KILL may continue inside Docker after local timeout; a later fresh observation is
mandatory. No 404-to-absence or 204-to-stopped inference is permitted.

Retain the active stopped CID until a next attempt is durably admitted after fresh
stopped reconfirmation. Lost-create-ACK/name lookup, no-start cleanup, unknown absence,
ambiguous daemon state, actual TERM/grace/KILL scheduling, inactive-container removal
and durable incident/retry policy remain subsequent root-owned increments.

Versioned source reviewed:
[kill endpoint](https://github.com/moby/moby/blob/docker-v29.1.3/daemon/server/router/container/container_routes.go),
[daemon signal and KILL semantics](https://github.com/moby/moby/blob/docker-v29.1.3/daemon/kill.go).
These establish documented behavior, not native lifecycle or deadline proof.

## Verification

1. Observe RED for missing snapshot/revocation/termination behavior using fictional
   private stores and socketpairs only. Never connect to a real daemon in tests.
2. Exercise reopened sessions/lost start ACK/old boot/expired deadline; malformed,
   inconsistent, substituted or missing receipts; no read-side durability grants;
   revocation before failed cleanup entry; and preserved begin/start denial.
3. Exercise exact two-request paths, returned-ID alias rejection, all ownership/state
   mismatches, receipt changes after connect, invalid signal, preflight and I/O budget
   exhaustion, transport/framing errors and dispatch-only success.
4. Run store/termination/create-start tests and coverage, then deployment/architecture
   plus the stock manifest/minute/technical/screen tests. Run Ruff, strict mypy,
   expanded Bandit, lock and diff checks. Independent exact-revision review follows.
5. Record actual results, unresolved boundaries and source hashes. No deployment or
   continuously operating stock research claim follows from local fixtures.
