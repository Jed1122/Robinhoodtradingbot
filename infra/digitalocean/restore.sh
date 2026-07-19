#!/bin/sh
set -eu
: "${TRADING_BOT_AGE_IDENTITY_FILE:?required}"
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"
age -d -i "$TRADING_BOT_AGE_IDENTITY_FILE" -o "$tmp" "$1"
python scripts/verify_restore.py "$tmp"
echo "restore verified; service remains --paused"
