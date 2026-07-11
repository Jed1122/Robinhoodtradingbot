# Locked Live Execution and Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement equity and crypto live-order code behind mandatory persistence, review, risk, authorization, idempotency, reconciliation, and kill-switch gates while keeping all live modes disabled by default.

**Architecture:** The execution service persists each state before and after the one external submission attempt. Provider-specific placement and cancellation remain narrow capabilities; ambiguous results transition to reconciliation-required, and startup receives only read plus cancel-known-order capability until a new live lease is verified.

**Tech Stack:** Python 3.12–3.14, SQLAlchemy 2.0.51 async unit of work, HTTPX 0.28.1, MCP Python SDK 1.28.1, PyNaCl 1.6.2, Pytest/Respx/local fake MCP only.

## Global Constraints

- This plan implements code paths but does not authorize or place a real order.
- All tests use fake brokers, HTTPX mock transport, or a local fake MCP server; CI contains no live credentials.
- Live placement capability cannot be constructed without verified provider evidence, allowlisted account, fresh signed preflight, valid live lease, clean reconciliation, successful risk self-test, synchronized clock, inactive kill switch, and no critical alerts.
- Equity requires official MCP order review when the verified tool exists; Crypto uses a persisted local review plus official timestamped estimated price because no official Crypto review endpoint is documented.
- The broker-reviewed request must exactly match the persisted intent and remain within a 30-second review lifetime.
- All 24 pretrade checks rerun after review and immediately before submission.
- Every write is attempted once. Timeouts after send become `UNKNOWN_REQUIRES_RECONCILIATION`, never automatic retries.
- Crypto uses documented `client_order_id`; equity uses a provider reference only when captured schema evidence proves it.
- Replacement cannot occur until cancellation is confirmed or reconciled and a new risk evaluation passes.
- Partial fills update actual quantity and remaining risk; full requested quantity is never assumed.
- Kill switch and expired authorization block placements but permit only positively identified risk-reducing entry cancellations.
- Ordinary entries/exits use limit orders. No market-order placement path is implemented; a future emergency policy requires a separate reviewed design, configuration migration, and authorization scope.
- Prediction live remains unsupported.

---

### Task 1: Implement persisted order review and exact intent matching

**Files:**
- Modify: `src/trading_bot/execution/review.py`
- Test: `tests/unit/execution/test_review.py`
- Test: `tests/integration/execution/test_review_persistence.py`

**Interfaces:**
- Produces: `OrderReviewService.review(intent) -> BrokerOrderReview`.
- Produces: `review_matches_intent(review, intent) -> CheckResult`.
- Consumes: `BrokerReview`, `MarketDataProvider`, unit of work, clock, and 30-second review lifetime.

- [ ] **Step 1: Write failing match and expiry tests**

```python
def test_review_with_changed_quantity_does_not_match() -> None:
    intent = make_intent(quantity=Decimal("1"))
    review = make_review(intent_id=intent.id, quantity=Decimal("2"))
    result = review_matches_intent(review, intent)
    assert not result.allowed
    assert result.code == "review_match"

def test_review_expires_after_thirty_seconds() -> None:
    assert not review_is_fresh(make_review(reviewed_at=NOW - timedelta(seconds=31)), NOW, timedelta(seconds=30))
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/execution/test_review.py tests/integration/execution/test_review_persistence.py -q`

Expected: FAIL with missing review service.

- [ ] **Step 3: Implement normalized review comparison**

```python
def review_matches_intent(review: BrokerOrderReview, intent: OrderIntent) -> CheckResult:
    expected = (
        intent.account_id,
        intent.instrument_id,
        intent.side,
        intent.order_type,
        intent.time_in_force,
        intent.quantity,
        intent.limit_price,
        intent.stop_price,
    )
    actual = review.normalized_order.matching_tuple()
    return CheckResult(
        code="review_match",
        allowed=actual == expected,
        observed="match" if actual == expected else "mismatch",
        configured_limit="exact persisted intent equality",
        reason="review matches persisted intent" if actual == expected else "review differs from persisted intent",
        observed_at=review.reviewed_at,
    )
```

- [ ] **Step 4: Persist review transitions atomically**

