# Capability and Repository Foundation Implementation Plan

> Historical planning snapshot from 2026-07-10. For current implementation and operational
> status, see the repository README and `docs/final-implementation-report.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible Python repository, strict configuration, canonical domain primitives, least-privilege broker protocols, and an evidence-based Robinhood capability matrix without making account or trading calls.

**Architecture:** This slice creates the dependency roots used by every later plan. Capability evidence distinguishes public documentation, unauthenticated schema declarations, authenticated reads, non-submitting order reviews, and unsupported operations; no broker mapper may be authored from prose alone.

**Tech Stack:** Python 3.12–3.14, uv 0.11.28, Hatchling 1.31.0, Pydantic 2.13.4, MCP Python SDK 1.28.1, PyYAML 6.0.3, Structlog 26.1.0, Pytest 9.1.1, Ruff 0.15.21, MyPy 2.2.0.

## Global Constraints

- Default state is paused; this slice has no live-order code.
- Only official Robinhood documentation and sanitized MCP schema discovery are accepted as capability sources.
- `tools/list` is schema evidence, not authenticated behavioral evidence.
- No account data, OAuth token, API key, signature, private key, authorization header, or signed artifact enters Git or logs.
- Python requires `>=3.12,<3.15`; all timestamps are aware UTC and all trading numerics use `Decimal`.
- One strict Pydantic configuration graph owns every threshold and rejects unknown keys.
- `configs/safety-envelope.yaml` may only be changed through code review; mode/environment/CLI values cannot weaken it.
- Prediction live execution remains unsupported and disabled.
- Tests have no live broker credentials or broker write network route.
- Code and documentation make no profitability claim.

---

### Task 1: Bootstrap the pinned Python project

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/trading_bot/__init__.py`
- Create: `src/trading_bot/py.typed`
- Create: `tests/conftest.py`
- Create: `tests/smoke/test_imports.py`
- Generate: `uv.lock`

**Interfaces:**
- Produces: `trading_bot.__version__: str == "0.1.0"`
- Produces: a locked development environment used by every later task.

- [ ] **Step 1: Add the exact package and tool configuration**

```toml
[build-system]
requires = ["hatchling==1.31.0"]
build-backend = "hatchling.build"

[project]
name = "robinhood-multi-asset-trading-system"
version = "0.1.0"
description = "Fail-closed research and trading system for official Robinhood interfaces."
requires-python = ">=3.12,<3.15"
dependencies = [
  "aiosqlite==0.22.1",
  "alembic==1.18.5",
  "fastapi==0.139.0",
  "httpx==0.28.1",
  "mcp==1.28.1",
  "prometheus-client==0.25.0",
  "pydantic==2.13.4",
  "pydantic-settings==2.14.2",
  "PyNaCl==1.6.2",
  "PyYAML==6.0.3",
  "SQLAlchemy==2.0.51",
  "structlog==26.1.0",
  "typer==0.26.8",
  "uvicorn==0.51.0",
]

[project.scripts]
trader = "trading_bot.cli.main:main"

[dependency-groups]
dev = [
  "bandit[toml]==1.9.4",
  "cyclonedx-bom==7.3.0",
  "hypothesis==6.156.6",
  "mypy==2.2.0",
  "pip-audit==2.10.1",
  "pytest==9.1.1",
  "pytest-asyncio==1.4.0",
  "pytest-cov==7.1.0",
  "respx==0.23.1",
  "ruff==0.15.21",
  "types-PyYAML==6.0.12.20260518",
]

[tool.hatch.build.targets.wheel]
packages = ["src/trading_bot"]

[tool.pytest.ini_options]
addopts = "-ra --strict-markers --strict-config -m 'not authenticated'"
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
  "authenticated: operator-run test that may read an authenticated official interface; never selected by default or CI",
  "external_capability_missing: verifies a capability remains explicitly locked when reproducible external evidence is absent",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["trading_bot"]

[tool.bandit]
exclude_dirs = ["tests"]
```

Set `.python-version` to `3.12`, ignore `.venv/`, `.env*` except `.env.example`, databases, authorization artifacts, reports, coverage, caches, Terraform state, and private keys. The two release-level flags retain the prompt's exact names and are mapped once into the central graph: `LIVE_TRADING_ENABLED=false` and `PREDICTION_LIVE_ENABLED=false`. Reject configurations that also set conflicting nested values.

