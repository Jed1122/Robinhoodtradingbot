# Active stock-worker supervision

`infra.hybrid.stock_supervisor.supervise_active(store)` supervises an already
durably created/start-fenced stock research worker while its root operations lock
remains open. This is implemented local runtime code, not an installed launcher or
evidence of a continuously operating service. It performs no create, start, remove,
broker, credential, provider or trading operation.

The public entry point requires the actual Linux UID-0 fixed operations store.
It revokes launch claims through `cleanup_target`, reconstructs the original start
fence, and fixes its reader/terminator internally. Caller CIDs, observations, clocks,
callbacks, budgets and broker adapters are not accepted. The ownership assumptions
remain the trusted-root, single sequential store-owner model; Python objects are
not independent authorization or authenticated attestation.

## Fixed phases and earlier-only I/O caps

| Phase | Absolute local cap |
| --- | --- |
| RUN polling | Persisted TERM/RUN boundary R |
| TERM dispatch and grace polling | K = R + 10 seconds |
| KILL exchange | C = K + 5 seconds |
| Final stopped observation | Q = C + 5 seconds |

The GET reader's `inspect` and terminator's `signal_active` accept optional
keyword-only `not_after_ns`. It is an exact positive bounded monotonic integer,
excluding booleans, and can only shorten their existing five-second entry budget.
The selected deadline is shared across every connection, send, receive and final
EOF check. A far-future cap cannot enlarge that budget. Ordinary GETs now reject
delayed trailing bytes as well as malformed, truncated and oversized responses.

R ends the normal RUN phase and initiates termination. It is not a claim that the
container physically stopped or received its signal at that instant: fresh owned
inspection precedes dispatch, and Docker's KILL may continue after a local timeout.
K/C/Q are fixed before cleanup, not derived from acknowledgements. A stalled active
run never gets replacement budgets after C/Q. Exhausting Q without verified exit
returns the fixed unresolved error; a future separate recovery hook remains required.
Native scheduling/physical termination and host-process-death behavior are unverified.

## Observation and recovery

Each poll derives the full CID from the checked snapshot, obtains fresh inspection
bytes through the fixed socket and rechecks the snapshot. Running state uses the
existing ownership/ordinary-first-running profile. Terminal state uses the existing
stopped-state verifier, then `record_stopped(raw)` for durable evidence. Created
after a start fence, missing/unknown/paused/restarting state, foreign identity,
bad receipts and opaque lookup failures never establish termination.

Current-session loss of START acknowledgement does not retry START: the persisted
fence supplies the original R. A reopened session enters cleanup immediately,
without receiving the remainder of a normal run. Initial old-boot or rollback
recovery preserves incomparable old timing and selects a finite current-domain
cleanup window only. An initially overdue same-boot attempt preserves a remaining
original grace; if that grace already elapsed, it skips TERM and obtains one
finite KILL/final-inspection budget. This recovery-only exception does not apply
to an active RUN whose observation or wakeup returns late.

Local boot changes or monotonic rollback during supervision fail unresolved; they
cannot renew selected phases. No-CID or no-start attempts are rejected before
daemon work. Their explicit resolution protocol and generated-name recovery are
still future work. Existing stopped active containers remain retained for later
fresh reconfirmation; this function does not remove them or admit a next attempt.

SIGTERM/SIGINT set shutdown intent and select an earlier fixed cleanup origin once.
Repeated signals never extend grace. Both previous handlers are restored on normal
and exceptional exit, and restoration attempts continue after one failure. Signal
registration requires the main thread. Registration/restoration failure returns an
unresolved error rather than a successful result.

TERM and KILL are each attempted at most once. Signal uncertainty does not itself
end reconciliation: fresh observations may prove exit within the remaining cap.
Read retries are bounded by fixed phases. A failed stopped-record write is propagated,
never treated as running state and retried as another signal. Successful recording
returns frozen repr-safe `StockSupervisionResult`: owned identities, original fence,
reason, signal-attempt flags, exit code, OOM and error presence. No diagnostic text,
arbitrary logs, research-success conclusion or qualification follows from exit zero.

## Verified locally and still outstanding

Twenty cap/EOF RED cases preceded the transport change; 316 transport/store tests
passed afterward. Twenty-seven missing-controller RED cases preceded implementation.
The initial controller suite expanded to 37 cases and passed with 95% combined
statement/branch coverage. Fresh whole-increment review found an active-budget renewal
bug. Nine RED cases reproduced late successful/failed reads and wakeups beyond K/C/Q;
the fix restricts the fresh cleanup budget to initial recovery. The corrected focused
suite passed 362 tests, at 97% combined coverage across reader/termination/supervisor
(96% for the supervisor). All use fictional daemon boundaries and virtual time.

The root integrated deployment/architecture/stock-data check passed 1,359 tests with
four optional local-age skips. Existing research/source-policy checks passed another
26 tests. Ruff, strict mypy (450 source files), expanded Bandit, lock and diff checks
passed. The separate older f04a63f full primary run finished with 12,110 passed,
33 optional skips, one dependency warning and 88.80% combined coverage. It does
not validate this later source; its integrated full run remains required.
No native Docker mutation or provider/authentication operation
occurred in this implementation.

Next: compose complete fresh-cycle launch/recovery, explicit ambiguous-attempt
resolution, identity-checked non-force older-CID cleanup and a trusted release producer.
Then verify native immutable/executing image, hardening, deadline/reboot recovery,
paused controls, disabled completion-relative timer, actual scheduled collection,
authentication lifecycle, backups/restore and freshness alerts. Data/strategy and
native nonempty broker reconciliation remain separate gates. Live execution stays
disabled; no fixed paper waiting period is introduced.
