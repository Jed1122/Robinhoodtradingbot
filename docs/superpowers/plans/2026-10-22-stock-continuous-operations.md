# Continuous stock research operations implementation plan

> Use the plan-execution and test-driven-development workflows. Root owns
> authentication, policy, controls, host integration and all native operations.
> Independent agents may implement separately contracted pure codecs/evaluators.

**Goal:** Complete project Task 3: actual scheduled individual-stock collection
independent of the developer client, persisted no-browser authentication renewal,
restart/reboot recovery without replay, bounded monitoring and alerts, scheduled
encrypted backup, off-host copy and decrypted application restore. Live trading
remains disabled. Task 4 data qualification and Task 5 strategy economics remain
separate; successful acquisition is not a qualified investment recommendation.

**Base:** `83fb520ad7415bf23feb3158c4ad55f07ed30bd5`, identical source tree to the
installed Task 2 source `0255d86141dae37993aee7529e008e91e7ec5a20`.
**Binding contracts:** stock research worker/controls/archive/export, container,
repeated lifecycle and producer operations, plus the readiness dependency chain.
**Workspace:** `.superpowers/sdd/2026-10-22-stock-continuous-operations`.

## Rulings and operational boundaries

- The user's explicit Task 3 request authorizes necessary official research-only
  access, private deployment of the dedicated research grant, stock-only timers,
  monitoring and backups on existing capacity. It does not authorize orders,
  account operations, unrelated services, paid infrastructure or live activation.
- Preserve the exact original grant; transfer ownership once under the workstation
  lease and forbid concurrent workstation use. Never copy the interactive Codex
  credential, unrelated stores or private backup identity onto the collector host.
- The existing saved grant's conservative renewal threshold is October 29, 2026
  18:45:38.277657 UTC. Its saved response time plus full provider lifetime is
  18:46:08.719989 UTC that day; natural-expiry acceptance must occur after that
  later bound. Natural expiry is a real-time acceptance gate: no edited
  clocks/token records, explicit-refresh substitute or premature completion claim.
  Implement/deploy the other work while this gate remains outstanding.
- Owner revocation requires an official human workflow for a separate test grant;
  never revoke production research access to manufacture a negative test, invent
  a revocation endpoint or bypass sign-in. Prepare the concrete test first.
- Reuse this already-isolated linked worktree. Preserve prior evidence, malformed
  unrelated refs, legacy runtimes and all pending reservations. Standing operator
  authority covers normal commits/pushes/PRs/merges; no redundant approvals.

## Architecture and workstreams

### 1. Authentication lifecycle and receipt

Fix the durable denial gap when a refreshed credential still receives MCP401.
Persist reauthorization_required without making an expired/denied generation
usable; test a fresh provider cannot send traffic after denial. Preserve existing
single refresh, pending-state ambiguity and atomic token/lifetime persistence.
Add owner-only sanitized auth status (generation/state/flow/absolute expiry and
observed time, no tokens/token hashes/client_id/authorization URL). Schema and
actual acquisition run through the fixed 13-tool research facade only.
Automatic token rotation first persists resource_validation_pending, including
the interruption window before its first resource send. Every new generation
resets acceptance; MCP401/403 after renewal cannot remain usable across restarts.
The separate owner-only explicit-renewal utility remains a token-endpoint migration
receipt and continues to declare runtime_reuse_verified=false; it is never the
daemon's retry or natural-expiry acceptance mechanism.

### 2. Coherent stock snapshot and cryptographic envelope

A root coordinator holds the existing operations lock, checks no unresolved owned
worker, and invokes a verified network-disabled helper as UID10001 with no OAuth.
Maintenance uses a separate immutable root-owned host virtual environment built
from this source's frozen hashed production dependencies, rather than a generic
maintenance Docker launcher. Verify this runtime independently of the research
image. Use the existing distro stdlib venv without pip and bootstrap from the exact
pip wheel/hash already in uv.lock, then install hashed production requirements plus
that pip pin. No global package, interactive credential or additional paid service enters
this runtime. Systemd denies outbound networking/OAuth; helper argv/env are fixed,
supplementary groups cleared and UID/GID dropped before app readers run. Narrow
writable anchor exceptions allow archive/control/export mutexes while payloads
remain read-only. Docker's root-owned socket is unavailable to the reduced owner.
The helper holds archive/control mutexes, copies SQLite using its backup API,
checks integrity and exact application replay, and inventories/hashes controls,
archive and exports without refunding pending claims or refreshing source times.
The snapshot includes source/image/config identities and reservation history.
Do not copy inode-bound operations state as an executable restored namespace.

