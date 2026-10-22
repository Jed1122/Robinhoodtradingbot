# Separate stock collector controls

The one-shot stock research worker requires an explicit private control store. It
starts from a manually initialized paused state. Missing, malformed, stale-clock,
unsafe or mismatched authority denies acquisition before a reservation or credential
connection. These controls govern research collection; they grant no trading access
and do not change portfolio risk, reconciliation, promotion or live authorization.

## State and acknowledgment

Use a dedicated existing owned mode-0700 directory outside the checkout, separate
from raw archives, exports, OAuth stores and the research database. Its bounded
canonical mode-0600 state retains a stable collector identity, generation, previous
state digest, fixed action/status, UTC timestamp and optional active code/configuration
binding. A separate stable private lock serializes cooperating processes. Unknown or
pending files deny access; no command repairs permissions or deletes an unsafe anchor.
Initialization cannot replace an existing state or recreate its lost lock.

Resume requires the exact observed state digest and binds the current verified code
identity and full canonical stock policy. The worker captures that generation once.
Any subsequent generation change fences that cycle, including pause followed by
resume. Pause and kill remain available across code/configuration changes. Kill is
sticky; this implementation provides no clear/reset operation. Ordinary pause can
be reversed only by the explicit resume command.

The admission mutex spans the final authority check through reservation commit,
bounded credential/session setup and schema validation, each actual awaited provider
data call, and successful result commit. Checking only the earlier pre-call hook
would leave a dispatch race. A controller cannot acknowledge pause/kill while one of
those operations holds the mutex. It returns `stock_control_busy`; the operator must
wait for that admitted operation to finish and inspect/retry deliberately. There is
no blocking lock thread or automatic retry. A successful acknowledgment follows
publication, file/directory fsync, readback and lock/root identity checks. No new
operation under the old grant can then start. Issued requests cannot be retracted.

Cleanup, partial/blocked result recording and export-only monitoring remain possible
while stopped. A stopped cycle retains its full reserved call budget and cannot
publish a successful cache head. Authentication/provider exceptions retain their own
classification rather than being mislabeled as control failures.

These are cooperating same-host controls under trusted private-directory ownership.
They do not protect against a compromised owner/root or coordinated rollback of
authority files. Never switch paths, delete state or reinitialize to evade a kill.
An uncertain publication can leave either old or new valid state: no acknowledgment
is claimed, and the operator must inspect the current record rather than blindly
retrying an old compare-and-swap. The state retains the latest transition and previous
digest, not a complete historical audit. The eventual supervisor must persist the
structured command output and operational logs; that installation remains unverified.

## Explicit operator commands

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_control \
  --control-dir /absolute/private/stock-controls initialize

PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_control \
  --control-dir /absolute/private/stock-controls status
```

Inspect the returned `state_sha256`. Supply that exact observed value to each
mutation. The placeholder below is not an accepted digest:

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_control \
  --control-dir /absolute/private/stock-controls \
  --expected-state-sha256 OBSERVED_STATE_SHA256 --config-root configs resume

PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_control \
  --control-dir /absolute/private/stock-controls \
  --expected-state-sha256 OBSERVED_STATE_SHA256 pause
```

Use `kill` instead of `pause` only for a latched stop. Resume uses the same startup
identity helper as the worker: clean verified Git locally, or paired
`--image-digest` / `--image-attestation` with the existing trusted-root verifier and
full configuration match. No arbitrary hash override exists. Credentials, broker
connections and research ledgers are not opened by these commands.

Add `--control-dir /absolute/private/stock-controls` to every worker acquisition
invocation. Omitting it fails before identity or resource access. Export-only may
omit it and does not inspect controls, credentials or providers. A changed code or
policy requires an explicit new resume before another acquisition.

The dashboard's existing controls still govern only `HybridJournal`; collector
actuation is CLI-only. The dashboard displays recorded acquisition outcomes, not
authoritative current control state. Use the status command for that state. Separate
manual capture/reconstruction commands remain explicit operator tools outside this
worker's control scope; they are not an alternative scheduled collector or a bypass.

## Verification and next steps

The focused/architecture suite passed 290 tests with 96.09% combined branch coverage
over controls, control CLI, worker and job store. Local fictional tests exercise
default/paused/killed admission, code/configuration binding, stale compare-and-swap,
generation fencing, lost/replaced anchors and roots, unsafe records, operation
exceptions, publication failure, separate-process lock contention and uncertain fsync
acknowledgment. Migrated fictional-ledger tests cover pre-reservation/pre-credential
pauses, the pre-call-to-dispatch race, pause/resume between calls, cancellation and
retained budgets. Independent probes also checked pause during report compilation and
terminal commit. The child and parent use the same fictional clock; future state is
correctly denied rather than relaxed for a test. Independent review cleared the
bounded implementation. These checks do not establish deployed controls or data quality.

Next: inspect the frozen baseline, then verify immutable executing image, fixed
control-path mounts, completion-relative scheduling with hard process limits,
recorded command audit, actual scheduled collection, encrypted backups/restore and
freshness alerts. Live execution stays disabled.
