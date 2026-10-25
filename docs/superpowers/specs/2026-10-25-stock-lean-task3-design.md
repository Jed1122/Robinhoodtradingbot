# Lean Task 3 first-release design

## Decision and authority

On October 25, 2026, the user explicitly approved a lean first release in the
active stock-operations conversation, following the discussion of which Task 3
qualification work could be deferred. The root agent recorded that approval and
the parallel execution method in its implementation handoff. This document
records that prospective scope change; it does not turn deferred evidence into
verified evidence. The earlier continuous-operations, backup-reliability and
replay-performance plans remain unchanged historical records.

The selected approach reuses the existing snapshot, encryption, restore,
monitoring and recovery paths with an explicit integrity-validation policy. A
full historical replay remains available. Continuing to block the first release
on the full replay budget and timed interruption drill was deferred by the user;
an unvalidated file copy would not meet the approved integrity requirement.

This release enables guarded stock research only. It grants no live-trading,
funding, order, account, credential or provider-revocation authority. Task 4 data
qualification and Task 5 strategy/economic validation remain separate.

## Required first-release behavior

1. Produce one actual complete, consistent, hash-verified application backup.
   Preserve the real operations barrier, source stability, private ownership,
   bounded inventories, exact file counts/bytes/digests, authenticated encryption
   and trusted artifact provenance. Preserve all retained files and original
   source/config/code identities. SQLite integrity and foreign-key checks, full
   typed stock ledger/audit parsing, hash-chain and claim/result consistency,
   canonical configuration history, budget charges, source references and
   original timestamp/deadline rules remain mandatory. Referenced manifests and
   reports must exist with their expected raw hashes. Valid pending claims remain
   pending and charged; nothing is cleared or reclassified to make backup pass.
2. Perform an actual isolated restore of that artifact into a new private
   namespace, verify its complete hashes and the same application-integrity
   policy, and read the restored typed application state. Restore controls as
   killed and offline-only; preserve the saved identity/generation and existing
   high-water protections. Never overwrite production, restore a running grant,
   create an executable operations namespace or contact a provider. Copying or
   parsing a manifest alone is not restore completion.
3. Configure and verify the current automated backup path, its finite resource
   bounds and enabled timer. Record the actual backup trigger. One successful
   manual invocation can meet the backup/restore requirement; it cannot establish
   genuine scheduled success. Keep the earlier scheduled failure and current
   backup/copy/restore freshness truthful and visible.
4. Keep health monitoring, original-source freshness, authentication fail-closed
   behavior and a visible basic alert route. The existing private incident spool
   and journal, surfaced through the dashboard/runbook, are sufficient; no new
   external messaging service is required. Unavailable observations preserve
   incidents, and a fresh export or acknowledgement cannot renew source or
   snapshot age. Existing recent reboot/restart evidence can cover basic restart
   with a fresh read-only check. Exercise restart/reopen, singleton ownership,
   reconciliation, sticky kill, auth failure and uncertainty preservation in
   offline tests; no new forced production interruption is required.

Single-owner execution, unknown-order/dispatch reconciliation, deterministic
risk limits, kill controls, authentication boundaries and sanitized secure logs
are unchanged. No real-money execution is enabled. Existing file, time, memory,
CPU, quota and security limits must not be relaxed to manufacture acceptance.

## Explicit validation scope

The shared `stock_snapshot_policy.py` defines `FULL_REPLAY_V1`,
`RECOVERY_INTEGRITY_V1` and their Literal type. Snapshot create/verify/control
restore and encrypted restore gain keyword `validation_policy=FULL_REPLAY_V1`.
The default retains schema 1, kind `stock_application_snapshot` and its exact
eight-key manifest. Explicit `recovery_integrity_v1` uses schema 2, kind
`stock_recovery_snapshot` and nine keys: the existing eight plus required
`validation_policy`. `created_at` retains its meaning. Default full callers
reject lean artifacts; unknown or mismatched policy/version is rejected.

`SnapshotResult` and legacy full restore dataclass/asdict output stay unchanged.
Lean restore uses `StockRecoveryBackupRestoreReceipt`, adding policy and
`snapshot_created_at`. The closed restore CLI accepts `--validation-policy` with
full as default. The helper adds `snapshot-integrity`; the coordinator exposes
explicit `backup-integrity`. Operational receipt v2 retains the v1 fields and
adds required `validation_policy` and UTC `snapshot_created_at`. The schema,
policy, snapshot time and existing artifact identities must match across
backup/off-host/restore. Root binds them to the actual manifest independently.
Backup age uses the original snapshot time; copy and restore completion clocks
remain separate. A later acknowledgement cannot conceal a stale backup. Legacy
v1 fields and bytes remain unchanged; artifacts are never silently relabeled.

The integrity policy verifies retained bytes and application recovery state. It
does not recompile every historical report, reconstruct every cached export or
establish that historical numerical outputs match the current compiler. Those
claims remain exclusive to completed full replay. Historical checks retain their
original clocks and configuration; neither backup nor restore refreshes TTLs.

## Deferred qualification

- Genuine complete historical semantic replay and its whole-pipeline native
  performance-budget qualification.
- A new genuine scheduled backup success after the changed release; do not wait
  for a new 24-hour trigger to accept the actual backup/restore above.
- The timed postcommit normal-service interruption and subsequent reconnect
  drill. Its safety checks remain mandatory if that drill is resumed.
- Natural-expiry renewal followed by fresh-process reuse, including the pending
  October 29 observation window.
- Safely isolated disposable-grant revocation and actual provider denial.

Report these as deferred/unobserved, never passed. Full unattended operational
qualification and investment readiness are not claims of this first release.

## Evidence and completion

Reuse independently accepted evidence where its exact source and scope still
apply: actual reboot/restart, ordinary scheduled acquisition, the current
successful monitor observation and the N106/53-pair/pending-zero ledger baseline.
The October 23 manual backup/off-host/restore remains historical evidence; a
fresh basic backup and restore are still required for this release.

Root's October 25 read-only DigitalOcean check reports daily backups enabled with
seven-day retention, image `251357577` available (created October 25 at
00:25:54 UTC), and the next window October 26 at 00:00–04:00 UTC. This is
supplementary host protection; no full-host restore was tested, and it does not
replace the application restore. No new paid service is needed.

Accept the lean release only after source review, relevant regression/security
checks, exact release/runtime verification and the actual backup/restore evidence
above. Retain original terminal results and artifact hashes. Report completion
as the October 25 lean Task 3 scope with its deferred list. Next work is Task 4
data qualification and Task 5 strategy validation; live activation remains
separately authorized.
