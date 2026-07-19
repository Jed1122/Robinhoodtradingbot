#!/bin/sh
set -eu
IMAGE="$1"; CONFIG_HASH="$2"; : "$CONFIG_HASH"
docker compose pull
docker compose up -d --wait
docker compose exec trading-bot trader run --config /etc/trading-bot/base.yaml --mode shadow --paused
curl --fail http://127.0.0.1:8080/healthz
