# Robinhood Multi-Asset Trading System Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete approved Robinhood multi-asset trading system through independently testable, fail-closed vertical slices.

**Architecture:** Broker-neutral domain, strategy, portfolio, risk, execution, reconciliation, and persistence code sits behind narrow protocols. Official Robinhood transports remain in adapters; live placement capability is injected only after signed authorization, while read and cancel-only recovery capabilities remain separately constrained.

**Tech Stack:** Python 3.12–3.14, Pydantic 2.13.4, SQLAlchemy 2.0.51, Alembic 1.18.5, HTTPX 0.28.1, MCP Python SDK 1.28.1 (`<2`), PyNaCl 1.6.2, FastAPI 0.139.0, Typer 0.26.8, Structlog 26.1.0, Pytest 9.1.1, Hypothesis 6.156.6, Ruff 0.15.21, MyPy 2.2.0, Docker, Terraform 1.15.8, DigitalOcean provider 2.95.0, Ubuntu 26.04 LTS.

## Global Constraints

- Python requires `>=3.12,<3.15`; CI runs 3.12, 3.13, and 3.14.
- All money, quantity, price, fee, percentage, and profit/loss arithmetic uses `Decimal`, never binary floating point.
- Every timestamp is timezone-aware UTC.
- The default process state is paused and unable to submit live orders.
- No live order is placed during implementation, tests, deployment, or demonstration.
- Only official Robinhood MCP, official Robinhood Crypto API, and officially documented data interfaces are permitted.
- Options, futures, margin, leverage, shorts, OTC securities, microcaps, leveraged ETFs, inverse ETFs, martingale, averaging down, and hidden size escalation remain prohibited.
- `PREDICTION_LIVE_ENABLED` is false and live prediction methods always fail closed.
- An environment variable alone can never activate live trading.
- All thresholds are validated configuration; `configs/safety-envelope.yaml` cannot be weakened through mode, environment, or CLI overrides.
- Micro-live defaults remain $5 per order, $20 gross exposure, and two new orders per UTC day.
- Normal-live promotion requires non-overridable elapsed evidence, reconciliation clearance, security clearance, and renewed manual acknowledgement.
- Structured logs redact secrets before serialization and contain no private keys, signatures, authorization headers, or signed artifacts.
- CI has no live broker credentials and no network route to a broker write path.
- Risk and order-state modules require at least 90% branch coverage; the repository requires at least 80% overall coverage.
- Code, docs, logs, and comments make no profitability claim.

---

## Plan Set and Required Order

Execute the plans in this exact order. Each plan ends in a green, reviewable repository state and a commit before the next begins.

1. [`2026-07-10-capability-foundation.md`](./2026-07-10-capability-foundation.md)
   - Packaging, dependency lock, canonical types, configuration, capability evidence, logging, and baseline CI.
2. [`2026-07-10-safety-persistence-kernel.md`](./2026-07-10-safety-persistence-kernel.md)
   - Durable ledger, append-only audit, risk, state machine, authorization, kill switch, reconciliation, and recovery.
3. [`2026-07-10-research-simulation-paper.md`](./2026-07-10-research-simulation-paper.md)
   - Market-data validation, strategies, backtest/replay, simulated broker, research reports, and offline modes.
4. [`2026-07-10-robinhood-adapters-shadow.md`](./2026-07-10-robinhood-adapters-shadow.md)
   - Official MCP and Crypto read adapters, schema drift gates, prediction refusal, and shadow mode.
5. [`2026-07-10-live-execution-reconciliation.md`](./2026-07-10-live-execution-reconciliation.md)
   - Reviewed live placement code, deduplication, partial fills, cancel-only recovery, locked live orchestration, and chaos tests.
6. [`2026-07-10-operations-deployment-acceptance.md`](./2026-07-10-operations-deployment-acceptance.md)
   - Health, metrics, alerts, operator CLI, hardened container, DigitalOcean, backups, docs, promotion evidence, and final verification.

