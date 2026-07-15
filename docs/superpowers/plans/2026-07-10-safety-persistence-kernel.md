# Safety, Persistence, and Risk Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable, broker-neutral safety kernel that makes every decision, risk check, state transition, authorization, reconciliation result, and recovery action explicit and auditable.

**Architecture:** Pure domain functions decide sizing, limits, transitions, and action permissions. Async repositories persist decisions and evidence attestations transactionally in SQLite WAL; broker capabilities are injected by protocol, and placement is absent unless a verified live lease exists.

**Tech Stack:** Python 3.12–3.14, Pydantic 2.13.4, SQLAlchemy 2.0.51 async ORM, Aiosqlite 0.22.1, Alembic 1.18.5, PyNaCl 1.6.2, Pytest 9.1.1, Hypothesis 6.156.6.

## Global Constraints

- All trading numerics use finite `Decimal`; all timestamps are aware UTC.
- Risk limits and operational thresholds come only from the validated configuration graph.
- A denied check never transitions to submission.
- No retry increases exposure without a new full risk evaluation.
- Unknown external orders, positions, fills, or accounts are material reconciliation drift.
- Reconciliation tolerance is zero except documented broker quantization.
- The kill switch blocks new orders and does not automatically liquidate positions.
- Existing protective orders remain resting while paused; new exposure-reducing writes follow the approved runtime action matrix.
- The authorization private key remains outside the service host; runtime code receives only a public verification key.
- A live activation artifact is one-time and short-lived; a live lease is bounded and cannot self-renew.
- Prediction live remains disabled; this plan contains no broker placement implementation.
- Risk and order-state code must reach at least 90% branch coverage.

---

### Task 1: Complete immutable broker-neutral domain records

**Files:**
- Modify: `src/trading_bot/domain/accounts.py`
- Modify: `src/trading_bot/domain/market.py`
- Modify: `src/trading_bot/domain/orders.py`
- Modify: `src/trading_bot/domain/decisions.py`
- Create: `src/trading_bot/domain/events.py`
- Test: `tests/unit/domain/test_accounts.py`
- Test: `tests/unit/domain/test_market.py`
- Test: `tests/unit/domain/test_orders.py`

**Interfaces:**
- Produces: `AccountSnapshot`, `Position`, `PortfolioSnapshot`, `Instrument`, `Quote`, `SpreadEstimate`, `Bar`, `MarketClock`, `OrderIntent`, `BrokerOrderReview`, `BrokerOrder`, `Fill`, `CancelReceipt`, `CheckResult`, `RiskEvaluation`, and `AuditEvent`.
- Consumes: identifiers, enums, decimals, and `require_utc` from Plan 1.

- [ ] **Step 1: Write failing domain-invariant tests**

```python
def test_quote_rejects_crossed_market() -> None:
    with pytest.raises(DomainValidationError, match="bid cannot exceed ask"):
        Quote(
            instrument_id=InstrumentId("AAPL"),
            bid=Decimal("101"),
            ask=Decimal("100"),
            last=Decimal("100.50"),
            observed_at=aware_now(),
            source="fixture",
            data_hash=DataHash("fixture-hash"),
            freshness_verified=True,
            timestamp_source=TimestampSource.PROVIDER,
        )

def test_order_intent_requires_exit_policy_for_entry() -> None:
    with pytest.raises(DomainValidationError, match="exit policy"):
        make_intent(purpose=OrderPurpose.ENTRY, exit_policy_version=None)
```

- [ ] **Step 2: Run domain tests and observe failure**

Run: `uv run pytest tests/unit/domain/test_accounts.py tests/unit/domain/test_market.py tests/unit/domain/test_orders.py -q`

Expected: FAIL with missing domain records.

- [ ] **Step 3: Implement immutable records with explicit validation**

```python
@dataclass(frozen=True, slots=True)
class Quote:
    instrument_id: InstrumentId
    bid: Decimal
    ask: Decimal
    last: Decimal | None
    observed_at: datetime
    source: str
    data_hash: DataHash
    freshness_verified: bool
    timestamp_source: TimestampSource

    def __post_init__(self) -> None:
        require_utc(self.observed_at)
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise DomainValidationError("bid and ask must be positive; bid cannot exceed ask")

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
```

Also define immutable `ReconciliationAttestation(clean, observed_at, evidence_hash)`, `LiveLeaseAttestation(valid, account_id, config_hash, expires_at, evidence_hash)`, `AlertAttestation(critical_count, observed_at, evidence_hash)`, `StrategyEligibilityAttestation(eligible, strategy_version, config_hash, code_hash, research_manifest_hash, report_hash, observed_at)`, and `PromotionAttestation(stage, eligible, evidence_hash, evaluated_at, expires_at)`. These are broker-neutral snapshots used by risk/runtime; later services create them without making core logic import reconciliation, authorization, monitoring, or research implementations.

Use `tuple` instead of mutable collections, reject nonfinite/negative numerics, enforce side/purpose consistency, require entry intents to carry a versioned exit policy, and keep raw provider payloads out of domain records. The internal deduplication key is derived and persisted by the execution service; it is not an `OrderIntent` field.

- [ ] **Step 4: Run and type-check domain tests**

Run:

```bash
uv run pytest tests/unit/domain -q
uv run mypy src/trading_bot/domain
```

Expected: PASS.

- [ ] **Step 5: Commit domain records**

```bash
git add src/trading_bot/domain tests/unit/domain
git commit -m "feat: add broker-neutral trading records"
```

### Task 2: Create SQLite WAL persistence and core migrations

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_core_ledger.py`
- Create: `src/trading_bot/persistence/__init__.py`
- Create: `src/trading_bot/persistence/base.py`
- Create: `src/trading_bot/persistence/models/__init__.py`
- Create: `src/trading_bot/persistence/models/accounts.py`
- Create: `src/trading_bot/persistence/models/market.py`
- Create: `src/trading_bot/persistence/models/decisions.py`
- Create: `src/trading_bot/persistence/models/orders.py`
- Create: `src/trading_bot/persistence/models/operations.py`
- Test: `tests/integration/persistence/test_migrations.py`
- Test: `tests/integration/persistence/test_wal.py`

**Interfaces:**
- Produces: `create_engine(database_url) -> AsyncEngine`, `async_session_factory(engine)`, and SQLAlchemy models for every approved ledger entity.

- [ ] **Step 1: Write failing migration and WAL tests**

```python
@pytest.mark.asyncio
async def test_sqlite_uses_wal_and_foreign_keys(database_url: str) -> None:
    engine = create_engine(database_url)
    async with engine.connect() as connection:
        journal = await connection.scalar(text("PRAGMA journal_mode"))
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
    assert str(journal).lower() == "wal"
    assert foreign_keys == 1

