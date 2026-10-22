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
Output/removal/terminal and closed-predecessor absence writers are implemented with
exact session evidence identity and crash/clock/durability tests. The actual transport
must still establish scoped HTTP status/body/EOF before minting private evidence;
the tests use fictional wire evidence. Fixed Engine operations now implement metadata,
CREATE/CID, strict prestart, START, scoped polling/discovery/signals, finite logs and
non-force retirement. Supervision/CLI, whole-increment review and this controller's
actual full regression are pending.

## Actual verification

The current local deployment/architecture regression passed **2,863 tests in48.99
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

The127-predecessor successor-admission test used an actual advancing local monotonic
clock and completed its observed setup in2.248seconds without extending the20second
setup or5secondCREATE cap. This local fictional-history test does not qualify host
capacity or native exchange timing.

Ruff passed. Strict mypy passed459 source files including the stock host modules.
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

Implement controller supervision/CLI, then obtain one fresh whole-increment review and run
revision-specific integrated checks. Preserve the running primary full unchanged.

Only afterward perform an actual credential-free intended-host probe. Source/image
provenance, trusted release production, paused installation, OAuth ownership and
lifecycle, backups/restore, scheduled individual-stock research, market-data semantics,
strategy evidence and nonempty broker reconciliation remain separate gates. No test,
merge or deployment activates real-money investing.
