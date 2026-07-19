# Disaster recovery

Daily backups use SQLite online backup, integrity verification, SHA-256, and age encryption.
Restore on an operator workstation with `TRADING_BOT_AGE_IDENTITY_FILE`; never copy the identity
to the host. Verify integrity, retain the previous database, migrate compatibly, and restart
paused. Test restores regularly.
