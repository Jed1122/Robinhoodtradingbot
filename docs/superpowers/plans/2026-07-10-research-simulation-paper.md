# Research, Simulation, and Paper Mode Implementation Plan

> Historical planning snapshot from 2026-07-10. For current implementation and operational
> status, see the repository README and `docs/final-implementation-report.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reproducible market-data validation, interpretable strategy research, event-driven backtesting/replay, deterministic simulated execution, and paper trading without any live broker write capability.

**Architecture:** Every mode calls one production `DecisionCycleService`; the simulation layer supplies a controlled clock, recorded events, and a fake broker rather than reimplementing strategy, portfolio, risk, state transition, or reconciliation logic. Raw data, normalized data, features, decisions, orders, fills, and results are independently hashed.

**Tech Stack:** Python 3.12–3.14 standard library numerics and statistics, Pydantic 2.13.4, SQLAlchemy 2.0.51, Pytest 9.1.1, Hypothesis 6.156.6; no deep-learning or high-frequency dependency.

## Global Constraints

- Research code cannot import official broker transports or choose live authorization.
- Strategies output deterministic direction and score only; they do not choose account exposure or call brokers.
- The central configuration graph owns every parameter grid, cost assumption, schedule, and acceptance threshold.
- Same-bar knowledge cannot produce a fill; a fill event must occur strictly after submission.
- Recorded providers expose only data available at the simulated clock time.
- Splits, dividends, point-in-time membership, spread, slippage, fees, rejections, unfilled orders, and partial fills are modeled or explicitly marked unavailable.
- Missing research-grade data makes a strategy ineligible; no silent substitution is allowed.
- Paper mode always composes a simulated broker and has no network write dependency.
- Identical code, configuration, data manifest, clock, and random seed must produce identical result hashes.
- Prediction-market research has no live placement interface and `PREDICTION_LIVE_ENABLED=false`.
- Research output reports every attempted family and makes no profitability claim.

---

### Task 1: Implement market-data protocol and validation gateway

**Files:**
- Modify: `src/trading_bot/domain/market.py`
- Create: `src/trading_bot/market_data/__init__.py`
- Create: `src/trading_bot/market_data/protocol.py`
- Create: `src/trading_bot/market_data/validation.py`
- Test: `tests/unit/market_data/test_protocol.py`
- Test: `tests/unit/market_data/test_validation.py`
- Test: `tests/property/market_data/test_validation_properties.py`

**Interfaces:**
- Produces: `CorporateAction`, `EarningsEvent`, `MarketDataCapability`, `DataQualityEvent`, `MarketDataProvider`, `ValidationResult[T]`, and `ValidatingMarketDataProvider`; consumes the canonical `BarInterval` from Plan 1.
- Uses: canonical `Quote`, `Bar`, `Instrument`, `MarketClock`, `DataHash`, and the Plan 2 append-only `DataQualityRepository`; every rejection is committed before `RejectedMarketData` is raised.

- [ ] **Step 1: Write failing validation tests**

```python
@pytest.mark.parametrize(
    ("quote", "code"),
    [
        (quote(bid="101", ask="100"), "crossed_quote"),
        (quote(bid="0", ask="100"), "nonpositive_price"),
        (quote(observed_at=minutes_ago(1)), "stale_quote"),
        (quote(instrument_id=InstrumentId("WRONG")), "instrument_mismatch"),
    ],
)
def test_invalid_quote_is_rejected(quote: Quote, code: str) -> None:
    result = MarketDataValidator(default_freshness()).validate_quote(
        quote,
        expected_instrument=InstrumentId("AAPL"),
        now=aware_now(),
        previous=None,
    )
    assert result.value is None
    assert code in {event.code for event in result.events}
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/market_data/test_protocol.py tests/unit/market_data/test_validation.py -q`

Expected: FAIL with missing market-data modules.

- [ ] **Step 3: Implement the exact provider protocol**

```python
class MarketDataProvider(Protocol):
    async def get_quote(self, instrument_id: InstrumentId) -> Quote: ...
    async def get_executable_quote(
        self, instrument_id: InstrumentId, quantity: Decimal,
    ) -> Quote: ...
    async def get_bars(
        self,
        instrument_id: InstrumentId,
        interval: BarInterval,
        start: datetime,
        end: datetime,
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
```

`get_quote` serves informational/research data. `get_executable_quote` must return a quantity-appropriate, provider-timestamped bid/ask snapshot suitable for the five-second final check; unsupported providers raise `MarketDataCapabilityError`. Providers never fabricate missing fields.

- [ ] **Step 4: Implement validation and quarantine**

```python
@dataclass(frozen=True, slots=True)
class ValidationResult(Generic[T]):
    value: T | None
    events: tuple[DataQualityEvent, ...]

class ValidatingMarketDataProvider:
    async def get_quote(self, instrument_id: InstrumentId) -> Quote:
        raw = await self._inner.get_quote(instrument_id)
        result = self._validator.validate_quote(
            raw, expected_instrument=instrument_id, now=self._clock.now(), previous=self._last.get(instrument_id)
        )
        await self._quality_events.append_all(result.events)
        if result.value is None:
            raise RejectedMarketData(result.events)
        self._last[instrument_id] = result.value
        return result.value
```

Validate freshness, require `timestamp_source is TimestampSource.PROVIDER` whenever `freshness_verified=true`, reject crossed quotes, positive finite violations, interval identity errors, market-clock conflicts, unconfirmed anomaly changes, missing fields, and forbidden interpolated bars.

- [ ] **Step 5: Add property tests**

```python
@given(non_finite_decimal_strings())
def test_nonfinite_market_values_are_always_rejected(raw: str) -> None:
    with pytest.raises((InvalidDecimal, DomainValidationError)):
        quote(bid=raw)
```

- [ ] **Step 6: Run and commit**

Run: `uv run pytest tests/unit/market_data tests/property/market_data -q`

Expected: PASS.

```bash
git add src/trading_bot/domain/market.py src/trading_bot/market_data tests/unit/market_data tests/property/market_data
git commit -m "feat: add validated market data gateway"
```

### Task 2: Add content-addressed recording, adjustments, and point-in-time universes

**Files:**
- Create: `src/trading_bot/market_data/recording.py`
- Create: `src/trading_bot/market_data/replay.py`
- Create: `src/trading_bot/market_data/adjustments.py`
- Create: `src/trading_bot/market_data/universe.py`
- Create: `tests/fixtures/market_data/equity_daily_bars.jsonl`
- Create: `tests/fixtures/market_data/crypto_four_hour_bars.jsonl`
- Create: `tests/fixtures/market_data/corporate_actions.jsonl`
- Create: `tests/fixtures/market_data/universe_membership.jsonl`
- Test: `tests/unit/market_data/test_adjustments.py`
- Test: `tests/unit/market_data/test_universe.py`
- Test: `tests/integration/market_data/test_recording_replay.py`

**Interfaces:**
- Produces: `ResearchDataManifest`, `RecordedMarketDataProvider`, `PointInTimeUniverse.members_at(as_of)`, `adjust_bars`, and `content_hash`.

- [ ] **Step 1: Write failing determinism and lookahead tests**

```python
def test_manifest_hash_is_key_order_independent() -> None:
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})

