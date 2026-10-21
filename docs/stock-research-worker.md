# Local one-shot stock research

`trading_bot.runtime.stock_research_worker` now composes the canonical policy, durable
research ledger, private archive lease, official research-only facade, complete request
plans, numerical stock screen and company dossiers. It has no account, portfolio,
review, order, transfer or live-activation operation. The OAuth credential itself
remains trading-capable; these are local capability restrictions.

This is an executable acquisition cycle, tested with fictional provider sessions and
migrated databases. At source 32f4de3, one authorized local discovery completed all 17
planned data calls using the dedicated saved grant. A separate immediate invocation
returned `not_due` without another claim or capture. Rehash/recomputation retained 16
complete query groups, 1,472 candidates, 1,058 scorable companies and ten research
priorities; all eligibility flags remained false. This is one local cycle, not a
deployed scheduled service. Existing
paused services and the hybrid account journal are not changed by this command.

## Admission and recovery

The outer archive flock is stable across phases, builds and policy changes. It is held
before ledger admission and credential construction through transport closure, artifact
verification and terminal persistence. The manual capture and dossier entry points use
the same lock. Nested internal calls borrow one validated directory descriptor. Locks
are never unlinked or repaired automatically; unsafe permissions and conflicting owners
deny access.

Storage admission counts every recognized observation, manifest, report and pending
file, including orphans. Unknown names, directories, symlinks, hardlinks and unsafe
metadata deny admission. Inventory stops at the configured file bound. Remaining
worst-case growth reserves `(remaining_calls + 3) * 9,000,000` bytes and
`remaining_calls + 3` entries, including publication scratch. Available blocks and
inodes are checked. This is not an OS reservation against unrelated filesystem writers;
a later write failure stops work without deleting files or refunding call charges.

The full frozen plan is durably charged before SDK construction. The worker rechecks
the active claim, exact plan, source freshness and remaining storage before each call.
No failed or ambiguous call is retried. The existing capture has a 300-second budget;
the complete worker uses the canonical maximum of 450 seconds, including setup.
Independent UTC and monotonic checks stop expired work before credentials/data and
before cache promotion. A successful terminal record also checks the claim deadline
and enrichment source inside its database transaction. Legacy generic late-outcome
recording remains available outside this opt-in worker path.

The plan is checked again against the committed claim's planning time. If a midnight
crossing changed the canonical history window during reservation, that cycle stops
without constructing a connection; its charge is retained. This prevents an accepted
report that cannot be reconstructed later.

Only rehashed manifest-committed observations count. Recovery recomputes cached reports
from those bytes and the original cutoff, matching config, code, profile, tool arguments,
plan and ledger references. Tampering blocks the cycle. Failed captures cannot replace
usable heads. Cancellation or a lost capture/commit acknowledgement retains its full
reservation; missing identities are not guessed from orphan files. Restart never
replays the same claimed slot.

Python cancellation is cooperative. Production operation also requires a supervisor's
hard process limit and observed cleanup/restart behavior; that deployment is not yet
verified.

The existing dashboard Pause/Kill controls affect its hybrid journal. Collector
actuation is a separate explicit CLI. Acquisition now requires its private active
code/configuration-bound grant, checked through reservation, session setup, actual
data dispatch and successful result commit. Missing or stopped authority fails closed.
See the [collector control contract](stock-research-controls.md). Its fixed path/mount
identity and deployed behavior still require verification before scheduling.

## Research selection

Discovery and enrichment are separate cycles, each subject to the 32-call cap and the
512-call default UTC-day budget. Default discovery is 17 calls; ten-company enrichment
is 25. The cadence is at least the configured elapsed interval after the prior claim;
there is no catch-up burst.

After a successful current discovery, the worker enriches a nonempty shortlist when
its companies changed or the canonical six-hour refresh interval elapsed. Otherwise
it refreshes discovery. A failed discovery does not authorize enrichment from an older
head. Stale sources cause another discovery cycle. Reuse keeps the original evidence
times; it does not relabel old observations as current. News-driven invalidation is
not implemented yet.

Discovery requires complete partition coverage before publishing a ranked research
head. Enrichment preserves explicit missing facts and symbol-level history quarantine;
invalid whole collections cannot become successful dossier heads. Research priority
scores have no calibrated relationship to returns. Missing Robinhood interpolation
flags remain unknown and block strict technical calculations. No strategy, investment
or live qualification follows from acquisition success.