Transition `RISK_APPROVED → REVIEW_REQUESTED`, commit; call review capability; store sanitized review plus source/hash/expiry; transition `REVIEW_REQUESTED → REVIEWED`. A review rejection, timeout, or malformed review transitions to `REVIEW_REJECTED`; because review is non-submitting, it never creates an economic-effect ambiguity and never uses `UNKNOWN_REQUIRES_RECONCILIATION`.

- [ ] **Step 5: Implement Crypto local review**

For Crypto, build a `BrokerOrderReview` with source `local_crypto_review` from current trading-pair constraints, timestamped estimated price, cost estimate, and exact outbound payload bytes. Set `client_order_id=ClientOrderId(str(intent.id))` and verify it parses as UUID before persisting the review. Do not claim broker review. Equity uses the verified official MCP review tool only.

- [ ] **Step 6: Run and commit**

Run: `uv run pytest tests/unit/execution/test_review.py tests/integration/execution/test_review_persistence.py -q`

Expected: PASS.

```bash
git add src/trading_bot/execution/review.py tests/unit/execution/test_review.py tests/integration/execution/test_review_persistence.py
git commit -m "feat: persist and verify order reviews"
```

### Task 2: Implement durable idempotency and one-attempt submission journal

**Files:**
- Modify: `src/trading_bot/execution/idempotency.py`
- Modify: `src/trading_bot/execution/service.py`
- Modify: `src/trading_bot/persistence/repositories.py`
- Modify: `src/trading_bot/persistence/lease.py`
- Create: `src/trading_bot/persistence/submission_mutex.py`
- Test: `tests/unit/execution/test_idempotency.py`
- Test: `tests/integration/execution/test_submission_journal.py`
- Test: `tests/chaos/execution/test_lost_submission_response.py`
- Test: `tests/chaos/execution/test_takeover_between_commit_and_send.py`

**Interfaces:**
- Produces: `DeduplicationKey`, `derive_deduplication_key(intent)`, `AccountSubmissionMutex` implementing `SubmissionExclusion`, `ExecutionService.execute`, and `ExecutionResult`.

- [ ] **Step 1: Write failing deduplication and ambiguity tests**

```python
def test_same_intent_has_same_deduplication_key() -> None:
    intent = make_intent(id=OrderIntentId("550e8400-e29b-41d4-a716-446655440000"))
    assert derive_deduplication_key(intent) == derive_deduplication_key(intent)

@pytest.mark.asyncio
async def test_timeout_after_send_requires_reconciliation(harness: ExecutionHarness) -> None:
    harness.broker_place.raise_after_send = TimeoutError()
    result = await harness.service.execute(harness.intent)
    assert result.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert harness.broker_place.calls == 1
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/execution/test_idempotency.py tests/integration/execution/test_submission_journal.py tests/chaos/execution/test_lost_submission_response.py tests/chaos/execution/test_takeover_between_commit_and_send.py -q`

Expected: FAIL with missing execution service.

- [ ] **Step 3: Implement stable keys and pre-call commit**

```python
def derive_deduplication_key(intent: OrderIntent) -> str:
    payload = f"{intent.account_id}|{intent.id}|{intent.config_hash}|{intent.purpose}"
    return hashlib.sha256(payload.encode()).hexdigest()

async def _persist_submission_pending(self, review: BrokerOrderReview) -> None:
    async with self._uow_factory() as uow:
        await uow.orders.add_transition(
            review.normalized_order.id, OrderEvent.PREPARE_SUBMISSION, self._clock.now()
        )
        await uow.submission_attempts.reserve_once(
            intent_id=review.normalized_order.id,
            review=review,
            deduplication_key=derive_deduplication_key(review.normalized_order),
            fencing_token=self._lease.fencing_token,
        )
        await uow.audit.append(submission_pending_event(review))
        await uow.commit()
```

`DeduplicationKey` is the internal SHA-256 key used by the journal. The provider-facing Crypto `client_order_id` is `ClientOrderId(str(intent.id))`, where the intent ID was generated by `new_order_intent_id()` and persisted before review. Tests prove the two values are distinct and the provider field is a valid UUID.

