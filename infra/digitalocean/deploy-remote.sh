#!/bin/sh
set -eu

[ "$#" -eq 2 ] || exit 2
IMAGE="$1"
CONFIG_HASH="$2"
COMPOSE_DIR=/opt/trading-bot
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
ENV_FILE="$COMPOSE_DIR/.env"
RELEASES_DIR="$COMPOSE_DIR/releases"
LAST_GOOD_POINTER="$COMPOSE_DIR/last-good"
RUNTIME_DIR=/run/trading-bot-deploy
LOCK_FILE="$RUNTIME_DIR/deploy.lock"
EXPECTED_COMPOSE_SHA256=2d6ff719e260ce3e60e5a8727fe8a3368c6301ebf6506fc1127d2f4dd07470d6
SAFE_PATH=/usr/sbin:/usr/bin:/sbin:/bin
PATH="$SAFE_PATH"
export PATH

printf '%s\n' "$IMAGE" | grep -Eq '^sha256:[0-9a-f]{64}$' || exit 2
printf '%s\n' "$CONFIG_HASH" | grep -Eq '^[0-9a-f]{64}$' || exit 2
[ "$(id -u)" -eq 0 ] || exit 2

clean_docker() {
  /usr/bin/env -i HOME=/root PATH="$SAFE_PATH" /usr/bin/docker "$@"
}

compose_with() {
  compose_env="$1"
  compose_file="$2"
  shift 2
  /usr/bin/env -i HOME=/root PATH="$SAFE_PATH" /usr/bin/docker compose \
    --project-name trading-bot \
    --project-directory "$COMPOSE_DIR" \
    --env-file "$compose_env" \
    -f "$compose_file" \
    "$@"
}

local_curl() {
  /usr/bin/env -i HOME=/root PATH="$SAFE_PATH" /usr/bin/curl \
    --disable \
    --noproxy '*' \
    --connect-timeout 2 \
    --max-time 5 \
    "$@"
}

observe_config_hash() {
  clean_docker run --rm \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --user 10001:10001 \
    --tmpfs /tmp \
    --env LIVE_TRADING_ENABLED=false \
    --env PREDICTION_LIVE_ENABLED=false \
    --env TRADING_BOT__MONITORING__HOST=0.0.0.0 \
    --env TRADING_BOT__MONITORING__CONTAINER_LOOPBACK_PUBLISH=true \
    "$1" config-hash --config /app/configs/shadow.yaml
}

validate_release_environment() (
  expected_image="$1"
  release_env="$2"
  # Accept the exact prior paused-release shape so the first no-volume release can
  # still roll back transactionally. New releases always write the two-line form.
  printf '%s\n' \
    "TRADING_BOT_IMAGE=$expected_image" \
    "TRADING_BOT_PULL_POLICY=never" \
    | cmp -s "$release_env" - \
    && exit 0
  printf '%s\n' \
    "TRADING_BOT_IMAGE=$expected_image" \
    "TRADING_BOT_PULL_POLICY=never" \
    "TRADING_BOT_STATE_DIR=/var/lib/trading-bot" \
    "TRADING_BOT_LOG_DIR=/var/log/trading-bot" \
    | cmp -s "$release_env" -
)

validate_resolved_images() (
  expected_image="$1"
  resolved_images="$2"
  printf '%s\n' "$resolved_images" \
    | awk -v expected="$expected_image" '
        BEGIN { seen = 0 }
        { seen = 1; if ($0 != expected) exit 1 }
        END { if (!seen) exit 1 }
      '
)

verify_paused_service() (
  expected_image="$1"
  compose_env="$2"
  compose_file="$3"
  container_id="$(compose_with "$compose_env" "$compose_file" ps -q trading-bot)" \
    || exit 1
  [ -n "$container_id" ] || exit 1
  started_image="$(clean_docker inspect --format '{{.Image}}' "$container_id")" \
    || exit 1
  [ "$started_image" = "$expected_image" ] || exit 1
  local_curl --fail --silent --show-error \
    http://127.0.0.1:8080/healthz >/dev/null || exit 1
  ready_status="$(local_curl --silent --output /dev/null --write-out '%{http_code}' \
    http://127.0.0.1:8080/readyz)" || exit 1
  [ "$ready_status" = "503" ] || exit 1
  local_curl --fail --silent http://127.0.0.1:8080/metrics \
    | grep -Fqx 'trading_bot_live_enabled 0.0'
)