Use the existing pinned PyNaCl/libsodium secretstream authenticated streaming
primitive, with a fresh stream key sealed to a public Curve25519 backup recipient.
The private key remains only on the trusted off-host receiver. Fixed versioned
framing, bounded chunks, required FINAL and EOF deny corruption/truncation/trailing
bytes. This avoids installing a new privileged binary and keeps memory bounded
for the canonical 1GiB archive quota. The public-recipient file is not a secret.
Provenance additionally depends on trusted root ownership, SSH and retained hashes;
public-key encryption alone does not authenticate an archive's sender.

Publish exclusive ciphertext and receipt only after complete snapshot/encryption,
fsync and readback. Bound wall time, disk use and retained generations; failed or
busy attempts cannot advance last-success freshness. Never prune unacknowledged
copies or the only known good backup. Off-host copies remain encrypted/private.

### 3. Application restore and controls

Decrypt into a new private isolated directory; never overwrite live state. Verify
all manifest/file hashes, migration/trigger/audit chains, pending budget charges,
committed captures/reports and original observation timestamps through actual
application readers. Restore authorization is always paused or killed: preserve
control_id, monotonic generation and predecessor hash, retaining the saved record
as forensic input. Never initialize a replacement identity, restore a saved running
grant or clear a later kill. This drill does not create a new executable host
operations namespace, start a provider, expose credentials or run a trade.

### 4. Stock monitoring and persistent incidents

Add a pure evaluator plus a fixed bounded host observer. Combine verified release,
control status, systemd state, owned lifecycle exit, actual job status/source/claim
and result times, storage capacity and backup/copy/restore receipts. Launcher exit0
is lifecycle evidence, not acquisition success. Export generated_at cannot renew
source TTL. Unknown/malformed/missing observations preserve uncertainty and cannot
clear incidents. Write a private durable deduplicated incident spool/journal;
never remediate, restart, resume controls or send external messages automatically.
No SQL write transaction against a live ledger is used for routine monitoring.

### 5. Scheduling and boot continuity

Preserve the completion-relative collector timer and no-catch-up rule. Add a
separate bounded boot recovery path using stock_recover only, then an explicitly
installed boot bootstrap that may initiate a fresh eligible cycle after recovery
completes and collector running authority is verified. Recovery and new execution
remain separate invocations; no old start fence or daily reservation is replayed.
Separate root singleton monitoring/backup timers have fixed argv, finite budgets,
private state, Restart=no and no financial execution capability.

### 6. Integration and native acceptance

TDD each safety boundary, independently review the integrated branch and run the
current-stock regression/static/coverage gates. Produce a new immutable release
from its exact clean source using the existing producer; never relabel the Task 2
archive with a merge SHA. Upgrade only stock units/release while controls paused,
preserving state/archive/control and original evidence.

Deploy the designated credential once with private ownership and no secret output.
Observe actual no-browser reuse and multiple scheduled discovery/enrichment jobs,
original source times, quotas and absent duplicate UTC reservations. Show operation
without a development-client process maintaining the session. Rehearse worker/helper
failure, scoped container termination, reconnect and a genuine host reboot while
preserving unrelated services and control identity. Collect actual stopped/fill-free
receipts; a host-helper timeout is never actual-container termination proof.

Observe scheduled encrypted backup, copy it to the off-host receiver, decrypt and
reconstruct the actual stock application. Inject safe fixture failures for disk,
corruption, source staleness, provider disconnect and alert persistence; clearly
separate fixture from native evidence. Natural-expiry automatic renewal/persistence
and official revoked-test-grant denial remain separate actual acceptance gates.

## Completion audit

Every item above requires current authoritative source/test/native receipts. Keep
Task 3 active while future authentication evidence or human sign-in/revocation is
outstanding. Only actual full completion permits goal completion. Then Task 4 is
stock data qualification; do not claim investment edge or enable live trading.
