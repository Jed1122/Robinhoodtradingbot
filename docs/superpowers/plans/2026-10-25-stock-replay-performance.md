# Stock replay performance implementation plan

**Goal:** Reduce avoidable historical replay work without changing report bytes,
provenance, validation, resource limits, or Task 3 operational acceptance.

**Base:** `acdc0e0d141fb21fb91ea0b1da65eb63f1396b29`, clean integration tree
`ea1bf9daada7519b84c9d5216530a563dd44dc96`; branch
`codex/stock-replay-performance`. The deployed f4 release remains unchanged.

The completed local compiler measurement identified duplicate dossier rendering.
Static replay analysis also shows that complete historical reports remain in
memory although later enrichment requests require only ordered discovery symbols.
These observations justify the separate changes below; they do not establish
native backup budget fit. Retain the original measurements and failed captures.

## Contracts and boundaries

- Preserve complete historical capture verification, report recompilation and
  canonical comparison, original source timestamps, all budget charges, and
  independent export replay. Never skip old-code or old-config history.
- Preserve the generic canonical codec, public dossier rendering/hash behavior,
  live-disabled controls, production limits, and all failure/evidence artifacts.
- Root alone handles any native observation or coherent diagnostic copy. A copy
  is not application-valid until full replay succeeds; exited nonzero workers
  are not successful research just because their terminal state is reconciled.
- No deployment, credential operation, financial execution, or forced renewal is
  part of these source edits. Natural expiry and isolated official revocation
  remain actual, separate Task 3 requirements.

## 1. Retain only validated discovery-symbol context

- [x] Add a failing resource-retention regression and historical older-discovery
  references, including ordered symbols, empty selections, mixed code/config,
  multiple enrichment references, and corrupted historical reports.
- [x] Replace full report retention with validated discovery-result hash to ordered
  symbol tuple. Insert only after all existing equality and coverage checks pass.
  Keep every compilation, validation and export path intact.
- [x] Run snapshot/archive/job/worker and historical compatibility tests.

## 2. Render each compiler-owned dossier once

- [x] Prove that the normalizer/build graph used by the compiler has no accepted
  stateful getter or copy behavior that makes render/hash interleaving observable.
  If that proof fails, leave the old behavior intact and record the limitation.
- [x] Add failing duplicate-render and complete canonical compatibility tests.
- [x] Introduce a narrow render-and-hash helper using the original document
  function. Preserve v1/v2 tagging and the distinction between report-only empty
  filing evidence and the original digest view. Keep public APIs as an oracle.
- [x] Verify legacy, filing-aware empty/mixed evidence, exact extreme Decimal,
  malformed/future sources, denial precedence, and unchanged report bytes.

## Integration and operational return

- [x] Independently review the combined diff. Run affected tests and complete
  current-stock regression/static/critical coverage gates for the final code.
- [x] Measure identical fictional reports unprofiled with finite parent process
  wall/CPU limits and actual terminal receipts. No custom Python profiler timer.
- [x] Separately obtain a coherent current-state diagnostic copy under the real
  operations lease, preserving pending claims and exact copy metadata.
- [ ] Use bounded scalar phase measurements on a private clone for full replay.
  A standalone replay is only a lower bound on whole backup cost. Verify actual
  whole-pipeline resource fit before any immutable replacement release.
- [ ] Complete scheduled encrypted backup, offhost copy and decrypted application
  restore, actual worker recovery/reconnect, natural-expiry rotation/reuse and
  isolated official revocation denial. Source tests cannot close these gates.

Technical-summary serialization and screener ranking are deferred candidates,
not bundled speculative changes. Reconsider only if measured replay still needs
them. Running-bot changes require their own recoverability and release evidence.

## Verified source results

The integrated Python 3.14 regression completed on October 25, 2026 with
12,118 passing tests, 36 warnings and 91.31% coverage. The original process exited
zero and was reaped; the tracked source/test inventory was unchanged throughout.
The critical branch gate, Ruff, mypy (455 source files), configured Bandit scan
and diff checks passed. Independent cross-reviews found no actionable findings.
Warnings include the existing SQLite resource and Starlette/httpx warnings.

Seven complete report cases matched the actual baseline compiler and retained
canonical oracle bytes. An unprofiled fictional 10-company, 252-bar comparison
also preserved all output bytes in three alternating pairs. Timing was noisy;
these samples establish no native backup budget bound or investment result.

The forensic copy completed under the real operations lease at the exact copy
clock `2026-10-25T17:43:57.493452Z`: 1,103 files and 75,445,187 bytes, content
inventory `76dd263f86b4f671993b5efafa123e7ee85684a3a79e1f06c41c402df98c747a`.
It preserves the reconciled worker exit 143 and pending reservations. Copy
completion is not application validation, scheduled backup success, or restore
acceptance. The deployed f4 source, controls and production units are unchanged.
