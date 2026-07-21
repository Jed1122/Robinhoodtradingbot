# Operations runbook

The default deployable service is a health-only paused process. It cannot construct broker read,
review, cancel, or place capabilities. Default deployment success therefore means `/healthz`
returns 200, `/readyz` returns 503 with paused denials, and `/metrics` contains
`trading_bot_live_enabled 0.0`. It has no host volumes and cannot access OAuth credentials, the
account fingerprint, or the promotion-evidence ledger.

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
- install the complete `/var/lib/trading-bot/oauth` credential directory only through the reviewed
  credential procedure, with mode `0700` and UID/GID 10001;
- create `/var/lib/trading-bot/evidence` as mode `0750`, owned by UID/GID 10001, for
  `/var/lib/trading-bot/evidence/ledger.db`;
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

`make deploy` starts and validates only that default paused service. It does not authorize OAuth,
run the connected profile, append promotion evidence, or activate trading.

## OAuth bootstrap and locally write-incapable connected probe

Run browser authorization on a trusted operator workstation, not on the headless host:

```shell
umask 077
mkdir -p "$HOME/.local/share/robinhood-trading-bot"
chmod 700 "$HOME/.local/share/robinhood-trading-bot"
test ! -e "$HOME/.local/share/robinhood-trading-bot/oauth"
PYTHONPATH=src uv run trader mcp-oauth-bootstrap \
  --oauth-store "$HOME/.local/share/robinhood-trading-bot/oauth" \
  --account-fingerprint-file \
    "$HOME/.local/share/robinhood-trading-bot/oauth/account-fingerprint"
```

Complete the Robinhood browser flow that returns to `127.0.0.1:18765`. The OAuth client requests and
pins Robinhood's sole official `internal` scope. That scope is not read-only; its bearer credential
must be treated as trading-capable. The command verifies the seven read declarations and one active
individual cash Agentic account. It first stages encrypted token and client state, the encryption
key, and a SHA-256 account fingerprint inside a private temporary directory, then atomically commits
the complete directory to `$HOME/.local/share/robinhood-trading-bot/oauth`. The parent must be
service-owned mode `0700` or stricter and the destination must be absent. The bootstrap client never
invokes review, place, or cancel because of local code controls, not because of broker scope.

Treat the entire OAuth directory, including `oauth-store.key`, as a trading credential. A stolen
token or compromised host could trade in the Agentic account using another client. Installing
it on a Droplet requires a separately reviewed credential-transfer procedure; do not paste it into
chat, logs, environment variables, Git, image layers, or shell arguments. On the host, the final
OAuth directory must be owned by `10001:10001` with mode `0700`, every file in it must be a regular
file owned by `10001:10001` with mode `0600`, and its fingerprint must be
`/var/lib/trading-bot/oauth/account-fingerprint`. The evidence directory must be owned by
`10001:10001` with mode `0750`; the ledger path is
`/var/lib/trading-bot/evidence/ledger.db` and remains inside the encrypted backup scope.

After the credential installation has been reviewed and completed, an administrator with Docker
access may run exactly one profile-gated probe from the deployment directory:

```shell
docker compose --profile connected-shadow run --rm --no-deps connected-shadow
```

The profile publishes no port, never restarts, retains the non-root, read-only-filesystem, and
Linux-capability-free container restrictions, and sets both live flags false. An SDK-session
allowlist and an independent transport allowlist permit only the seven reviewed reads, and no
review/place/cancel adapter is constructed. Those local controls make this client write-incapable;
the OAuth token remains trading-capable. Its successful sanitized status is
`connected_shadow_nonpromotable`; hashes may be recorded, but no provider values should appear. A
failure exits nonzero with a generic message.

The present probe records a durable but ineligible shadow observation because strategy eligibility
and complete outcomes are not yet established. Without a probe symbol, market data is also marked
incomplete. It is connection evidence, not qualifying promotion evidence, and it cannot activate
live trading. Qualifying evidence must eventually match the exact account, provider declarations,
strategy, config, and image code identities. Production thresholds are 100 eligible paper cycles,
seven distinct UTC shadow dates, and—before normal live—at least 100 eligible combined
paper/shadow/micro observations across 30 distinct UTC dates, at least one micro-live observation,
and current micro-review, security-clearance, manual-acknowledgement, runtime-control, slippage,
and drawdown evidence. The micro-review summary must match the configured interval and cover every
completed ten-order boundary.
Normal-live evaluation retains the paper and shadow prerequisites. Normal-live observations never
add progress, but their latest dirty state blocks re-promotion; a clean normal-live observation
also cannot mask dirty qualifying paper, shadow, or micro evidence.

Use loopback `/healthz`, `/readyz`, and `/metrics` plus `docker compose ps` for observation. Use
`make backup` and `make restore-test` only after their external storage prerequisites are reviewed.
Review reconciliation, alerts, clock synchronization, disk, heartbeat, and lease expiry before any
future resume path. No current application composition can resume live trading or place an order.
Tax exports are records, not tax advice.
