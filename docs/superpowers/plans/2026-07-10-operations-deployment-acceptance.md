# Operations, Deployment, and Acceptance Implementation Plan

> Historical planning snapshot from 2026-07-10. For current implementation and operational
> status, see the repository README and `docs/final-implementation-report.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the system observable, operable, securely deployable, recoverable, fully documented, and able to record—but never fabricate—the staged evidence required for live promotion.

**Architecture:** A host-loopback-only read API exposes health and metrics but no trading controls. Operator mutations stay in audited CLI commands; the container is non-root/read-only, Terraform provisions a restricted 1 GB DigitalOcean Droplet, and encrypted backups plus promotion evidence are verified independently of live trading.

**Tech Stack:** FastAPI 0.139.0, Uvicorn 0.51.0, Prometheus Client 0.25.0, Typer 0.26.8, Docker 29+, Docker Compose, Terraform 1.15.8, DigitalOcean provider 2.95.0, Ubuntu 26.04 LTS (`ubuntu-26-04-x64`), CycloneDX BOM 7.3.0.

## Global Constraints

- Local execution binds the administrative HTTP service to `127.0.0.1`. The container may listen on `0.0.0.0:8080` only under the verified Compose profile that publishes exactly `127.0.0.1:8080:8080`; the host-facing service remains loopback-only and read-only.
- No HTTP route can activate live mode, clear the kill switch, place/cancel an order, or expose secrets/account identifiers.
- Metrics labels contain no account IDs, symbols from untrusted payloads, or secret values.
- Webhook alerts pass through centralized redaction and are optional.
- First deployment starts paused; deployment scripts cannot generate authorization artifacts.
- The service runs non-root with a read-only root filesystem and only declared writable volumes.
- SSH uses keys only, root login/password auth are disabled, and inbound SSH is restricted to required CIDRs.
- No database or admin port is public; administration uses SSH tunnel/VPN/private connection.
- Terraform state, cloud-init, deployment logs, and backups contain no broker secrets.
- Database backups are encrypted, checksummed, retained, and restore-tested; credential files are excluded.
- Promotion gates are evidence evaluations, not mode switches; mandatory durations and clearances are non-overridable.
- Automated tests and CI never submit or cancel a real order and never provision cloud resources.
- All documentation distinguishes implemented, verified, locked, unsupported, and externally pending capabilities.
- No profitability claim is made.

---

### Task 1: Implement health and readiness models

**Files:**
- Create: `src/trading_bot/monitoring/__init__.py`
- Create: `src/trading_bot/monitoring/health.py`
- Create: `src/trading_bot/monitoring/readiness.py`
- Test: `tests/unit/monitoring/test_health.py`
- Test: `tests/unit/monitoring/test_readiness.py`

**Interfaces:**
- Produces: `HealthCheckResult`, `HealthSnapshot`, `ReadinessSnapshot`, `HealthService.snapshot`, and `ReadinessService.snapshot`.
- Consumes: the locked-live `LivePreflightResult`; it does not define a second set of live gates.

- [ ] **Step 1: Write failing fail-closed readiness tests**

```python
@pytest.mark.parametrize(
    "mutation",
    [stale_market_data, failed_broker_health, dirty_reconciliation, active_kill_switch, expired_live_lease],
)
def test_live_readiness_fails_on_mandatory_gate(mutation: ReadinessMutation) -> None:
    snapshot = ReadinessService().snapshot(mutation(ready_context()))
    assert not snapshot.ready
    assert snapshot.denials
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/monitoring/test_health.py tests/unit/monitoring/test_readiness.py -q`

Expected: FAIL with missing monitoring models.

- [ ] **Step 3: Implement liveness versus mode readiness**

```python
@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    name: str
    healthy: bool
    reason_code: str
    observed_at: datetime
    details: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    mode: ExecutionMode
    ready: bool
    checks: tuple[HealthCheckResult, ...]
    observed_at: datetime
```

Health covers process, event loop, database, disk, and clock. Readiness continuously reruns the same shared check functions used to create `LivePreflightResult`, then adds mode-specific market data, broker, reconciliation, capability, authorization, risk self-test, alert, kill-switch, and lease status. There is no `LiveReadiness` class or duplicate threshold table. Paused is reported explicitly rather than treated as live-ready.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/unit/monitoring/test_health.py tests/unit/monitoring/test_readiness.py -q`

Expected: PASS.

```bash
git add src/trading_bot/monitoring tests/unit/monitoring
git commit -m "feat: add fail-closed health and readiness"
```

### Task 2: Add host-loopback-only health, readiness, and metrics API

**Files:**
- Create: `src/trading_bot/monitoring/metrics.py`
- Create: `src/trading_bot/monitoring/api.py`
- Test: `tests/integration/monitoring/test_api.py`
- Test: `tests/architecture/test_admin_api_read_only.py`

**Interfaces:**
- Produces: `build_monitoring_app(health, readiness, metrics) -> FastAPI`.
- Produces: `AdminBindPolicy.validate(host, container_loopback_publish) -> None`.
- Exposes: `GET /healthz`, `GET /readyz`, and `GET /metrics` only.

- [ ] **Step 1: Write failing API and route-surface tests**