List these external references, with blank/safe values only, in `.env.example`: `LIVE_TRADING_ENABLED`, `PREDICTION_LIVE_ENABLED`, `ROBINHOOD_MCP_SERVER_URL`, `ROBINHOOD_MCP_OAUTH_STORE_DIR`, `ROBINHOOD_CRYPTO_API_KEY_FILE`, `ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE`, `TRADING_BOT_AUTH_SIGNING_KEY_FILE` (operator workstation only), `TRADING_BOT_AUTH_VERIFY_KEY_FILE` (service host only), `TRADING_BOT_ACCOUNT_ALLOWLIST_FILE`, `TRADING_BOT_WEBHOOK_URL_FILE`, `TRADING_BOT_LLM_API_KEY_FILE`, `TRADING_BOT_AGE_RECIPIENT_FILE`, `TRADING_BOT_AGE_IDENTITY_FILE` (restore workstation only), `TRADING_BOT_RCLONE_CONFIG_FILE`, `TRADING_BOT_BACKUP_REMOTE`, `TRADING_BOT_IMAGE_DIGEST`, `TRADING_BOT_IMAGE`, `DEPLOY_HOST`, `DEPLOY_USER`, and `DIGITALOCEAN_TOKEN`. Defaults are `https://agent.robinhood.com/mcp/trading` only for the public MCP URL and `false` for both live flags; credential, account, deployment, webhook, LLM, backup, and token references remain blank. Restricted secret files live outside Git, are mode `0600`, and are never copied into config snapshots.

- [ ] **Step 2: Install uv and lock dependencies**

Run:

```bash
python3 -m pip install --user uv==0.11.28
uv lock
uv sync --all-groups
```

Expected: `uv.lock` is created and every pinned package resolves for Python 3.12.

- [ ] **Step 3: Write the failing package smoke test**

```python
def test_package_has_expected_version() -> None:
    import trading_bot

    assert trading_bot.__version__ == "0.1.0"
```

- [ ] **Step 4: Run the smoke test and observe the failure**

Run: `uv run pytest tests/smoke/test_imports.py -q`

Expected: FAIL because `trading_bot` or `__version__` does not exist.

- [ ] **Step 5: Add the minimal package module**

```python
"""Deterministic, fail-closed Robinhood trading system."""

__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [ ] **Step 6: Verify bootstrap quality**

Run:

```bash
uv run pytest tests/smoke/test_imports.py -q
uv run ruff check .
uv run mypy src
uv lock --check
```

Expected: all commands pass.

- [ ] **Step 7: Commit the bootstrap**

```bash
git add pyproject.toml uv.lock .python-version .gitignore .env.example src tests
git commit -m "chore: bootstrap safe trading system repository"
```

### Task 2: Add canonical identifiers, enums, decimals, and clocks

**Files:**
- Create: `src/trading_bot/clock.py`
- Create: `src/trading_bot/code_identity.py`
- Create: `src/trading_bot/domain/__init__.py`
- Create: `src/trading_bot/domain/enums.py`
- Create: `src/trading_bot/domain/identifiers.py`
- Create: `src/trading_bot/domain/decimal_utils.py`
- Create: `src/trading_bot/domain/accounts.py`
- Create: `src/trading_bot/domain/market.py`
- Create: `src/trading_bot/domain/orders.py`
- Create: `src/trading_bot/domain/decisions.py`
- Test: `tests/unit/domain/test_primitives.py`
- Test: `tests/unit/domain/test_records.py`
- Test: `tests/unit/test_code_identity.py`
- Test: `tests/property/domain/test_decimal_utils.py`

**Interfaces:**
- Produces: `AssetClass`, `Side`, `OrderPurpose`, `OrderType`, `TimeInForce`, `BarInterval`, `TimestampSource`, `ExecutionMode`, `RuntimeState`, `OrderState`, and `OrderEvent`.
- Produces: `AccountId`, `InstrumentId`, `OrderIntentId`, `ClientOrderId`, `ReviewId`, `SubmissionAttemptId`, `BrokerOrderId`, `FillId`, `OrderTransitionId`, `RunId`, `AuthorizationId`, `ReconciliationId`, `LeaseId`, `AuditEventId`, `EvidenceId`, `ConfigVersionId`, `CorrelationId`, `ConfigHash`, `DataHash`, and `CodeHash` as distinct `NewType` aliases over `str`, plus `new_order_intent_id() -> OrderIntentId` backed by UUIDv4.
- Produces: `parse_decimal(value: str) -> Decimal`, `quantize_down(value, increment) -> Decimal`, `require_utc(value) -> datetime`, and `Clock`.
- Produces: `CodeIdentity`, `resolve_code_identity(repo_root, image_digest) -> CodeIdentity`, and `require_clean_live_identity(identity) -> None`.
- Produces the immutable record names required by broker protocols: `AccountSnapshot`, `Position`, `PortfolioSnapshot`, `Instrument`, `Quote`, `SpreadEstimate`, `Bar`, `MarketClock`, `OrderIntent`, `BrokerOrderReview`, `BrokerOrder`, `Fill`, `CancelReceipt`, `BrokerHealth`, `CheckResult`, and `RiskEvaluation`.

- [ ] **Step 1: Write failing primitive tests**

```python
def test_quantize_down_never_increases_exposure() -> None:
    assert quantize_down(Decimal("1.239"), Decimal("0.01")) == Decimal("1.23")

def test_system_clock_is_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC
    assert now.utcoffset() == timedelta(0)

@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_parse_decimal_rejects_nonfinite_values(raw: str) -> None:
    with pytest.raises(InvalidDecimal):
        parse_decimal(raw)

