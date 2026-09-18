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

## Remaining lifecycle work

This is not the complete options ledger or operating service. Normalized strategy legs,
order/fill/collateral/settlement ownership, broker reconciliation, expiry deadlines,
exercise/assignment incidents, unexpected shares, protective monitoring, recovery
composition, operational latches and continuous scheduling remain unimplemented.
The current replay still uses in-memory trial state; its production wiring to this
synthetic journal is intentionally not implied. Live options remain disabled.
