#!/bin/sh
set -eu

: "${DEPLOY_HOST:?DEPLOY_HOST required}"
: "${TRADING_BOT_IMAGE:?immutable local image ID required}"
: "${CONFIG_HASH:?CONFIG_HASH required}"

printf '%s\n' "$TRADING_BOT_IMAGE" | grep -Eq '^sha256:[0-9a-f]{64}$' || exit 2
printf '%s\n' "$CONFIG_HASH" | grep -Eq '^[0-9a-f]{64}$' || exit 2

ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
  "${DEPLOY_USER:-tradingbot}@${DEPLOY_HOST}" \
  sudo -- /usr/local/sbin/trading-bot-deploy "$TRADING_BOT_IMAGE" "$CONFIG_HASH"