Do not start a later plan to work around a failing gate in an earlier plan.

## Target Repository Map

This map shows primary implementation files. Package `__init__.py` files, generated sanitized fixtures, individual tests, and migration revision filenames are omitted here but specified exactly in the owning task.

```text
.
├── Codex.md
├── README.md
├── Makefile
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── Dockerfile
├── .docker-base-image
├── docker-compose.yml
├── alembic.ini
├── configs/
│   ├── safety-envelope.yaml
│   ├── base.yaml
│   ├── backtest.yaml
│   ├── simulation.yaml
│   ├── paper.yaml
│   ├── shadow.yaml
│   ├── micro_live.yaml
│   └── normal_live.yaml
├── docs/
│   ├── architecture.md
│   ├── capability-matrix.md
│   ├── implementation-plan.md
│   ├── threat-model.md
│   ├── risk-policy.md
│   ├── strategy-research.md
│   ├── live-activation.md
│   ├── incident-response.md
│   ├── disaster-recovery.md
│   ├── operations-runbook.md
│   ├── limitations.md
│   ├── final-implementation-report.md
│   ├── sbom.cdx.json
│   └── superpowers/
├── infra/digitalocean/
│   ├── versions.tf
│   ├── .terraform.lock.hcl
│   ├── variables.tf
│   ├── main.tf
│   ├── firewall.tf
│   ├── monitoring.tf
│   ├── outputs.tf
│   ├── cloud-init.yaml.tftpl
│   ├── deploy.sh
│   ├── deploy-remote.sh
│   ├── backup.sh
│   └── restore.sh
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── scripts/
│   ├── capture_mcp_capabilities.py
│   ├── healthcheck.py
│   ├── verify_base_image.py
│   ├── run_backtest.py
│   ├── run_simulation.py
│   ├── run_paper.py
│   ├── run_shadow.py
│   ├── run_shadow_smoke.py
│   ├── run_live.py
│   ├── verify_robinhood_equity_reads.py
│   ├── generate_sbom.py
│   └── verify_restore.py
├── src/trading_bot/
│   ├── __init__.py
│   ├── app.py
│   ├── clock.py
│   ├── code_identity.py
│   ├── logging.py
│   ├── capabilities/
│   │   ├── models.py
│   │   ├── registry.py
│   │   └── snapshot.py
│   ├── config/
│   │   ├── models.py
│   │   ├── loader.py
│   │   └── hashing.py
│   ├── domain/
│   │   ├── enums.py
│   │   ├── identifiers.py
│   │   ├── decimal_utils.py
│   │   ├── accounts.py
│   │   ├── market.py
│   │   ├── orders.py
│   │   ├── decisions.py
│   │   ├── events.py
│   │   └── prediction.py
│   ├── market_data/
│   │   ├── protocol.py
│   │   ├── validation.py
│   │   ├── recording.py
│   │   ├── replay.py
│   │   ├── adjustments.py
│   │   ├── universe.py
│   │   ├── robinhood_crypto_api.py
│   │   └── robinhood_equity_mcp.py
│   ├── brokers/
│   │   ├── protocols.py
│   │   ├── errors.py
│   │   ├── fake.py
│   │   ├── robinhood_mcp_transport.py
│   │   ├── robinhood_mcp_schema_gate.py
│   │   ├── robinhood_equity_mcp.py
│   │   ├── robinhood_equity_mapping.py
│   │   ├── robinhood_crypto_auth.py
│   │   ├── robinhood_crypto_transport.py
│   │   ├── robinhood_crypto_schemas.py
│   │   ├── robinhood_crypto_mapping.py
│   │   ├── robinhood_crypto_api.py
│   │   ├── robinhood_prediction.py
│   │   └── schema_snapshots/
│   ├── strategies/
│   │   ├── protocol.py
│   │   ├── features.py
│   │   ├── momentum.py
│   │   ├── relative_strength.py
│   │   ├── regime.py
│   │   ├── mean_reversion.py
│   │   ├── crypto.py
│   │   └── registry.py
│   ├── portfolio/
│   │   ├── targets.py
│   │   ├── intents.py
│   │   ├── sizing.py
│   │   └── correlation.py
│   ├── risk/
│   │   ├── models.py
│   │   ├── limits.py
│   │   ├── losses.py
│   │   ├── pretrade.py
│   │   ├── action_policy.py
│   │   ├── kill_switch.py
│   │   └── self_test.py
│   ├── execution/
│   │   ├── state_machine.py
│   │   ├── review.py
│   │   ├── idempotency.py
│   │   ├── exclusion.py
│   │   ├── service.py
│   │   ├── partial_fills.py
│   │   ├── cancel_policy.py
│   │   └── recovery.py
│   ├── reconciliation/
│   │   ├── models.py
│   │   └── service.py
│   ├── persistence/
│   │   ├── base.py
│   │   ├── unit_of_work.py
│   │   ├── repositories.py
│   │   ├── audit.py
│   │   ├── lease.py
│   │   ├── submission_mutex.py
│   │   └── models/
│   │       ├── accounts.py
│   │       ├── market.py
│   │       ├── decisions.py
│   │       ├── orders.py
│   │       └── operations.py
│   ├── authorization/
│   │   ├── models.py
│   │   ├── signing.py
│   │   ├── verifier.py
│   │   └── preflight.py
│   ├── research/
│   │   ├── engine.py
│   │   ├── validation.py
│   │   ├── metrics.py
│   │   ├── monte_carlo.py
│   │   └── report.py
│   ├── simulation/
│   │   ├── clock.py
│   │   ├── events.py
│   │   ├── costs.py
│   │   ├── fills.py
│   │   ├── engine.py
│   │   └── replay.py
│   ├── runtime/
│   │   ├── modes.py
│   │   ├── runner.py
│   │   ├── scheduler.py
│   │   ├── daemon.py
│   │   ├── backtest.py
│   │   ├── simulation.py
│   │   ├── paper.py
│   │   ├── shadow.py
│   │   ├── live.py
│   │   └── shutdown.py
│   ├── monitoring/
│   │   ├── health.py
│   │   ├── readiness.py
│   │   ├── metrics.py
│   │   ├── alerts.py
│   │   ├── heartbeat.py
│   │   ├── promotion.py
│   │   └── api.py
│   ├── reporting/
│   │   ├── performance.py
│   │   ├── incident.py
│   │   ├── tax.py
│   │   └── llm.py
│   └── cli/
│       ├── main.py
│       ├── status.py
│       ├── preflight.py
│       ├── live.py
│       └── kill_switch.py
└── tests/
    ├── unit/
    ├── property/
    ├── integration/
    ├── replay/
    ├── chaos/
    ├── architecture/
    ├── deployment/
    ├── smoke/
    └── fixtures/
```