def test_upgrade_head_creates_required_tables(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    assert REQUIRED_TABLES <= inspect_table_names(alembic_config)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/persistence/test_migrations.py tests/integration/persistence/test_wal.py -q`

Expected: FAIL because engine and migrations are absent.

- [ ] **Step 3: Implement the async engine policy**

```python
def create_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection: object, _: object) -> None:
        cursor = cast(Any, dbapi_connection).cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    return engine
```

- [ ] **Step 4: Define the initial normalized schema**

The migration creates accounts, instruments, market snapshots, bars, data-quality events, features, signals, strategy decisions, risk evaluations, research-acceptance evidence, order intents, broker reviews, submission attempts, orders, order transitions, fills, positions, portfolio snapshots, equity curve, realized P/L, drawdown events, alerts, reconciliation events, promotion evidence, configuration versions, live authorizations, live leases, used nonces, kill-switch events, heartbeats, execution leases, and audit events. Money and quantity columns use fixed-precision numeric storage or canonical decimal strings; no SQLite float column stores trading values.

Enforce database uniqueness for local intent ID, one submission-attempt row per intent, provider plus broker-order ID, provider plus external execution key, activation nonce, promotion evidence hash, and audit event ID. `submission_attempts` stores intent ID, review ID, internal deduplication key, provider client reference when supported, fencing token, attempt-start UTC, outcome class, and sanitized response hash. These constraints exist before the execution and partial-fill tasks so a crash or duplicate event cannot create a second economic effect.

- [ ] **Step 5: Run migration tests**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/persistence/test_migrations.py tests/integration/persistence/test_wal.py -q
```

Expected: PASS and the database reports WAL mode.

- [ ] **Step 6: Commit persistence schema**

```bash
git add alembic.ini migrations src/trading_bot/persistence tests/integration/persistence
git commit -m "feat: add durable SQLite trading ledger"
```

### Task 3: Add unit of work, repositories, and append-only audit

**Files:**
- Create: `src/trading_bot/persistence/unit_of_work.py`
- Create: `src/trading_bot/persistence/repositories.py`
- Create: `src/trading_bot/persistence/audit.py`
- Create: `migrations/versions/0002_append_only_guards.py`
- Test: `tests/integration/persistence/test_unit_of_work.py`
- Test: `tests/integration/persistence/test_append_only.py`

**Interfaces:**
- Produces: `SqlAlchemyUnitOfWork`, `OrderRepository`, `SubmissionAttemptRepository`, `FillRepository`, `DataQualityRepository`, `AuditRepository`, `AuthorizationRepository`, `ReconciliationRepository`, and `EvidenceRepository`.
- Produces: `append_audit(event: AuditEvent) -> None`; no update/delete method exists for critical events.

- [ ] **Step 1: Write failing rollback and immutability tests**

```python
@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_order_and_audit_together(uow_factory: UowFactory) -> None:
    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await uow.orders.add(make_order_intent())
            await uow.audit.append(make_audit_event())
            raise RuntimeError("force rollback")
    assert await count_rows("order_intents") == 0
    assert await count_rows("audit_events") == 0

@pytest.mark.asyncio
async def test_audit_rows_cannot_be_updated(session: AsyncSession) -> None:
    event_id = await insert_audit_event(session)
    with pytest.raises(IntegrityError):
        await session.execute(update(AuditEventRow).where(AuditEventRow.id == event_id).values(reason="changed"))
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/persistence/test_unit_of_work.py tests/integration/persistence/test_append_only.py -q`

Expected: FAIL because repositories and triggers are missing.

- [ ] **Step 3: Implement async unit-of-work transactions**

```python
class SqlAlchemyUnitOfWork:
    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self.orders = SqlOrderRepository(self.session)
        self.audit = SqlAuditRepository(self.session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            await self.session.rollback()
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()
```

- [ ] **Step 4: Add insert-only database triggers**

Guard audit events, transitions, risk evaluations, configuration versions, authorizations, kill-switch events, and reconciliation events against update/delete. Corrections append compensating events referencing the original ID.

- [ ] **Step 5: Run persistence tests**

Run: `uv run pytest tests/integration/persistence -q`

Expected: PASS.

- [ ] **Step 6: Commit repositories and audit**

```bash
git add src/trading_bot/persistence migrations/versions/0002_append_only_guards.py tests/integration/persistence
git commit -m "feat: add transactional append-only audit"
```

### Task 4: Implement the pure order state machine

**Files:**
- Create: `src/trading_bot/execution/__init__.py`
- Create: `src/trading_bot/execution/state_machine.py`
- Test: `tests/unit/execution/test_state_machine.py`
- Test: `tests/property/execution/test_state_machine_properties.py`

**Interfaces:**
- Produces: `transition(current: OrderState, event: OrderEvent) -> OrderState` and `InvalidOrderTransition`.

- [ ] **Step 1: Write failing transition tests**

```python
def test_approved_order_can_be_reviewed() -> None:
    assert transition(OrderState.RISK_APPROVED, OrderEvent.REQUEST_REVIEW) is OrderState.REVIEW_REQUESTED

def test_rejected_order_cannot_submit() -> None:
    with pytest.raises(InvalidOrderTransition):
        transition(OrderState.RISK_REJECTED, OrderEvent.PREPARE_SUBMISSION)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/execution/test_state_machine.py -q`

Expected: FAIL because the transition function is missing.

- [ ] **Step 3: Implement the explicit transition table**