def test_domain_records_are_frozen() -> None:
    account = minimal_account_snapshot()
    with pytest.raises(FrozenInstanceError):
        account.provider_state = "changed"  # type: ignore[misc]

def test_dirty_tree_cannot_supply_live_identity(tmp_git_repo: Path) -> None:
    identity = resolve_code_identity(tmp_git_repo, image_digest=None)
    assert identity.dirty
    with pytest.raises(UnsafeCodeIdentity):
        require_clean_live_identity(identity)
```

- [ ] **Step 2: Run tests and observe missing modules**

Run: `uv run pytest tests/unit/domain/test_primitives.py -q`

Expected: FAIL with import errors.

- [ ] **Step 3: Implement the exact decimal and clock behavior**

```python
class InvalidDecimal(ValueError):
    pass

def parse_decimal(value: str) -> Decimal:
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise InvalidDecimal("decimal must be finite")
    return parsed

def quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if not value.is_finite() or not increment.is_finite() or increment <= 0:
        raise InvalidDecimal("value and positive increment must be finite")
    return (value // increment) * increment

class Clock(Protocol):
    def now(self) -> datetime: ...

@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
```

Implement the enums exactly as listed in the Interfaces block and reject naive datetimes with `require_utc`. `AssetClass` contains `EQUITY`, `CRYPTO`, and `PREDICTION`; `Side` contains `BUY` and `SELL`; `OrderPurpose` contains `ENTRY`, `STRATEGY_EXIT`, and `PROTECTIVE_EXIT`; `OrderType` contains `MARKET`, `LIMIT`, `STOP_LOSS`, and `STOP_LIMIT`; `TimeInForce` contains `GOOD_FOR_DAY`, `GOOD_TIL_CANCELED`, and `IMMEDIATE_OR_CANCEL`; `ExecutionMode` contains `BACKTEST`, `SIMULATION`, `PAPER`, `SHADOW`, `MICRO_LIVE`, and `NORMAL_LIVE`. `BarInterval` contains exactly `ONE_MINUTE`, `FIVE_MINUTE`, `ONE_HOUR`, `FOUR_HOUR`, and `ONE_DAY`; `TimestampSource` contains `PROVIDER`, `LOCAL_RECEIPT`, and `SIMULATED`. `RuntimeState` contains exactly `RUNNING_LIVE`, `ENTRY_BLOCKED`, `PAUSED`, `KILL_SWITCH_ACTIVE`, `RECONCILIATION_REQUIRED`, and `SHUTTING_DOWN`. `OrderState` contains exactly `PROPOSED`, `RISK_REJECTED`, `RISK_APPROVED`, `REVIEW_REQUESTED`, `REVIEWED`, `SUBMISSION_PENDING`, `SUBMITTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `EXPIRED`, and `UNKNOWN_REQUIRES_RECONCILIATION`. `OrderEvent` contains exactly `RISK_DENY`, `RISK_ALLOW`, `EXPIRE`, `REQUEST_REVIEW`, `REVIEW_ACCEPTED`, `REVIEW_REJECTED`, `FINAL_RISK_DENY`, `PREPARE_SUBMISSION`, `BROKER_ACCEPTED`, `BROKER_REJECTED`, `BROKER_AMBIGUOUS`, `PARTIAL_FILL`, `FILL`, `REQUEST_CANCEL`, `CANCEL_CONFIRMED`, `CANCEL_REJECTED`, `BROKER_EXPIRED`, `RECONCILIATION_DRIFT`, `RECONCILE_SUBMITTED`, `RECONCILE_PARTIAL`, `RECONCILE_FILLED`, `RECONCILE_CANCELED`, `RECONCILE_REJECTED`, and `RECONCILE_EXPIRED`.

Use UUIDv4 only for the durable client-visible intent identifier; keep deterministic content hashes separate:

```python
def new_order_intent_id() -> OrderIntentId:
    return OrderIntentId(str(uuid.uuid4()))
```

Add frozen, slotted domain records with these stable fields; Plan 2 adds complete cross-field validation and persistence mappings without renaming them:

```python
@dataclass(frozen=True, slots=True)
class Quote:
    instrument_id: InstrumentId
    observed_at: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal | None
    source: str
    data_hash: DataHash
    freshness_verified: bool
    timestamp_source: TimestampSource

@dataclass(frozen=True, slots=True)
class SpreadEstimate:
    instrument_id: InstrumentId
    observed_at: datetime
    absolute: Decimal
    percentage: Decimal
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: InstrumentId
    interval: BarInterval
    starts_at: datetime
    ends_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str
    data_hash: DataHash
    interpolated: bool = False

@dataclass(frozen=True, slots=True)
class Instrument:
    id: InstrumentId
    symbol: str
    asset_class: AssetClass
    provider_status: str
    tradable: bool
    fractional_eligible: bool
    price_increment: Decimal
    quantity_increment: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal
    maximum_quantity: Decimal | None
    correlation_group: str
    observed_at: datetime
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class MarketClock:
    asset_class: AssetClass
    venue: str
    observed_at: datetime
    is_open: bool
    halted: bool
    trading_disabled: bool
    cancel_only: bool
    next_open_at: datetime | None
    next_close_at: datetime | None

@dataclass(frozen=True, slots=True)
class AssetBuyingPower:
    asset_class: AssetClass
    amount: Decimal

@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: AccountId
    provider_state: str
    equity: Decimal
    cash: Decimal
    buying_power: tuple[AssetBuyingPower, ...]
    restricted: bool
    observed_at: datetime
    data_hash: DataHash

    def buying_power_for(self, asset_class: AssetClass) -> Decimal:
        matches = tuple(item.amount for item in self.buying_power if item.asset_class is asset_class)
        if len(matches) != 1:
            raise DomainValidationError("exactly one asset-class buying-power value is required")
        return matches[0]

@dataclass(frozen=True, slots=True)
class Position:
    account_id: AccountId
    instrument_id: InstrumentId
    asset_class: AssetClass
    quantity: Decimal
    average_price: Decimal | None
    market_value: Decimal
    observed_at: datetime
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    account_id: AccountId
    positions: tuple[Position, ...]
    cash: Decimal
    equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    crypto_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    observed_at: datetime
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class OrderIntent:
    id: OrderIntentId
    account_id: AccountId
    instrument_id: InstrumentId
    asset_class: AssetClass
    side: Side
    purpose: OrderPurpose
    order_type: OrderType
    time_in_force: TimeInForce
    quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    created_at: datetime
    expires_at: datetime
    strategy_version: str
    config_hash: ConfigHash
    data_hash: DataHash
    exit_policy_version: str | None

@dataclass(frozen=True, slots=True)
class BrokerOrderReview:
    normalized_order: OrderIntent
    source: str
    reviewed_at: datetime
    expires_at: datetime
    estimated_notional: Decimal
    estimated_fees: Decimal
    client_order_id: ClientOrderId | None
    outbound_payload_sha256: str
    broker_review_id: str | None

@dataclass(frozen=True, slots=True)
class BrokerOrder:
    id: BrokerOrderId
    account_id: AccountId
    intent_id: OrderIntentId | None
    client_order_id: ClientOrderId | None
    instrument_id: InstrumentId
    side: Side
    purpose: OrderPurpose
    order_type: OrderType
    time_in_force: TimeInForce
    requested_quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    state: OrderState
    created_at: datetime
    updated_at: datetime
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class Fill:
    id: FillId
    broker_order_id: BrokerOrderId
    account_id: AccountId
    instrument_id: InstrumentId
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class CancelReceipt:
    broker_order_id: BrokerOrderId
    accepted: bool
    ambiguous: bool
    observed_at: datetime
    reason_code: str

@dataclass(frozen=True, slots=True)
class BrokerHealth:
    healthy: bool
    observed_at: datetime
    latency_ms: Decimal | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PersistedReviewedOrder:
    review_id: ReviewId
    submission_attempt_id: SubmissionAttemptId
    review: BrokerOrderReview
    deduplication_key: str
    fencing_token: int
    live_lease_evidence_hash: str
    account_id: AccountId
    config_hash: ConfigHash

@dataclass(frozen=True, slots=True)
class CheckResult:
    code: str
    allowed: bool
    observed: str | None
    configured_limit: str | None
    reason: str
    observed_at: datetime

@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    intent_id: OrderIntentId
    allowed: bool
    checks: tuple[CheckResult, ...]
    evaluated_at: datetime
    config_hash: ConfigHash

@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: AuditEventId
    occurred_at: datetime
    category: str
    actor: str
    reason_code: str
    correlation_id: CorrelationId
    config_hash: ConfigHash
    code_hash: CodeHash
    data_hash: DataHash | None
    details: tuple[tuple[str, str], ...]
```

Every record validates finite `Decimal` values, UTC-aware timestamps, immutable tuple collections, cross-field quantities, and hashes. No record contains provider response objects or secret-bearing fields.

Resolve code identity by hashing each Git-tracked path and its current bytes in sorted path order with unambiguous length prefixes, plus any untracked file under `src/`, `configs/`, `migrations/`, or runtime scripts using an `UNTRACKED` prefix. Record the clean Git commit when available. A deployed process additionally records and verifies the configured immutable OCI image digest (`sha256:...`). Modified or relevant untracked source sets `dirty=True`; `require_clean_live_identity` rejects it, and no authorization or promotion evidence may use it. Research may run dirty only when that complete dirty tree hash and `non_promotable=true` are recorded.

- [ ] **Step 4: Add property tests for downward quantization**

```python
@given(
    value=decimals(min_value="0", max_value="100000", allow_nan=False, allow_infinity=False),
    increment=decimals(min_value="0.00000001", max_value="100", allow_nan=False, allow_infinity=False),
)
def test_quantize_down_is_bounded(value: Decimal, increment: Decimal) -> None:
    result = quantize_down(value, increment)
    assert result <= value
    assert value - result < increment
```

- [ ] **Step 5: Run primitive tests**

Run: `uv run pytest tests/unit/domain tests/unit/test_code_identity.py tests/property/domain -q`

Expected: PASS.

- [ ] **Step 6: Commit the primitives**

```bash
git add src/trading_bot/clock.py src/trading_bot/code_identity.py src/trading_bot/domain tests/unit/domain tests/unit/test_code_identity.py tests/property/domain
git commit -m "feat: add canonical trading primitives"
```

### Task 3: Implement the single strict configuration graph

**Files:**
- Create: `src/trading_bot/config/__init__.py`
- Create: `src/trading_bot/config/models.py`
- Create: `src/trading_bot/config/loader.py`
- Create: `src/trading_bot/config/hashing.py`
- Create: `configs/safety-envelope.yaml`
- Create: `configs/base.yaml`
- Create: `configs/backtest.yaml`
- Create: `configs/simulation.yaml`
- Create: `configs/paper.yaml`
- Create: `configs/shadow.yaml`
- Create: `configs/micro_live.yaml`
- Create: `configs/normal_live.yaml`
- Test: `tests/unit/config/test_models.py`
- Test: `tests/unit/config/test_loader.py`
- Test: `tests/property/config/test_safety_envelope.py`

**Interfaces:**
- Produces: frozen Pydantic models `PortfolioSettings`, `PositionRiskSettings`, `LossLimitSettings`, `ActivitySettings`, `EquitySettings`, `CryptoSettings`, `PredictionSettings`, `FreshnessSettings`, `AuthorizationSettings`, `RuntimeSettings`, `MarketDataSettings`, `ResearchSettings`, `SimulationSettings`, `CostSettings`, `RetrySettings`, `SchedulerSettings`, `MonitoringSettings`, `PromotionSettings`, `LlmReportingSettings`, `BackupSettings`, `EquityStrategySettings`, `CryptoStrategySettings`, `PredictionResearchSettings`, `AppConfig`, and `SafetyEnvelope`.
- Produces: `load_config(base_path, mode_path, safety_path, environ) -> LoadedConfig`.
- Produces: `LoadedConfig.config`, `.canonical_json`, and `.config_hash`.

- [ ] **Step 1: Write failing validation tests**

```python
def test_unknown_config_key_fails() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({**valid_config_dict(), "mystery": True})

def test_environment_flag_is_only_one_live_gate(tmp_path: Path) -> None:
    loaded = load_config(
        base_path=fixture_path("base.yaml"),
        mode_path=fixture_path("normal_live.yaml"),
        safety_path=fixture_path("safety-envelope.yaml"),
        environ={"LIVE_TRADING_ENABLED": "true"},
    )
    assert loaded.config.live_trading_enabled
    assert loaded.config.runtime.start_paused

def test_prediction_live_is_always_false() -> None:
    with pytest.raises(ValidationError):
        PredictionSettings(simulation_enabled=True, live_enabled=True)
```

- [ ] **Step 2: Run config tests and observe failure**

Run: `uv run pytest tests/unit/config/test_models.py tests/unit/config/test_loader.py -q`

Expected: FAIL with missing config modules.

- [ ] **Step 3: Implement strict frozen models**

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class PortfolioSettings(StrictModel):
    expected_starting_equity_usd: Decimal = Decimal("100")
    live_account_equity_ceiling_usd: Decimal = Decimal("150")
    max_total_gross_exposure_pct: Decimal = Decimal("60")
    min_cash_reserve_pct: Decimal = Decimal("40")
    max_open_positions: int = 5

class AppConfig(StrictModel):
    mode: ExecutionMode
    live_trading_enabled: bool = False
    portfolio: PortfolioSettings
    position_risk: PositionRiskSettings
    loss_limits: LossLimitSettings
    activity: ActivitySettings
    equities: EquitySettings
    crypto: CryptoSettings
    prediction_markets: PredictionSettings
    freshness: FreshnessSettings
    authorization: AuthorizationSettings
    runtime: RuntimeSettings
    market_data: MarketDataSettings
    research: ResearchSettings
    simulation: SimulationSettings
    costs: CostSettings
    retry: RetrySettings
    scheduler: SchedulerSettings
    monitoring: MonitoringSettings
    promotion: PromotionSettings
    llm_reporting: LlmReportingSettings
    backup: BackupSettings
    equity_strategies: EquityStrategySettings
    crypto_strategies: CryptoStrategySettings
    prediction_research: PredictionResearchSettings
```

Add every approved default exactly: 0.50% trade risk, 15% position notional, 25% correlated exposure, 2.0 reward/risk, 2% daily loss, 5% weekly loss, 10% drawdown, three-loss/240-minute pause, three daily orders, one symbol order, 30-minute spacing, 0.35% equity spread, $5 price, $50,000,000 ADV, earnings windows 2/1, 20% total crypto, 10% single crypto, BTC-USD/ETH-USD, 0.60% crypto spread, and all prohibited features false.

The same graph owns every later operational/research threshold. Set executable quote age to 5 seconds; account/broker-health snapshot age and review lifetime to 30 seconds; preflight lifetime to 300 seconds; clock drift to 2 seconds; one-time activation lifetime to 900 seconds; live lease to 28,800 seconds with a 86,400-second envelope maximum; safe read attempts to 3 with 0.25-second initial and 2-second maximum backoff; all write attempts to exactly 1; equity and Crypto reconciliation cadence to 60 seconds; paper cycles to 100; shadow days to 7; micro order review interval to 10; normal combined days to 30; normal observations to 100; backup cadence to 86,400 seconds and retention to 30 daily archives; monitoring host to `127.0.0.1`, port to `8080`, and `container_loopback_publish=false`; optional LLM reporting to disabled with explicit daily/monthly token budgets and timeout. Strategy grids, bar intervals, research seeds, simulation fill/cost/latency assumptions, anomaly bounds, spread/slippage limits, webhook retry/timeouts, shutdown deadline, backup destination/cadence, and data-age-in-bars are explicit required YAML keys with no logic-level fallback. Safety-envelope validation requires read retries `>=1`, write attempts `==1`, and can only shorten freshness/authorization windows or tighten promotion/risk thresholds.

- [ ] **Step 4: Implement deterministic merge and hashing**

```python
@dataclass(frozen=True, slots=True)
class LoadedConfig:
    config: AppConfig
    canonical_json: bytes
    config_hash: ConfigHash

def hash_config(config: AppConfig) -> tuple[bytes, ConfigHash]:
    raw = config.model_dump(mode="json", round_trip=True)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return canonical, ConfigHash(hashlib.sha256(canonical).hexdigest())
```

Map nested environment names using `TRADING_BOT__` and `__`. Explicitly map only `LIVE_TRADING_ENABLED` to `AppConfig.live_trading_enabled` and `PREDICTION_LIVE_ENABLED` to `AppConfig.prediction_markets.live_enabled`; reject every other alias and any duplicate/conflicting representation. Validate mode values against the non-overridable safety envelope.

- [ ] **Step 5: Add safety-envelope property tests**

```python
@given(order_notional=decimals(min_value="5.01", max_value="100"))
def test_micro_mode_cannot_exceed_five_dollars(order_notional: Decimal) -> None:
    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=micro_config(max_order_notional_usd=order_notional),
            envelope=default_envelope(),
        )
