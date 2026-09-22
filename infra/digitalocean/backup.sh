#!/bin/sh
set -eu
: "${TRADING_BOT_AGE_RECIPIENT_FILE:?required}"
umask 077
database="${TRADING_BOT_DATABASE:-/var/lib/trading-bot/evidence/ledger.db}"
research="${TRADING_BOT_RESEARCH_ARTIFACT_DIR:-/var/lib/trading-bot/evidence/research}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/payload" "$tmp/payload/research"
sqlite3 "$database" ".backup '$tmp/payload/ledger.db'"
test "$(sqlite3 "$tmp/payload/ledger.db" 'PRAGMA integrity_check')" = ok
if test -d "$research"; then
  if find "$research" -mindepth 1 -maxdepth 1 ! -type f -print -quit | grep -q .; then
    echo "research artifact directory contains a non-regular entry" >&2
    exit 1
  fi
  for artifact in "$research"/*.json; do
    test -e "$artifact" || continue
    cp -p "$artifact" "$tmp/payload/research/"
  done
fi
tar -C "$tmp/payload" -cf "$tmp/evidence.tar" ledger.db research
python scripts/verify_restore.py "$tmp/evidence.tar"
sha256sum "$tmp/evidence.tar" > "$tmp/evidence.tar.sha256"
age -R "$TRADING_BOT_AGE_RECIPIENT_FILE" \
  -o "${BACKUP_OUTPUT:-evidence.tar.age}" "$tmp/evidence.tar"