```python
TRANSITIONS: Final[dict[tuple[OrderState, OrderEvent], OrderState]] = {
    (OrderState.PROPOSED, OrderEvent.RISK_DENY): OrderState.RISK_REJECTED,
    (OrderState.PROPOSED, OrderEvent.RISK_ALLOW): OrderState.RISK_APPROVED,
    (OrderState.PROPOSED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.RISK_APPROVED, OrderEvent.REQUEST_REVIEW): OrderState.REVIEW_REQUESTED,
    (OrderState.RISK_APPROVED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.REVIEW_REQUESTED, OrderEvent.REVIEW_ACCEPTED): OrderState.REVIEWED,
    (OrderState.REVIEW_REQUESTED, OrderEvent.REVIEW_REJECTED): OrderState.REJECTED,
    (OrderState.REVIEW_REQUESTED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.REVIEWED, OrderEvent.FINAL_RISK_DENY): OrderState.RISK_REJECTED,
    (OrderState.REVIEWED, OrderEvent.PREPARE_SUBMISSION): OrderState.SUBMISSION_PENDING,
    (OrderState.REVIEWED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_ACCEPTED): OrderState.SUBMITTED,
    (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_REJECTED): OrderState.REJECTED,
    (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_AMBIGUOUS): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.SUBMITTED, OrderEvent.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.SUBMITTED, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.SUBMITTED, OrderEvent.REQUEST_CANCEL): OrderState.CANCEL_PENDING,
    (OrderState.SUBMITTED, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
    (OrderState.SUBMITTED, OrderEvent.RECONCILIATION_DRIFT): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.PARTIALLY_FILLED, OrderEvent.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.PARTIALLY_FILLED, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.PARTIALLY_FILLED, OrderEvent.REQUEST_CANCEL): OrderState.CANCEL_PENDING,
    (OrderState.PARTIALLY_FILLED, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
    (OrderState.PARTIALLY_FILLED, OrderEvent.RECONCILIATION_DRIFT): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.CANCEL_PENDING, OrderEvent.CANCEL_CONFIRMED): OrderState.CANCELED,
    (OrderState.CANCEL_PENDING, OrderEvent.CANCEL_REJECTED): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.CANCEL_PENDING, OrderEvent.PARTIAL_FILL): OrderState.CANCEL_PENDING,
    (OrderState.CANCEL_PENDING, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.CANCEL_PENDING, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
    (OrderState.CANCEL_PENDING, OrderEvent.RECONCILIATION_DRIFT): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.CANCEL_PENDING, OrderEvent.BROKER_AMBIGUOUS): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderEvent.RECONCILE_SUBMITTED): OrderState.SUBMITTED,
    (OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderEvent.RECONCILE_PARTIAL): OrderState.PARTIALLY_FILLED,
    (OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderEvent.RECONCILE_FILLED): OrderState.FILLED,
    (OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderEvent.RECONCILE_CANCELED): OrderState.CANCELED,
    (OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderEvent.RECONCILE_REJECTED): OrderState.REJECTED,
    (OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderEvent.RECONCILE_EXPIRED): OrderState.EXPIRED,
}
```

This is the complete transition table. `EXPIRE` is valid only before broker acceptance. After acceptance, only a broker-confirmed `BROKER_EXPIRED` or reconciled `RECONCILE_EXPIRED` can move an order specifically to `EXPIRED`, so a local deadline can never hide a resting order; fills, confirmed cancellations, and other reconciled terminal outcomes retain their distinct states. Reconciliation drift discovered for a known submitted, partially filled, or cancel-pending order must first use `RECONCILIATION_DRIFT`; the resulting unknown state accepts only explicit reconciliation outcomes. Reconciliation events assert broker-backed facts; the later reconciliation service must reject `RECONCILE_SUBMITTED` or `RECONCILE_REJECTED` when any cumulative durable or broker-reported fill exists, and no state transition may delete or reset fill records. `RISK_REJECTED`, `REJECTED`, `FILLED`, `CANCELED`, and `EXPIRED` are terminal. A partial fill received while cancellation is pending keeps the state at `CANCEL_PENDING`; its cumulative fill quantity is persisted separately. No terminal state has an outgoing transition.

- [ ] **Step 4: Add property invariants**

```python
@given(events=lists(sampled_from(list(OrderEvent)), max_size=30))
def test_risk_rejected_never_reaches_submitted(events: list[OrderEvent]) -> None:
    state = OrderState.RISK_REJECTED
    for event in events:
        try:
            state = transition(state, event)
        except InvalidOrderTransition:
            pass
    assert state not in {OrderState.SUBMISSION_PENDING, OrderState.SUBMITTED, OrderState.FILLED}
```

- [ ] **Step 5: Verify 90% branch coverage locally**

Run: `uv run pytest tests/unit/execution tests/property/execution --cov=trading_bot.execution.state_machine --cov-branch --cov-fail-under=90`

Expected: PASS with at least 90% branch coverage.

- [ ] **Step 6: Commit state machine**

```bash
git add src/trading_bot/execution tests/unit/execution tests/property/execution
git commit -m "feat: add auditable order state machine"
```

### Task 5: Implement unit-consistent position sizing and exposure limits

**Files:**
- Create: `src/trading_bot/portfolio/__init__.py`
- Create: `src/trading_bot/portfolio/sizing.py`
- Create: `src/trading_bot/portfolio/correlation.py`
- Create: `src/trading_bot/risk/__init__.py`
- Create: `src/trading_bot/risk/models.py`
- Create: `src/trading_bot/risk/limits.py`
- Test: `tests/unit/risk/test_sizing.py`
- Test: `tests/unit/risk/test_limits.py`
- Test: `tests/property/risk/test_sizing_properties.py`

**Interfaces:**
- Produces: `SizingRequest`, `SizingDecision`, `size_position`, `ExposureSnapshot`, and `evaluate_exposure_limits`.

- [ ] **Step 1: Write failing sizing tests**

```python
def test_position_size_uses_smaller_quantity_cap() -> None:
    decision = size_position(
        SizingRequest(
            reconciled_equity=Decimal("100"),
            authorized_risk_equity=Decimal("100"),
            risk_pct=Decimal("0.50"),
            stop_distance_per_unit=Decimal("1"),
            entry_price=Decimal("10"),
            max_position_notional_pct=Decimal("15"),
            quantity_increment=Decimal("0.001"),
            minimum_notional=Decimal("1"),
        )
    )
    assert decision.quantity == Decimal("0.500")
    assert decision.notional == Decimal("5.000")

def test_unrealized_or_winning_streak_growth_does_not_auto_scale_live_risk() -> None:
    baseline = live_sizing_request(reconciled_equity="100", authorized_risk_equity="100")
    higher = live_sizing_request(reconciled_equity="120", authorized_risk_equity="100")
    assert size_position(higher).risk_budget == size_position(baseline).risk_budget
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/risk/test_sizing.py -q`

