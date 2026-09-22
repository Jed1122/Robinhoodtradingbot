# Options encrypted-backup validation

`tests/deployment/test_encrypted_backup_roundtrip.py` exercises the existing
`infra/digitalocean/backup.sh` and `restore.sh` helpers with fresh, temporary SQLite
and content-addressed synthetic research artifacts. It creates ephemeral age identities
with mode `0600`; tests never print their contents. No account, cloud resource, network
download, or deployment is used by the tests.

## Local prerequisite and execution

The tests do not download or install cryptographic software. They require executable
`age` and `age-keygen` binaries already available on `PATH`, or absolute local paths in
`TRADING_BOT_TEST_AGE_BIN` and `TRADING_BOT_TEST_AGE_KEYGEN_BIN`. When neither is
available, pytest skips the integration tests rather than pretending that encryption
was exercised. On macOS, the test process sets `COPYFILE_DISABLE=1` so BSD `tar` does
not add AppleDouble `._` metadata entries that the archive verifier intentionally
rejects; this is a local test-harness accommodation, not a deployment configuration.

Run with the repository's pinned interpreter exposed as `python` to the shell helpers:

```shell
TRADING_BOT_TEST_AGE_BIN=/absolute/path/to/age \
TRADING_BOT_TEST_AGE_KEYGEN_BIN=/absolute/path/to/age-keygen \
uv run pytest tests/deployment/test_encrypted_backup_roundtrip.py -q
uv run ruff check tests/deployment/test_encrypted_backup_roundtrip.py
```

## What this verifies

- the backup helper produces age ciphertext from a SQLite online backup and a valid
  synthetic research report;
- the restore helper decrypts and validates it, reports `service remains --paused`,
  and does not overwrite the source database;
- an independent age decryption opens the archive without extracting it, accepts only the
  expected `ledger.db` and content-addressed research member names, and compares recovered
  SQLite row, research bytes, and SHA-256 to the original synthetic inputs;
- a different identity, truncated ciphertext, and altered ciphertext fail closed, with
  the source database unchanged; source database and ciphertext modes are asserted as
  `0600`.

## Limits

This is local script coverage, not backup or deployment readiness evidence. It does not
prove a scheduled/off-host backup, retention, operator key custody, a host restore,
alert delivery, a running options process, or any cloud-account configuration. The
current archive contains the SQLite ledger and JSON research artifacts; it omits options
replay input and Parquet artifacts. It also does not demonstrate schema rollback, so a
successful archive validation is not evidence that a future schema can be safely
downgraded.