@pytest.mark.asyncio
async def test_recorded_provider_hides_future_bars(provider: RecordedMarketDataProvider) -> None:
    provider.clock.set(datetime(2026, 1, 2, tzinfo=UTC))
    bars = await provider.get_bars(AAPL, BarInterval.DAY, day(1), day(10))
    assert all(bar.ends_at <= provider.clock.now() for bar in bars)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/market_data/test_adjustments.py tests/unit/market_data/test_universe.py tests/integration/market_data/test_recording_replay.py -q`

Expected: FAIL with missing recording modules.

- [ ] **Step 3: Implement canonical manifests and JSONL storage**

```python
@dataclass(frozen=True, slots=True)
class ResearchDataManifest:
    raw_hashes: tuple[DataHash, ...]
    cleaned_hashes: tuple[DataHash, ...]
    corporate_action_coverage: str
    point_in_time_universe: bool
    survivorship_limitations: tuple[str, ...]
    licensing_limitations: tuple[str, ...]
    known_gaps: tuple[str, ...]
    manifest_hash: DataHash
```

Serialize `Decimal` as canonical strings and timestamps as `Z`-normalized RFC 3339. Preserve raw, normalized, feature, signal, order, fill, and result namespaces separately.

- [ ] **Step 4: Implement split/dividend adjustments and point-in-time membership**

Apply only corporate actions whose effective time is available at `as_of`. Universe membership queries return the set known at that time; missing point-in-time history records an ineligibility reason rather than using today's constituents.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/unit/market_data tests/integration/market_data -q`