Expected: FAIL with missing sizing implementation.

- [ ] **Step 3: Implement quantity-to-quantity comparison**

```python
def size_position(request: SizingRequest) -> SizingDecision:
    if request.stop_distance_per_unit <= 0 or request.entry_price <= 0:
        return SizingDecision.denied("invalid_stop_or_entry_price")
    risk_equity = min(request.reconciled_equity, request.authorized_risk_equity)
    risk_budget = risk_equity * request.risk_pct / Decimal("100")
    risk_quantity = risk_budget / request.stop_distance_per_unit
    max_notional = risk_equity * request.max_position_notional_pct / Decimal("100")
    notional_quantity = max_notional / request.entry_price
    quantity = quantize_down(min(risk_quantity, notional_quantity), request.quantity_increment)
    notional = quantity * request.entry_price
    risk = quantity * request.stop_distance_per_unit
    return SizingDecision.validate_final(quantity=quantity, notional=notional, risk=risk, request=request)
```

Backtest/paper set `authorized_risk_equity` to the run's fixed starting-capital reference. Live authorization signs the reference equity for the lease. Losses reduce `reconciled_equity` and therefore size immediately; gains never increase the risk reference until a new preflight and manual authorization. Consecutive losses/wins do not otherwise alter risk percentage or quantity.

- [ ] **Step 4: Add exposure and correlation checks**

Test total gross, open position count, per-position notional, correlated-group exposure, total crypto, single crypto, and cash reserve. Every denial includes a stable code and observed/configured values.

- [ ] **Step 5: Add property tests**

```python
@given(valid_sizing_requests())
def test_approved_sizing_never_exceeds_budget(request: SizingRequest) -> None:
    decision = size_position(request)
    if decision.allowed:
        risk_equity = min(request.reconciled_equity, request.authorized_risk_equity)
        assert decision.risk <= risk_equity * request.risk_pct / Decimal("100")
        assert decision.notional <= risk_equity * request.max_position_notional_pct / Decimal("100")
```

- [ ] **Step 6: Run risk tests**

Run: `uv run pytest tests/unit/risk tests/property/risk -q`

Expected: PASS.

- [ ] **Step 7: Commit sizing and limits**

```bash
git add src/trading_bot/portfolio src/trading_bot/risk tests/unit/risk tests/property/risk
git commit -m "feat: add bounded position sizing and exposure limits"
```

### Task 6: Implement loss, drawdown, and activity gates

**Files:**
- Create: `src/trading_bot/risk/losses.py`
- Test: `tests/unit/risk/test_losses.py`
- Test: `tests/property/risk/test_loss_properties.py`

**Interfaces:**
- Produces: `LossSnapshot`, `ActivitySnapshot`, `LossDecision`, `evaluate_loss_limits`, and `evaluate_activity_limits`.

- [ ] **Step 1: Write failing boundary tests**

```python
def test_daily_limit_blocks_new_entries_at_exact_threshold() -> None:
    decision = evaluate_loss_limits(
        snapshot=loss_snapshot(daily_loss_pct=Decimal("2")),
        settings=default_loss_settings(),
        purpose=OrderPurpose.ENTRY,
    )
    assert not decision.new_entries_allowed
    assert decision.cancel_unfilled_entries
    assert decision.reason_code == "daily_loss_limit_reached"
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/risk/test_losses.py -q`

Expected: FAIL with missing loss gates.

- [ ] **Step 3: Implement deterministic UTC boundaries**

Daily state resets only on a configured trading-session boundary after reconciliation; weekly state resets at the configured UTC week boundary only after manual review. Three consecutive losses create a 240-minute entry pause. Drawdown at 10% requests kill-switch activation but never liquidation.

- [ ] **Step 4: Add activity-limit property tests**

```python
@given(count=integers(min_value=3, max_value=1000))
def test_daily_order_limit_always_blocks_at_or_above_three(count: int) -> None:
    assert not evaluate_activity_limits(activity_snapshot(new_orders_today=count), default_activity()).allowed
```

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/unit/risk/test_losses.py tests/property/risk/test_loss_properties.py -q`

Expected: PASS.

```bash
git add src/trading_bot/risk/losses.py tests/unit/risk/test_losses.py tests/property/risk/test_loss_properties.py
git commit -m "feat: add loss drawdown and activity gates"
```

### Task 7: Implement all 24 final pretrade checks

**Files:**
- Create: `src/trading_bot/risk/pretrade.py`
- Test: `tests/unit/risk/test_pretrade.py`
- Test: `tests/property/risk/test_pretrade_properties.py`

**Interfaces:**
- Produces: `InitialRiskContext`, `FinalPretradeContext`, `InstrumentEligibility`, `ExposureProjection`, `ExecutionCostEstimate`, `PretradeEngine.evaluate_initial(context) -> RiskEvaluation`, and `PretradeEngine.evaluate_final(context) -> RiskEvaluation` exactly as defined in the index.
- Produces: one `PretradeCheckCode` enum member for each approved check.

- [ ] **Step 1: Write a failing parameterized denial test**

```python
@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (without_live_lease, "live_authorization"),
        (with_kill_switch, "kill_switch"),
        (with_stale_quote, "market_data_freshness"),
        (with_account_mismatch, "account_allowlist"),
        (with_dirty_reconciliation, "reconciliation"),
    ],
)
def test_each_failed_check_denies(mutator: ContextMutator, expected_code: str) -> None:
    result = PretradeEngine(default_config()).evaluate_final(mutator(valid_pretrade_context()))
    assert not result.allowed
    assert expected_code in {check.code for check in result.checks if not check.allowed}
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/risk/test_pretrade.py -q`

Expected: FAIL with missing pretrade engine.

- [ ] **Step 3: Implement stable check codes in approved order**

```python
class PretradeCheckCode(StrEnum):
    LIVE_AUTHORIZATION = "live_authorization"
    KILL_SWITCH = "kill_switch"
    ACCOUNT_ALLOWLIST = "account_allowlist"
    BROKER_HEALTH = "broker_health"
    MARKET_DATA_FRESHNESS = "market_data_freshness"
    SYMBOL_TRADABILITY = "symbol_tradability"
    FRACTIONAL_ELIGIBILITY = "fractional_eligibility"
    MARKET_SESSION = "market_session"
    MARKET_HALT = "market_halt"
    BUYING_POWER = "buying_power"
    CASH_RESERVE = "cash_reserve"
    POSITION_CAP = "position_cap"
    CORRELATION_CAP = "correlation_cap"
    CRYPTO_CAP = "crypto_cap"
    LOSS_LIMITS = "loss_limits"
    ACTIVITY_LIMITS = "activity_limits"
    SPREAD = "spread"
    SLIPPAGE = "slippage"
    AFTER_COST_EDGE = "after_cost_edge"
    DUPLICATE_ORDER = "duplicate_order"
    EXIT_POLICY = "exit_policy"
    REVIEW_MATCH = "review_match"
    BROKER_MINIMUMS = "broker_minimums"
    RECONCILIATION = "reconciliation"