write_last_good_pointer() {
  pointer_value="$1"
  if [ -n "$POINTER_TEMP" ]; then
    rm -f -- "$POINTER_TEMP"
    POINTER_TEMP=""
  fi
  POINTER_TEMP="$(mktemp "$COMPOSE_DIR/.last-good.XXXXXX")" || return 1
  printf '%s\n' "$pointer_value" > "$POINTER_TEMP" || return 1
  chmod 0600 "$POINTER_TEMP" || return 1
  mv "$POINTER_TEMP" "$LAST_GOOD_POINTER" || return 1
  POINTER_TEMP=""
}

TEMP_ENV=""
SNAPSHOT_DIR=""
COMPOSE_SNAPSHOT=""
RELEASE_TEMP=""
POINTER_TEMP=""
MUTATED=0
HAD_PREVIOUS=0
LAST_GOOD_COMPOSE=""
LAST_GOOD_ENV=""
LAST_GOOD_RELEASE_KEY=""
LAST_GOOD_IMAGE=""
LAST_GOOD_CONFIG_HASH=""
LAST_GOOD_COMPOSE_SHA256=""

cleanup() {
  if [ -n "$TEMP_ENV" ]; then
    rm -f -- "$TEMP_ENV"
  fi
  if [ -n "$POINTER_TEMP" ]; then
    rm -f -- "$POINTER_TEMP"
  fi
  if [ -n "$RELEASE_TEMP" ]; then
    rm -rf -- "$RELEASE_TEMP"
  fi
  if [ -n "$SNAPSHOT_DIR" ]; then
    rm -rf -- "$SNAPSHOT_DIR"
  fi
}

stop_candidate() {
  if [ -f "$ENV_FILE" ] && [ -n "$COMPOSE_SNAPSHOT" ]; then
    compose_with "$ENV_FILE" "$COMPOSE_SNAPSHOT" down || true
  fi
  clean_docker rm -f trading-bot-trading-bot-1 >/dev/null 2>&1 || true
}

rollback() {
  stop_candidate
  if [ "$HAD_PREVIOUS" -eq 1 ]; then
    if ! install -m 0644 -o root -g root "$LAST_GOOD_COMPOSE" "$COMPOSE_FILE"; then
      MUTATED=0
      return 1
    fi
    if ! install -m 0600 -o root -g root "$LAST_GOOD_ENV" "$ENV_FILE"; then
      MUTATED=0
      return 1
    fi
    if ! compose_with "$ENV_FILE" "$COMPOSE_FILE" up -d --wait --wait-timeout 60; then
      clean_docker rm -f trading-bot-trading-bot-1 >/dev/null 2>&1 || true
      MUTATED=0
      return 1
    fi
    if ! verify_paused_service "$LAST_GOOD_IMAGE" "$ENV_FILE" "$COMPOSE_FILE"; then
      clean_docker rm -f trading-bot-trading-bot-1 >/dev/null 2>&1 || true
      MUTATED=0
      return 1
    fi
    if ! write_last_good_pointer "$LAST_GOOD_RELEASE_KEY"; then
      MUTATED=0
      return 1
    fi
  else
    rm -f -- "$ENV_FILE"
    rm -f -- "$LAST_GOOD_POINTER"
  fi
  MUTATED=0
}

on_signal() {
  trap '' HUP INT TERM
  if [ "$MUTATED" -eq 1 ]; then
    rollback || true
  fi
  exit 2
}

trap cleanup EXIT
trap on_signal HUP INT TERM

[ ! -L /opt ] || exit 2
[ "$(stat -c '%u:%g:%a' /opt)" = "0:0:755" ] || exit 2
[ -d "$COMPOSE_DIR" ] && [ ! -L "$COMPOSE_DIR" ] || exit 2
[ "$(stat -c '%u:%g:%a' "$COMPOSE_DIR")" = "0:0:755" ] || exit 2
[ -f "$COMPOSE_FILE" ] && [ ! -L "$COMPOSE_FILE" ] || exit 2
[ "$(stat -c '%u:%g:%a' "$COMPOSE_FILE")" = "0:0:644" ] || exit 2
[ -d /var/lib/trading-bot ] && [ ! -L /var/lib/trading-bot ] || exit 2
[ "$(stat -c '%u:%g:%a' /var/lib/trading-bot)" = "10001:10001:750" ] || exit 2
[ -d /var/log/trading-bot ] && [ ! -L /var/log/trading-bot ] || exit 2
[ "$(stat -c '%u:%g:%a' /var/log/trading-bot)" = "10001:10001:750" ] || exit 2
if [ -e "$ENV_FILE" ]; then
  [ -f "$ENV_FILE" ] && [ ! -L "$ENV_FILE" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$ENV_FILE")" = "0:0:600" ] || exit 2