```

- [ ] **Step 6: Run config tests and type checks**

Run:

```bash
uv run pytest tests/unit/config tests/property/config -q
uv run mypy src/trading_bot/config
```

Expected: PASS.

- [ ] **Step 7: Commit configuration**

```bash
git add src/trading_bot/config configs tests/unit/config tests/property/config
git commit -m "feat: add fail-closed configuration graph"
```

### Task 4: Add capability evidence models and registry

**Files:**
- Create: `src/trading_bot/capabilities/__init__.py`
- Create: `src/trading_bot/capabilities/models.py`
- Create: `src/trading_bot/capabilities/registry.py`
- Create: `src/trading_bot/capabilities/snapshot.py`
- Test: `tests/unit/capabilities/test_models.py`
- Test: `tests/unit/capabilities/test_registry.py`

**Interfaces:**
- Produces: `EvidenceLevel`, `OperationKind`, `CapabilityEvidence`, `CapabilityRecord`, `CapabilityManifest`, `canonical_sha256`, and `require_capability`.

- [ ] **Step 1: Write failing evidence-level tests**

```python
def test_documentation_cannot_claim_authenticated_evidence() -> None:
    with pytest.raises(InvalidCapabilityEvidence):
        CapabilityEvidence(
            level=EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
            source_uri="https://robinhood.com/support",
            observed_at=aware_now(),
            schema_sha256=None,
            authenticated=False,
            contains_account_data=False,
            notes=(),
        )