```

- [ ] **Step 4: Evaluate every check without unsafe short-circuiting**

```python
def evaluate_final(self, context: FinalPretradeContext) -> RiskEvaluation:
    checks = tuple(check(context, self._config) for check in self._checks)
    return RiskEvaluation(
        intent_id=context.initial.intent.id,
        allowed=all(result.allowed for result in checks),
        checks=checks,
        evaluated_at=context.initial.observed_at,
        config_hash=context.initial.intent.config_hash,
    )
```

`evaluate_initial` accepts `InitialRiskContext` and runs the same ordered check functions except `REVIEW_MATCH`, producing exactly 23 results. `evaluate_final` accepts a newly loaded `FinalPretradeContext` and runs all 24. There is one implementation per check; the preliminary pass cannot maintain a competing rule set. When an upstream prerequisite is unavailable, the dependent check returns an explicit denial rather than raising or assuming a value. Simulation marks only live authorization as not applicable and cannot construct a network write adapter.

Implement the exact inputs and decision for each final check:

| Code | Required input | Allow condition |
|---|---|---|
| `LIVE_AUTHORIZATION` | lease attestation, runtime state, critical-alert attestation, strategy eligibility | lease is valid, unexpired, account/config/stage match, runtime permits the action, no unresolved critical alert exists, and the exact strategy/config/code version has accepted research evidence; simulation uses an explicit not-applicable attestation |
| `KILL_SWITCH` | filesystem/database switch attestation | both inactive at `observed_at` |
| `ACCOUNT_ALLOWLIST` | account snapshot and configured allowlist | exact account ID is allowed, active/unrestricted, unchanged, and at or below configured equity ceiling |
| `BROKER_HEALTH` | broker health | healthy and no older than configured 30-second maximum |
| `MARKET_DATA_FRESHNESS` | quote and current time | identity/hash valid, `freshness_verified`, and no older than configured 5-second executable maximum |
| `SYMBOL_TRADABILITY` | instrument eligibility | symbol allowlisted, provider tradable, asset policy eligible, and configured earnings/liquidity/price filters clear |
| `FRACTIONAL_ELIGIBILITY` | quantity and instrument eligibility | integer quantity or current fractional eligibility is verified |
| `MARKET_SESSION` | market clock and order policy | venue/session accepts this order type now; crypto pair status is active |
| `MARKET_HALT` | market clock/instrument status | no halt, cancel-only, trading-disabled, or provider restriction |
| `BUYING_POWER` | authoritative asset-class buying power and projected debit | buying power covers notional plus fees without using margin |
| `CASH_RESERVE` | exposure projection | projected cash/equity remains at or above configured reserve |
| `POSITION_CAP` | exposure projection | projected symbol notional and open-position count remain within caps |
| `CORRELATION_CAP` | exposure projection | projected correlation-group notional remains within cap |
| `CRYPTO_CAP` | exposure projection | projected total and single-asset crypto notionals remain within caps |
| `LOSS_LIMITS` | reconciled loss/drawdown snapshot | daily, weekly, drawdown, and consecutive-loss pause gates all allow this purpose |
| `ACTIVITY_LIMITS` | activity snapshot | daily, per-symbol, and spacing limits all allow this new order |
| `SPREAD` | execution cost estimate | verified spread percentage is at or below the asset-class maximum |
| `SLIPPAGE` | execution cost estimate | estimated slippage percentage is at or below the configured maximum |
| `AFTER_COST_EDGE` | execution cost estimate | expected edge after spread, slippage, fees, and commission is positive and reward/risk meets the configured minimum |
| `DUPLICATE_ORDER` | broker open orders plus local pending intents | no same-account/instrument/purpose conflict or unresolved submission exists |
| `EXIT_POLICY` | intent and current position | entry has a versioned stop/exit policy; exit is linked to an existing position and cannot increase exposure |
| `REVIEW_MATCH` | persisted review and intent | review is fresh, exact normalized fields match, and rebuilt outbound payload hash matches |
| `BROKER_MINIMUMS` | instrument increments/min/max and intent | quantity/price are exactly quantized and resulting quantity/notional are within current broker bounds |
| `RECONCILIATION` | reconciliation attestation | clean, current, exact-account evidence with no unknown order/position/fill |

`InitialRiskContext` contains every field above except `reviewed_order`; `FinalPretradeContext` contains an `initial: InitialRiskContext` plus `reviewed_order`. `PretradeContextLoader.load_initial(intent)` and `.load_final(intent, review)` perform fresh reads and build immutable contexts. Neither context reads global state from inside a check.

- [ ] **Step 5: Prove invariants with Hypothesis**

Parameterize one denial fixture for every code in the table, then add property tests for negative/nonfinite prices, stale data, disabled markets, duplicate orders, exposure caps, cash reserve, and review mismatch. An allowed preliminary result must have exactly 23 allowed checks; an allowed final result must have exactly 24 allowed checks.

- [ ] **Step 6: Verify branch coverage**

Run: `uv run pytest tests/unit/risk/test_pretrade.py tests/property/risk/test_pretrade_properties.py --cov=trading_bot.risk.pretrade --cov-branch --cov-fail-under=90`

Expected: PASS with at least 90% branch coverage.

- [ ] **Step 7: Commit pretrade engine**

```bash
git add src/trading_bot/risk/pretrade.py tests/unit/risk/test_pretrade.py tests/property/risk/test_pretrade_properties.py
git commit -m "feat: enforce final pretrade checklist"
```

### Task 8: Add the broker-neutral durable execution pipeline

**Files:**
- Create: `src/trading_bot/execution/review.py`
- Create: `src/trading_bot/execution/idempotency.py`
- Create: `src/trading_bot/execution/exclusion.py`
- Create: `src/trading_bot/execution/service.py`
- Test: `tests/unit/execution/test_review.py`
- Test: `tests/unit/execution/test_idempotency.py`
- Test: `tests/unit/execution/test_exclusion.py`
- Test: `tests/integration/execution/test_service.py`

**Interfaces:**
- Produces: `OrderReviewService`, `derive_deduplication_key`, `SubmissionExclusion`, `InProcessSubmissionExclusion`, `ExecutionService.execute`, and `ExecutionResult`.
- Consumes: `BrokerReview`, `BrokerPlace`, `PretradeEngine`, unit of work, and a `PretradeContextLoader` that refreshes final state.

- [ ] **Step 1: Write failing end-to-end fake-broker tests**

```python
@pytest.mark.asyncio
async def test_denied_initial_risk_never_reviews_or_places(harness: ExecutionHarness) -> None:
    harness.initial_risk.allowed = False
    result = await harness.service.execute(harness.intent)
    assert result.state is OrderState.RISK_REJECTED
    assert harness.review.calls == 0
    assert harness.place.calls == 0