```python
def test_admin_api_has_only_read_routes(client: TestClient) -> None:
    paths = {(route.path, method) for route in client.app.routes for method in route.methods or set()}
    assert not {(path, method) for path, method in paths if method not in {"GET", "HEAD", "OPTIONS"}}
    assert {"/healthz", "/readyz", "/metrics"} <= {path for path, _ in paths}

def test_unready_returns_503(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 503
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/monitoring/test_api.py tests/architecture/test_admin_api_read_only.py -q`

Expected: FAIL with missing API.

- [ ] **Step 3: Implement read-only endpoints and safe metrics**

Metrics include uptime; last successful market data, broker health, and reconciliation; database health; account equity/cash without account labels; gross/crypto exposure; daily/weekly P&L; drawdown; open/unknown orders; API errors/rate limits; clock drift; memory/CPU/disk; restarts; kill switch; activation and live-lease expiry.

```python
def build_monitoring_app(
    health: HealthService, readiness: ReadinessService, metrics: MetricsRegistry
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> JSONResponse: ...

    @app.get("/readyz")
    async def readyz() -> JSONResponse: ...

    @app.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics() -> str: ...

    return app
```

- [ ] **Step 4: Add the exact bind-address guard**

`AdminBindPolicy` accepts `127.0.0.1` for ordinary local execution. It accepts `0.0.0.0` only when `container_loopback_publish=True`; every other host fails startup. The default is `127.0.0.1:8080`. Deployment tests in Task 7 require the container profile to set the flag and publish exactly `127.0.0.1:8080:8080`; no other host mapping is accepted.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/integration/monitoring/test_api.py tests/architecture/test_admin_api_read_only.py -q`

Expected: PASS.

```bash
git add src/trading_bot/monitoring/metrics.py src/trading_bot/monitoring/api.py tests/integration/monitoring/test_api.py tests/architecture/test_admin_api_read_only.py
git commit -m "feat: add read-only monitoring API"
```

### Task 3: Implement redacted webhook alerts and heartbeat

**Files:**
- Create: `src/trading_bot/monitoring/alerts.py`
- Create: `src/trading_bot/monitoring/heartbeat.py`
- Test: `tests/unit/monitoring/test_alerts.py`
- Test: `tests/integration/monitoring/test_webhook.py`
- Test: `tests/integration/monitoring/test_heartbeat.py`

**Interfaces:**
- Produces: `Alert`, `AlertSink`, `WebhookAlertSink`, `HeartbeatService.tick`, and `AlertType` for every required event.

- [ ] **Step 1: Write failing redaction and deduplication tests**

```python
@pytest.mark.asyncio
async def test_webhook_never_receives_secret(alert_sink: WebhookHarness) -> None:
    await alert_sink.send(alert(details={"x-api-key": "secret", "account_id": "RHC1234567"}))
    body = alert_sink.requests[0].json
    assert "secret" not in json.dumps(body)
    assert "RHC1234567" not in json.dumps(body)

@pytest.mark.asyncio
async def test_repeated_alerts_are_deduplicated(alert_service: AlertService) -> None:
    await alert_service.emit(stale_data_alert())
    await alert_service.emit(stale_data_alert())
    assert alert_service.sink.calls == 1
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/monitoring/test_alerts.py tests/integration/monitoring/test_webhook.py tests/integration/monitoring/test_heartbeat.py -q`

Expected: FAIL with missing alert services.

- [ ] **Step 3: Implement alert types and safe delivery**

Include process start/stop, live activation/deactivation, order submitted/rejected/partial/fill, failed cancellation, broker disagreement, stale data, account restriction, drawdown, kill switch, auth failure, database error, repeated API failure, and unexpected restart. Webhook retries are safe because alerts are idempotent and cannot trade; bound retry count and timeout in config.

- [ ] **Step 4: Persist heartbeat and restart detection**

Heartbeat records process ID, instance ID, mode, runtime state, code/config hash, and UTC time. Startup emits unexpected-restart alert when the prior heartbeat ended without a clean shutdown event.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/monitoring/test_alerts.py tests/integration/monitoring/test_webhook.py tests/integration/monitoring/test_heartbeat.py -q`

Expected: PASS.

```bash
git add src/trading_bot/monitoring/alerts.py src/trading_bot/monitoring/heartbeat.py tests/unit/monitoring/test_alerts.py tests/integration/monitoring/test_webhook.py tests/integration/monitoring/test_heartbeat.py
git commit -m "feat: add redacted alerts and heartbeat"
```

### Task 4: Implement scheduler cadence and single-leader orchestration

**Files:**
- Create: `src/trading_bot/runtime/scheduler.py`
- Create: `src/trading_bot/runtime/daemon.py`
- Modify: `src/trading_bot/cli/main.py`
- Test: `tests/unit/runtime/test_scheduler.py`
- Test: `tests/integration/runtime/test_daemon.py`
- Test: `tests/chaos/runtime/test_overlapping_runs.py`

**Interfaces:**
- Produces: `Schedule`, `ScheduledJob`, `Scheduler.run`, `RunCoordinator.try_start`, `DaemonApplication.run`, `build_daemon_application`, and the complete `trader run` lifecycle.