## Local invocation

Use an existing dedicated research ledger created with the repository's Alembic
migration helper. Its parent must be a canonical owned directory with mode 0700; the
ledger must be an existing, single-link SQLite regular file with mode 0600. Initialize
a new dedicated ledger explicitly with `migrate_sqlite_ledger`; do not reuse or rewrite
the frozen hybrid account ledger. Never reset or replace research history to evade
the daily budget.

The archive must be a separate existing owned directory with mode 0700, outside the
checkout. Select the separately authorized official OAuth store explicitly. The
command never creates a missing ledger, repairs permissions, opens browser login,
chooses another credential store or enables live mode.

Select a separately initialized collector control directory explicitly with
`--control-dir`. Initialization is paused; only an explicit current-code/current-policy
resume authorizes acquisition. Export-only may omit this option and never reads it.

The CLI retains the validated file descriptor through engine disposal. Its opt-in
SQLite engine uses existing-file-only `mode=rw` and checks held/named inode identity,
private ownership and path metadata before connection and pooled-checkout policy
queries. A missing or substituted file blocks. This guards persistent substitutions;
it does not attest the DBAPI's opened inode against arbitrary same-user swap-and-restore
attacks. Selecting the dedicated ledger remains an operator responsibility; the command
does not discover or select another service's database.

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_worker \
  --config-root configs \
  --database /absolute/private/research/state/ledger.sqlite3 \
  --archive-dir /absolute/private/research/archive \
  --control-dir /absolute/private/research/controls \
  --oauth-store /absolute/private/authorized-oauth
```

The CLI derives identity from the actual clean checkout using the existing code-identity
resolver. Dirty, uncommitted or non-promotable source is rejected. No caller-provided
code-hash flag exists.

For an image without Git, provide both `--image-digest sha256:...` and
`--image-attestation /absolute/root-controlled/release.json`. The existing canonical
verifier requires a root-owned immutable attestation, matching image digest, release
key and full stock configuration hash. The worker uses its image-derived code hash.
An incomplete pair or failed verification blocks before opening research resources;
it never falls back to local Git. With neither option, clean-Git checks still apply.

The operator/deployment process must independently verify the executing image and
produce the attestation outside the unprivileged worker. These startup arguments do
not prove that verification occurred. The stock deployment's attestation producer,
mounts and exact executing-image checks have not been implemented or run yet.

Output is a sanitized JSON status with counts and artifact digests. Successful cycles
and ordinary `not_due` return exit 0; other blocked outcomes return exit 2. Credentials,
account IDs, raw provider text and private filesystem paths are not printed.

## Dashboard projection

The optional `--export-dir` publishes a verified, sanitized dashboard projection after
the acquisition result. `--export-only` recomputes that projection without constructing
an SDK, reading credentials or reserving calls. It still requires the existing ledger,
canonical configuration and code-identity checks. Export failure is reported separately
and cannot replace a committed acquisition outcome. The authenticated dashboard can opt
in with `serve --stock-export-dir`; its filesystem-only reader receives no raw archive,
research ledger or OAuth access. See the [export contract](stock-dashboard-export.md)
for private directory requirements, freshness, UTC budget handling and exact CLI use.

## Verification and remaining work

Fictional integration tests exercise discovery/enrichment, fresh reuse, changed
shortlists, six-hour refresh, incomplete coverage, same-slot restart, storage exhaustion,
schema/auth failure, partial captures, closure failure, cancellation, tampering, both
clock deadlines, UTC-midnight planning and lost claim/terminal commit acknowledgements.
Separate process tests exercise lock contention; fault tests verify lock release even
when closing a writer directory fails. These tests establish local behavior only.

The authenticated dashboard projection and stock UI are implemented and locally verified
as described in the export contract. The independent collector gate is implemented
locally with explicit CLI actuation. Next: inspect integrated verification, implement
the resource-bounded external timer and deployed identity/control-path checks, then
verify actual scheduled collection, authentication
expiry/revocation, encrypted backup/restore and watchdog alerts. Market-data qualification,
out-of-sample stock-strategy validation, costs/taxes, nonempty brokerage reconciliation
and separate live authorization remain required.