def test_prediction_execution_is_forced_unsupported() -> None:
    with pytest.raises(InvalidCapabilityManifest):
        manifest_with_prediction_place(EvidenceLevel.SCHEMA_DECLARED)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/capabilities -q`

Expected: FAIL with missing capability modules.

- [ ] **Step 3: Implement evidence types and validation**

```python
class EvidenceLevel(StrEnum):
    DOCUMENTED = "documented"
    SCHEMA_DECLARED = "schema-declared"
    AUTHENTICATED_READ_VERIFIED = "authenticated-read-verified"
    AUTHENTICATED_WRITE_REVIEWED = "authenticated-write-reviewed"
    UNSUPPORTED = "unsupported"

@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    level: EvidenceLevel
    source_uri: str
    observed_at: datetime
    schema_sha256: str | None
    authenticated: bool
    contains_account_data: bool
    notes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    provider: str
    operation: str
    asset_class: AssetClass
    operation_kind: OperationKind
    evidence: tuple[CapabilityEvidence, ...]
    limitations: tuple[str, ...]
    locked_reason: str | None
```

Reject authenticated levels without `authenticated=True`, committed account data, naive timestamps, unpinned schema digests, and any supported prediction placement record.

- [ ] **Step 4: Implement canonical SHA-256 and capability requirements**

```python
def canonical_sha256(value: JsonValue) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()