- [ ] **Step 1: Write failing cadence and overlap tests**

```python
def test_crypto_reconciliation_defaults_to_sixty_seconds() -> None:
    assert default_schedule().job("crypto_reconcile").interval == timedelta(seconds=60)

@pytest.mark.asyncio
async def test_second_instance_cannot_submit(harness: TwoInstanceHarness) -> None:
    await harness.first.acquire()
    assert not (await harness.second.try_start()).acquired
    assert harness.second.place_calls == 0

@pytest.mark.asyncio
async def test_paused_daemon_serves_health_but_runs_no_decision_cycle(
    daemon: DaemonHarness,
) -> None:
    await daemon.start(paused=True)
    assert (await daemon.get("/healthz")).status_code == 200
    assert daemon.decision_cycles == 0
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/runtime/test_scheduler.py tests/integration/runtime/test_daemon.py tests/chaos/runtime/test_overlapping_runs.py -q`

Expected: FAIL with missing scheduler.

- [ ] **Step 3: Implement intentional schedules**

Default equity reconciliation is 60 seconds while active and less frequent outside sessions; equity signals are daily/research-approved; Crypto reconciliation is 60 seconds; Crypto signals are four-hour/daily; risk runs around execution and heartbeat; reports/backups are daily; security reports are weekly.

- [ ] **Step 4: Enforce lease fencing on each job**

Each job has unique run ID and account-scoped fencing token. A stale owner cannot write after takeover. Jobs record start/end/result and skip overlap rather than spawning duplicates.

`build_daemon_application` composes exactly one selected mode runner, paused startup recovery, health/readiness/metrics server, heartbeat, scheduler, lease coordinator, and shutdown coordinator. `trader run --config PATH --mode MODE --paused` is the container/host entrypoint. Paused startup serves health and records heartbeats but schedules no decision or broker-write job. `SIGTERM` invokes the durable shutdown sequence. The daemon never calls an operator signing function and never changes a promotion decision into authorization.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/runtime/test_scheduler.py tests/integration/runtime/test_daemon.py tests/chaos/runtime/test_overlapping_runs.py -q`

Expected: PASS.

```bash
git add src/trading_bot/runtime/scheduler.py src/trading_bot/runtime/daemon.py src/trading_bot/cli/main.py tests/unit/runtime/test_scheduler.py tests/integration/runtime/test_daemon.py tests/chaos/runtime/test_overlapping_runs.py
git commit -m "feat: add fenced runtime scheduler"
```

### Task 5: Add operational reports and CLI commands

**Files:**
- Create: `src/trading_bot/reporting/incident.py`
- Create: `src/trading_bot/reporting/tax.py`
- Create: `src/trading_bot/reporting/llm.py`
- Create: `src/trading_bot/cli/status.py`
- Create: `src/trading_bot/cli/kill_switch.py`
- Modify: `src/trading_bot/cli/main.py`
- Test: `tests/unit/reporting/test_incident.py`
- Test: `tests/unit/reporting/test_tax.py`
- Test: `tests/unit/reporting/test_llm_isolation.py`
- Test: `tests/integration/cli/test_operations.py`

**Interfaces:**
- Produces CLI: `status`, `pause`, `resume`, `reconcile`, `positions`, `open-orders`, `proposed-orders`, `explain-last-decision`, `export-journal`, `export-tax-records`, `activate-kill-switch`, `clear-kill-switch`, and `generate-incident-report`.

- [ ] **Step 1: Write failing CLI and report tests**

```python
def test_clear_kill_switch_requires_reason(cli: CliRunner) -> None:
    result = cli.invoke(app, ["clear-kill-switch", "--acknowledge", CLEAR_ACK])
    assert result.exit_code != 0
    assert "reason" in result.stdout

def test_tax_export_marks_missing_basis_unknown() -> None:
    row = build_tax_rows((fill_without_basis(),))[0]
    assert row.cost_basis_status == "unknown"