## Canonical Cross-Plan Interfaces

Later plans must import these names exactly; do not create alternate abstractions.

```python
# trading_bot.clock
class Clock(Protocol):
    def now(self) -> datetime: ...

@dataclass(frozen=True)
class SystemClock:
    def now(self) -> datetime: ...
```

```python
# trading_bot.market_data.protocol
class MarketDataProvider(Protocol):
    async def get_quote(self, instrument_id: InstrumentId) -> Quote: ...
    async def get_executable_quote(
        self, instrument_id: InstrumentId, quantity: Decimal,
    ) -> Quote: ...
    async def get_bars(
        self, instrument_id: InstrumentId, interval: BarInterval,
        start: datetime, end: datetime,
    ) -> tuple[Bar, ...]: ...
    async def get_market_clock(self, asset_class: AssetClass) -> MarketClock: ...
    async def get_corporate_actions(
        self, instrument_id: InstrumentId, start: date, end: date,
    ) -> tuple[CorporateAction, ...]: ...
    async def get_earnings_calendar(
        self, instrument_ids: tuple[InstrumentId, ...], start: date, end: date,
    ) -> tuple[EarningsEvent, ...]: ...
    async def get_instrument_metadata(self, instrument_id: InstrumentId) -> Instrument: ...
    async def get_spread_estimate(self, instrument_id: InstrumentId) -> SpreadEstimate: ...

class MarketSnapshotLoader(Protocol):
    async def load(
        self, universe: tuple[InstrumentId, ...], as_of: datetime,
    ) -> ValidatedMarketSnapshot: ...
```