fi

if [ -e "$RUNTIME_DIR" ]; then
  [ -d "$RUNTIME_DIR" ] && [ ! -L "$RUNTIME_DIR" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$RUNTIME_DIR")" = "0:0:700" ] || exit 2
else
  install -d -m 0700 -o root -g root "$RUNTIME_DIR"
fi
if [ -e "$RELEASES_DIR" ]; then
  [ -d "$RELEASES_DIR" ] && [ ! -L "$RELEASES_DIR" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$RELEASES_DIR")" = "0:0:700" ] || exit 2
else
  install -d -m 0700 -o root -g root "$RELEASES_DIR"
fi
exec 9>"$LOCK_FILE"
flock -n 9 || exit 2

SNAPSHOT_DIR="$(mktemp -d "$RUNTIME_DIR/snapshot.XXXXXX")"
chmod 0700 "$SNAPSHOT_DIR"
COMPOSE_SNAPSHOT="$SNAPSHOT_DIR/docker-compose.yml"
install -m 0600 -o root -g root "$COMPOSE_FILE" "$COMPOSE_SNAPSHOT"
ACTUAL_COMPOSE_SHA256="$(sha256sum "$COMPOSE_SNAPSHOT" | awk '{print $1}')"
[ "$ACTUAL_COMPOSE_SHA256" = "$EXPECTED_COMPOSE_SHA256" ] || exit 2

if [ -e "$LAST_GOOD_POINTER" ]; then
  [ -f "$LAST_GOOD_POINTER" ] && [ ! -L "$LAST_GOOD_POINTER" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$LAST_GOOD_POINTER")" = "0:0:600" ] || exit 2
  LAST_GOOD_RELEASE_KEY="$(sed -n '1p' "$LAST_GOOD_POINTER")"
  printf '%s\n' "$LAST_GOOD_RELEASE_KEY" \
    | grep -Eq '^[0-9a-f]{64}-[0-9a-f]{64}-[0-9a-f]{64}$' || exit 2
  [ "$(wc -l < "$LAST_GOOD_POINTER")" -eq 1 ] || exit 2
  LAST_GOOD_IMAGE_HEX="${LAST_GOOD_RELEASE_KEY%%-*}"
  LAST_GOOD_REMAINDER="${LAST_GOOD_RELEASE_KEY#*-}"
  LAST_GOOD_CONFIG_HASH="${LAST_GOOD_REMAINDER%%-*}"
  LAST_GOOD_COMPOSE_SHA256="${LAST_GOOD_REMAINDER##*-}"
  LAST_GOOD_IMAGE="sha256:$LAST_GOOD_IMAGE_HEX"
  LAST_GOOD_DIR="$RELEASES_DIR/$LAST_GOOD_RELEASE_KEY"
  [ -d "$LAST_GOOD_DIR" ] && [ ! -L "$LAST_GOOD_DIR" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$LAST_GOOD_DIR")" = "0:0:700" ] || exit 2
  LAST_GOOD_COMPOSE="$LAST_GOOD_DIR/docker-compose.yml"
  LAST_GOOD_ENV="$LAST_GOOD_DIR/deployment.env"
  [ -f "$LAST_GOOD_COMPOSE" ] && [ ! -L "$LAST_GOOD_COMPOSE" ] || exit 2
  [ -f "$LAST_GOOD_ENV" ] && [ ! -L "$LAST_GOOD_ENV" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$LAST_GOOD_COMPOSE")" = "0:0:600" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$LAST_GOOD_ENV")" = "0:0:600" ] || exit 2
  [ "$(sha256sum "$LAST_GOOD_COMPOSE" | awk '{print $1}')" \
    = "$LAST_GOOD_COMPOSE_SHA256" ] || exit 2
  validate_release_environment "$LAST_GOOD_IMAGE" "$LAST_GOOD_ENV" || exit 2
  ACTUAL_LAST_GOOD_IMAGE_ID="$(clean_docker image inspect --format '{{.Id}}' \
    "$LAST_GOOD_IMAGE")"
  [ "$ACTUAL_LAST_GOOD_IMAGE_ID" = "$LAST_GOOD_IMAGE" ] || exit 2
  OBSERVED_LAST_GOOD_CONFIG_HASH="$(observe_config_hash "$LAST_GOOD_IMAGE")"
  [ "$OBSERVED_LAST_GOOD_CONFIG_HASH" = "$LAST_GOOD_CONFIG_HASH" ] || exit 2
  HAD_PREVIOUS=1
