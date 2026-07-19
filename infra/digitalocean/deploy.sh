#!/bin/sh
set -eu
: "${DEPLOY_HOST:?DEPLOY_HOST required}" "${TRADING_BOT_IMAGE:?digest image required}"
case "$TRADING_BOT_IMAGE" in *@sha256:*) ;; *) exit 2;; esac
ssh -o StrictHostKeyChecking=yes "${DEPLOY_USER:-tradingbot}@${DEPLOY_HOST}" sudo /usr/local/sbin/trading-bot-deploy "$TRADING_BOT_IMAGE" "${CONFIG_HASH:?required}"
