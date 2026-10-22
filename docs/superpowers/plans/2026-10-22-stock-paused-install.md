# Native stock release and paused installation

**Goal:** Complete project task 2 on the existing `robinhood-bot-prod-paused`
droplet: produce and verify the exact clean source release, prove that its worker
denies collection while paused, and install a disabled completion-relative timer.
This is the existing approved operations design, not permission to start research.

**Baseline:** Integrated commit `9704b1e9a95abd1bc258d1fbef4f6b5d5519da8b`.
Use the existing linked worktree, preserve unrelated refs/worktrees and legacy
services. The current task authorizes credential-free native build/probe and
paused installation. Historical source-only implementation boundaries do not bar
this task. No credential transfer, provider call, resume, schedule activation,
paid provisioning, account access or live trading is permitted.

## Binding design and implementation

1. Expose a no-argument recovery-only CLI using the existing operations lock,
   scoped recovery and supervisor. It must never load a release or create/start a
   worker, including after a completed attempt. ExecStopPost must use this CLI.
2. Add a separate pure paused-check profile derived from the production worker
   request: network disabled, no OAuth mount, distinct identity, otherwise the
   same image/worker command, ledger, controls and resource constraints. Verify
   actual created metadata before start. Never relax the production profile.
   Run it only as a bounded operator acceptance operation and preserve full CID,
   prestart inspection, natural exit, output and stopped/removal evidence.
3. Generate fixed systemd service/timer bytes from the verified release and exact
   trusted checkout. Root-owned checkout and stdlib host interpreter execute the
   launcher. Restart=no; finite start/stop budgets; recovery-only ExecStopPost;
   completion-relative cadence; Persistent=false. Install disabled/inactive,
   without starting a scheduled worker. Do not overwrite any existing unit.
4. Before the first producer attempt, resolve native compatibility against actual
   metadata. The observed distro Compose reports
   `2.40.3+ds1-0ubuntu1~24.04.1`; if admitted, pin that exact build string alongside
   upstream 2.40.3 in current and historical validation, retaining exact policy
   comparison. No arbitrary suffix/version fallback or global plugin replacement.
5. Integrate and independently review the source, run critical regressions and
   static checks, then commit/publish normally under existing operator authority.
6. Transfer an exact clean Git checkout without credentials. Explicitly initialize
   absent producer/probe/operations namespaces; never repair partial attempts.
   Run the public producer once from the final clean HEAD; require actual exit0,
   complete success JSON and the native build/probe/render/publication closure.
7. Explicitly create new private runtime directories and a dedicated migrated
   ledger, initialize controls paused, prove integrity/zero claims and unchanged
   controls across the network-disabled paused invocation (expected exit2 and
   control_denied), then install and verify disabled/inactive units.

## Verification and acceptance

- RED/GREEN: recovery with empty, completed, unfinished and ambiguous attempts;
  no CREATE/START paths, sanitized CLI errors, no caller release/CID overrides.
- Profile tests deny OAuth/network/identity/mount/resource drift; production
  profile regression stays unchanged.
- Unit tests check exact executable/source/release identity, no autostart/restart,
  finite cleanup budget and canonical cadence. Native systemd-analyze verification
  and installed byte/owner/mode checks must also pass.
- Native source HEAD/status, daemon/image IDs, producer/probe original terminal
  outcomes, release hashes/ownership, SQLite integrity/claim count, paused-control
  identity and stock-only unit state form the final evidence receipt.
- Progress, copied artifacts, passing fixture tests or a host-helper timeout never
  prove native success. Preserve unresolved records and report an unconfirmed
  outcome instead of retrying/repairing them.

**Next gate after task 2:** Task 3 verifies actual 24/7 collection, authentication
renewal, restart/reboot recovery, monitoring and backup restoration. Data/strategy
qualification and separately authorized live activation remain later gates.