@pytest.mark.asyncio
async def test_safe_fake_order_persists_before_place(harness: ExecutionHarness) -> None:
    result = await harness.service.execute(harness.intent)
    assert result.state is OrderState.SUBMITTED
    assert harness.place.observed_persisted_state is OrderState.SUBMISSION_PENDING

@pytest.mark.asyncio
async def test_in_process_exclusion_rejects_overlap() -> None:
    exclusion = InProcessSubmissionExclusion()
    async with exclusion.acquire(AccountId("acct")):
        with pytest.raises(SubmissionAlreadyInProgress):
            async with exclusion.acquire(AccountId("acct")):
                pass
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/execution/test_review.py tests/unit/execution/test_idempotency.py tests/unit/execution/test_exclusion.py tests/integration/execution/test_service.py -q`

Expected: FAIL with missing pipeline.

- [ ] **Step 3: Implement stable review matching and deduplication**

```python
def derive_deduplication_key(intent: OrderIntent) -> str:
    canonical = f"{intent.account_id}|{intent.id}|{intent.config_hash}|{intent.purpose}"
    return hashlib.sha256(canonical.encode()).hexdigest()

def review_matches_intent(review: BrokerOrderReview, intent: OrderIntent) -> bool:
    return review.normalized_order.matching_tuple() == intent.matching_tuple()
```

The SHA-256 deduplication key is an internal persistence key. The official Crypto `client_order_id` is `ClientOrderId(str(intent.id))`, derived from the already-persisted UUID; never substitute the SHA-256 digest into a UUID field. `SubmissionExclusion.acquire(account_id)` is an async context-manager protocol. Simulation uses `InProcessSubmissionExclusion`; Plan 5 supplies the filesystem-backed production implementation.

- [ ] **Step 4: Implement the single durable sequence**

Persist `PROPOSED`; load `InitialRiskContext`; run and persist the 23-check preliminary evaluation; on allow transition to `RISK_APPROVED`; request/persist review; acquire the submission exclusion primitive; only then load a new `FinalPretradeContext`, run/persist all 24 final checks, and recheck current time against quote/review/lease expirations; on denial transition from `REVIEWED` to `RISK_REJECTED`; on allow atomically reserve a unique submission attempt, commit `SUBMISSION_PENDING`, and construct `PersistedReviewedOrder` with the current fencing token plus lease/account/config attestations; call `BrokerPlace` exactly once with that object; persist accepted/rejected/ambiguous outcome before releasing exclusion. Simulation supplies an in-process fake exclusion/place capability and marks only live authorization not applicable.

- [ ] **Step 5: Verify the final-risk-denial transition in the service**

Exercise the existing `(OrderState.REVIEWED, OrderEvent.FINAL_RISK_DENY) -> OrderState.RISK_REJECTED` transition and assert that the review is durably retained, every final check is journaled, and no place call occurs.

- [ ] **Step 6: Run and commit**

Run: `uv run pytest tests/unit/execution tests/property/execution tests/integration/execution/test_service.py -q`

Expected: PASS with one common pipeline for fake and future official adapters.

```bash
git add src/trading_bot/execution tests/unit/execution tests/property/execution tests/integration/execution/test_service.py
git commit -m "feat: add durable broker-neutral execution pipeline"
```

### Task 9: Implement runtime action policy and kill switch

**Files:**
- Create: `src/trading_bot/risk/action_policy.py`
- Create: `src/trading_bot/risk/kill_switch.py`
- Test: `tests/unit/risk/test_action_policy.py`
- Test: `tests/integration/risk/test_kill_switch.py`

**Interfaces:**
- Produces: `ActionContext` and `is_action_allowed(state, action, context) -> ActionDecision`.
- Produces: `FileKillSwitch.status()`, `.activate(reason)`, and `.clear(request)`.

- [ ] **Step 1: Write the complete action-matrix tests**

```python
@pytest.mark.parametrize("state", list(RuntimeState))
@pytest.mark.parametrize("action", list(BrokerAction))
def test_runtime_action_matrix_covers_all_24_cells(
    state: RuntimeState, action: BrokerAction
) -> None:
    result = is_action_allowed(state, action, fully_attested_action_context())
    assert result.allowed is EXPECTED_ACTION_MATRIX[(state, action)]

