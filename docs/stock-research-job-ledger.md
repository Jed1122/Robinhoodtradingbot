# Stock research job ledger

This is the durable admission and cache-reference component for the stock worker.
It is not yet a running acquisition service. It creates no account, order, broker
session, credential or execution permission. Existing paused services and hybrid
account journals remain unchanged.

## Canonical configuration

`load_config` accepts the opt-in `stock_worker_policy_path` together with the existing
hybrid and stock research policies. `configs/hybrid/stock-worker.yaml` selects
`StockWorkerAppConfig` and its paired safety envelope. The old hybrid/stock graphs,
canonical bytes and hashes remain restorable; they do not silently gain new defaults.
The new section defaults to:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `live_enabled` | false | Strict false; no live authority |
| `max_run_seconds` | 450 | Whole-worker ceiling, including acquisition setup |
| `enrichment_refresh_minutes` | 360 | Planned deeper-evidence refresh cadence |
| `max_archive_bytes` | 1,073,741,824 | Local archive admission ceiling |
| `max_archive_files` | 10,000 | Local archive file admission ceiling |

Unknown fields, booleans masquerading as integer limits, out-of-bound values,
unpaired extensions, environment overrides and envelope mismatches fail closed.
The runtime must enforce the storage/deadline fields; their presence alone does not
establish an operational control. No path, credential, API key or endpoint is added
to this policy. All provider data-tool budgets remain in `stock_research`.

## Durable admission

`SqlStockResearchJobs` uses the existing canonical `audit_events` table and existing
append-only protections. It adds no schema or parallel database format. Its fixed
provider scope is independent of config/code hashes so changing builds cannot reset
the local daily budget. The supplied canonical graph is restored and checked; the
validated session factory is pinned to its original engine and checked at every call.
The injected code hash is an identity binding, not a build attestation. The eventual
runtime owner must establish the actual executable identity.

Every transaction verifies the current reviewed migration head and exact normalized
SQL hashes for all four audit mutation/replace guards. A named no-op trigger is not
accepted. Bounded records contain canonical typed claim/result payloads, sequence,
predecessor hash, content hash, metadata and fixed category/actor/scope. Corrections,
gaps, malformed records, changed metadata and inconsistent plan/result links deny
recovery. The query fetches at most 100,001 rows before rejecting overflow.

A claim has one stable provider-scope/UTC-slot identity independent of phase, plan,
config or code. Within `BEGIN IMMEDIATE`, admission checks the expected state hash,
prior cadence, source head/age where applicable, cycle limit and full remaining
budget. It commits the entire planned data-call charge before returning a usable
claim. Unknown commit acknowledgements never grant permission to proceed. A failed,
cancelled or abandoned claim retains its full charge; it is never retried in that slot.
Near midnight, every UTC day touched by the bounded execution window is charged
conservatively. Clock rollback and code/config changes cannot create free reservations.

Admission reserves terminal-record capacity for all pending claims and the new claim.
Reaching the 100,000-event bound stops new work without stranding an admitted job's
terminal slot. An identical terminal retry still succeeds at capacity. Do not delete
the chain or start an empty replacement ledger to evade budgets; retention/recovery
requires preserving and verifying its prior state.

`assert_active` rechecks the exact pending claim, frozen plan hash/count, deadline,
reserved UTC day and enrichment source freshness immediately before a data-tool send.
The eventual runtime must also enforce a monotonic whole-run timeout, no retries,
exact request ordering and complete plan validation. A database claim is not a
substitute for those runtime controls.

## Results and cache heads

Terminal records bind the original plan, actual capture-plan identity, bounded
attempted/successful counts and immutable manifest/report references. Success requires
all reserved calls to have succeeded and both output hashes. Partial/failure outcomes
cannot become cache heads. Conflicting terminal metadata fails; an exact repeat returns
the original record. The runtime must rehash and validate actual artifacts before
calling `finish`; arbitrary digest arguments are not acquisition evidence.

Heads are selected by source claim order, not completion arrival. A delayed older
result stays in history without replacing newer research. Only successful records
matching the current config and code can become current heads. Replay resolves
backward source references through an index of already verified results, without
repeated prefix scans. Source/report timestamps remain availability evidence rather
than historical publication times or forecasts.

## Secret-safe audit encoding

Raw digests use the existing approved SHA columns. The shared audit sanitizer also
rejects long high-entropy strings in detail values, including normal SHA text. A closed
typed codec therefore stores only validated digest fields as colon-separated groups
of four hexadecimal characters and verifies the exact round trip on replay. Registered
secret values are rejected before encoding. This is not a general text encoder, and
the existing secret sanitizer is unchanged. No provider text, identifiers or credentials
enter job events.

## Verified scope and next steps

Fictional migrated-database tests cover competition, restart reconstruction, failed
and cancelled commit acknowledgements, same-slot denial, full budget retention,
the 512-call boundary, midnight, changed configuration/code, rollback clocks, stale
sources, exact pre-send checks, missing/no-op guards, engine rebinding, capacity,
idempotence, late cache results and strict capture-plan replay. Independent review
cleared the corrected config/job-store scope. These tests do not prove real provider
calls, physical power-loss durability, scheduled operation or live readiness.

Next: wire the bounded one-shot runtime owner to private artifact quotas and the
capture pre-call check; verify exact plan/manifest/report identities and recovery;
then add the authenticated dashboard projection and resource-bounded external timer.
A completion-relative timer must respect the persisted cadence; do not replay missed
UTC slots or assume a fixed wall-clock timer's jitter guarantees elapsed eligibility.
Encrypted backup/restore and actual deployed collection remain separate requirements.
