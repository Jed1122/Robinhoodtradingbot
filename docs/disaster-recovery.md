# Disaster recovery

Daily backups use SQLite online backup, integrity verification, SHA-256, and age encryption.
Restore on an operator workstation with `TRADING_BOT_AGE_IDENTITY_FILE`; never copy the identity
to the host. Verify integrity, retain the previous database, migrate compatibly, and restart
paused. Test restores regularly.

The ledger backup includes append-only promotion observations and aggregate promotion decisions.
A restore preserves that history but does not renew expired attestations, make an ineligible
observation eligible, merge different account/provider/strategy/config/code identities, or grant
live authority. OAuth state is credential material and is not part of the ledger backup; back it up
and restore it only through a separately reviewed credential-management procedure.