def test_tax_export_keeps_account_reference_out_of_console(cli: CliRunner, tmp_path: Path) -> None:
    output = tmp_path / "tax-records.json"
    result = cli.invoke(app, ["export-tax-records", "--output", str(output)])
    assert result.exit_code == 0
    assert full_account_reference() in output.read_text()
    assert full_account_reference() not in result.stdout
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/reporting tests/integration/cli/test_operations.py -q`

Expected: FAIL with missing reports/commands.

- [ ] **Step 3: Implement deterministic incident and tax reports**

Incident report includes trigger, timeline, code/config/data hashes, account masked, orders/transitions/fills, reconciliation, alerts, health, operator actions, and unresolved items. `export-tax-records` writes operator-selected canonical CSV/JSON mode `0600` with full broker account reference, fill IDs, order IDs, instrument, side, quantity, time, price, fees, and available basis/lot reference; console/log output masks the account and prints only path/hash/row count. The export states it is not tax advice.

- [ ] **Step 4: Enforce LLM isolation**

`ReadOnlyLlmReporter` accepts `RedactedReport`, is disabled by default, has daily/monthly token counters, holds no broker/secret/execution reference, and falls back to local deterministic text. Architecture tests reject imports from `brokers`, `execution`, or `authorization.signing`.

- [ ] **Step 5: Implement audited operations CLI**

Mutating commands require exact acknowledgement, nonempty reason, current reconciliation, and appropriate authorization. HTTP remains read-only. Mask all account identifiers except last four.

- [ ] **Step 6: Run and commit**

Run: `uv run pytest tests/unit/reporting tests/integration/cli/test_operations.py -q`

Expected: PASS.

```bash
git add src/trading_bot/reporting src/trading_bot/cli tests/unit/reporting tests/integration/cli/test_operations.py
git commit -m "feat: add audited operator reports and CLI"
```

### Task 6: Implement promotion evidence without automatic activation

**Files:**
- Create: `src/trading_bot/monitoring/promotion.py`
- Modify: `src/trading_bot/runtime/live.py`
- Test: `tests/unit/monitoring/test_promotion.py`
- Test: `tests/property/monitoring/test_promotion_invariants.py`
- Test: `tests/integration/monitoring/test_evidence_ledger.py`
- Test: `tests/integration/runtime/test_promotion_wiring.py`

**Interfaces:**
- Produces: `PromotionStage`, `PromotionEvidence`, `PromotionDecision`, `PromotionEvaluator.evaluate`, and `EvidenceLedger`.

- [ ] **Step 1: Write failing non-overridable gate tests**

```python
@pytest.mark.parametrize(
    "mutation",
    [only_29_days, only_99_observations, dirty_reconciliation, critical_security_finding, missing_acknowledgement],
)
def test_normal_live_gate_cannot_be_overridden(mutation: EvidenceMutation) -> None:
    decision = PromotionEvaluator().evaluate(mutation(valid_normal_evidence()))
    assert not decision.eligible
    assert not decision.override_allowed
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/monitoring/test_promotion.py tests/property/monitoring/test_promotion_invariants.py tests/integration/monitoring/test_evidence_ledger.py tests/integration/runtime/test_promotion_wiring.py -q`

Expected: FAIL with missing promotion evaluator.

- [ ] **Step 3: Implement stage evidence**

Simulation requires full tests/replay/security/failure injection. Paper requires 100 unique complete cycles tied to accepted strategy/config/code evidence. Shadow requires seven calendar days, the same accepted strategy evidence, authenticated reads, validated live data, accurate simulation, and zero unexplained drift. Micro requires manual authorization, configured caps, alerts, ten-order reviews, and unknown-state pause. Normal requires 30 combined days, 100 observations, clean reconciliation/security, acceptable slippage/drawdown, and renewed acknowledgement.

A valid observation is one unique scheduled strategy decision cycle with complete input/data/code/config hashes, all risk results, execution or explicit no-trade outcome, and clean end-of-cycle reconciliation. Fixture, replay, duplicate, incomplete, dirty-code, rejected-strategy, and manually repeated cycles do not count. A calendar day counts once per UTC date only when it contains at least one valid eligible cycle; wall-clock passage alone does not create evidence.

- [ ] **Step 4: Ensure evaluator cannot activate modes**

`PromotionDecision` contains `eligible`, reasons, and evidence hash only. It has no broker, config mutation, authorization, or runtime control method.

Convert an eligible decision to a short-lived, signed-or-locally-attested `PromotionAttestation` keyed to the current evidence hash and requested stage. Wire the live composition root to require this attestation in addition to authorization. Integration tests prove missing, expired, wrong-stage, or changed-evidence attestations keep the place factory uncalled. Evaluator output never calls `enable-live`, mutates config, creates a lease, or starts the runtime.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/monitoring/test_promotion.py tests/property/monitoring/test_promotion_invariants.py tests/integration/monitoring/test_evidence_ledger.py tests/integration/runtime/test_promotion_wiring.py -q`

Expected: PASS.

```bash
git add src/trading_bot/monitoring/promotion.py src/trading_bot/runtime/live.py tests/unit/monitoring/test_promotion.py tests/property/monitoring/test_promotion_invariants.py tests/integration/monitoring/test_evidence_ledger.py tests/integration/runtime/test_promotion_wiring.py
git commit -m "feat: add non-activating promotion evidence"
```

### Task 7: Build a hardened non-root container and Compose service

**Files:**
- Create: `Dockerfile`
- Generate and review: `.docker-base-image`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Create: `scripts/healthcheck.py`
- Create: `scripts/verify_base_image.py`
- Test: `tests/deployment/test_compose.py`
- Test: `tests/deployment/test_container_security.py`

**Interfaces:**
- Produces container command `trader run --config /etc/trading-bot/base.yaml --mode shadow --paused` and local healthcheck.

- [ ] **Step 1: Write failing static hardening tests**

```python
def test_compose_is_read_only_and_non_root() -> None:
    service = load_compose()["services"]["trading-bot"]
    assert service["read_only"] is True
    assert service["user"] not in {"0", "root"}
    assert service["cap_drop"] == ["ALL"]
    assert service["ports"] == ["127.0.0.1:8080:8080"]
    assert service["environment"]["TRADING_BOT__MONITORING__CONTAINER_LOOPBACK_PUBLISH"] == "true"
    assert service["mem_limit"] == "768m"
    assert service["cpus"] == "0.75"
    assert service["pids_limit"] == 256
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/deployment/test_compose.py tests/deployment/test_container_security.py -q`

