# Inert stock probe controller: implementation checkpoint

The individual-stock product remains continuous research, qualified selection and
risk-controlled automatic investing after separate explicit live activation. The
new controller is **partial and not deployable**. No native container, broker,
credential, account, order or deployment operation was performed in this increment.

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
The expanded store regression passed922 checks in6.79seconds at100% statement/branch
coverage. These are fictional filesystem/process observations, not native execution.
Task2 remains in progress: output/removal/closed writers and fresh scoped closed-CID
absence evidence are not implemented. Fixed Engine transports, supervision/CLI, whole-increment review
and this controller's actual full regression are also pending. A closed CID denies
new admission until the missing actual absence path is implemented.

## Actual verification

The current local focused run passed **1,867 tests in15.79 seconds**. Store tests
passed873 checks with100% statement/branch coverage; the observer separately reached
100% in its611-check regression. These are fictional filesystem/wire observations,
not native Docker or broker evidence.

Ruff passed. Strict mypy passed458 source files including the stock host modules.
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

Finish Task2's STOP/output/removal/closed writers, cleanup fences, fresh scoped
entry absence and acknowledgement behavior with crash-window tests. Then implement the fixed
bounded transports and controller, obtain one fresh whole-increment review and run
revision-specific integrated checks. Preserve the running primary full unchanged.

Only afterward perform an actual credential-free intended-host probe. Source/image
provenance, trusted release production, paused installation, OAuth ownership and
lifecycle, backups/restore, scheduled individual-stock research, market-data semantics,
strategy evidence and nonempty broker reconciliation remain separate gates. No test,
merge or deployment activates real-money investing.
