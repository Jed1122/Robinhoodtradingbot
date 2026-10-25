# Stock Backup Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reduce redundant snapshot replay work and prevent a backup start from overtaking an already running research unit.

**Architecture:** Preserve the current isolated snapshot, deterministic validation, encryption and receipt pipeline. Reuse each validated history batch hash within its existing dossier/technical consumer, and add ordering to the backup service without activating or stopping research. The deployed release remains immutable until a separately reviewed replacement passes release checks.

**Tech Stack:** Python, pytest, existing systemd unit renderer; no new dependencies.

**Spec:** `docs/superpowers/plans/2026-10-22-stock-continuous-operations.md`, especially the scheduled application backup and scoped failure-recovery acceptance requirements.

## Global Constraints

- Live execution remains disabled; no credentials, account data or broker calls in development tests.
- Preserve all failed stages, original captures and receipts; no backup retry, cleanup or success acknowledgement is part of these source changes.
- Keep all canonical hashing, validation, security limits, resource budgets and research quotas unchanged.
- Do not add Requires/Wants on research, Conflicts, reciprocal ordering or automatic restart.
- Ordering mitigates backup activation during research, including ExecStopPost. It does not claim universal serialization when research is requested during an existing backup.

## Review Focus

- Populated multi-company batches must retain exactly the same per-symbol results and provenance hashes while avoiding repeated full-batch hashing.
- Empty or disqualified candidates must retain existing validation and exception precedence.
- Mutated or malformed input must still be rejected; do not introduce a process-wide cached validation result.
- Backup ordering must include the research unit's cleanup and must not create an activation dependency or a cycle.
- The opposite activation order must remain fail closed; no ambiguous side effect may be retried.

### Task 1: Preserve output while reusing each batch hash

**Files:** `src/trading_bot/research/stock_dossiers.py`, `src/trading_bot/research/stock_technicals.py`, corresponding `tests/unit/research/test_stock_dossiers.py` and `test_stock_technicals.py`.

**Interfaces:** Keep `build_stock_dossiers` and `compute_stock_technicals` signatures and returned domain objects unchanged. No hash-codec changes or external cache.

- [x] Run the existing dossier/technical tests on clean base `f4f37c12ce978d4c5fae4f1c4aeb68f448297b8d`.
- [x] Add failing populated multi-symbol tests that count full-batch hash evaluation and also assert the exact returned provenance and results. Cover empty/disqualified inputs and malformed input using existing fixture contracts.
- [x] Reuse the batch's deterministic hash at its existing validation boundary, once per consumer invocation when needed.
- [x] Run the affected tests, snapshot replay tests and historical canonical-compatibility tests.
- [x] Repeat the fictional differential measurement with unchanged archived reports; record CPU timings as diagnostic evidence, never fabricated native-backup success.

### Task 2: Order backup behind existing research

**Files:** `infra/hybrid/stock_continuous_units.py`, `tests/deployment/test_stock_continuous_units.py`, `docs/stock-continuous-operations.md`.

**Interfaces:** `unit_files(release, checkout)` keeps the same eight named units. Backup gains `After=... hybrid-stock-research.service`; collector bytes, timers, execution commands and budgets stay unchanged.

- [x] Run the existing unit-rendering tests on the clean base.
- [x] Add a failing test for the research ordering edge, absence of activation/conflict dependencies, unchanged collector and timer bytes, and no reverse ordering cycle.
- [x] Add only the required ordering argument to the pure renderer and update historical byte-regression assertions to describe the precise additional change.
- [x] Run all affected deployment/maintenance tests. Verify harmless native oneshot fixtures include ExecStopPost before claiming actual scheduling behavior; otherwise retain that verification as pending.
- [x] Document the observed collision, bounded mitigation and opposite-order limitation. Do not claim complete serialization.

### Integration and return to Task 3 qualification

- [x] Independently review both changes together; run the current-stock regression/static/coverage gates appropriate to the final diff.
- [ ] Preserve old native acceptances as historical evidence. Produce a new exact-source release only after its checks pass; do not overwrite the frozen f4 source or relabel its artifacts.
- [ ] Follow the existing paused upgrade, control, broker-authentication and native verification procedure before deployment. Reconcile any actual action using its original capture.
- [ ] Complete genuine scheduled backup/copy/restore, scoped worker recovery/reconnect, natural-expiry renewal/reuse and safely isolated official revocation evidence. These remain actual acceptance requirements; source tests cannot close them.

## Verification record

On October 25, 2026 the integrated Python 3.14 regression completed with 12,095
passing tests, 36 warnings and 91.30% coverage. The critical branch coverage gate,
Ruff, mypy and the configured Bandit scan passed. The first full invocation is
preserved separately: its three permission-fixture failures resulted from the
test launcher's inherited umask 0077. The unchanged tests passed with the normal
test-process umask 0022; no validation or permission checks were weakened.

An independently reviewed native systemd255 fixture showed the queued fake
backup job waiting during fake research `ExecStopPost`, then starting after
cleanup. This proves that ordering mechanism, not a replacement deployment or a
genuine scheduled backup. All four Task 3 operational acceptance groups remain
open. Release integration targets `codex/robinhood-system-implementation`; the
repository's unrelated `main` branch is outside this change.