Expected: FAIL with missing container files.

- [ ] **Step 3: Implement multi-stage container**

```dockerfile
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE} AS builder
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.28 \
    && uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_BASE_IMAGE} AS runtime
RUN groupadd --system --gid 10001 tradingbot && useradd --system --uid 10001 --gid tradingbot tradingbot
WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY scripts/healthcheck.py /app/scripts/healthcheck.py
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "-m", "trading_bot.cli.main"]
CMD ["run", "--config", "/etc/trading-bot/base.yaml", "--mode", "shadow", "--paused"]
```

Resolve the official `python:3.12-slim-bookworm` multi-architecture digest during this task with `docker buildx imagetools inspect`, store as the sole line of `.docker-base-image` a reviewed reference matching `^python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}$`, and have `scripts/verify_base_image.py` reject tags, malformed digests, or a repository other than the official Python image. Docker builds pass the exact file value through the `PYTHON_BASE_IMAGE` build argument; the Dockerfile has no unpinned base default.

Compose uses `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`, tmpfs `/tmp`, `mem_limit: 768m`, `cpus: 0.75`, `pids_limit: 256`, `init: true`, `stop_grace_period: 45s`, restart `unless-stopped`, container listen host `0.0.0.0`, exact host publish `127.0.0.1:8080:8080`, and declared config/data/log volumes. It sets `TRADING_BOT__MONITORING__CONTAINER_LOOPBACK_PUBLISH=true`; a deployment test rejects wildcard or non-loopback host publication. Secrets mount read-only from host paths outside Git.

- [ ] **Step 4: Build and inspect**

Run:

```bash
docker compose config --quiet
uv run python scripts/verify_base_image.py .docker-base-image
docker build --build-arg PYTHON_BASE_IMAGE="$(cat .docker-base-image)" -t trading-bot:test .
uv run pytest tests/deployment/test_compose.py tests/deployment/test_container_security.py -q
```

Expected: build and tests pass; image default is paused.

- [ ] **Step 5: Commit container files**

```bash
git add Dockerfile .docker-base-image docker-compose.yml .dockerignore scripts/healthcheck.py scripts/verify_base_image.py tests/deployment
git commit -m "build: add hardened paused container"
```

### Task 8: Add DigitalOcean Terraform with restricted networking

**Files:**
- Create: `infra/digitalocean/versions.tf`
- Create: `infra/digitalocean/variables.tf`
- Create: `infra/digitalocean/main.tf`
- Create: `infra/digitalocean/firewall.tf`
- Create: `infra/digitalocean/monitoring.tf`
- Create: `infra/digitalocean/outputs.tf`
- Generate: `infra/digitalocean/.terraform.lock.hcl`
- Test: `tests/deployment/test_terraform.py`

**Interfaces:**
- Provisions one `s-1vcpu-1gb` Droplet using a required immutable DigitalOcean image ID whose inspected slug is `ubuntu-26-04-x64`, plus Cloud Firewall, monitoring, alerts, and required SSH CIDRs.
- Reads DO token only from `DIGITALOCEAN_TOKEN`; no token variable enters state.

- [ ] **Step 1: Write failing Terraform-policy tests**

```python
def test_terraform_has_no_open_ssh_cidr() -> None:
    text = read_all_tf()
    assert "0.0.0.0/0" not in inbound_ssh_blocks(text)
    assert "::/0" not in inbound_ssh_blocks(text)

def test_trusted_cidrs_have_no_default() -> None:
    variables = parse_tf_variables()
    assert "default" not in variables["trusted_ssh_cidrs"]
    assert "default" not in variables["droplet_image_id"]
    assert "default" not in variables["droplet_image_slug"]
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/deployment/test_terraform.py -q`

Expected: FAIL with missing Terraform.

- [ ] **Step 3: Pin Terraform/provider versions**

```hcl
terraform {
  required_version = ">= 1.15.8, < 2.0.0"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "2.95.0"
    }
  }
}

provider "digitalocean" {}
```

- [ ] **Step 4: Implement required variables and resources**

Require `region`, `ssh_key_fingerprints`, `trusted_ssh_cidrs`, backup alert email/webhook metadata, `droplet_image_id`, and `droplet_image_slug`; neither image value has a default. A data lookup/precondition verifies that the supplied immutable ID currently resolves to slug `ubuntu-26-04-x64`. Default only size `s-1vcpu-1gb`. Enable monitoring and graceful shutdown. Firewall permits inbound SSH only from configured CIDRs and no public app/database/admin ports. Outbound allows DNS, NTP, and HTTPS; document that L3 firewall cannot enforce HTTPS destination domains.

- [ ] **Step 5: Add CPU/memory/disk/restart/heartbeat alerts**

Use DigitalOcean monitoring alert resources where supported and application heartbeat webhook for process-specific alerting.

- [ ] **Step 6: Validate without applying**

Run:

```bash
terraform -chdir=infra/digitalocean fmt -check
terraform -chdir=infra/digitalocean init -backend=false
terraform -chdir=infra/digitalocean validate
uv run pytest tests/deployment/test_terraform.py -q
```

Expected: PASS. Do not run `terraform apply`.

