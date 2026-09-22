# Durable synthetic options trial journal

Migration `0006_options_trial_history` adds `options_trial_events` to the existing
SQLAlchemy/Alembic ledger. Development tests migrate only temporary databases. No
production database was inspected or migrated.

`OptionsTrialJournal` persists versioned, exact, synthetic `TrialJournalEvent` snapshots.
Financial values remain canonical Decimal strings in bounded JSON. Each account has a
contiguous sequence and hash chain binding account, sequence, fencing token, previous
hash and payload. Existing evidence schemas and hashes are unchanged.

Writes run within the existing SQLite `BEGIN IMMEDIATE` single-writer boundary. The
repository verifies the account's execution lease after waiting for the database lock
and again after flushing, before committing. Expiry during either boundary rolls back.
Lease release now preserves its fencing-token high-water mark instead of deleting it;
a later same-owner process cannot reuse a historical token.

Database triggers prohibit updates, deletes, replacement and row-ID replacement. Exact
duplicate event delivery returns the original receipt; a conflicting duplicate fails.
Restart reconstruction rejects altered hashes, links, sequence, event identity, malformed
payloads or invalid trial transitions. Hashes establish integrity, not authenticity or
protection from an administrator replacing the entire database and its trusted anchor.

## Non-replenishing accounting

- Each new episode starts with a positive, unconsumed reservation.
- An incomplete episode cannot reduce its reservation. Partial outcomes, pending cancels
  and incomplete settlement retain the full high-water amount.
- Completion requires the existing explicit flat, terminal-order and final-settlement/fee
  facts, together with a reconciled net cash flow.
- Completed episodes cannot be reopened or rewritten.
- Losing completed episodes consume cumulative capacity. Profitable episodes do not offset
  those losses. Changing configuration identity does not discard earlier episodes.
- Actual loss exceeding the reservation is retained, not capped. Capacity remains zero if
  historical loss exhausts the $50 ceiling.

The journal preserves these facts; it does not independently prove them. Its schema is
explicitly synthetic and is not a broker reconciliation result or live promotion artifact.
There is no deposit/reset operation. Rolling would require separately conserved episodes;
automated rolling is not implemented or authorized.

History is bounded for reconstruction and fails closed at capacity rather than dropping
old losses. Streaming reconstruction is required before supporting larger histories.
Downgrade refuses a nonempty trial table to prevent erasing economic history. Operators
must not treat code rollback as permission to remove durable evidence.

## Existing recorded replay integration

`RecordedOptionsSession` already coordinates this journal with the synthetic replay.
`start` durably reserves the episode before any simulated acceptance. `restore` verifies
the saved checkpoints against the original immutable input document and reconstructs
cash, orders and trial state. `advance` requires an explicit resume flag and the expected
event count, then atomically compares and appends one checkpoint under the journal's
lease, fencing and hash-chain rules. Every returned checkpoint remains paused.

This integration permits only one recorded script per isolated trial account. The caller
must retain the original input document; conflicting history, changed input or stale
progress stops reconstruction or advancement instead of merging state automatically.
The session never schedules the next event, creates a broker capability or submits an
order. Durable synthetic replay evidence is not a live executor or promotion artifact.

## Separate synthetic loss-history observer

`risk/options_loss_history.py` provides immutable `OptionsLossPoint` observations and
`evaluate_options_loss_history`. It reconstructs flow-adjusted daily and weekly loss,
drawdown and halt latches from the complete supplied observation tuple. Its reports are
always paused, not production-eligible and not economic evidence. Session boundaries,
liquidation marks and external flows remain synthetic fixture assertions, not
authenticated account observations.

That observer is distinct from the episode reservations and non-replenishing loss
capacity preserved by `OptionsTrialJournal`. Trial checkpoints do not persist the
observer's point history or establish its session completeness. The separate
`OptionsRiskJournal` and [offline operator rehearsal](options-risk-history.md) now
preserve and reconstruct that synthetic history; neither is a live admission path.

## Remaining lifecycle work

This is not a complete broker-connected options ledger or operating service.
`PausedOptionsMonitor` separately evaluates supplied normalized observations, includes
expiry checks, persists reconciliation results and supports bounded recurring cycles.
Its status remains paused with entries disabled; even a clean result cannot enable
trading. The provided monitoring composition is credential-free, not an authenticated
broker-connected recovery or protective-order executor.

Live options remain disabled. Authenticated lifecycle ownership, provider execution,
production recovery and live promotion remain separate blocked capabilities; neither
the trial journal, recorded replay nor synthetic loss observer unlocks them.
