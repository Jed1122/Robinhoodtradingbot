# Active stock-worker supervisor

Root-owned continuation of the approved operations plan. Base: 08e3cfb.
The prior goal turn made source, review and verification progress. The primary
f04a63f full run remains live; do not modify it or start a duplicate full suite.
Parallel SEC work owns only its three declared data/docs/test paths in another
worktree. No agent may change this protected runtime.

Goal: actually supervise a durably identified active research worker through
natural exit, deadline, shutdown or recovery, retaining the original start fence
and requiring actual stopped observation. This is the active-process part of the
launcher, not deployment or evidence of a continuously operating service.

Dependency chain: earlier-only transport cap -> closed actual observation -> fixed
RUN/TERM/KILL/verify controller -> integration/review -> later fresh-cycle launcher,
older-container cleanup, trusted producer, paused installation and native proof.
Do not mark the overall operations plan or goal complete at this increment.

## Task 1: Absolute transport caps

Files: stock_engine.py, stock_engine_termination.py and their deployment tests.

1. Write failing tests for expired/mistyped caps, late connection/read, no budget
   renewal and delayed extra GET bytes. Expected: RED before implementation.
2. Add one shared `_deadline(not_after_ns: int | None) -> float`: validate exact
   positive bounded int (not bool) when supplied, use min(entry monotonic+5sec,
   absolute cap), reject expired values before opening a socket. Infinity/floating
   caps are unsupported; omission preserves the five-second bound.
3. Thread keyword-only `not_after_ns` through reader `_get`, `inspect` and terminator
   `_exchange`/`signal_active`. It only shortens an I/O operation; it grants no
   launch or deadline-renewal authority. Require final EOF on ordinary GETs too.
4. Run reader/termination/store/create-start tests. Expected: all pass, old closed
   paths, root/socket peer checks, sanitized errors and one-use launch intact.

## Task 2: Actual active observations and fixed-phase supervision

Files: new infra/hybrid/stock_supervisor.py and test_stock_supervisor.py.

1. Observe missing-module and behavioral RED using real fictional private stores,
   fake monotonic/boot clocks and fake daemon boundary responses only.
2. Add frozen repr-safe `StockSupervisionResult` with owned attempt/CID, reason,
   original fence timing and retained exit/OOM/error-presence facts. It describes
   stopped-container evidence only, never successful research or qualification.
3. Public `supervise_active(store: AttemptStore) -> StockSupervisionResult` fixes the
   production root store, reader and terminator internally. No caller CID, clocks,
   observations, callbacks, time/risk settings or broker adapter. Reconstruct a
   nonterminal created/start-bound target through cleanup_target; revoke launch
   claims before work. Reopening may clean up, never adopt for execution.
4. Internal observation derives the full CID from that target, calls the fixed
   reader with a phase cap, and rechecks the current snapshot. Reuse existing
   `_owned_running` for ordinary running and `_stopped` for terminal ownership.
   Created-after-start, unknown/paused/restarting state, 404 and malformed/drifted
   observations remain unresolved. Never catch failed `record_stopped` as running.
5. Preserve original same-boot RUN boundary R. TERM dispatch/grace cap K=R+10s;
   KILL operation cap C=K+5s; final stopped observation cap Q=C+5s. All leaf calls
   keep their own five-second max shortened by that phase's absolute cap. Do not
   derive K/C/Q from response times. Poll at most once per second without catch-up.
   R is the RUN-phase/TERM initiation boundary, not proof of physical stopped time;
   ownership inspection precedes signal dispatch and native KILL may outlast its
   local timeout. Report unresolved exit if stopped state cannot be observed by Q.
6. Current owning session after a lost START acknowledgement uses original R, never
   repeats START. A reopened session must not receive the remaining normal RUN
   allowance: enter bounded cleanup immediately. Old boot, monotonic rollback or
   an already overdue R likewise enters cleanup using current clock for finite
   cleanup only; retain the original fence unchanged. For same-boot overdue work,
   preserve an original not-yet-expired K; if K already elapsed, escalate to KILL.
7. On SIGTERM/SIGINT record shutdown intent, initiate earlier cleanup once and
   derive a fixed earlier grace origin. Install/restore both handlers safely, main
   thread only; a blocked call remains bounded by its phase cap. A signal never
   enables a new cycle, and repeated signals never renew grace.
8. Send TERM at most once and KILL at most once. After signal uncertainty, fresh
   scoped observations may establish actual exit; never retry START or infer exit
   from signal acknowledgement. Observations can retry within fixed phase caps.
   Confirmed terminal bytes go to record_stopped; persistence errors propagate and
   grant no result. Retain the actual stopped container and immutable receipts.
9. Controller clock regressions during supervision must not extend any previously
   selected cap. Fail unresolved on an incomparable local clock instead of granting
   a new RUN period. Initial old-boot recovery uses a finite current-domain cleanup
   window without rewriting old timing. Root controls this policy explicitly.
10. Tests cover natural/nonzero/OOM/error exits, deadline boundaries, slow/uncertain
    signals, lost START acknowledgement, old/reopened/overdue attempts, created/noCID,
    wrong identity, stopped persistence failure, clock drift, host shutdown, handler
    restoration and no start/create/begin or implicit source/live authority.

## Task 3: Central integration and fresh review

Run focused coverage, then deployment+architecture+stock manifest/minute/technical/
screen tests, Ruff, strict mypy including infra files, expanded Bandit, lock and
diff checks. Expected: all required checks pass; optional local-age skips disclosed.
Record exact commands/results/commits in this plan's ignored ledger. Independently
review the whole increment before integration. Full repository verification remains
required on its eventual integrated candidate; a running old baseline is not a pass.

No Docker mutation, credential/provider operation, production state initialization,
service composition, timer installation, real order, transfer or live activation is
authorized by these local tests. Next root work remains full fresh-cycle creation/
recovery, explicit incomplete-attempt resolution, non-force older-CID cleanup and
native paused deployment proof. Source/strategy/broker reconciliation qualification
remain independent requirements; no fixed paper waiting period is introduced.