- [ ] **Step 7: Commit Terraform**

```bash
git add infra/digitalocean/*.tf infra/digitalocean/.terraform.lock.hcl tests/deployment/test_terraform.py
git commit -m "infra: add restricted DigitalOcean Terraform"
```

### Task 9: Add cloud-init and paused deployment workflow

**Files:**
- Create: `infra/digitalocean/cloud-init.yaml.tftpl`
- Create: `infra/digitalocean/deploy.sh`
- Create: `infra/digitalocean/deploy-remote.sh`
- Modify: `infra/digitalocean/main.tf`
- Test: `tests/deployment/test_cloud_init.py`
- Test: `tests/deployment/test_deploy_script.py`

**Interfaces:**
- Creates non-root service user, UTC/NTP, 1 GB swap, Docker/Compose, monitoring, log rotation, restricted directories, and paused service.

- [ ] **Step 1: Write failing hardening tests**

```python
def test_cloud_init_disables_root_and_password_ssh() -> None:
    config = render_cloud_init()
    assert "PermitRootLogin no" in config
    assert "PasswordAuthentication no" in config
    assert "Automatic-Reboot \"false\"" in config

def test_deploy_script_never_enables_live() -> None:
    script = "\n".join(
        Path(path).read_text()
        for path in ("infra/digitalocean/deploy.sh", "infra/digitalocean/deploy-remote.sh")
    )
    assert "enable-live" not in script
    assert "--paused" in script

def test_host_and_container_ids_match() -> None:
    config = render_cloud_init()
    service = load_compose()["services"]["trading-bot"]
    assert "uid: 10001" in config
    assert "gid: 10001" in config
    assert service["user"] == "10001:10001"
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/deployment/test_cloud_init.py tests/deployment/test_deploy_script.py -q`

Expected: FAIL with missing cloud-init/deploy script.

- [ ] **Step 3: Implement host hardening**

Set timezone UTC; enable systemd-timesyncd; create group/user `tradingbot` with fixed GID/UID `10001`; create `/var/lib/trading-bot`, `/var/lib/trading-bot/locks`, `/var/log/trading-bot`, `/etc/trading-bot`, and `/var/backups/trading-bot` owned by `10001:10001`; create 1 GB swap; install Docker Engine/Compose and backup tools; configure unattended security upgrades with no automatic reboot; set SSH hardening; install logrotate; ensure secrets are not in cloud-init. Rendered cloud-init and Compose tests must prove the IDs match so bind-mounted paths are writable only by the non-root container identity.

- [ ] **Step 4: Implement workstation and remote deployment boundaries**

`infra/digitalocean/deploy.sh` runs only on the operator workstation. It requires `DEPLOY_HOST`, `DEPLOY_USER` (default `tradingbot`), immutable `TRADING_BOT_IMAGE` including digest, and a local canonical config hash. It uses `ssh` with strict host-key checking and passes only image digest/config hash arguments—never broker secrets—to the already installed `/usr/local/sbin/trading-bot-deploy` helper. It verifies `/healthz` through an SSH-local command and reports masked host metadata.

`infra/digitalocean/deploy-remote.sh` is installed by cloud-init as root-owned mode `0755` at `/usr/local/sbin/trading-bot-deploy`. It verifies expected directory ownership and config hash, pins the prior image for rollback, runs `docker compose pull`, runs migrations in a one-shot container with trading paused and no place capability, then `docker compose up -d` using `trader run ... --paused`. It polls `http://127.0.0.1:8080/healthz`, leaves runtime paused, and restores the prior pinned image on failed health. Neither script copies secret material, provisions infrastructure, signs authorization, or resumes trading.

- [ ] **Step 5: Run and commit**

Run:

```bash
bash -n infra/digitalocean/deploy.sh infra/digitalocean/deploy-remote.sh
uv run pytest tests/deployment/test_cloud_init.py tests/deployment/test_deploy_script.py -q
```

Expected: PASS; no deployment occurs.

```bash
git add infra/digitalocean/cloud-init.yaml.tftpl infra/digitalocean/deploy.sh infra/digitalocean/deploy-remote.sh infra/digitalocean/main.tf tests/deployment
git commit -m "infra: add hardened paused host bootstrap"
```

### Task 10: Implement encrypted backup and restore verification

**Files:**
- Create: `infra/digitalocean/backup.sh`
- Create: `infra/digitalocean/restore.sh`
- Create: `scripts/verify_restore.py`
- Test: `tests/deployment/test_backup_restore.py`

**Interfaces:**
- Daily online SQLite backup, SHA-256, age encryption to operator public key, optional rclone upload, 30-daily retention, and restore integrity check.

- [ ] **Step 1: Write failing exclusion and restore tests**

```python
def test_backup_archive_excludes_secrets(tmp_path: Path) -> None:
    result = run_backup_fixture(tmp_path)
    names = list_encrypted_archive_names(result, test_age_identity())
    assert not any("secret" in name or ".env" in name or "private" in name for name in names)

def test_restore_runs_integrity_check(tmp_path: Path) -> None:
    restored = restore_fixture(valid_encrypted_backup(), tmp_path)
    assert sqlite_integrity_check(restored.database) == "ok"
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/deployment/test_backup_restore.py -q`

