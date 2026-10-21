#!/bin/sh
# Run only after operator review on the existing host. Never calls the paused-service helper.
set -eu
[ "$(id -u)" = 0 ] || exit 2
[ "$#" = 2 ] || exit 2
archive=$1
expected=$2
printf '%s\n' "$expected" | grep -Eq '^[0-9a-f]{64}$' || exit 2
[ -f "$archive" ] && [ ! -L "$archive" ] || exit 2
[ "$(sha256sum "$archive" | cut -d ' ' -f1)" = "$expected" ] || exit 2
root=/opt/hybrid-paper
state=/var/lib/hybrid-paper
private_root() {
    [ ! -L "$1" ] || exit 2
    [ -d "$1" ] || install -d -m 0700 -o root -g root "$1"
    [ "$(stat -c '%u:%g:%a' "$1")" = '0:0:700' ] || exit 2
}
for path in /opt /var /var/lib; do
    [ -d "$path" ] && [ ! -L "$path" ] || exit 2
    [ "$(stat -c '%u:%g:%a' "$path")" = '0:0:755' ] || exit 2
done
if [ -e "$root" ]; then
    [ ! -L "$root" ] && [ -f "$root/.hybrid-paper-owned" ] || exit 2
    [ ! -L "$root/.hybrid-paper-owned" ] || exit 2
    [ "$(stat -c '%u:%g:%a' "$root/.hybrid-paper-owned")" = '0:0:600' ] || exit 2
else
    install -d -m 0700 -o root -g root "$root"
    install -m 0600 /dev/null "$root/.hybrid-paper-owned"
fi
private_root "$root"
private_root "$root/releases"
exec 9>"$root/deploy.lock"
flock -n 9 || exit 2
if [ -e "$state" ] || [ -L "$state" ]; then
    [ -d "$state" ] && [ ! -L "$state" ] || exit 2
    [ "$(stat -c '%u:%g:%a' "$state")" = '10001:10001:700' ] || exit 2
    [ -f "$root/current" ] && [ ! -L "$root/current" ] || exit 2
else
    install -d -m 0700 -o 10001 -g 10001 "$state"
fi
release="$root/releases/$expected"
[ ! -e "$release" ] && [ ! -L "$release" ] || exit 2
install -d -m 0700 "$release"
# Restrict tar entries to regular files/directories and safe relative names.
python3 - "$archive" "$release" <<'PY'
import pathlib, sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
            raise SystemExit('Unsafe source archive')
    archive.extractall(sys.argv[2], filter='data')
PY
base=$(cat "$release/.docker-base-image")
printf '%s\n' "$base" | grep -Eq '^python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}$' || exit 2
[ -f "$release/dashboard/dist/index.html" ] || exit 2
[ -f "$release/src/trading_bot/hybrid/cli.py" ] || exit 2
# Classic builders ignore per-Dockerfile ignore files. Normalize only this isolated
# extracted release to the same reviewed allowlist; never change the existing app.
[ -f "$release/Dockerfile.hybrid.dockerignore" ] || exit 2
install -m 0600 "$release/Dockerfile.hybrid.dockerignore" "$release/.dockerignore"
# No registry publication. Build dependencies/base may be downloaded within existing host capacity.
/usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin docker build \
    --build-arg "PYTHON_BASE_IMAGE=$base" --iidfile "$release/image" \
    -f "$release/Dockerfile.hybrid" "$release"
clean_docker() {
    /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin docker "$@"
}
image=$(cat "$release/image")
printf '%s\n' "$image" | grep -Eq '^sha256:[0-9a-f]{64}$' || exit 2
[ "$(clean_docker image inspect --format '{{.Id}}' "$image")" = "$image" ] || exit 2
compose() {
    compose_release=$1
    compose_image=$2
    shift 2
    /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin HYBRID_IMAGE="$compose_image" \
        docker compose --project-name hybrid-paper --project-directory "$root/releases/$compose_release" \
        --env-file /dev/null -f "$root/releases/$compose_release/compose.hybrid.yml" "$@"
}
previous=''
if [ -e "$root/current" ]; then
    [ ! -L "$root/current" ] && [ "$(stat -c '%u:%g:%a' "$root/current")" = '0:0:600' ] || exit 2
    previous=$(cat "$root/current")
    printf '%s\n' "$previous" | grep -Eq '^[0-9a-f]{64}$' || exit 2
    [ -d "$root/releases/$previous" ] && [ ! -L "$root/releases/$previous" ] || exit 2
    previous_image=$(cat "$root/releases/$previous/image")
    printf '%s\n' "$previous_image" | grep -Eq '^sha256:[0-9a-f]{64}$' || exit 2
else
    # Refuse adoption/replacement of any unknown pre-existing project container.
    [ -z "$(clean_docker ps -aq --filter label=com.docker.compose.project=hybrid-paper)" ] || exit 2
    compose "$expected" "$image" run --rm --no-deps hybrid-paper \
        --state-dir /state --config-root /app/configs init
fi
rollback() {
    if [ -n "$previous" ]; then
        compose "$previous" "$previous_image" up -d --wait --wait-timeout 60 || true
    else
        compose "$expected" "$image" down || true
    fi
}
trap 'rollback; exit 2' HUP INT TERM
if ! compose "$expected" "$image" up -d --wait --wait-timeout 60; then
    rollback
    exit 2
fi
container=$(compose "$expected" "$image" ps -q hybrid-paper)
if [ "$(clean_docker inspect --format '{{.Image}}' "$container")" != "$image" ]; then
    rollback
    exit 2
fi
if ! python3 "$release/infra/hybrid/probe.py"; then
    rollback
    exit 2
fi
[ ! -L "$root/previous" ] && [ ! -L "$root/current.next" ] || { rollback; exit 2; }
umask 077
printf '%s\n' "$previous" > "$root/previous"
printf '%s\n' "$expected" > "$root/current.next"
mv "$root/current.next" "$root/current"
trap - HUP INT TERM
printf 'Hybrid candidate passed bounded startup checks; live remains disabled.\n'