Expected: PASS.

```bash
git add src/trading_bot/market_data tests/fixtures/market_data tests/unit/market_data tests/integration/market_data
git commit -m "feat: add reproducible recorded market data"
```

### Task 3: Implement lookahead-safe features

**Files:**
- Create: `src/trading_bot/strategies/__init__.py`
- Create: `src/trading_bot/strategies/protocol.py`
- Create: `src/trading_bot/strategies/features.py`
- Test: `tests/unit/strategies/test_features.py`
- Test: `tests/property/strategies/test_feature_determinism.py`

**Interfaces:**
- Produces: `FeatureVector`, `FeatureSnapshot`, `HistoricalSlice`, `FeaturePipeline.compute(history, as_of)`.

- [ ] **Step 1: Write failing lookahead tests**

```python
def test_incomplete_bar_cannot_change_features() -> None:
    complete = historical_slice(bars=bars_ending_before(AS_OF))
    with_future = historical_slice(bars=bars_ending_before(AS_OF) + (bar_ending_after(AS_OF),))
    with pytest.raises(LookaheadViolation):
        FeaturePipeline().compute(with_future, as_of=AS_OF)
    assert FeaturePipeline().compute(complete, as_of=AS_OF).observed_at == AS_OF
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/strategies/test_features.py -q`

Expected: FAIL with missing feature pipeline.

- [ ] **Step 3: Implement deterministic Decimal features**

Compute total return, moving averages, realized volatility, ATR, breakout high/low, drawdown, volume/liquidity, and spread from bars ending at or before `as_of`. Feature names and canonical order are stable; insufficient history returns an explicit unavailable feature, not zero.

```python
@dataclass(frozen=True, slots=True)
class FeatureVector:
    instrument_id: InstrumentId
    observed_at: datetime
    values: tuple[tuple[str, Decimal | int | bool | str | None], ...]
    data_hash: DataHash
```

- [ ] **Step 4: Prove deterministic feature hashes**

Run: `uv run pytest tests/unit/strategies/test_features.py tests/property/strategies/test_feature_determinism.py -q`

Expected: PASS.

- [ ] **Step 5: Commit features**

```bash
git add src/trading_bot/strategies tests/unit/strategies/test_features.py tests/property/strategies/test_feature_determinism.py
git commit -m "feat: add lookahead-safe feature pipeline"
```

### Task 4: Implement deterministic strategy candidates and portfolio targets

**Files:**
- Create: `src/trading_bot/strategies/momentum.py`
- Create: `src/trading_bot/strategies/relative_strength.py`
- Create: `src/trading_bot/strategies/regime.py`
- Create: `src/trading_bot/strategies/mean_reversion.py`
- Create: `src/trading_bot/strategies/crypto.py`
- Create: `src/trading_bot/strategies/registry.py`
- Create: `src/trading_bot/portfolio/targets.py`
- Create: `src/trading_bot/portfolio/intents.py`
- Test: `tests/unit/strategies/test_candidates.py`
- Test: `tests/unit/portfolio/test_targets.py`
- Test: `tests/architecture/test_strategy_boundaries.py`

**Interfaces:**
- Produces: `Strategy`, `StrategyContext`, `StrategyDescriptor`, `StrategyDecision`, `StrategyAction`, `TargetPortfolio`, `ExitPolicy`, `PortfolioConstructor.construct`, and `IntentPlanner.plan`.