def require_capability(
    manifest: CapabilityManifest,
    *,
    provider: str,
    operation: str,
    minimum: EvidenceLevel,
) -> CapabilityRecord:
    record = manifest.find(provider=provider, operation=operation)
    if not record.satisfies(minimum):
        raise UnsupportedCapabilityError(provider, operation, minimum)
    return record
```

- [ ] **Step 5: Run capability tests**

Run: `uv run pytest tests/unit/capabilities -q`

Expected: PASS.

- [ ] **Step 6: Commit evidence registry**

```bash
git add src/trading_bot/capabilities tests/unit/capabilities
git commit -m "feat: add capability evidence registry"
```

### Task 5: Capture sanitized MCP schemas and render the matrix

**Files:**
- Create: `scripts/capture_mcp_capabilities.py`
- Modify: `src/trading_bot/capabilities/registry.py`
- Modify: `src/trading_bot/capabilities/snapshot.py`
- Create: `tests/fixtures/capabilities/documented_robinhood.json`
- Create: `tests/integration/capabilities/test_snapshot.py`
- Create: `docs/capability-matrix.md`

**Interfaces:**
- Consumes: MCP `ClientSession.list_tools()` only.
- Produces: `capture_tools_list(endpoint: str) -> CapabilityManifest` and `render_capability_matrix(manifest) -> str`.
- Never calls `ClientSession.call_tool` in this task.

- [ ] **Step 1: Write the failing no-tool-call integration test**

```python
@pytest.mark.asyncio
async def test_capture_uses_tools_list_only(fake_mcp_session: FakeMcpSession) -> None:
    manifest = await capture_tools_list(fake_mcp_session)

    assert manifest.records
    assert fake_mcp_session.list_tools_calls == 1
    assert fake_mcp_session.call_tool_calls == []