- [ ] **Step 4: Attempt placement once and persist outcome**

Before loading the final mutable context, acquire an account-scoped `fcntl.flock(LOCK_EX | LOCK_NB)` on a mode-`0600` file under `/var/lib/trading-bot/locks`; the filename uses the SHA-256 digest of the account ID rather than the account ID itself. Lease acquisition/takeover and every production placement must acquire this same `AccountSubmissionMutex`. While holding it, reload and validate the current execution lease/fencing token, reload all final context, run all 24 checks, recheck quote/review/lease age against the current clock, verify the unique submission reservation, commit `SUBMISSION_PENDING`, call `BrokerPlace.place_order` once, and persist accepted/rejected/ambiguous outcome before release. The configured broker timeout is shorter than the lease TTL.

If the process crashes, the OS releases the mutex, while the durable pending/unknown state prevents resubmission. If the lease expires during a call, a nonblocking takeover attempt fails and is deferred until the mutex is released; the later attempt observes the persisted state and cannot send concurrently. Document this as a single-host primitive; a future multi-host topology requires an external distributed exclusion mechanism and remains unsupported.

The global lock order is submission mutex first, then database transaction; no code may wait for the filesystem mutex while holding a database write transaction. A chaos test pauses exactly after the pending commit and before transport send, attempts takeover from a second process, and proves the second process cannot call the transport.

- [ ] **Step 5: Prove restart idempotency**

On restart, a `SUBMISSION_PENDING` or unknown intent never resubmits. Recovery reconciles by client/dedup key or bounded order attributes.

- [ ] **Step 6: Run and commit**

Run: `uv run pytest tests/unit/execution/test_idempotency.py tests/integration/execution/test_submission_journal.py tests/chaos/execution/test_lost_submission_response.py tests/chaos/execution/test_takeover_between_commit_and_send.py -q`

Expected: PASS and one broker call.

```bash
git add src/trading_bot/execution/idempotency.py src/trading_bot/execution/service.py src/trading_bot/persistence/repositories.py src/trading_bot/persistence/lease.py src/trading_bot/persistence/submission_mutex.py tests/unit/execution/test_idempotency.py tests/integration/execution/test_submission_journal.py tests/chaos/execution/test_lost_submission_response.py tests/chaos/execution/test_takeover_between_commit_and_send.py
git commit -m "feat: add durable one-attempt submission"
```

### Task 3: Add locked Crypto order placement and cancellation

**Files:**
- Modify: `src/trading_bot/brokers/robinhood_crypto_api.py`
- Create: `tests/integration/brokers/test_robinhood_crypto_write.py`
- Create: `tests/chaos/brokers/test_robinhood_crypto_write_ambiguity.py`

**Interfaces:**
- Produces: `RobinhoodCryptoPlaceAdapter` implementing `BrokerPlace` and `RobinhoodCryptoCancelAdapter` implementing `BrokerCancelOnly`.
- Consumes: `PersistedReviewedOrder`, whose review ID, submission-attempt ID, current fencing token, live-lease evidence, account/config hashes, and deduplication key were durably validated, plus the exact official schema manifest.

- [ ] **Step 1: Write failing payload and single-attempt tests**

```python
@pytest.mark.asyncio
async def test_limit_order_payload_uses_client_order_id(adapter: CryptoWriteHarness) -> None:
    await adapter.place.place_order(adapter.persisted_submission)
    request = adapter.transport.requests[0]
    assert request.method == "POST"
    assert request.json["client_order_id"] == adapter.review.client_order_id
    assert request.json["type"] == "limit"
    assert len(adapter.transport.requests) == 1

@pytest.mark.asyncio
async def test_cancel_timeout_is_ambiguous_not_retried(adapter: CryptoWriteHarness) -> None:
    adapter.transport.timeout_after_send = True
    with pytest.raises(BrokerCancellationAmbiguous):
        await adapter.cancel.cancel_known_order(adapter.account_id, adapter.order_id)
    assert len(adapter.transport.requests) == 1
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/brokers/test_robinhood_crypto_write.py tests/chaos/brokers/test_robinhood_crypto_write_ambiguity.py -q`