Expected: FAIL with missing scripts.

- [ ] **Step 3: Implement safe online backup**

Use SQLite `.backup` to a temporary restricted file, include canonical nonsecret config/version manifest, run `PRAGMA integrity_check`, create checksum, encrypt with the public key read from `TRADING_BOT_AGE_RECIPIENT_FILE`, upload only encrypted data through `TRADING_BOT_RCLONE_CONFIG_FILE` to `TRADING_BOT_BACKUP_REMOTE`, remove plaintext temporary files with trap cleanup, and retain 30 daily archives. Never include broker/authorization signing keys, API credentials, `.env`, tokens, or live artifacts.

- [ ] **Step 4: Implement paused restore**

`restore.sh` is operator-side. Require the remote service stopped/paused, verify encrypted checksum, obtain `TRADING_BOT_AGE_IDENTITY_FILE` only on the operator restore workstation, decrypt to a local mode-`0600` temp file, run integrity check, and stream it over strict-host-key SSH to a remote restricted temp path without copying the identity. The remote restore phase preserves the current database for rollback, restores atomically, runs migrations only after compatibility check, and leaves service paused. Trap cleanup removes both plaintext temporary files.

- [ ] **Step 5: Run and commit**

Run:

```bash
bash -n infra/digitalocean/backup.sh infra/digitalocean/restore.sh
uv run pytest tests/deployment/test_backup_restore.py -q
```

Expected: PASS using temporary local directories only.

```bash
git add infra/digitalocean/backup.sh infra/digitalocean/restore.sh scripts/verify_restore.py tests/deployment/test_backup_restore.py
git commit -m "infra: add encrypted backup and restore testing"
```

### Task 11: Complete CI, coverage, security scans, and SBOM

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `scripts/generate_sbom.py`
- Modify: `Makefile`
- Test: `tests/smoke/test_make_targets.py`
- Test: `tests/smoke/test_sbom_reproducible.py`
- Test: `tests/architecture/test_ci_no_live_secrets.py`

**Interfaces:**
- Produces all required Make targets and `docs/sbom.cdx.json`.

- [ ] **Step 1: Write failing Make/CI tests**

```python
REQUIRED_TARGETS = {
    "setup", "format", "lint", "typecheck", "test", "test-unit", "test-integration",
    "test-chaos", "security", "backtest", "simulate", "paper", "shadow", "live-preflight",
    "build", "deploy", "status", "logs", "backup", "restore-test",
}

def test_makefile_has_every_required_target() -> None:
    assert REQUIRED_TARGETS <= parse_make_targets(Path("Makefile"))
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/smoke/test_make_targets.py tests/smoke/test_sbom_reproducible.py tests/architecture/test_ci_no_live_secrets.py -q`

Expected: FAIL until targets/workflow are complete.

- [ ] **Step 3: Implement CI matrix and thresholds**

CI runs Python 3.12/3.13/3.14 lint, strict MyPy, unit/property/integration/replay/chaos, 90% branch thresholds for risk/state-machine, 80% overall, Bandit, pip-audit, lock check, Docker build/security assertions, Terraform validate, backup/restore test, and CycloneDX SBOM. Authenticated tests are never selected and no live secret names are configured. Every third-party GitHub Action is pinned to a reviewed full commit SHA; an architecture test rejects mutable tags such as `@v4`, branch names, or short SHAs.

Complete the operational targets with these exact bodies (keep the mode targets from Plans 3–5):

```make
.PHONY: setup test test-unit test-integration test-chaos build deploy status logs backup restore-test

setup:
	uv sync --all-groups --frozen

test:
	uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80

test-unit:
	uv run pytest tests/unit tests/property -q

test-integration:
	uv run pytest tests/integration tests/replay tests/architecture tests/deployment -q

test-chaos:
	uv run pytest tests/chaos -q

build:
	uv run python scripts/verify_base_image.py .docker-base-image
	docker build --build-arg PYTHON_BASE_IMAGE="$$(cat .docker-base-image)" -t "$${TRADING_BOT_IMAGE:-trading-bot:local}" .

deploy:
	@test -n "$${TRADING_BOT_IMAGE:-}" || (echo "TRADING_BOT_IMAGE is required" >&2; exit 2)
	@test -n "$${DEPLOY_HOST:-}" || (echo "DEPLOY_HOST is required" >&2; exit 2)
	./infra/digitalocean/deploy.sh

status:
	uv run trader status

logs:
	docker compose logs --tail=200 trading-bot

backup:
	./infra/digitalocean/backup.sh

restore-test:
	uv run pytest tests/deployment/test_backup_restore.py -q
```

`deploy` is a workstation-side orchestrator for an already provisioned host, always starts the image with `--paused`, and never runs `terraform apply`, `enable-live`, `resume`, or an authorization-signing command. `restore-test` uses temporary fixture data and never touches the configured production database.

- [ ] **Step 4: Generate and normalize a reproducible SBOM**

