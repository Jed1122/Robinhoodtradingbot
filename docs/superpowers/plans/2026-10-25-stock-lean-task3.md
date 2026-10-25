# Lean Task 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver the user-approved October 25 guarded research release with a
complete integrity-verified backup and actual isolated restore, while retaining
core safety and explicitly deferring the deeper operational qualifications.

**Architecture:** Reuse existing copy/locks, SQLite/typed ledger validation,
bundle/crypto, receipts, health and killed-control restore. Introduce an explicit
versioned integrity policy alongside the unchanged full-replay default; do not
fork the collector or add a new operational subsystem. Root owns native release
and artifact verification; parallel source and core-safety audits are already
authorized.

**Tech Stack:** Existing Python 3.12 maintenance runtime, pytest, SQLite,
SQLAlchemy and snapshot/bundle/crypto modules; no new dependency or paid service.

**Spec:** [Lean first-release design](../specs/2026-10-25-stock-lean-task3-design.md).

## Global Constraints

- Live trading stays disabled. No broker, credential, revocation or financial
  action follows from this plan.
- Preserve original plans, failed captures and historical receipts. The user
  approved the new scope on October 25, 2026; deferred work is not verified work.
- Preserve single-owner execution, unknown-order/dispatch fail-closed behavior,
  risk limits, kill controls, authentication and sanitized secure logging.
- Preserve complete retained bytes, typed ledger/audit/configuration integrity,
  budget charges, pending claims, source references and original timestamps.
- Keep existing production resource/security limits. Use normal test-process
  umask 0022 while keeping private evidence directories 0700/files 0600.
- One actual backup and isolated restore are required. Verify the bounded
  automated path and enabled timer; a new 24-hour trigger is not a release wait.

## Review Focus

- A legacy or unknown artifact must not silently acquire the new policy or lose
  full-replay validation: Task 1 legacy/unknown-policy tests.
- A complete inventory hash must not hide broken SQLite, audit/configuration,
  source, budget or pending state: Task 1 corruption and historical-state tests.
- A later off-host/restore acknowledgement must not refresh old snapshot/source
  evidence: Task 1 receipt/health clock tests.
- A restored running control or copied operations namespace must not authorize
  work: Task 1 killed/offline restore tests and Task 2 ownership checks.
- A monitor/auth/restart failure must remain visible without a duplicate worker
  or retry into uncertain execution: Task 2 core-safety regressions.

### Task 1: Explicit recovery-integrity backup and restore

**Files:** Create `src/trading_bot/runtime/stock_snapshot_policy.py`; modify
`src/trading_bot/runtime/stock_snapshot.py`,
`stock_local_state.py`, `stock_backup_restore.py`,
`stock_operation_receipts.py`; `infra/hybrid/stock_maintenance_process.py`,
`stock_backup.py`, `stock_maintenance.py`, `stock_continuous_units.py`.

**Tests:** `tests/unit/runtime/test_stock_snapshot.py`,
`test_stock_snapshot_helper.py`, `test_stock_local_state.py`,
`test_stock_backup_restore.py`, `test_stock_operation_receipts.py`,
`test_stock_health.py`; `tests/deployment/test_stock_backup_coordinator.py`,
`test_stock_maintenance_process.py`, `test_stock_maintenance_cli.py`,
`test_stock_continuous_units.py`, `test_stock_monitor.py`.
Keep bundle/crypto implementations unchanged unless a demonstrated interface
dependency requires a reviewed change.

**Ownership:** Independent workstreams implement snapshot/restore core,
operational receipts, and host/helper integration; root integrates and verifies.

**Interfaces:** Shared `FULL_REPLAY_V1="full_replay_v1"`,
`RECOVERY_INTEGRITY_V1="recovery_integrity_v1"` and Literal type.
`create_stock_snapshot`, `verify_stock_snapshot`, `restore_snapshot_controls`
and `restore_encrypted_stock_backup` gain keyword
`validation_policy=FULL_REPLAY_V1`; all other arguments remain intact.
Full keeps exact schema-1/eight-key/kind `stock_application_snapshot` behavior.
Explicit lean requires schema 2/kind `stock_recovery_snapshot` and the ninth
`validation_policy` field; default full rejects lean. `SnapshotResult` and full
restore/asdict remain unchanged; lean-only `StockRecoveryBackupRestoreReceipt`
adds policy/time. Restore CLI adds closed `--validation-policy`, full by default.
Helper `snapshot-integrity` and coordinator `backup-integrity` select lean
explicitly. Receipt v2 retains v1 fields and adds required `validation_policy`
and UTC `snapshot_created_at`; schema, policy, time and existing artifact fields
bind its predecessors. Root independently verifies manifest policy/time. Backup
age uses snapshot time; copy/restore completion times remain separate.

- [x] Add failing policy tests: explicit integrity succeeds without invoking
  historical compiler/cache reconstruction; legacy default still invokes full
  replay; unknown policy/version and cross-policy evidence are rejected.
- [x] Add failing real-artifact/typed-reader tests for altered/missing/extra files,
  wrong hashes or unsafe identities, invalid SQLite/foreign keys, corrupted audit
  chain, missing historical configuration, inconsistent claims/results, changed
  budget charges, dangling source references and invalid original clocks.
- [x] Add mixed historical code/config and valid pending-claim tests: every row
  remains parsed, pending count/charges remain exact, and no state is repaired or
  cleared. Preserve the existing full-replay tests and historical report bytes.
- [x] Implement the smallest policy branch using existing copy/inventory and real
  application readers. Emit compact truthful policy-specific summaries; never
  claim full replay when it was omitted. Preserve complete bundle bytes and all
  current encryption/provenance checks.