def test_cancel_requires_positive_ownership_and_risk_reduction() -> None:
    context = replace(
        fully_attested_action_context(), order_owned=False, cancellation_reduces_risk=False
    )
    assert not is_action_allowed(
        RuntimeState.KILL_SWITCH_ACTIVE, BrokerAction.CANCEL_KNOWN_ENTRY, context
    ).allowed
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/risk/test_action_policy.py tests/integration/risk/test_kill_switch.py -q`

Expected: FAIL with missing policies.

- [ ] **Step 3: Implement the complete conditional matrix and atomic filesystem switch**

`BrokerAction` contains `NEW_ENTRY`, `REDUCE_EXPOSURE`, `CANCEL_KNOWN_ENTRY`, and `CANCEL_PROTECTIVE_EXIT`. `ActionContext` contains `lease_valid`, `account_authenticated`, `order_owned`, `broker_state_current`, `cancellation_reduces_risk`, `replacement_is_deterministic`, `explicit_operator_action`, and `last_reconciled_state`.

Encode all 24 cells from the approved design: `RUNNING_LIVE` permits risk-approved entry/reduce-only actions with a lease, known-entry cancellation, and protective-exit cancellation only for deterministic replacement or explicit operator action; `ENTRY_BLOCKED` permits only non-increasing reduce-only actions and known-entry cancellation; `PAUSED` permits only positively owned/current known-entry cancellation that reduces risk; `KILL_SWITCH_ACTIVE` requires that same safe entry cancellation when broker health permits; `RECONCILIATION_REQUIRED` permits only positively identified local entry cancellation; `SHUTTING_DOWN` permits only known-entry cancellation justified by the last reconciled state. No state automatically cancels a protective exit. Cancel-only actions do not require an entry lease, but all require authenticated account, ownership, current broker state, risk reduction, and auditability.

Use `os.open(..., O_CREAT | O_EXCL, 0o600)` for kill-switch activation and `os.replace` for audited updates. `clear` requires no active breach, clean reconciliation, explicit acknowledgement, and a nonempty reason. Existing protective orders are never automatically canceled.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/unit/risk/test_action_policy.py tests/integration/risk/test_kill_switch.py -q`

Expected: PASS.

```bash
git add src/trading_bot/risk/action_policy.py src/trading_bot/risk/kill_switch.py tests/unit/risk/test_action_policy.py tests/integration/risk/test_kill_switch.py
git commit -m "feat: add runtime action policy and kill switch"
```

### Task 10: Implement signed preflight, one-time activation, and live leases

**Files:**
- Create: `src/trading_bot/authorization/__init__.py`
- Create: `src/trading_bot/authorization/models.py`
- Create: `src/trading_bot/authorization/signing.py`
- Create: `src/trading_bot/authorization/verifier.py`
- Create: `src/trading_bot/authorization/preflight.py`
- Test: `tests/unit/authorization/test_signing.py`
- Test: `tests/unit/authorization/test_verifier.py`
- Test: `tests/integration/authorization/test_nonce_and_lease.py`

**Interfaces:**
- Produces: `PreflightReport`, `SignedActivationArtifact`, `LiveAuthorization`, `LiveLease`, `sign_activation`, `verify_activation`, and `consume_activation`.

- [ ] **Step 1: Write failing signature and replay tests**

```python
def test_tampered_artifact_is_rejected(key_pair: TestKeyPair) -> None:
    signed = sign_activation(valid_unsigned_artifact(), key_pair.private_key)
    tampered = replace(signed, payload=replace(signed.payload, account_id=AccountId("other")))
    with pytest.raises(InvalidAuthorization, match="signature"):
        verify_activation(tampered, key_pair.public_key, now=aware_now())

@pytest.mark.asyncio
async def test_activation_nonce_is_one_time(authorization_store: AuthorizationStore) -> None:
    artifact = valid_signed_artifact()
    await consume_activation(artifact, authorization_store)
    with pytest.raises(InvalidAuthorization, match="already used"):
        await consume_activation(artifact, authorization_store)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/authorization tests/integration/authorization -q`

Expected: FAIL with missing authorization code.

- [ ] **Step 3: Implement canonical signed payloads**

```python
def canonical_payload(payload: ActivationPayload) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()

def sign_activation(payload: ActivationPayload, signing_key: SigningKey) -> SignedActivationArtifact:
    signature = signing_key.sign(canonical_payload(payload)).signature
    return SignedActivationArtifact(payload=payload, signature_b64=base64.b64encode(signature).decode())
```

Runtime modules import only `VerifyKey`; an architecture test rejects `SigningKey` imports outside operator-side signing code and tests.

The operator command reads `TRADING_BOT_AUTH_SIGNING_KEY_FILE`, requires a mode-`0600` 32-byte Ed25519 seed, and refuses to run on the service host profile. The runtime reads only `TRADING_BOT_AUTH_VERIFY_KEY_FILE`, validates a mode-`0644` or stricter public key file, and rejects any configured signing-key path. Signing/private material is never included in deployment, backups, or the service container.

- [ ] **Step 4: Enforce time, account, config, acknowledgement, and evidence**

Verify five-minute preflight freshness, 15-minute one-time activation TTL, exact acknowledgement hash, account allowlist, $150 equity ceiling, signed risk-reference equity, clean code identity/OCI digest, code/config/preflight hashes, exact strategy-eligibility hash, requested-stage promotion-evidence hash, inactive kill switch, clean reconciliation, risk self-test, clock drift, and no critical alerts. Create an eight-hour live lease capped by the 24-hour safety envelope. The lease fixes `authorized_risk_equity` at or below reconciled preflight equity, so gains cannot auto-scale size. Any code/config/strategy/promotion hash change invalidates the artifact. Renewal requires a newly signed artifact.

- [ ] **Step 5: Run authorization tests and commit**

Run: `uv run pytest tests/unit/authorization tests/integration/authorization -q`

Expected: PASS.

```bash
git add src/trading_bot/authorization tests/unit/authorization tests/integration/authorization
git commit -m "feat: add signed live authorization leases"
```

### Task 11: Implement zero-tolerance reconciliation

**Files:**
- Create: `src/trading_bot/reconciliation/__init__.py`
- Create: `src/trading_bot/reconciliation/models.py`
- Create: `src/trading_bot/reconciliation/service.py`
- Test: `tests/unit/reconciliation/test_diff.py`
- Test: `tests/integration/reconciliation/test_service.py`