```python
def main() -> int:
    Path("docs").mkdir(exist_ok=True)
    with TemporaryDirectory() as directory:
        raw_path = Path(directory) / "raw.cdx.json"
        subprocess.run(
            ["cyclonedx-py", "environment", "--output-format", "JSON", "--output-file", str(raw_path)],
            check=True,
            env={**os.environ, "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH", "0")},
        )
        document = json.loads(raw_path.read_text())
    document.pop("serialNumber", None)
    document.get("metadata", {}).pop("timestamp", None)
    document["components"] = sorted(
        document.get("components", []), key=lambda item: (item.get("purl", ""), item.get("bom-ref", ""))
    )
    for dependency in document.get("dependencies", []):
        dependency["dependsOn"] = sorted(dependency.get("dependsOn", []))
    document["dependencies"] = sorted(
        document.get("dependencies", []), key=lambda item: item.get("ref", "")
    )
    Path("docs/sbom.cdx.json").write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return 0
```

Run the generator twice in the same locked environment and assert byte equality; validate the normalized document against CycloneDX JSON rules. The script records the lockfile SHA-256 in metadata properties and rejects an unlocked environment, so removal of nondeterministic serial/timestamp fields does not hide dependency drift.

- [ ] **Step 5: Run and commit**

Run:

```bash
uv run pytest tests/smoke/test_make_targets.py tests/smoke/test_sbom_reproducible.py tests/architecture/test_ci_no_live_secrets.py -q
make lint
make typecheck
make test
make security
uv run python scripts/generate_sbom.py
```

Expected: all pass and SBOM validates as JSON.

```bash
git add .github/workflows/ci.yml scripts/generate_sbom.py Makefile docs/sbom.cdx.json tests/smoke/test_make_targets.py tests/smoke/test_sbom_reproducible.py tests/architecture/test_ci_no_live_secrets.py
git commit -m "ci: enforce quality security and SBOM gates"
```

### Task 12: Complete runbooks, README, and final implementation report

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/capability-matrix.md`
- Create: `docs/risk-policy.md`
- Create: `docs/live-activation.md`
- Create: `docs/threat-model.md`
- Create: `docs/incident-response.md`
- Create: `docs/disaster-recovery.md`
- Create: `docs/operations-runbook.md`
- Modify: `docs/limitations.md`
- Create: `docs/final-implementation-report.md`
- Test: `tests/smoke/test_documentation.py`

**Interfaces:**
- Documents exact setup, environment names, MCP/Crypto connection, all modes, preflight, micro-live activation syntax, kill switch, deployment, monitoring, backup, restore, rollback, incident, tax export, limitations, and external pending gates.

- [ ] **Step 1: Write failing documentation completeness test**

```python
def test_required_docs_and_disclosures_exist() -> None:
    for path in REQUIRED_DOCS:
        text = Path(path).read_text()
        assert "profit" in text.lower() or path not in PROFIT_DISCLOSURE_DOCS
    final = Path("docs/final-implementation-report.md").read_text()
    assert "No live order was placed during development" in final
    assert "prediction-market live execution: unsupported" in final.lower()
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/smoke/test_documentation.py -q`

Expected: FAIL until documents are complete.

- [ ] **Step 3: Write exact operational documentation**

Include daily/weekly review, rejection, unknown order, broker/data outage, auth failure, drawdown breach, reboot, restore, credential rotation, rollback, local setup, official MCP command, Crypto API setup, all env names, every Make/CLI command, SSH tunnel access, Terraform plan/apply procedure, backup/restore, and manual rollback. Never include a secret value.

- [ ] **Step 4: Write threat model and limitations candidly**

Cover credential theft, malicious dependency, compromised Droplet, unauthorized activation, prompt/data/log injection, replay, duplicate submission, DB corruption, stale authorization, account substitution, DoS, clock attack, small-account economics, hosting/data cost, latency, slippage, model/regime/overfit risk, taxes, state/account eligibility, and unsupported prediction API.

- [ ] **Step 5: Generate evidence-backed final report**

Record repository tree, architecture, exact commands/env names, tests, coverage, scans, SBOM, capability matrix, unresolved limitations, deployment validation, and external evidence gates. Mark only commands actually run as passed. State no live prediction execution and no live order during development. Do not claim cloud deployment if `terraform apply` was not separately authorized and performed.

- [ ] **Step 6: Run documentation and repository verification**

Run:

```bash
uv run pytest tests/smoke/test_documentation.py -q
make lint
make typecheck
make test
make security
make backtest
make simulate
make paper
make shadow-smoke
set +e
make live-preflight
status=$?
set -e
test "$status" -eq 2
make build
make restore-test
terraform -chdir=infra/digitalocean validate
git diff --check
```

Expected: all offline checks pass; live preflight exits exactly `2` and reports locked/not ready without authorization; no cloud mutation or broker write occurs.

- [ ] **Step 7: Commit documentation and final report**

```bash
git add README.md docs tests/smoke/test_documentation.py docs/sbom.cdx.json
git commit -m "docs: complete operations and implementation report"
test -z "$(git status --short)"
```

## Final Code-Complete Gate

All six implementation plans are committed and their checks pass. The final report distinguishes code-complete from externally pending account access, authenticated MCP evidence, DigitalOcean apply, paper/shadow elapsed time, and separately authorized micro-live evidence. Normal-live remains locked. Prediction live remains unsupported. No real broker write or cloud provisioning occurred without separate explicit authorization.
