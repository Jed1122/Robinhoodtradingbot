# Inert stock probe controller: implementation checkpoint

The individual-stock product remains continuous research, qualified selection and
risk-controlled automatic investing after separate explicit live activation. The
new controller is **implemented locally and not deployment-ready**. No native container, broker,
credential, account, order or deployment operation was performed in this increment.

## Latest acceptance checkpoint — October 22

Task4 acceptance completed with1,139 passing checks in30.37seconds. The subsequent
fresh whole-branch review returned one Important final-publication timing/clock gap,
reproduced by root as28 failing composed tests before correction. All28 now pass;
the corrected focused suite passed1,167checks in31.10seconds at96.67% combined
controller/transport statement/branch coverage. The deployment/architecture group
passed2,951checks in50.38seconds with four optional local-age skips. Ruff, strict
mypy460, expanded stock-module Bandit, lock and diff checks passed. Existing broader
12Low host-script findings remain unchanged. See the exhaustive
[review disposition](stock-inert-controller-review.md), including deferred historical
prose and all separate qualification gates.

The private completion context now checks the original retirement cap, clock
continuity and shared shutdown after store closure/handler restoration and after
CLI serialization. Complete closed bytes may remain when publication is denied;
they are neither rewritten nor treated as fresh success on reopen.

Task5 remains incomplete until the actual corrected-source full suite terminates
successfully. The earlier primary full at0af7687 is still running and cannot certify
this later source; it remains unchanged. Only afterward may this revision's full
start. No native intended-host probe, trusted release production or deployment has
occurred. A separate [read-only broker checkpoint](stock-broker-reconciliation-2026-10-22.md)
records only empty-position/recent-order evidence; it grants no nonempty fill/lot or
background-authentication qualification. Historical sections below retain earlier
checkpoints and should not be read as this latest acceptance status.

## Implemented and verified locally

- Pure probe ownership/lifecycle observation, preserving failure facts for cleanup
  while requiring strict separate prestart checks before any future START.
- Separate fixed-root private namespace, permanent nonblocking lock, bounded original
  byte persistence and strict canonical receipt schemas. Worker stores/configuration
  and their authority are unchanged.
- Complete bounded history validation, original-byte/hash binding, precursor and CID
  uniqueness checks, single complete predecessor chain, exact 128-probe retention
  bound, copied snapshots and cleanup-only unfinished-entry classification.
- Per-lock cache checks exact named-file fingerprints and inventories. Historical
  nodes retain validated facts; large original payloads remain on disk.

- Setup admission, immutable metadata/request/intent/head acknowledgement and the
  CREATE/CID/strict-prestart/START writer prefix now have one-use session fences.
  Original setup/dispatch/RUN deadlines survive delays, lost acknowledgements and
  reopening. Copied objects and complete unacknowledged bytes cannot issue a token.

Task1 is complete. Task2 now also implements bounded cleanup, owned-CID discovery,
single-use signal fences, STOP persistence and cleanup-only STOP reconfirmation.
Output/removal/terminal and closed-predecessor absence writers are implemented with
exact session evidence identity and crash/clock/durability tests. The actual transport
must still establish scoped HTTP status/body/EOF before minting private evidence;
the tests use fictional wire evidence. Fixed Engine operations now implement metadata,
CREATE/CID, strict prestart, START, scoped polling/discovery/signals, finite logs and
non-force retirement. Controller supervision and a fixed-image CLI now compose the
actual store/verifiers/transports. Whole-increment review and this controller's
actual full regression are pending.

## Actual verification

The current local deployment/architecture regression passed **2,923 tests in48.08
seconds**, with four optional local-age checks skipped. The terminal-writer group
passed94 checks in7.25seconds. Task2's final acceptance passed1,016store checks
in16.98seconds at100% statement/branch coverage; the observer separately reached
100% in its611-check regression. These are fictional filesystem/wire observations,
not native Docker or broker evidence. Tasks1and2 are complete locally. The63transport
checks passed in3.21seconds with100% statement/branch coverage over the new transport.
Task3's actual acceptance passed394transport/worker/terminal checks in19.35seconds,
again at100% transport statement/branch coverage. Tasks1through3 are complete locally.
These include partial-send/disconnection and
complete Content-Length without final EOF, one shared signal-exchange budget and
no retry after ambiguous CREATE/START. Existing worker transport files are unchanged.

The current controller/transport candidate passed123checks in11.75seconds at96.96%
combined statement/branch coverage (controller94%, transport100%). These use actual
files, verifiers, store and HTTP transport with fictional socket/clock/root boundaries.
Task4's final acceptance rerun is next. They include repeated shutdown, original
cleanup windows, old-boot recovery, ambiguous acknowledgements, queued-created states,
handler/store-context failure and suppression of publication during terminal fsync.

Integration exposed a cleanup poll using the final cap during TERM/KILL. Root observed
the failing phase-budget test before adding fixed TERM/KILL/FINAL selectors derived
only from the existing cleanup token. Normal RUN rejects a selector and no numeric
deadline override exists. The same integration test then passed. A successor fixture
also required Docker's CID-derived hostname to change along with its fictional CID;
only that fixture was corrected, with no relaxed prestart policy.

The127-predecessor successor-admission test used an actual advancing local monotonic
clock and completed its observed setup in2.248seconds without extending the20second
setup or5secondCREATE cap. This local fictional-history test does not qualify host
capacity or native exchange timing.

Ruff passed. Strict mypy passed460 source files including the stock host modules.
The dependency lock check and diff check passed. Bandit over src plus the stock
host modules reported no findings. The broader scan of every infra/hybrid script
reported12 inherited Low findings in unchanged prepare.py/watchdog.py; these were
inspected and were not suppressed or silently repaired. That broader scan is not a
clean security result and remains relevant to later producer/deployment review.

The retained-history memory test first failed at16,462,277 bytes for16 fictional
900KiB image observations. After excluding original payloads from historical nodes
and clearing temporary byte cache per newly validated node, the same test passed
its12MiB peak bound. This does not qualify the intended host's memory or deadlines.

The earlier primary revision f05dbe8 completed its actual full suite:13,008passed,
33 optional skips, one warning,89.04% coverage,8331.44 seconds. Root then integrated
only the already reviewed prior probe-profile branch0af7687. One full at exactly
0af7687 is running as session4761, logging to
/tmp/stock-operations-full-suite-0af7687.log. That result is pending and will not
certify these later controller changes.

## Next required work

Complete Task4 acceptance, obtain one fresh whole-increment review and run the actual
source-specific full once the earlier primary full terminates. Preserve that running
primary full unchanged. See [operator interface](stock-inert-controller-operations.md)
for the fixed roots, outputs, incident handling and remaining native gates.

Only afterward perform an actual credential-free intended-host probe. Source/image
provenance, trusted release production, paused installation, OAuth ownership and
lifecycle, backups/restore, scheduled individual-stock research, market-data semantics,
strategy evidence and nonempty broker reconciliation remain separate gates. No test,
merge or deployment activates real-money investing.