- [ ] **Step 1: Write failing boundary and behavior tests**

```python
def test_strategy_emits_no_quantity_or_broker_order() -> None:
    fields = {field.name for field in dataclasses.fields(StrategyDecision)}
    assert "quantity" not in fields
    assert "order" not in fields

def test_mean_reversion_is_research_only() -> None:
    with pytest.raises(StrategyNotAllowed):
        StrategyRegistry(default_config()).get("equity_mean_reversion", mode=ExecutionMode.PAPER)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/strategies/test_candidates.py tests/unit/portfolio/test_targets.py tests/architecture/test_strategy_boundaries.py -q`

Expected: FAIL with missing strategies.

- [ ] **Step 3: Implement the strategy contract**

```python
class Strategy(Protocol):
    @property
    def descriptor(self) -> StrategyDescriptor: ...

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]: ...

@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    strategy_id: str
    family: str
    version: str
    rationale: str
    research_only: bool
    parameter_hash: str

@dataclass(frozen=True, slots=True)
class StrategyDecision:
    instrument_id: InstrumentId
    decided_at: datetime
    action: StrategyAction
    score: Decimal
    reason_codes: tuple[str, ...]
    strategy_version: str
    config_hash: ConfigHash
    data_hash: DataHash

@dataclass(frozen=True, slots=True)
class ExitPolicy:
    version: str
    stop_kind: str
    stop_distance_per_unit: Decimal
    minimum_reward_risk: Decimal
    maximum_holding_bars: int | None

@dataclass(frozen=True, slots=True)
class TargetPosition:
    instrument_id: InstrumentId
    target_notional: Decimal
    exit_policy: ExitPolicy | None
    source_strategy_version: str

@dataclass(frozen=True, slots=True)
class TargetPortfolio:
    as_of: datetime
    positions: tuple[TargetPosition, ...]
    cash_target: Decimal
    config_hash: ConfigHash
    data_hash: DataHash
```

`StrategyAction` contains exactly `ENTER_LONG`, `EXIT_LONG`, and `HOLD`. Time-series momentum requires positive medium-term return, short moving average above long moving average, and price above the configured long average. Relative strength ranks only eligible liquid instruments. Regime returns configured exposure multiplier `1`, `0.5`, or `0`. Crypto trend/breakout returns cash/HOLD in a negative trend. All parameters come from config; the initial equity grid is short `20/30/50` and long `100/150/200`.

- [ ] **Step 4: Construct targets, then plan intents through production sizing**

`PortfolioConstructor` converts strategy decisions into a broker-neutral `TargetPortfolio` containing desired long exposure and versioned ATR/volatility exit policies, but no order type or broker fields. `IntentPlanner` compares the target with the current portfolio and uses Plan 2 sizing, correlation, cash, and asset-class caps to create candidate intents. It never averages down or pyramids; an existing long position makes a new ENTER_LONG decision HOLD. An expired, canceled, or missed entry cannot be chased inside the same cycle: reconsideration waits for the next scheduled decision and still passes symbol spacing/activity gates. Tests prove target construction and intent planning are separate calls and every entry intent carries its exit-policy version.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/strategies tests/unit/portfolio tests/architecture/test_strategy_boundaries.py -q`

Expected: PASS.

```bash
git add src/trading_bot/strategies src/trading_bot/portfolio/targets.py src/trading_bot/portfolio/intents.py tests/unit/strategies tests/unit/portfolio tests/architecture/test_strategy_boundaries.py
git commit -m "feat: add interpretable strategy candidates"
```

### Task 5: Implement prediction-market research with no live surface

**Files:**
- Create: `src/trading_bot/domain/prediction.py`
- Create: `src/trading_bot/research/prediction.py`
- Test: `tests/unit/research/test_prediction.py`
- Test: `tests/property/research/test_prediction_costs.py`
- Test: `tests/architecture/test_prediction_no_live.py`

**Interfaces:**
- Produces: `PredictionContractSnapshot`, `ProbabilityEstimate`, `PredictionCosts`, `PredictionEvaluation`, `evaluate_prediction_contract`, `calculate_calibration`, and `calculate_brier_score`.

- [ ] **Step 1: Write failing cost and surface tests**

```python
@given(nonnegative_costs())
def test_costs_never_increase_edge(costs: PredictionCosts) -> None:
    gross = evaluate_prediction_contract(snapshot(), estimate(), zero_costs(), Decimal("0"))
    net = evaluate_prediction_contract(snapshot(), estimate(), costs, Decimal("0"))
    assert net.edge <= gross.edge