```python
# trading_bot.brokers.protocols
class BrokerRead(Protocol):
    async def get_accounts(self) -> tuple[AccountSnapshot, ...]: ...
    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot: ...
    async def get_positions(self, account_id: AccountId) -> tuple[Position, ...]: ...
    async def get_open_orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]: ...
    async def get_recent_orders(
        self, account_id: AccountId, since: datetime,
    ) -> tuple[BrokerOrder, ...]: ...
    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple[Fill, ...]: ...
    async def get_buying_power(
        self, account_id: AccountId, asset_class: AssetClass,
    ) -> Decimal: ...
    async def health_check(self) -> BrokerHealth: ...

class BrokerReview(Protocol):
    async def review_order(self, intent: OrderIntent) -> BrokerOrderReview: ...

class BrokerPlace(Protocol):
    async def place_order(self, submission: PersistedReviewedOrder) -> BrokerOrder: ...

class BrokerCancelOnly(Protocol):
    async def cancel_known_order(
        self, account_id: AccountId, order_id: BrokerOrderId,
    ) -> CancelReceipt: ...
```

```python
# trading_bot.strategies.protocol
class Strategy(Protocol):
    @property
    def descriptor(self) -> StrategyDescriptor: ...
    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]: ...

# trading_bot.portfolio.targets
class PortfolioConstructor(Protocol):
    def construct(
        self,
        decisions: tuple[StrategyDecision, ...],
        snapshot: PortfolioSnapshot,
        market: ValidatedMarketSnapshot,
    ) -> TargetPortfolio: ...

class IntentPlanner(Protocol):
    def plan(
        self,
        target: TargetPortfolio,
        current: PortfolioSnapshot,
        market: ValidatedMarketSnapshot,
    ) -> tuple[OrderIntent, ...]: ...
```

```python
# trading_bot.risk.pretrade
@dataclass(frozen=True, slots=True)
class InitialRiskContext:
    intent: OrderIntent
    account: AccountSnapshot
    portfolio: PortfolioSnapshot
    instrument: Instrument
    eligibility: InstrumentEligibility
    quote: Quote
    market_clock: MarketClock
    broker_health: BrokerHealth
    open_orders: tuple[BrokerOrder, ...]
    local_pending_intents: tuple[OrderIntent, ...]
    reconciliation: ReconciliationAttestation
    live_lease: LiveLeaseAttestation | None
    alerts: AlertAttestation
    strategy_eligibility: StrategyEligibilityAttestation
    runtime_state: RuntimeState
    kill_switch_active: bool
    losses: LossSnapshot
    activity: ActivitySnapshot
    projection: ExposureProjection
    costs: ExecutionCostEstimate
    observed_at: datetime

@dataclass(frozen=True, slots=True)
class FinalPretradeContext:
    initial: InitialRiskContext
    reviewed_order: BrokerOrderReview

class PretradeEngine:
    def evaluate_initial(self, context: InitialRiskContext) -> RiskEvaluation: ...
    def evaluate_final(self, context: FinalPretradeContext) -> RiskEvaluation: ...

class PretradeContextLoader(Protocol):
    async def load_initial(self, intent: OrderIntent) -> InitialRiskContext: ...
    async def load_final(
        self, intent: OrderIntent, review: BrokerOrderReview,
    ) -> FinalPretradeContext: ...
```