Expected: FAIL because write capabilities are absent.

- [ ] **Step 3: Implement exact official order configurations**

Parse documented `market`, `limit`, `stop_loss`, and `stop_limit` DTO variants so broker reads remain complete, but construct live placement payloads only for `limit`, `stop_loss`, and `stop_limit`. No market-order placement method or configuration branch is implemented in this plan. Include account number in query, uppercase verified symbol, UUID `client_order_id=str(review.normalized_order.id)`, side, type, and exactly one documented configuration object. Use either asset quantity or quote amount only where official schema permits; never both.

- [ ] **Step 4: Enforce construction gates**

Factory requires capability evidence, current live lease stage, account attestation, fencing token, `is_api_tradable`, increments/minimums, and redacted credential provider. No default constructor exists.

- [ ] **Step 5: Implement bounded ambiguity reconciliation**

After a submission timeout, query orders once through the read adapter using account, exact client order ID, and creation bound. If exactly one match exists, persist it. Zero or multiple matches leave `UNKNOWN_REQUIRES_RECONCILIATION` and require operator review.

- [ ] **Step 6: Run and commit**

Run: `uv run pytest tests/integration/brokers/test_robinhood_crypto_write.py tests/chaos/brokers/test_robinhood_crypto_write_ambiguity.py -q`

Expected: PASS against mock transport only.

```bash
git add src/trading_bot/brokers/robinhood_crypto_api.py tests/integration/brokers/test_robinhood_crypto_write.py tests/chaos/brokers/test_robinhood_crypto_write_ambiguity.py
git commit -m "feat: add locked Crypto order capability"
```

### Task 4: Add evidence-backed equity review, placement, and cancellation

**Files:**
- Modify only with verified schemas: `src/trading_bot/brokers/robinhood_equity_mapping.py`
- Modify only with verified schemas: `src/trading_bot/brokers/robinhood_equity_mcp.py`
- Test: `tests/integration/brokers/test_robinhood_equity_review.py`
- Test: `tests/integration/brokers/test_robinhood_equity_write.py`
- Test: `tests/chaos/brokers/test_robinhood_equity_ambiguity.py`

**Interfaces:**
- Produces: `RobinhoodEquityReviewAdapter`, `RobinhoodEquityPlaceAdapter`, and `RobinhoodEquityCancelAdapter` only for captured, reviewed schemas.

- [ ] **Step 1: Verify prerequisites without placing an order**

Require schema-declared input/output evidence for `review_equity_order`, `place_equity_order`, and `cancel_equity_order`, authenticated-read evidence for account/tradability/buying-power/orders, and one successful non-submitting authenticated review shape. If any evidence is absent, keep equity placement unimplemented/locked, update the matrix, and do not create guessed mapper fields.

- [ ] **Step 2: Write tests from sanitized captured schemas**

```python
@pytest.mark.asyncio
async def test_place_arguments_equal_reviewed_intent(adapter: EquityWriteHarness) -> None:
    review = await adapter.review.review_order(adapter.intent)
    submission = await adapter.persist_review_and_reserve_attempt(review)
    await adapter.place.place_order(submission)
    actual = adapter.fake_mcp.calls[-1].arguments
    expected = adapter.mapper.build_place_arguments(review.normalized_order)
    assert actual == expected
    assert canonical_sha256(actual) == review.outbound_payload_sha256
```

- [ ] **Step 3: Run tests and observe mapper failure**

Run: `uv run pytest tests/integration/brokers/test_robinhood_equity_review.py tests/integration/brokers/test_robinhood_equity_write.py tests/chaos/brokers/test_robinhood_equity_ambiguity.py -q`

Expected when evidence exists: FAIL because write mapping is absent. When evidence does not exist: tests are collected under an explicit `external_capability_missing` marker, the unit-level lock test passes, and live readiness remains false; do not report adapter completion.

- [ ] **Step 4: Implement exact captured tool calls**