fi
if [ -e "$ENV_FILE" ] && [ "$HAD_PREVIOUS" -ne 1 ]; then
  exit 2
fi

ACTUAL_IMAGE_ID="$(clean_docker image inspect --format '{{.Id}}' "$IMAGE")"
[ "$ACTUAL_IMAGE_ID" = "$IMAGE" ] || exit 2

OBSERVED_CONFIG_HASH="$(observe_config_hash "$IMAGE")"
[ "$OBSERVED_CONFIG_HASH" = "$CONFIG_HASH" ] || exit 2

umask 077
TEMP_ENV="$(mktemp "$COMPOSE_DIR/.env.XXXXXX")"
printf '%s\n' \
  "TRADING_BOT_IMAGE=$IMAGE" \
  "TRADING_BOT_PULL_POLICY=never" \
  > "$TEMP_ENV"
chmod 0600 "$TEMP_ENV"

RELEASE_KEY="${IMAGE#sha256:}-$CONFIG_HASH-$EXPECTED_COMPOSE_SHA256"
CANDIDATE_DIR="$RELEASES_DIR/$RELEASE_KEY"
if [ -e "$CANDIDATE_DIR" ]; then
  [ -d "$CANDIDATE_DIR" ] && [ ! -L "$CANDIDATE_DIR" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$CANDIDATE_DIR")" = "0:0:700" ] || exit 2
  [ -f "$CANDIDATE_DIR/docker-compose.yml" ] \
    && [ ! -L "$CANDIDATE_DIR/docker-compose.yml" ] || exit 2
  [ -f "$CANDIDATE_DIR/deployment.env" ] \
    && [ ! -L "$CANDIDATE_DIR/deployment.env" ] || exit 2
  [ "$(stat -c '%u:%g:%a' "$CANDIDATE_DIR/docker-compose.yml")" = "0:0:600" ] \
    || exit 2
  [ "$(stat -c '%u:%g:%a' "$CANDIDATE_DIR/deployment.env")" = "0:0:600" ] \
    || exit 2
  [ "$(sha256sum "$CANDIDATE_DIR/docker-compose.yml" | awk '{print $1}')" \
    = "$EXPECTED_COMPOSE_SHA256" ] || exit 2
  cmp -s "$TEMP_ENV" "$CANDIDATE_DIR/deployment.env" || exit 2
else
  RELEASE_TEMP="$(mktemp -d "$RELEASES_DIR/.candidate.XXXXXX")"
  chmod 0700 "$RELEASE_TEMP"
  install -m 0600 -o root -g root "$COMPOSE_SNAPSHOT" \
    "$RELEASE_TEMP/docker-compose.yml"
  install -m 0600 -o root -g root "$TEMP_ENV" "$RELEASE_TEMP/deployment.env"
  mv "$RELEASE_TEMP" "$CANDIDATE_DIR"
  RELEASE_TEMP=""
fi

MUTATED=1
if ! mv "$TEMP_ENV" "$ENV_FILE"; then
  MUTATED=0
  exit 2
fi
TEMP_ENV=""

if ! RESOLVED_IMAGES="$(compose_with "$ENV_FILE" "$COMPOSE_SNAPSHOT" config --images)"; then
  rollback || true
  exit 2
fi
if ! validate_resolved_images "$IMAGE" "$RESOLVED_IMAGES"; then
  rollback || true
  exit 2
fi
if ! compose_with "$ENV_FILE" "$COMPOSE_SNAPSHOT" up -d --wait --wait-timeout 60; then
  rollback || true
  exit 2
fi
if ! verify_paused_service "$IMAGE" "$ENV_FILE" "$COMPOSE_SNAPSHOT"; then
  rollback || true
  exit 2
fi

if ! write_last_good_pointer "$RELEASE_KEY"; then
  rollback || true
  exit 2
fi
MUTATED=0