```python
# trading_bot.execution.state_machine
def transition(current: OrderState, event: OrderEvent) -> OrderState: ...

# trading_bot.execution.service
class ExecutionService:
    async def execute(self, intent: OrderIntent) -> ExecutionResult: ...
    async def cancel_known_entry(self, order_id: BrokerOrderId) -> CancelReceipt: ...
```

```python
# trading_bot.reconciliation.service
class ReconciliationService:
    async def reconcile(self, account_id: AccountId) -> ReconciliationResult: ...

# trading_bot.persistence.unit_of_work
class UnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

## Prompt Coverage Map

| Requested area | Owning plans | Completion evidence |
|---|---|---|
| Official Robinhood capability discovery and unofficial-interface prohibition | 1, 4, 5 | Sanitized manifests, capability matrix, schema-drift and import-boundary tests |
| Deterministic architecture, all operating modes, and LLM isolation | 1, 3, 4, 5, 6 | Canonical interfaces, composition tests, no-live-write tests, read-only LLM tests |
| Small-account portfolio/risk policy and all 24 pretrade checks | 1, 2, 5 | Strict config/safety envelope, sizing properties, 23/24-check tests, final refresh chaos tests |
| Equity, Crypto, and prediction research plus rejection reporting | 3 | Candidate registry, prediction research-only boundary, full attempt reports, acceptance evidence |
| Bias/cost-aware backtesting, replay, walk-forward, PBO, stress, and metrics | 3 | Deterministic replay hashes, no-lookahead tests, validation reports and acceptance tests |
| Market-data quality, provenance, point-in-time universes, and corporate actions | 2, 3, 4 | Append-only quality events, manifests, validation/quarantine and adapter capability tests |
| Equity MCP, Crypto v2, prediction refusal, fake broker, and shadow | 1, 3, 4 | Official-schema evidence, signer/transport tests, local MCP/HTTP fakes, shadow no-place tests |
| Durable state machine, review, submission, fills, cancel/replace, and restart recovery | 2, 5 | Explicit transition table, unique submission journal, mutex/fencing chaos, reconciliation/recovery tests |
| Persistence, append-only audit, provenance, and reconciliation | 2, 3, 5 | Alembic schema, repository/UoW tests, immutable event guards, zero-tolerance diff tests |
| Live authorization, kill switch, promotion, and evidence durations | 2, 5, 6 | Signed one-time artifacts, action matrix, locked composition, non-activating promotion evaluator |
| Secrets, threat model, supply chain, container, DigitalOcean, and egress/inbound controls | 1, 4, 6 | Redaction tests, scans/SBOM, hardened image/Compose tests, Terraform validation and runbooks |
| Monitoring, alerts, scheduler, operator CLI, tax export, backup/restore, and incidents | 6 | Health/readiness API, daemon lifecycle, CLI tests, encrypted backup/restore tests, reports |
| Quality gates, documentation, and final handoff | 1–6 | Unit/property/integration/replay/chaos suites, coverage thresholds, exact commands and final report |

Authenticated MCP behavior, real elapsed evidence, cloud apply, and any live broker observation remain external—not silently converted into code-complete claims.

## Implementation Discipline

- Begin execution by using `superpowers:using-git-worktrees`; do not implement directly on the design branch.
- Use test-driven development for every behavior change: failing test, observed failure, minimal implementation, observed pass, focused commit.
- Never run authenticated broker integration tests in CI.
- Authenticated read verification is a separate operator action and writes only redacted schema/status evidence.
- Any command that could submit or cancel a real order must require an explicit non-CI profile; implementation tests use fakes or local mock servers.
- Stop a slice when a required official capability is not verified. Record the unsupported state and keep later live gates closed.
- Run the narrowest test first, then the plan-level suite, then the repository-wide suite.
- Each task has one reviewer gate and one focused commit.

## Completion Boundary

Completing all code plans does not satisfy elapsed paper, shadow, micro-live, or normal-live evidence. The final repository must report those gates as pending until real, separately authorized observations exist. No plan authorizes live trading or DigitalOcean provisioning.