def test_prediction_research_exports_no_place_method() -> None:
    assert not any(name.startswith("place") for name in dir(trading_bot.research.prediction))
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/research/test_prediction.py tests/property/research/test_prediction_costs.py tests/architecture/test_prediction_no_live.py -q`

Expected: FAIL with missing prediction research.

- [ ] **Step 3: Implement after-cost evaluation and calibration**

Compute Yes/No entry price, spread, commission, exchange fee, slippage, uncertainty deduction, maximum loss, maximum payout, net edge, margin-of-safety decision, calibration bins, and Brier score with `Decimal`.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/unit/research/test_prediction.py tests/property/research/test_prediction_costs.py tests/architecture/test_prediction_no_live.py -q`

Expected: PASS.

```bash
git add src/trading_bot/domain/prediction.py src/trading_bot/research/prediction.py tests/unit/research tests/property/research tests/architecture/test_prediction_no_live.py
git commit -m "feat: add prediction market research only"
```

### Task 6: Implement deterministic simulated broker and fill model

**Files:**
- Create: `src/trading_bot/simulation/__init__.py`
- Create: `src/trading_bot/simulation/clock.py`
- Create: `src/trading_bot/simulation/events.py`
- Create: `src/trading_bot/simulation/costs.py`
- Create: `src/trading_bot/simulation/fills.py`
- Create: `src/trading_bot/brokers/fake.py`
- Test: `tests/unit/simulation/test_clock.py`
- Test: `tests/unit/simulation/test_fills.py`
- Test: `tests/integration/brokers/test_fake.py`

**Interfaces:**
- Produces: `EventCursor`, `SimulatedClock`, `FillModel`, `FillPlan`, and `FakeBroker` implementing all split broker protocols without network imports.

- [ ] **Step 1: Write failing no-same-event and partial-fill tests**

```python
def test_order_cannot_fill_on_submission_cursor(fill_model: FillModel) -> None:
    plan = fill_model.evaluate(fill_request(submitted=cursor(10), market=cursor(10)), rng=random.Random(7))
    assert plan.fills == ()

def test_seeded_partial_fill_is_reproducible(fill_model: FillModel) -> None:
    first = fill_model.evaluate(partial_fill_request(), rng=random.Random(20260710))
    second = fill_model.evaluate(partial_fill_request(), rng=random.Random(20260710))
    assert first == second
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/simulation tests/integration/brokers/test_fake.py -q`

Expected: FAIL with missing simulation classes.

- [ ] **Step 3: Implement deterministic events and fill outcomes**

Models cover reject, no fill, full fill, partial fill, spread, slippage, fees, latency, market session, and cancellation race. Persist the seed and never use module-global randomness.

- [ ] **Step 4: Implement fake broker idempotency**

