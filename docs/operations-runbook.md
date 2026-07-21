# Operations runbook

The deployable service is a health-only paused shadow process. It cannot construct broker read,
review, cancel, or place capabilities. Deployment success therefore means `/healthz` returns 200,
`/readyz` returns 503 with paused denials, and `/metrics` contains
`trading_bot_live_enabled 0.0`.

Build from the reviewed base-image reference in `.docker-base-image`, load the image onto the host,
and record its exact local OCI image ID.

`make deploy` does not bootstrap a fresh Droplet. Before the first deployment, an administrator must:

- install current Ubuntu security updates, Docker Engine, and the Docker Compose plugin;
- create key-only SSH administration and `tradingbot` accounts, disable password and direct-root
  SSH, pin the host key on the operator workstation, and grant `tradingbot` sudo access only to the
  root-owned deployment helper;
- enable a default-deny inbound firewall with SSH allowed from an operator-approved source, enable
  time synchronization and monitoring, and provision modest swap;
- install `/opt/trading-bot` as root-owned mode `0755`, its reviewed `docker-compose.yml` as
  root-owned mode `0644`, and `/usr/local/sbin/trading-bot-deploy` as root-owned mode `0755`;
- create `/var/lib/trading-bot` and `/var/log/trading-bot` as mode `0750`, owned by UID/GID 10001;
- preload the reviewed image without giving the service account Docker-group membership.

The helper rejects an unexpected Compose content hash or unsafe path ownership. It creates a
root-private release record and stores the last-good Compose and environment together for rollback.
The Terraform and cloud-init templates are not a substitute for this checklist until their complete
bootstrap path is independently validated.

On the trusted build or image host, calculate the exact container-resolved shadow configuration
hash using the same overrides as production:

```shell
TRADING_BOT_IMAGE=sha256:<64-lowercase-hex-image-id>
CONFIG_HASH="$(
  docker run --rm \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --user 10001:10001 \
    --tmpfs /tmp \
    --env LIVE_TRADING_ENABLED=false \
    --env PREDICTION_LIVE_ENABLED=false \
    --env TRADING_BOT__MONITORING__HOST=0.0.0.0 \
    --env TRADING_BOT__MONITORING__CONTAINER_LOOPBACK_PUBLISH=true \
    "$TRADING_BOT_IMAGE" config-hash --config /app/configs/shadow.yaml
)"
```

Then deploy from the trusted operator workstation:

```shell
TRADING_BOT_IMAGE=sha256:<64-lowercase-hex-image-id> \
CONFIG_HASH=<64-lowercase-hex-resolved-shadow-config-hash> \
DEPLOY_HOST=<ssh-host> \
DEPLOY_USER=tradingbot \
make deploy
```

The helper scrubs ambient Docker and Compose variables, verifies the local image identity and
resolved configuration hash, checks the fully resolved Compose image, and inspects the actual
started image. It checks bounded-time health requests, requires readiness to stay unavailable,
checks the live-disabled metric, and transactionally restores the prior image, Compose definition,
and environment on failure or interruption. The container is non-root, read-only, capability-free,
resource-limited, and publishes port 8080 only on host loopback.

Use loopback `/healthz`, `/readyz`, and `/metrics` plus `docker compose ps` for observation. Use
`make backup` and `make restore-test` only after their external storage prerequisites are reviewed.
Review reconciliation, alerts, clock synchronization, disk, heartbeat, and lease expiry before any
future resume path. No current command can resume this service or place an order. Tax exports are
records, not tax advice.