```

- [ ] **Step 2: Run the test and observe failure**

Run: `uv run pytest tests/integration/capabilities/test_snapshot.py -q`

Expected: FAIL because schema capture is missing.

- [ ] **Step 3: Implement schema-only capture and sanitization**

```python
async def capture_tools_list(session: ClientSession) -> CapabilityManifest:
    result = await session.list_tools()
    records = tuple(
        CapabilityRecord.from_declared_schema(
            provider="robinhood-trading",
            name=tool.name,
            description=tool.description,
            input_schema=tool.inputSchema,
            output_schema=getattr(tool, "outputSchema", None),
        )
        for tool in result.tools
    )
    return CapabilityManifest(records=records)
```

Before writing a snapshot, recursively reject keys or values matching account numbers, tokens, cookies, authorization headers, signatures, private keys, or bearer material. Exit with code 2 and print the official setup command when `robinhood-trading` is not configured.

- [ ] **Step 4: Seed documented-only evidence**

Record official source URLs and the documented equity tool names. Mark Crypto v2 endpoints documented and prediction execution unsupported. Do not invent MCP schemas and do not label the active app's transient declarations as a configured Trading MCP snapshot.

- [ ] **Step 5: Render and test the matrix**

Run:

```bash
uv run pytest tests/integration/capabilities/test_snapshot.py -q
uv run python scripts/capture_mcp_capabilities.py --help
```

Expected: tests pass; the help output states that capture performs `tools/list` only and writes no account data.

- [ ] **Step 6: Commit capability documentation**

```bash
git add scripts/capture_mcp_capabilities.py src/trading_bot/capabilities tests/fixtures/capabilities tests/integration/capabilities docs/capability-matrix.md
git commit -m "docs: add reproducible Robinhood capability baseline"
```

### Task 6: Define least-privilege broker protocols

**Files:**
- Create: `src/trading_bot/brokers/__init__.py`
- Create: `src/trading_bot/brokers/protocols.py`
- Create: `src/trading_bot/brokers/errors.py`
- Test: `tests/unit/brokers/test_protocols.py`
- Test: `tests/architecture/test_broker_imports.py`

**Interfaces:**
- Produces: `BrokerRead`, `BrokerReview`, `BrokerPlace`, and `BrokerCancelOnly` exactly as defined in the implementation index.
- Produces: `UnsupportedCapabilityError`, `BrokerUnavailable`, `BrokerSubmissionAmbiguous`, and `SchemaDriftError`.

- [ ] **Step 1: Write failing protocol and import-boundary tests**

```python
def test_recovery_capability_has_no_place_method() -> None:
    assert "place_order" not in BrokerCancelOnly.__dict__

def test_strategy_modules_do_not_import_brokers() -> None:
    violations = forbidden_imports("src/trading_bot/strategies", prefix="trading_bot.brokers")
    assert violations == []

def test_place_calls_exist_only_in_execution_service_and_adapter_definitions() -> None:
    assert production_place_call_sites("src/trading_bot") == {
        Path("src/trading_bot/execution/service.py")
    }
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/brokers/test_protocols.py tests/architecture/test_broker_imports.py -q`

Expected: FAIL with missing broker protocols.

- [ ] **Step 3: Implement split protocols**

```python
class BrokerReview(Protocol):
    async def review_order(self, intent: OrderIntent) -> BrokerOrderReview: ...