`FakeBroker.place_order(submission: PersistedReviewedOrder)` implements the canonical protocol. Repeated calls with the same persisted `submission.deduplication_key` return the same broker order and create no new economic effect. A different key creates a distinct order only after review and a unique submission-attempt reservation.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/simulation tests/integration/brokers/test_fake.py -q`

Expected: PASS.

```bash
git add src/trading_bot/simulation src/trading_bot/brokers/fake.py tests/unit/simulation tests/integration/brokers/test_fake.py
git commit -m "feat: add deterministic simulated broker"
```

### Task 7: Compose the single production decision cycle and replay engine

**Files:**
- Create: `src/trading_bot/app.py`
- Create: `src/trading_bot/simulation/engine.py`
- Create: `src/trading_bot/simulation/replay.py`
- Create: `src/trading_bot/runtime/__init__.py`
- Create: `src/trading_bot/runtime/modes.py`
- Create: `tests/integration/simulation/test_decision_cycle.py`
- Create: `tests/replay/test_determinism.py`
- Create: `tests/replay/test_no_same_bar_fill.py`
- Create: `tests/replay/test_partial_fill.py`

**Interfaces:**
- Produces: `MarketSnapshotLoader.load(universe, as_of) -> ValidatedMarketSnapshot`, `DecisionCycleRequest`, `DecisionCycleResult`, `DecisionCycleService.run_cycle`, `SimulationRequest`, `SimulationResult`, and `SimulationEngine.run`.
- `MarketSnapshotLoader` composes one or more `MarketDataProvider` instances, capability checks, validation, point-in-time universe membership, and a data manifest; it is not an extra provider method.

- [ ] **Step 1: Write failing end-to-end cycle test**

```python
@pytest.mark.asyncio
async def test_cycle_uses_production_risk_and_execution(services: CycleServices) -> None:
    result = await DecisionCycleService(**services.as_kwargs()).run_cycle(cycle_request())
    assert result.risk_evaluations
    assert result.order_outcomes
    assert services.fake_broker.place_calls == 1
    assert result.audit_event_ids
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/simulation/test_decision_cycle.py tests/replay -q`

Expected: FAIL with missing composition service.

- [ ] **Step 3: Implement the single path**

```python
class DecisionCycleService:
    async def run_cycle(self, request: DecisionCycleRequest) -> DecisionCycleResult:
        market = await self.snapshot_loader.load(request.universe, request.as_of)
        features = self.features.compute(market.history, as_of=request.as_of)
        decisions = self.strategies.decide(features)
        target = self.portfolio.construct(decisions, request.portfolio, market)
        intents = self.intent_planner.plan(target, request.portfolio, market)
        outcomes = tuple(await self.execution.execute(intent) for intent in intents)
        return await self.journal.finalize(
            request, market, features, decisions, target, intents, outcomes
        )
```

All modes call this service. Do not create research-only risk or execution classes.

- [ ] **Step 4: Implement deterministic event priority**

Process corporate/session events, market data, scheduled broker updates, strategy cycles, reconciliation, then reporting. Every event has UTC time plus monotonic sequence.

- [ ] **Step 5: Verify result hashes**

Run: `uv run pytest tests/integration/simulation/test_decision_cycle.py tests/replay -q`

Expected: PASS; identical replay inputs yield identical hashes and no same-bar fills.

- [ ] **Step 6: Commit cycle and engine**

```bash
git add src/trading_bot/app.py src/trading_bot/simulation src/trading_bot/runtime tests/integration/simulation tests/replay
git commit -m "feat: add deterministic decision cycle and replay"
```

### Task 8: Implement complete performance metrics and research reports

**Files:**
- Create: `src/trading_bot/research/__init__.py`
- Create: `src/trading_bot/research/metrics.py`
- Create: `src/trading_bot/research/report.py`
- Create: `src/trading_bot/reporting/__init__.py`
- Create: `src/trading_bot/reporting/performance.py`
- Test: `tests/unit/research/test_metrics.py`
- Test: `tests/unit/research/test_report.py`
- Test: `tests/property/research/test_metric_invariants.py`

**Interfaces:**
- Produces: `PerformanceInput`, `PerformanceMetrics`, `calculate_performance`, `ResearchReport`, `build_research_report`, `render_json`, and `render_markdown`.

- [ ] **Step 1: Write failing metric boundary tests**

```python
def test_zero_downside_returns_none_sortino() -> None:
    metrics = calculate_performance(performance_input(all_positive_returns()))
    assert metrics.sortino.value is None
    assert metrics.sortino.status == "undefined_no_downside_variation"