Map only captured names/arguments/results. The deterministic mapper rebuilds place arguments from the normalized reviewed intent, and their canonical hash must equal the persisted `outbound_payload_sha256`; raw provider arguments stay outside broker-neutral domain records. Require dedicated accessible Agentic account, explicit allowlisted account number, verified long-only tradability/fractional eligibility, current unleveraged buying power, no duplicate order, current official review, and intent equality. Options tools are never imported.

- [ ] **Step 5: Handle provider reference conditionally**

Use a client reference only if the captured `place_equity_order` schema supports it. Otherwise attempt placement once and reconcile ambiguous results through bounded account/symbol/side/quantity/price/time matching; never infer a failure from timeout.

- [ ] **Step 6: Run local fake MCP tests and commit**

Run: `uv run pytest tests/integration/brokers/test_robinhood_equity_review.py tests/integration/brokers/test_robinhood_equity_write.py tests/chaos/brokers/test_robinhood_equity_ambiguity.py -q`

Expected: PASS only against sanitized local fixtures; no official place/cancel call occurs.

```bash
git add src/trading_bot/brokers/robinhood_equity_mapping.py src/trading_bot/brokers/robinhood_equity_mcp.py tests/integration/brokers/test_robinhood_equity_review.py tests/integration/brokers/test_robinhood_equity_write.py tests/chaos/brokers/test_robinhood_equity_ambiguity.py docs/capability-matrix.md
git commit -m "feat: add evidence-backed equity order capability"
```

If evidence is absent, commit only the locked readiness and matrix update; the final report must list equity live as externally pending.

### Task 5: Implement partial-fill accounting and cancel-replace policy

**Files:**
- Create: `src/trading_bot/execution/partial_fills.py`
- Create: `src/trading_bot/execution/cancel_policy.py`
- Modify: `src/trading_bot/persistence/repositories.py`
- Test: `tests/unit/execution/test_partial_fills.py`
- Test: `tests/integration/execution/test_cancel_replace.py`
- Test: `tests/property/execution/test_fill_deduplication.py`

**Interfaces:**
- Produces: `apply_fill`, `RemainingOrderDecision`, `evaluate_remainder`, and `CancelReplaceService`.

- [ ] **Step 1: Write failing fill and replacement tests**

```python
def test_partial_fill_updates_actual_not_requested_quantity() -> None:
    result = apply_fill(position=flat_position(), order=order(quantity="1"), fill=fill(quantity="0.25"))
    assert result.position.quantity == Decimal("0.25")
    assert result.remaining_quantity == Decimal("0.75")

@pytest.mark.asyncio
async def test_replacement_waits_for_confirmed_cancel(service: CancelReplaceHarness) -> None:
    service.cancel_result = cancel_pending()
    result = await service.replace(service.order, service.new_intent)
    assert result.state is OrderState.CANCEL_PENDING
    assert service.place_calls == 0
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/execution/test_partial_fills.py tests/integration/execution/test_cancel_replace.py tests/property/execution/test_fill_deduplication.py -q`

Expected: FAIL with missing policies.

- [ ] **Step 3: Implement fill deduplication and remaining risk**

Store each provider execution by stable external ID where documented. For Crypto's embedded executions, use the adapter's persisted multiset tuple plus occurrence ordinal; duplicate/reordered polls have no second effect, while equal legitimate executions retain distinct ordinals. Compare persisted fill sum with broker cumulative executed quantity on every reconciliation and treat disagreement as material. Recompute position, cash, fees, stop risk, gross exposure, and remaining allowed quantity after every newly inserted fill.

- [ ] **Step 4: Implement deterministic remainder policy**