class BrokerPlace(Protocol):
    async def place_order(self, submission: PersistedReviewedOrder) -> BrokerOrder: ...

class BrokerCancelOnly(Protocol):
    async def cancel_known_order(
        self, account_id: AccountId, order_id: BrokerOrderId,
    ) -> CancelReceipt: ...
```

Add the full `BrokerRead` signature from the index. Keep transport types out of the protocols. The architecture matrix forbids broker imports in strategies, portfolio, risk, research, reporting/LLM, monitoring, and recovery; forbids `BrokerPlace` imports in CLI and cancel-only recovery; allows runtime composition to receive a place factory only after all live gates; and permits the sole production `.place_order(...)` call in `execution/service.py`. Provider adapter files may define the method but never invoke it internally.

- [ ] **Step 4: Run boundary tests**

Run: `uv run pytest tests/unit/brokers/test_protocols.py tests/architecture/test_broker_imports.py -q`

Expected: PASS.

- [ ] **Step 5: Commit protocols**

```bash
git add src/trading_bot/brokers tests/unit/brokers tests/architecture
git commit -m "feat: define least-privilege broker capabilities"
```

### Task 7: Add structured redaction and baseline quality commands

**Files:**
- Create: `src/trading_bot/logging.py`
- Create: `tests/unit/test_logging.py`
- Create: `Makefile`
- Create: `Codex.md`
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `SecretRegistry`, `configure_logging(level: str) -> None`, and `redact_secrets(logger, method_name, event_dict) -> dict[str, object]`.
- Produces: `make format`, `lint`, `typecheck`, `test`, and `security` baseline targets.

- [ ] **Step 1: Write failing redaction tests**

```python
@pytest.mark.parametrize(
    "key",
    ["api_key", "private_key", "x-signature", "authorization", "cookie", "live_authorization"],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    event = redact_secrets(None, "info", {key: "secret", "safe": "visible"})
    assert event[key] == "[REDACTED]"
    assert event["safe"] == "visible"

def test_secret_in_generic_exception_text_is_redacted(secret_registry: SecretRegistry) -> None:
    secret_registry.register("actual-secret-value")
    event = redact_secrets(
        None, "error", {"error": "request failed with actual-secret-value"}
    )
    assert "actual-secret-value" not in json.dumps(event)

def test_account_query_value_is_masked() -> None:
    event = redact_secrets(
        None,
        "error",
        {"error": "https://host/path?account_number=RHC123456789&safe=true"},
    )
    assert "RHC123456789" not in json.dumps(event)
```

- [ ] **Step 2: Run the test and observe failure**

Run: `uv run pytest tests/unit/test_logging.py -q`

Expected: FAIL because logging configuration is missing.

- [ ] **Step 3: Implement recursive pre-serialization redaction**

```python
SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key", "private_key", "signature", "authorization", "cookie", "secret",
        "token", "account_id", "account_number",
    }
)

def redact_secrets(
    logger: object, method_name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    return {key: _redact(key, value) for key, value in event_dict.items()}
```

`SecretRegistry` receives credential values immediately after restricted-file loading, stores only in memory, and replaces exact matches in every nested string. Redaction then masks configured/recognized account identifiers, sensitive URL query parameters, header-like substrings, and multiline exception text before serialization. It recursively handles mappings, sequences, dataclasses, and exceptions; output truncation occurs after redaction. Configure Structlog JSON output with ISO UTC timestamps and ensure exceptions pass through the same processor. Tests scan serialized logs for fixture secrets, full account IDs, authorization headers, signature bytes, and query values.

- [ ] **Step 4: Add baseline Make and CI commands**

```make
format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest --cov=trading_bot --cov-branch

security:
	uv run bandit -c pyproject.toml -r src
	uv run pip-audit
```

CI runs lint, MyPy, and tests on Python 3.12, 3.13, and 3.14 with no secrets and no authenticated integration marker.

- [ ] **Step 5: Document the safe baseline**

State clearly in `README.md` and `Codex.md` that only capability/foundation code exists, Trading MCP is not currently configured, prediction live is unsupported, no live order was placed, and no profitability claim is made.

- [ ] **Step 6: Run the slice verification**

Run:

```bash
make lint
make typecheck
make test
make security
uv lock --check
```

Expected: all commands pass; coverage is reported without claiming the final repository threshold yet.

- [ ] **Step 7: Commit the quality baseline**

```bash
git add src/trading_bot/logging.py tests/unit/test_logging.py Makefile Codex.md README.md docs/architecture.md .github/workflows/ci.yml
git commit -m "chore: add structured logging and quality gates"
```

## Slice Completion Gate

Run:

```bash
git status --short
make lint
make typecheck
make test
make security
uv lock --check
```

Expected: clean worktree and all checks pass. `docs/capability-matrix.md` must state that `robinhood-trading` is not locally configured, MCP schemas are not yet reproducible, Crypto v2 is documented, prediction execution is unsupported, and no authenticated account or order action occurred.