def test_report_contains_rejected_attempts() -> None:
    report = build_research_report(run_record(), attempts=(accepted_attempt(), rejected_attempt()))
    assert {attempt.status for attempt in report.attempts} == {"accepted", "rejected"}
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/research/test_metrics.py tests/unit/research/test_report.py -q`

Expected: FAIL with missing metrics.

- [ ] **Step 3: Implement every required metric**

Include total return, CAGR, annualized volatility, Sharpe, Sortino, Calmar, max/average drawdown, duration, win rate, average win/loss, payoff, profit factor, expectancy, median trade, turnover, gross/net exposure, time in market, spread/slippage/fees, independent opportunities, longest losing streak, tail loss, and year/regime breakdown. Undefined values use `None` plus reason; never NaN or infinity.

- [ ] **Step 4: Render canonical reports**

JSON output sorts keys and serializes `Decimal` as strings. Markdown includes data limitations, all candidates, cost assumptions, parameter grid, code/config/data hashes, and no-profit disclaimer.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/research tests/property/research -q`

Expected: PASS.

```bash
git add src/trading_bot/research src/trading_bot/reporting tests/unit/research tests/property/research
git commit -m "feat: add reproducible research metrics"
```

### Task 9: Implement walk-forward, stability, Monte Carlo, PBO, and acceptance

**Files:**
- Create: `src/trading_bot/research/validation.py`
- Create: `src/trading_bot/research/monte_carlo.py`
- Create: `src/trading_bot/research/engine.py`
- Modify: `src/trading_bot/persistence/repositories.py`
- Test: `tests/unit/research/test_validation.py`
- Test: `tests/unit/research/test_monte_carlo.py`
- Test: `tests/integration/research/test_engine.py`

**Interfaces:**
- Produces: `rolling_walk_forward_splits`, `purged_splits`, `analyze_parameter_stability`, `resample_trade_sequences`, `estimate_pbo`, `ResearchAcceptancePolicy`, `assess_research`, and persisted `StrategyEligibilityAttestation`.

- [ ] **Step 1: Write failing split and acceptance tests**

```python
def test_purged_split_has_no_overlap() -> None:
    for split in purged_splits(overlapping_observations(), default_purged_spec()):
        assert not labels_overlap(split.train, split.test)

@pytest.mark.parametrize(
    "report",
    [negative_oos_report(), single_trade_dependent_report(), unstable_parameters_report(), leakage_report()],
)
def test_research_gate_fails_closed(report: ResearchReport) -> None:
    assert not assess_research(report, default_acceptance_policy()).eligible
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/research/test_validation.py tests/unit/research/test_monte_carlo.py tests/integration/research/test_engine.py -q`

Expected: FAIL with missing validation engine.

- [ ] **Step 3: Implement deterministic validation**

Use an explicit seed for Monte Carlo. PBO returns `insufficient_sample` when combinatorial requirements are not met. Stress scenarios materially worsen spreads, slippage, fees, and fill probability. Compare with cash and configured passive benchmarks.

- [ ] **Step 4: Implement fail-closed acceptance**

Reject nonpositive after-cost OOS expectancy, one-trade dependence, unstable neighboring parameters, stressed drawdown breach, insufficient independent opportunities, unresolved leakage/survivorship, or missing edge-persistence rationale. Persist both accepted and rejected attestations keyed by exact strategy version, configuration hash, code hash, research data-manifest hash, and report hash. Dirty-code research is always `non_promotable`. Eligibility means research acceptance only; it cannot activate a mode. A changed strategy/config/code version has no live attestation until re-researched.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/research tests/integration/research -q`

Expected: PASS.

```bash
git add src/trading_bot/research src/trading_bot/persistence/repositories.py tests/unit/research tests/integration/research
git commit -m "feat: add rigorous research validation"
```

### Task 10: Compose backtest, simulation, and paper modes

**Files:**
- Create: `src/trading_bot/runtime/backtest.py`
- Create: `src/trading_bot/runtime/simulation.py`
- Create: `src/trading_bot/runtime/paper.py`
- Create: `tests/integration/runtime/test_backtest.py`
- Create: `tests/integration/runtime/test_paper.py`
- Create: `tests/integration/runtime/test_no_live_writes.py`
- Create: `tests/replay/test_paper_restart.py`

**Interfaces:**
- Produces: `build_backtest_application`, `build_simulation_application`, `build_paper_application`, and `PaperApplication.run_cycle`.

- [ ] **Step 1: Write failing composition test**

```python
def test_paper_composition_cannot_accept_place_capability() -> None:
    signature = inspect.signature(build_paper_application)
    assert "broker_place" not in signature.parameters