**Interfaces:**
- Produces: `ReconciliationDifference`, `ReconciliationResult`, and `ReconciliationService.reconcile(account_id)`.

- [ ] **Step 1: Write failing drift tests**

```python
@pytest.mark.asyncio
async def test_unexpected_broker_order_is_material(service: ReconciliationService) -> None:
    service.broker.open_orders = (unexpected_broker_order(),)
    result = await service.reconcile(AccountId("acct"))
    assert not result.clean
    assert result.differences[0].code == "unexpected_broker_order"
    assert result.differences[0].material

@pytest.mark.parametrize("outcome", [OrderEvent.RECONCILE_SUBMITTED, OrderEvent.RECONCILE_REJECTED])
async def test_fill_provenance_blocks_incompatible_reconciliation_outcome(
    service: ReconciliationService, outcome: OrderEvent
) -> None:
    service.local.fills = (persisted_partial_fill(),)
    with pytest.raises(IncompatibleReconciliationOutcome):
        await service.apply_outcome(outcome)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/reconciliation tests/integration/reconciliation -q`

Expected: FAIL with missing reconciliation service.

- [ ] **Step 3: Implement explicit comparisons**

Compare account identity/state, positions, open and recent orders, executions/fills, quantities, buying power, and local pending submissions. Quantization tolerance comes from current instrument metadata; no generic monetary drift is ignored. Reconciliation derives an order event only after comparing cumulative persisted and broker-reported fills. Any positive fill blocks `RECONCILE_SUBMITTED` and `RECONCILE_REJECTED`; a transition never deletes, resets, or implicitly interprets that fill as zero.

- [ ] **Step 4: Persist the complete result atomically**

Write the result and every difference to append-only reconciliation tables. Material drift sets runtime state `RECONCILIATION_REQUIRED` and revokes any live lease.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/unit/reconciliation tests/integration/reconciliation -q`

Expected: PASS.

```bash
git add src/trading_bot/reconciliation tests/unit/reconciliation tests/integration/reconciliation
git commit -m "feat: add fail-closed broker reconciliation"
```

### Task 12: Add execution leases, recovery, and risk self-test

**Files:**
- Create: `src/trading_bot/persistence/lease.py`
- Create: `src/trading_bot/execution/recovery.py`
- Create: `src/trading_bot/risk/self_test.py`
- Test: `tests/integration/persistence/test_execution_lease.py`
- Test: `tests/integration/execution/test_recovery.py`
- Test: `tests/unit/risk/test_self_test.py`
- Test: `tests/chaos/test_stale_leader.py`

**Interfaces:**
- Produces: `ExecutionLease`, `LeaseRepository.acquire/renew/release`, `RecoveryService.recover(account_id)`, and `run_risk_self_test() -> SelfTestResult`.

- [ ] **Step 1: Write failing fencing and recovery tests**

```python
@pytest.mark.asyncio
async def test_stale_fencing_token_cannot_renew(lease_repo: LeaseRepository) -> None:
    first = await lease_repo.acquire(AccountId("acct"), owner="one")
    second = await lease_repo.take_over_expired(AccountId("acct"), owner="two")
    with pytest.raises(StaleFencingToken):
        await lease_repo.renew(first)
    assert second.fencing_token > first.fencing_token

@pytest.mark.asyncio
async def test_recovery_uses_cancel_only_capability(recovery: RecoveryService) -> None:
    await recovery.recover(AccountId("acct"))
    assert not hasattr(recovery.broker_cancel, "place_order")
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/persistence/test_execution_lease.py tests/integration/execution/test_recovery.py tests/unit/risk/test_self_test.py -q`

Expected: FAIL with missing lease/recovery/self-test code.

- [ ] **Step 3: Implement transactional lease fencing**

Acquire and takeover use `BEGIN IMMEDIATE` under SQLite, monotonically increase the fencing token, and compare owner/token/expiry on every renewal. A placement request later carries the current fencing token.

- [ ] **Step 4: Implement paused startup recovery**

Load durable state, verify exact account, fetch positions/open/recent orders/fills, reconcile, retain existing protective orders, cancel only positively identified unfilled entries when action policy allows, and leave runtime paused. Recovery receives `BrokerRead` and `BrokerCancelOnly`; it cannot import `BrokerPlace`.

- [ ] **Step 5: Implement deterministic risk self-test vectors**

```python
SELF_TEST_CASES = (
    SelfTestCase("reject_stale_quote", stale_quote_context(), expected_allowed=False),
    SelfTestCase("reject_overexposure", overexposed_context(), expected_allowed=False),
    SelfTestCase("allow_safe_micro_order", safe_micro_context(), expected_allowed=True),
    SelfTestCase("reject_kill_switch", kill_switch_context(), expected_allowed=False),
)
```

Return a content hash over test names, inputs, and results; preflight stores the successful hash.

- [ ] **Step 6: Run safety-kernel verification**

Run:

```bash
uv run pytest tests/unit/risk tests/property/risk tests/unit/execution tests/property/execution tests/integration/persistence tests/integration/reconciliation tests/integration/execution tests/chaos/test_stale_leader.py --cov=trading_bot.risk --cov=trading_bot.execution --cov-branch
uv run ruff check src/trading_bot tests
uv run mypy src
```

Expected: all pass; risk and state-machine branch coverage are at least 90%.

- [ ] **Step 7: Commit lease, recovery, and self-test**

```bash
git add src/trading_bot/persistence/lease.py src/trading_bot/execution/recovery.py src/trading_bot/risk/self_test.py tests
git commit -m "feat: add fenced recovery and risk self-test"
```

## Slice Completion Gate

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/unit/domain tests/unit/risk tests/property/risk tests/unit/execution tests/property/execution tests/unit/authorization tests/integration/persistence tests/integration/authorization tests/integration/reconciliation tests/integration/execution tests/chaos/test_stale_leader.py --cov=trading_bot.risk --cov=trading_bot.execution --cov-branch
uv run ruff check .
uv run mypy src
git status --short
```

Expected: clean worktree; all checks pass; risk and order-state branch coverage are at least 90%; no broker placement implementation exists; startup recovery is limited to reads and positively identified cancel-only actions.