- [x] Add and pass restore/receipt/health tests: actual fixture decrypt/unpack and
  typed read, same hashes/counts/tip/pending, fresh private destination, killed
  offline controls, high-water safety, mismatched policy rejection and unchanged
  snapshot/source freshness after later copy/restore acknowledgement.
- [x] Run affected suites and independently review policy propagation across
  helper, root coordinator, restore, receipts and health. Record exact source,
  commands, terminal results and evidence paths; do not launch native work here.

### Task 2: Verify the existing core-safety path

**Files/tests:** Inspect `infra/hybrid/stock_maintenance.py`,
`stock_launcher.py`, `stock_recover.py`, `stock_supervisor.py`,
`stock_attempts.py`; `src/trading_bot/runtime/stock_health.py`,
`stock_incidents.py`, `stock_research_controls.py`; existing worker/provider and
corresponding deployment/runtime/persistence tests. Change source only for a
demonstrated failure within this lean scope.

**Interfaces:** Retain current monitor/incident semantics and fixed recovery-only
entry point. Reuse exact-source accepted reboot evidence and current read-only
monitor/worker state; no timed postcommit interruption or auth-state action.

- [x] Run focused existing tests for auth denial/no SDK work after kill, durable
  auth failure across a fresh provider, stale-source/identity health failures,
  unavailable-observation incident preservation and restart/reopen behavior.
- [x] Run singleton/reconciliation tests for duplicate slots, uncertain create or
  start, preserved pending charges and recovery without a new create/start.
- [x] Reconcile accepted actual reboot/restart and current successful monitor
  evidence with the final source. Keep local journal/incident visibility linked
  in the runbook; do not imply external notifications exist.
- [x] Add a failing test and minimal fix only for any concrete core gap found;
  retain failed results and independently review the final diff.

The unchanged core's focused run completed October 25: 662 passed in 28.71s,
actual exit 0/reaped, with unchanged before/after inventory. Private evidence:
`.superpowers/sdd/2026-10-25-stock-backup-reliability/lean-core-focused-20261025T194751Z-f7c67b2e32b2/result.json`,
SHA256 `1b83134aff8383cb484df7c54a154ff2ab4edca606db38b608309ac141b99535`.
This does not validate the new backup-policy edits or complete native release.

### Task 3: Integrate and verify the actual lean release

**Files:** This plan/spec and `docs/stock-continuous-operations.md`; existing
release/backup/restore tooling and private evidence directories. Native actions
are performed by root through the existing authorized deployment workflow.

**Interfaces:** Exact source/release/runtime and current controls bind the actual
artifact. Completion names the validation policy and trigger, with original
snapshot time, hashes, file/ledger counts, pending state and restored killed
control; it does not set deferred qualification flags true.

- [x] Independently review the integrated diff and run required full regression,
  static, security and critical-coverage gates on the final revision. Review all
  failures by name; green focused tests alone are not final acceptance.
- [ ] Verify the exact replacement source/runtime, helper isolation, unchanged
  controls/safety limits and configured bounded backup timer. Reuse current
  DigitalOcean daily/seven-day protection as supplementary evidence; no full-host
  restore claim or new paid service.
- [ ] Root captures one actual complete backup and isolated restore, preserving
  original process terminal/reaping/stream evidence, artifact hashes and policy.
  Verify SQLite/typed state, charges/pending and killed restored controls. Use the
  existing receiver/off-host path and record its actual availability and outcome.
- [ ] Freshly read monitor/health and the configured timer. Preserve prior
  scheduled failures/freshness truthfully; label manual success as manual and new
  genuine scheduled success as unobserved until it actually occurs.
- [ ] Report the lean criteria completed only when actual evidence passes. List
  full historical replay/performance fit, new scheduled success, timed stop/
  reconnect drill, natural-expiry reuse and isolated revocation as deferred.
  Continue to Task 4 data qualification and Task 5 economics without enabling live
  execution.

## Source verification checkpoint — October 25

The complete frozen stock suite finished with actual exit 0/reaped:
**12,192 passed, 36 warnings in 587.99 seconds**; no failures or skips. Total
statement/branch coverage was **91.33%**, and the independent critical branch/host
coverage gate passed. All 1,234 tracked/nonignored files had identical before and
after content inventories. The 36 retained warnings are a Starlette/httpx
deprecation and SQLite resource warnings in the test process; they are not silently
suppressed. Ruff, strict mypy, expanded Bandit and whitespace checks also passed.

Private full-run receipt:
`.superpowers/sdd/2026-10-25-stock-backup-reliability/lean-integrated-regression-af8a7ab075a54dc5b6477f4c49a6a376/result.json`,
SHA256 `a1ba37b4d2b989e353ac47aa9225ff52563079b53871383f30756a2d3e99e1a3`.
Coverage SHA256 `463ffb7e3c61827da615833569076b30d1779d81159e23a58e5ceae01cd5dda3`.
The preceding failed full run is preserved. Its 18 failures were traced to a
restricted runner omitting `uv` and the normal macOS temporary directory; restoring
those environment inputs made the 31 targeted tests pass without source/test or
ownership-guard changes. The subsequent complete run above is a separate result.

A fresh read-only droplet observation at 20:18:53 UTC confirmed the existing f4
research worker exited 0 at 20:10:12, the current monitor exited 0, research and
maintenance timers were enabled, and the earlier scheduled backup failure remained
visible. This supports the unchanged core's basic runtime evidence; it does not
certify installation or backup/restore of the new release. Native release and the
actual new artifact/restore checkboxes remain open.