Policy returns `LEAVE`, `CANCEL`, or `REVIEW_REPLACEMENT` based only on configured age, current quote, remaining risk, session, and strategy validity. Replacement creates a new intent and full risk/review cycle only after confirmed cancel or reconciled terminal state.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/execution/test_partial_fills.py tests/integration/execution/test_cancel_replace.py tests/property/execution/test_fill_deduplication.py -q`

Expected: PASS.

```bash
git add src/trading_bot/execution/partial_fills.py src/trading_bot/execution/cancel_policy.py src/trading_bot/persistence/repositories.py tests/unit/execution/test_partial_fills.py tests/integration/execution/test_cancel_replace.py tests/property/execution/test_fill_deduplication.py
git commit -m "feat: add safe partial-fill and replacement policy"
```

### Task 6: Wire all 24 checks into the final live execution service

**Files:**
- Modify: `src/trading_bot/execution/service.py`
- Test: `tests/integration/execution/test_final_pretrade.py`
- Test: `tests/chaos/execution/test_change_between_review_and_submit.py`

**Interfaces:**
- `ExecutionService.execute(intent) -> ExecutionResult` refreshes mutable data, requests review, evaluates 24 checks, commits pending state, and attempts once.

- [ ] **Step 1: Write failing changed-state tests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [reduce_buying_power, widen_spread, activate_kill_switch, add_duplicate_order, dirty_reconciliation],
)
async def test_change_after_review_blocks_submission(change: StateChange, harness: ExecutionHarness) -> None:
    harness.after_review(change)
    result = await harness.service.execute(harness.intent)
    assert result.state is OrderState.RISK_REJECTED
    assert harness.broker_place.calls == 0
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/execution/test_final_pretrade.py tests/chaos/execution/test_change_between_review_and_submit.py -q`

Expected: FAIL because mutable refresh is missing.

- [ ] **Step 3: Implement final refresh and evaluation sequence**

After review and after acquiring `AccountSubmissionMutex`, refresh account, positions, open orders/local pending intents, authoritative asset-class buying power, quantity-specific executable quote, market clock/halt, tradability/increments, loss/activity state, exposure projection, cost/edge estimate, strategy eligibility, broker health, active alerts, live lease, kill switch, and reconciliation. Build `FinalPretradeContext`, require exactly 24 allowed checks, compare rebuilt reviewed payload hash once more, and reject if quote/review/lease has expired before `SUBMISSION_PENDING`.

- [ ] **Step 4: Persist every allow/deny reason**

Store the complete risk evaluation even when one or more checks deny. Logs contain stable codes and redacted observed/configured values; no secret provider payload is logged.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/integration/execution/test_final_pretrade.py tests/chaos/execution/test_change_between_review_and_submit.py -q`

Expected: PASS and zero place calls after any mutation.

```bash
git add src/trading_bot/execution/service.py tests/integration/execution/test_final_pretrade.py tests/chaos/execution/test_change_between_review_and_submit.py
git commit -m "feat: enforce pre-submit state refresh"
```

### Task 7: Implement live preflight and composition roots

**Files:**
- Create: `src/trading_bot/runtime/live.py`
- Create: `src/trading_bot/runtime/runner.py`
- Create: `tests/integration/runtime/test_live_preflight.py`
- Create: `tests/architecture/test_live_composition.py`

**Interfaces:**
- Produces: `LiveStage`, `LivePreflightResult`, `build_cancel_only_recovery`, `build_live_application`, and `LiveApplication.start_paused/run_cycle`.
- Consumes: a stage-specific `PromotionAttestation`; missing evidence is a hard deny, and this plan has no way to fabricate it.

- [ ] **Step 1: Write failing composition-gate tests**

```python
def test_place_capability_is_not_requested_before_authorization(factory: LiveFactoryHarness) -> None:
    with pytest.raises(LiveNotReady):
        factory.build_live_application(expired_authorization())
    assert factory.place_factory.calls == 0

def test_cancel_only_recovery_has_no_place_dependency() -> None:
    assert "broker_place" not in inspect.signature(build_cancel_only_recovery).parameters

def test_missing_promotion_attestation_denies_live(factory: LiveFactoryHarness) -> None:
    with pytest.raises(LiveNotReady, match="promotion evidence"):
        factory.build_live_application(valid_authorization(), promotion=None)
    assert factory.place_factory.calls == 0
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/runtime/test_live_preflight.py tests/architecture/test_live_composition.py -q`

Expected: FAIL with missing live composition.

- [ ] **Step 3: Implement exact readiness gates**

Require `LIVE_TRADING_ENABLED=true`, a clean live code identity, exact strategy-version eligibility evidence, allowlisted unchanged account, signed one-time artifact, clean reconciliation, successful risk self-test, clock drift ≤2 seconds, inactive kill switch, exact acknowledgement, preflight ≤5 minutes old, no critical alerts, capability evidence, a current stage-specific promotion attestation, and valid execution lease. Enforce $150 account ceiling.

- [ ] **Step 4: Enforce stage bounds**

Micro-live caps are $5 order notional, $20 gross, and two new orders per UTC day and requires a `MICRO` promotion attestation. Normal-live requires a `NORMAL` attestation proving non-overridable 30 combined days, 100 observations, no unresolved incident, acceptable configured realized slippage, researched drawdown bounds, and renewed acknowledgement. `build_live_application(..., promotion=None)` is the default and always denies; the later evidence-ledger evaluator can supply an attestation but cannot activate a mode.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/integration/runtime/test_live_preflight.py tests/architecture/test_live_composition.py -q`