@pytest.mark.asyncio
async def test_paper_restart_does_not_duplicate_effect(paper_harness: PaperHarness) -> None:
    first = await paper_harness.run_once()
    second = await paper_harness.restart().run_same_cycle()
    assert second.economic_effect_ids == first.economic_effect_ids
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/runtime tests/replay/test_paper_restart.py -q`

Expected: FAIL with missing runtime composition.

- [ ] **Step 3: Implement mode-specific composition roots**

Backtest and simulation accept recorded data and fake broker only. Paper accepts recorded or approved public current/delayed data and fake broker only. Every process records config, code, data, and seed hashes. Completed unique paper cycles append evidence, but promotion counting requires an eligible `StrategyEligibilityAttestation` matching the exact strategy/config/code version; research/rejected-strategy paper runs are retained as non-promotable. Risk-denied cycles count only when the full decision cycle completed and was journaled.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/integration/runtime tests/replay/test_paper_restart.py -q`

Expected: PASS and network write guard records zero attempts.

```bash
git add src/trading_bot/runtime tests/integration/runtime tests/replay/test_paper_restart.py
git commit -m "feat: add offline and paper runtimes"
```

### Task 11: Add offline CLI, Make targets, and research documentation

**Files:**
- Create: `src/trading_bot/cli/__init__.py`
- Create: `src/trading_bot/cli/main.py`
- Create: `scripts/run_backtest.py`
- Create: `scripts/run_simulation.py`
- Create: `scripts/run_paper.py`
- Modify: `Makefile`
- Modify: `README.md`
- Create: `docs/strategy-research.md`
- Create: `docs/limitations.md`
- Test: `tests/integration/cli/test_offline_modes.py`

**Interfaces:**
- Produces exact commands: `trader backtest`, `trader simulate`, and `trader paper`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_paper_once_returns_success(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["paper", "--config", "configs/paper.yaml", "--once"])
    assert result.exit_code == 0
    assert '"mode":"paper"' in result.stdout
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/cli/test_offline_modes.py -q`

Expected: FAIL because CLI commands are absent.

- [ ] **Step 3: Implement Typer commands and Make targets**

```make
backtest:
	uv run trader backtest --config configs/backtest.yaml --seed 20260710

simulate:
	uv run trader simulate --config configs/simulation.yaml --seed 20260710

paper:
	uv run trader paper --config configs/paper.yaml --once
```

Commands emit structured summary paths and hashes, never profit claims.

- [ ] **Step 4: Document research behavior and limitations**

Explain data provenance, costs, bias controls, all candidates, acceptance/rejection, paper evidence, lack of guaranteed profitability, small-account constraints, data licensing, latency, slippage, tax consequences, and prediction limitations.

- [ ] **Step 5: Run slice verification**

Run:

```bash
uv run pytest tests/unit/market_data tests/property/market_data tests/unit/strategies tests/unit/portfolio tests/unit/simulation tests/unit/research tests/property/research tests/integration/market_data tests/integration/brokers/test_fake.py tests/integration/simulation tests/integration/research tests/integration/runtime tests/integration/cli/test_offline_modes.py tests/replay -q
make backtest
make simulate
make paper
uv run ruff check .
uv run mypy src
```

Expected: all pass; repeated runs produce identical hashes; network write attempts remain zero.

- [ ] **Step 6: Commit offline modes and docs**

```bash
git add src/trading_bot/cli scripts Makefile README.md docs/strategy-research.md docs/limitations.md tests/integration/cli
git commit -m "feat: add reproducible offline trading modes"
```

## Slice Completion Gate

The worktree is clean; backtest, simulation, and paper commands pass; identical fixtures produce identical result hashes; impossible same-bar fills are rejected; every candidate and limitation is reported; no official broker write capability is imported, constructed, or called.
