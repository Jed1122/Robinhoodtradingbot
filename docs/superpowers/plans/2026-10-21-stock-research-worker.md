# Durable individual-stock research worker

This continues the authorized hybrid stock plan. Individual companies remain the
primary universe; ETFs remain optional benchmarks. The worker has no execution,
account, portfolio, order or live-activation authority. It does not resume the existing
paused hybrid account. Natural-expiry/revocation proof and strategy qualification
remain separate from research scheduling.

## Existing composition

Reuse the canonical `LoadedConfig` stock extension, `discovery_requests`, bounded
stock capture, the fixed dual-gated research profile, verified archive reader,
`screen_stocks`, typed normalizers, dossier/technical report and private immutable
artifact publication. Reuse the existing canonical database/audit-event schema and
append-only protections for research claims/results; do not add another account
journal, queue framework or configuration schema. Deployment paths are operator
arguments, not a second investment-policy graph.

The existing in-memory Scheduler does not provide durable claims. HybridJournal
binds a frozen account/config identity and must remain untouched. A narrow
`persistence/stock_research_jobs.py` can append strict `stock_research` audit events
inside `BEGIN IMMEDIATE` using the existing event sanitizer and immutable domain
records. A new one-shot runtime owner composes that ledger with acquisition/reporting.

## Execution order

1. Validate canonical stock-only, live-disabled configuration and immutable code/profile
   identities. Acquire a deployment-shared worker lock before loading credentials.
   Check the private artifact directory, available space and configured byte/file quota.
2. Reconstruct strict bounded claim/result records, clock high-water, source cache heads
   and spent/reserved call budget. Sum budget across code/config changes in the same
   provider scope. A crash or missing terminal result never refunds reserved calls.
3. Derive the current UTC cadence slot and exact phase/request-plan identity. Reserve
   the full planned data-tool count durably before connection or data effects. An
   existing claim suppresses same-slot replay, including after restart. Clock rollback
   fails closed. Near-midnight reservations must conservatively cover every UTC budget
   day the bounded run could cross; changing dates must not create a quota loophole.
4. Discovery and deeper enrichment are separate cadence cycles. Default discovery is
   17 calls and default enrichment is 25; a 42-call combined cycle violates the current
   32-call cap. At most hourly alternation costs 504 data calls per UTC day, within the
   512 local cap. This cap is a local operating hypothesis, not a provider quota promise.
   Faster configured cadence stops at the durable cap and never catches up in a burst.
5. Reuse exact fresh tool/arguments/profile/config-bound observations. Trigger deeper
   work for new shortlisted companies or expired/event-changed evidence. Record cache
   hits and original availability times; reuse must not relabel old data current.
   Document the selected refresh semantics before implementing the selector. Each new
   scanner session must initialize its own vocabulary latch from the official tool.
6. Validate the complete immutable request plan, capture bounded native SDK observations,
   rehash the committed manifest and build screening/dossier outputs. Preserve explicit
   partial, stale, truncated and normalization-denied states. Never turn research scores
   into expected returns, strategy qualification or orders. The current interpolation
   omission remains unknown and blocks strict technical metrics.
7. Append a terminal event linking its claim to verified capture/report hashes. Only
   committed successful heads can replace prior usable cache. Orphans count toward
   storage and reservations but cannot become research evidence implicitly. Source
   failures retain prior evidence with its original age and a blocked current status.
8. Expose sanitized last-attempt/success, staleness, remaining local budget and stable
   failure reasons. Keep account values, auth material, provider exceptions and raw
   external text out of logs and the audit details. Feed the existing authenticated
   dashboard through a separate read-only projection, without changing live readiness.

## Storage and deployment

Add archive byte/file ceilings only through the canonical stock policy/envelope.
Admission must account for the actual 8 MiB payload bound, 9 MB observation/report
verifiers, manifests and crash orphans before new calls. No unattended deletion or
plaintext backup is introduced. A full archive stops collection until a separately
verified encrypted archive/retention procedure makes space. Keep the research credential
in a dedicated worker-only private mount; the dashboard/default service gets no OAuth
mount. No credential transfer or timer installation has occurred at this checkpoint.

After local recovery tests, create a resource-bounded one-shot systemd timer around the
same owner. Verify immutable image/config/Compose identity, encrypted backup and restore,
watchdog incidents and actual scheduled collection with the development client closed.
Do not claim 24/7 operation from source code or a healthy paused container.

## Required verification

- Failed preclaim/commit/disk admission causes zero provider calls.
- Competing processes, same-slot restart and missing terminal events cause no replay.
- Partial/cancelled/crashed runs retain budget and preserve the prior cache head.
- Daily boundary, backward clock and config/code changes do not reset local quotas.
- Actual 17/25 plans obey the 32-call cycle cap and 512 default daily cap.
- Rehashed manifests reject tampering, symlinks, orphans, future/stale/duplicate heads.
- Missing data, schema drift, revoked auth and provider failures block new collection
  safely without interactive fallback or account/order operations.
- Existing canonical hybrid hashes, paused account journal and live denial remain intact.
- A deployed scheduled run, backup restore and alerts are observed independently of tests.

The durable claim/budget/cache ledger and one-shot owner are implemented locally; see
[the current worker contract](../../stock-research-worker.md). The next implementation
step is the dashboard read projection and external timer, followed by actual deployed
identity, authentication, backup/restore and monitoring evidence. Source code and fake
sessions do not establish scheduled production operation.