Expected: PASS; default configs cannot build placement.

```bash
git add src/trading_bot/runtime/live.py src/trading_bot/runtime/runner.py tests/integration/runtime/test_live_preflight.py tests/architecture/test_live_composition.py
git commit -m "feat: add locked live composition roots"
```

### Task 8: Complete restart recovery and cancel-only behavior

**Files:**
- Modify: `src/trading_bot/execution/recovery.py`
- Test: `tests/integration/execution/test_cancel_only_recovery.py`
- Test: `tests/chaos/execution/test_restart_submission_boundaries.py`

**Interfaces:**
- Recovery can read and cancel a positively identified unfilled entry; it cannot place, replace, or cancel a protective exit automatically.

- [ ] **Step 1: Write failing restart-boundary tests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("crash_point", ["before_send", "after_send_before_response", "after_response_before_commit"])
async def test_restart_never_duplicates_order(crash_point: str, harness: CrashRecoveryHarness) -> None:
    await harness.crash_at(crash_point)
    await harness.restart_and_recover()
    assert harness.total_external_orders <= 1
    assert harness.runtime_state is not RuntimeState.RUNNING_LIVE
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/execution/test_cancel_only_recovery.py tests/chaos/execution/test_restart_submission_boundaries.py -q`

Expected: FAIL until recovery handles all persisted states.

- [ ] **Step 3: Implement state-specific recovery**

`PROPOSED`/unsubmitted intents are expired locally. `SUBMISSION_PENDING` and unknown states reconcile before action. Known open entries may be canceled through `BrokerCancelOnly` when action policy allows. Existing protective exits remain. Any unresolved result leaves runtime paused and emits a critical alert.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/integration/execution/test_cancel_only_recovery.py tests/chaos/execution/test_restart_submission_boundaries.py -q`

Expected: PASS with no duplicate effect.

```bash
git add src/trading_bot/execution/recovery.py tests/integration/execution/test_cancel_only_recovery.py tests/chaos/execution/test_restart_submission_boundaries.py
git commit -m "feat: complete cancel-only restart recovery"
```

### Task 9: Implement graceful shutdown

**Files:**
- Create: `src/trading_bot/runtime/shutdown.py`
- Test: `tests/integration/runtime/test_shutdown.py`
- Test: `tests/chaos/runtime/test_shutdown_during_partial_fill.py`

**Interfaces:**
- Produces: `ShutdownCoordinator.shutdown(reason, deadline) -> ShutdownResult`.

- [ ] **Step 1: Write failing shutdown tests**

```python
@pytest.mark.asyncio
async def test_shutdown_blocks_new_intents_and_preserves_position(harness: ShutdownHarness) -> None:
    result = await harness.coordinator.shutdown("SIGTERM", deadline=NOW + timedelta(seconds=30))
    assert result.new_intents_blocked
    assert harness.liquidation_calls == 0
    assert result.state_persisted
    assert result.reason == "SIGTERM"
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/runtime/test_shutdown.py tests/chaos/runtime/test_shutdown_during_partial_fill.py -q`

Expected: FAIL with missing coordinator.

- [ ] **Step 3: Implement ordered shutdown**

