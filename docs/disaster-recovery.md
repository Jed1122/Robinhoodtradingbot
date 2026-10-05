# Disaster recovery

Daily backups use SQLite online backup, integrity verification, SHA-256, and age encryption. The
encrypted `evidence.tar` payload contains both `ledger.db` and private content-addressed research
reports, including their cleaned bar snapshots and complete data-manifest preimages. Restore
verification checks the database, report hash, manifest hash, and snapshot-to-manifest binding.
Restore on an operator workstation with `TRADING_BOT_AGE_IDENTITY_FILE`; never copy the identity
to the host. Verify integrity, retain the previous database, migrate compatibly, and restart
paused. Test restores regularly.

The evidence backup includes append-only promotion observations and aggregate promotion decisions.
A restore preserves that history but does not renew expired attestations, make an ineligible
observation eligible, merge different account/provider/strategy/config/code identities, or grant
live authority. OAuth state is credential material and is not part of the ledger backup; back it up
and restore it only through a separately reviewed credential-management procedure.

## Forward-paper diagnostic owner

The new `etf-forward-paper-owner-v1` filesystem namespace is separate from the
deployment ledger/research backup above and is **not included** by that backup script.
Preserve its complete private directory, original typed `ForwardPaperTape`, and the
independently retained latest head together. A cash snapshot or journal alone is not
sufficient to reconstruct economic/risk history or authenticate the supplied inputs.
Do not delete incomplete claims, invent a head, or reset the owner to resume work.

`recover_forward_paper` verifies all prefixes and returns paused state without admitting
new cycles. Missing/corrupt commits, a mismatched head or unresolved claim deny recovery;
retain the original files for incident review. A complete publication with an uncertain
response may be verified by an exact retry. Single-host exclusion does not prevent
complete host rollback or a compromised same-UID writer. Local separate-process and
SIGKILL tests do not constitute a deployed-host, encrypted-backup or rollback drill.
