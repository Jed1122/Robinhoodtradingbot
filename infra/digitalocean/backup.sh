#!/bin/sh
set -eu
: "${TRADING_BOT_AGE_RECIPIENT_FILE:?required}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
sqlite3 "${TRADING_BOT_DATABASE:-/var/lib/trading-bot/evidence/ledger.db}" ".backup '$tmp/ledger.db'"
test "$(sqlite3 "$tmp/ledger.db" 'PRAGMA integrity_check')" = ok
sha256sum "$tmp/ledger.db" > "$tmp/ledger.db.sha256"
age -R "$TRADING_BOT_AGE_RECIPIENT_FILE" -o "${BACKUP_OUTPUT:-ledger.db.age}" "$tmp/ledger.db"