Enter `SHUTTING_DOWN`, block new intents, stop lease renewal, finish/rollback DB transactions, persist state, reconcile in-flight requests, discard unsubmitted proposals, handle submitted orders according to actual state/action policy, record reason, and exit after durable confirmation or deadline. Never blanket-liquidate.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/integration/runtime/test_shutdown.py tests/chaos/runtime/test_shutdown_during_partial_fill.py -q`

Expected: PASS.

```bash
git add src/trading_bot/runtime/shutdown.py tests/integration/runtime/test_shutdown.py tests/chaos/runtime/test_shutdown_during_partial_fill.py
git commit -m "feat: add durable graceful shutdown"
```

### Task 10: Add live operator commands while preserving default lock

**Files:**
- Create: `src/trading_bot/cli/preflight.py`
- Create: `src/trading_bot/cli/live.py`
- Create: `scripts/run_live.py`
- Modify: `src/trading_bot/cli/main.py`
- Modify: `Makefile`
- Test: `tests/integration/cli/test_live_commands.py`
- Test: `tests/architecture/test_no_test_live_network.py`

**Interfaces:**
- Produces: `trader preflight`, `trader enable-live --stage micro`, `trader disable-live`, `trader pause`, `trader resume`, and the initially paused `trader run --mode micro-live|normal-live` command.
- `enable-live` operator signing runs outside the service host and emits a signed artifact; it does not start trading by itself.

- [ ] **Step 1: Write failing CLI gate tests**

```python
def test_enable_live_requires_exact_acknowledgement(cli: CliRunner) -> None:
    result = cli.invoke(app, ["enable-live", "--stage", "micro", "--acknowledge", "wrong"])
    assert result.exit_code != 0
    assert "exact acknowledgement" in result.stdout

def test_run_live_defaults_paused(cli: CliRunner) -> None:
    result = cli.invoke(
        app,
        ["run", "--mode", "micro-live", "--config", "configs/micro_live.yaml", "--once"],
    )
    assert result.exit_code == 2
    assert "paused" in result.stdout
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/cli/test_live_commands.py tests/architecture/test_no_test_live_network.py -q`

Expected: FAIL with missing commands.

- [ ] **Step 3: Implement explicit commands**

The exact acknowledgement is `I ACCEPT THAT THIS SYSTEM CAN LOSE THE ENTIRE TRADING BALANCE`. `preflight` produces masked metadata and a canonical report, exits `0` only when every gate is ready, and exits `2` for the expected locked/not-ready state. `enable-live` signs only on the operator workstation. `run` always starts paused and `--once` exits `2` without an already valid stage-specific authorization/promotion/readiness set. `resume` requires valid lease/readiness and cannot clear kill switch. `disable-live` revokes lease and blocks new entries. The operations plan later composes this runner with the scheduler, heartbeat, and monitoring server without changing its paused default.

- [ ] **Step 4: Add Make target that performs preflight only**

```make
live-preflight:
	uv run trader preflight --config configs/micro_live.yaml
```

There is no default Make target that activates live trading.

- [ ] **Step 5: Run full locked-live verification**

Run:

```bash
uv run pytest tests/unit/execution tests/property/execution tests/integration/execution tests/integration/runtime/test_live_preflight.py tests/integration/runtime/test_shutdown.py tests/integration/cli/test_live_commands.py tests/chaos/execution tests/chaos/runtime tests/architecture/test_live_composition.py tests/architecture/test_no_test_live_network.py --cov=trading_bot.execution --cov-branch --cov-fail-under=90
uv run ruff check .
uv run mypy src
set +e
make live-preflight
status=$?
set -e
test "$status" -eq 2
```

Expected: automated tests pass; `make live-preflight` exits exactly `2` and reports not ready without credentials/authorization; no broker write occurs.

- [ ] **Step 6: Commit live commands**

```bash
git add src/trading_bot/cli scripts/run_live.py Makefile tests/integration/cli/test_live_commands.py tests/architecture/test_no_test_live_network.py
git commit -m "feat: add explicitly locked live operator flow"
```

## Slice Completion Gate

All local unit, property, integration, replay, and chaos tests pass. Risk and state-machine branch coverage are at least 90%. Default configuration cannot construct `BrokerPlace`. Unknown submissions always reconcile before action. Restart exposes only read/cancel-known-order capability. Prediction live is unavailable. No real order or cancellation was placed during this slice.
