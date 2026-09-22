# Official Robinhood Adapters and Shadow Mode Implementation Plan

> Historical planning snapshot from 2026-07-10. For current implementation and operational
> status, see the repository README and `docs/final-implementation-report.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement verified read-only Robinhood Crypto and Trading MCP integrations, schema-drift protection, explicit prediction refusal, and shadow trading without exposing a live placement capability.

**Architecture:** Official transports parse provider DTOs into broker-neutral domain records behind split read/review/place/cancel protocols. Committed schema manifests determine which capabilities may be constructed; shadow mode combines real reads with the simulated broker and cannot import or receive `BrokerPlace`.

**Tech Stack:** HTTPX 0.28.1, MCP Python SDK 1.28.1 (`<2`), Pydantic 2.13.4 strict provider DTOs, PyNaCl 1.6.2, Structlog 26.1.0, Respx 0.23.1, local fake MCP server.

## Global Constraints

- Use only `https://agent.robinhood.com/mcp/trading` and `https://trading.robinhood.com` official interfaces.
- The repository currently has no configured `robinhood-trading` MCP server; public names are documented evidence only.
- Never derive MCP DTOs from descriptions. Mapping requires a sanitized `tools/list` snapshot and authenticated response-shape evidence.
- A missing or incompatible schema disables the affected capability and makes readiness false.
- Authenticated evidence stores shapes, hashes, timestamps, and limitations, never account values or secrets.
- Crypto signing uses exact bytes: `api_key + timestamp + path_with_query + HTTP_method + body`; omit body when absent.
- Safe retries apply only to classified reads. Order and cancel POSTs are not retried blindly.
- Crypto `best_bid_ask` is informational because its documented response lacks a provider timestamp; executable freshness uses timestamped estimated price data.
- No v2 single-order GET or standalone fill endpoint is invented; bounded order listing and embedded executions are used.
- Shadow mode has zero official broker writes and always uses a simulated execution adapter.
- Prediction live remains disabled and throws `UnsupportedCapabilityError`.
- No account identifier, credential, signature, token, or raw authenticated payload is committed or logged.

---

### Task 1: Snapshot official Crypto v2 schemas and add strict provider DTOs

**Files:**
- Create: `src/trading_bot/brokers/schema_snapshots/manifest.json`
- Create: `src/trading_bot/brokers/schema_snapshots/robinhood_crypto_v2.json`
- Create: `src/trading_bot/brokers/robinhood_crypto_schemas.py`
- Create: `src/trading_bot/brokers/robinhood_crypto_mapping.py`
- Create: `tests/fixtures/robinhood_crypto/accounts.json`
- Create: `tests/fixtures/robinhood_crypto/holdings.json`
- Create: `tests/fixtures/robinhood_crypto/trading_pairs.json`
- Create: `tests/fixtures/robinhood_crypto/estimated_price.json`
- Create: `tests/fixtures/robinhood_crypto/orders.json`
- Test: `tests/unit/brokers/test_robinhood_crypto_schemas.py`
- Test: `tests/unit/brokers/test_robinhood_crypto_mapping.py`

**Interfaces:**
- Produces strict DTOs: `CryptoAccountDto`, `CryptoHoldingDto`, `TradingPairDto`, `BestBidAskDto`, `EstimatedPriceDto`, `CryptoExecutionDto`, and `CryptoOrderDto`.
- Produces mapping functions returning `AccountSnapshot`, `Position`, `Instrument`, `Quote`, `BrokerOrder`, and `Fill`.

- [ ] **Step 1: Write failing strict-schema tests**

```python
def test_trading_pair_decimal_fields_remain_exact() -> None:
    dto = TradingPairDto.model_validate_json(fixture("trading_pairs.json"))
    assert dto.results[0].asset_increment == Decimal("0.00000001")

def test_unknown_provider_field_fails_schema() -> None:
    payload = fixture_json("accounts.json")
    payload["results"][0]["unreviewed_field"] = "value"
    with pytest.raises(ValidationError):
        CryptoAccountsResponse.model_validate(payload)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/brokers/test_robinhood_crypto_schemas.py tests/unit/brokers/test_robinhood_crypto_mapping.py -q`

Expected: FAIL with missing Crypto DTOs.

- [ ] **Step 3: Record a source-hashed schema subset**

Capture only the official v2 operations and fields used by the adapter:

```text
GET  /api/v2/crypto/trading/accounts/
GET  /api/v2/crypto/trading/trading_pairs/
GET  /api/v2/crypto/trading/holdings/
GET  /api/v2/crypto/marketdata/best_bid_ask/
GET  /api/v2/crypto/trading/estimated_price/
GET  /api/v2/crypto/trading/orders/
POST /api/v2/crypto/trading/orders/
POST /api/v2/crypto/trading/orders/{id}/cancel/
```

The manifest records official source URL, retrieval UTC time, content SHA-256, operation, evidence level `documented`, and limitations. It does not claim a v2 single-order GET, websocket, sandbox, review endpoint, fill endpoint, transfer, or withdrawal.

- [ ] **Step 4: Implement strict DTOs and neutral mapping**

```python
class StrictProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class TradingPairDto(StrictProviderModel):
    symbol: str
    asset_code: str
    quote_code: str
    asset_increment: Decimal
    quote_increment: Decimal
    max_order_size: Decimal
    min_order_amount: Decimal
    status: str
    is_api_tradable: bool
```

Reject naive timestamps, nonfinite values, unsupported currencies, unexpected symbols, and malformed embedded executions. Because the official schema does not promise a fill ID, reconcile executions as a multiset keyed by broker order ID plus execution timestamp, side, price, and quantity. Assign a persisted zero-based occurrence ordinal within each identical tuple. On every poll, compare observed multiplicity with persisted ordinals and insert only missing ordinals; a reordered replay has no second effect, while two legitimate identical-looking executions produce ordinals `0` and `1`. A decrease in observed multiplicity or a mismatch between summed executions and the broker's cumulative executed quantity is material drift and blocks trading.

Add fixtures/tests for: the same response replayed twice, the same executions reordered, two legitimate identical tuples, and cumulative-filled quantity disagreement. The first two create no duplicate effect; the third records two fills; the fourth raises reconciliation-required.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/unit/brokers/test_robinhood_crypto_schemas.py tests/unit/brokers/test_robinhood_crypto_mapping.py -q`

Expected: PASS.

```bash
git add src/trading_bot/brokers/schema_snapshots src/trading_bot/brokers/robinhood_crypto_schemas.py src/trading_bot/brokers/robinhood_crypto_mapping.py tests/fixtures/robinhood_crypto tests/unit/brokers
git commit -m "feat: add verified Crypto v2 schemas"
```

### Task 2: Implement exact Crypto request signing and transport

**Files:**
- Create: `src/trading_bot/brokers/robinhood_crypto_auth.py`
- Create: `src/trading_bot/brokers/robinhood_crypto_transport.py`
- Test: `tests/unit/brokers/test_robinhood_crypto_auth.py`
- Test: `tests/integration/brokers/test_robinhood_crypto_transport.py`

**Interfaces:**
- Produces: `CryptoCredentialMaterial`, `CryptoCredentialProvider`, `FileCryptoCredentialProvider`, `SignedHeaders`, `sign_crypto_request`, `RobinhoodCryptoTransport.request`, and `RetryClass`.

- [ ] **Step 1: Write failing deterministic signing tests**

```python
def test_signer_uses_exact_query_and_body_bytes(test_credentials: CryptoCredentialMaterial) -> None:
    headers = sign_crypto_request(
        credentials=test_credentials,
        timestamp_seconds=1_800_000_000,
        method="POST",
        path_with_query="/api/v2/crypto/trading/orders/?account_number=RHC1",
        body=b'{"symbol":"BTC-USD"}',
    )
    expected_message = (
        test_credentials.api_key.get_secret_value().encode()
        + b"1800000000"
        + b"/api/v2/crypto/trading/orders/?account_number=RHC1"
        + b"POST"
        + b'{"symbol":"BTC-USD"}'
    )
    verify_key = SigningKey(
        test_credentials.private_key_seed.get_secret_value()
    ).verify_key
    verify_key.verify(expected_message, base64.b64decode(headers.x_signature))
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/brokers/test_robinhood_crypto_auth.py -q`

Expected: FAIL with missing signer.

- [ ] **Step 3: Implement secret-safe signing**

```python
@dataclass(frozen=True, slots=True, repr=False)
class CryptoCredentialMaterial:
    api_key: SecretStr
    private_key_seed: SecretBytes

def sign_crypto_request(
    *,
    credentials: CryptoCredentialMaterial,
    timestamp_seconds: int,
    method: Literal["GET", "POST"],
    path_with_query: str,
    body: bytes | None,
) -> SignedHeaders:
    message = (
        credentials.api_key.get_secret_value().encode()
        + str(timestamp_seconds).encode()
        + path_with_query.encode()
        + method.encode()
        + (body or b"")
    )
    signature = SigningKey(credentials.private_key_seed.get_secret_value()).sign(message).signature
    return SignedHeaders(...)
```

`repr`, exceptions, and structured logs never contain credential values, message bytes, or signed headers.

`FileCryptoCredentialProvider` reads paths only from `ROBINHOOD_CRYPTO_API_KEY_FILE` and `ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE`, requires regular files owned by the service user with no group/other permission bits, strips one trailing newline, Base64-decodes an exact 32-byte Ed25519 private seed, and registers both loaded values with `SecretRegistry` before any exception can be logged. Raw keys in environment variables are rejected.

- [ ] **Step 4: Implement exact-byte transport**

Serialize JSON once to canonical bytes, build the actual encoded query in stable order, sign those exact bytes/path, and pass the same bytes to HTTPX. GET may use bounded exponential retry for connect/timeout/429/5xx according to config. `RetryClass.WRITE_NEVER` performs one POST attempt and returns `BrokerSubmissionAmbiguous` on a timeout after send.

- [ ] **Step 5: Run transport tests**

Run: `uv run pytest tests/unit/brokers/test_robinhood_crypto_auth.py tests/integration/brokers/test_robinhood_crypto_transport.py -q`

Expected: PASS; Respx records exact headers and a single POST attempt.

- [ ] **Step 6: Commit signer and transport**

```bash
git add src/trading_bot/brokers/robinhood_crypto_auth.py src/trading_bot/brokers/robinhood_crypto_transport.py tests/unit/brokers/test_robinhood_crypto_auth.py tests/integration/brokers/test_robinhood_crypto_transport.py
git commit -m "feat: add exact Crypto v2 signing transport"
```

### Task 3: Implement the Crypto read and market-data adapters

**Files:**
- Create: `src/trading_bot/brokers/robinhood_crypto_api.py`
- Create: `src/trading_bot/market_data/robinhood_crypto_api.py`
- Test: `tests/integration/brokers/test_robinhood_crypto_read.py`
- Test: `tests/integration/market_data/test_robinhood_crypto.py`

**Interfaces:**
- Produces: `RobinhoodCryptoReadAdapter` implementing `BrokerRead`.
- Produces: `RobinhoodCryptoMarketData` implementing `MarketDataProvider` for verified Crypto operations.
- Produces: `find_order(account_id, client_order_id, created_after) -> BrokerOrder | None` using bounded list filtering.

- [ ] **Step 1: Write failing read-adapter tests**

```python
@pytest.mark.asyncio
async def test_crypto_buying_power_is_not_equity_margin(adapter: RobinhoodCryptoReadAdapter) -> None:
    account = await adapter.get_account_state(AccountId("RHC1"))
    assert account.buying_power_for(AssetClass.CRYPTO) == Decimal("100.00")

@pytest.mark.asyncio
async def test_best_bid_ask_cannot_satisfy_executable_freshness(provider: RobinhoodCryptoMarketData) -> None:
    quote = await provider.get_quote(InstrumentId("BTC-USD"))
    assert not quote.freshness_verified

@pytest.mark.asyncio
async def test_executable_quote_uses_two_timestamped_estimates(
    provider: RobinhoodCryptoMarketData,
) -> None:
    quote = await provider.get_executable_quote(
        InstrumentId("BTC-USD"), quantity=Decimal("0.001")
    )
    assert quote.source == "robinhood_crypto_estimated_price_pair"
    assert quote.freshness_verified
    assert quote.timestamp_source is TimestampSource.PROVIDER
    assert provider.estimated_price_sides == ("buy", "sell")
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/brokers/test_robinhood_crypto_read.py tests/integration/market_data/test_robinhood_crypto.py -q`

Expected: FAIL with missing adapters.

- [ ] **Step 3: Implement read operations and pagination**

Map accounts, holdings, tradable pairs, timestamped estimated price, orders, and embedded executions. Use current trading-pair increments/minimums/status; never hard-code product precision. Bounded order lookup requires account, client order ID, and creation lower bound.

- [ ] **Step 4: Implement market-data capability reporting**

`best_bid_ask` is exposed only as informational data with `freshness_verified=False` and `timestamp_source=TimestampSource.LOCAL_RECEIPT`. `get_executable_quote(instrument_id, quantity)` makes two documented estimated-price reads for the exact quantity: the sell-side estimate becomes the executable bid proxy and the buy-side estimate becomes the executable ask proxy. Both provider timestamps must be within the configured five-second age and within the configured cross-response skew; otherwise reject. Its result uses `timestamp_source=TimestampSource.PROVIDER`. Preserve each response hash and hash the pair. Do not turn a single estimated price into a two-sided quote or substitute local receipt time for provider time. Unsupported corporate actions or earnings raise explicit capability errors.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/integration/brokers/test_robinhood_crypto_read.py tests/integration/market_data/test_robinhood_crypto.py -q`

Expected: PASS with only mocked official endpoints.

```bash
git add src/trading_bot/brokers/robinhood_crypto_api.py src/trading_bot/market_data/robinhood_crypto_api.py tests/integration/brokers/test_robinhood_crypto_read.py tests/integration/market_data/test_robinhood_crypto.py
git commit -m "feat: add Robinhood Crypto read adapters"
```

### Task 4: Implement generic MCP transport and schema-drift gate

**Files:**
- Create: `src/trading_bot/brokers/robinhood_mcp_transport.py`
- Create: `src/trading_bot/brokers/robinhood_mcp_schema_gate.py`
- Create: `tests/fixtures/mcp/generic_tools_list.json`
- Test: `tests/unit/brokers/test_robinhood_mcp_schema_gate.py`
- Test: `tests/integration/brokers/test_robinhood_mcp_transport.py`
- Test: `tests/chaos/brokers/test_robinhood_mcp_schema_drift.py`

**Interfaces:**
- Produces: `DeclaredMcpTool`, `McpToolSession`, `SchemaDrift`, `SchemaDriftReport`, `compare_mcp_schema`, and `RobinhoodMcpTransport`.

- [ ] **Step 1: Write failing schema-drift tests**

```python
@pytest.mark.parametrize(
    "mutation",
    [remove_required_tool, add_required_argument, change_enum, remove_output_field],
)
def test_incompatible_schema_disables_capability(mutation: SchemaMutation) -> None:
    report = compare_mcp_schema(mutation(expected_tools()), expected_manifest())
    assert not report.live_ready
    assert report.incompatible
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/unit/brokers/test_robinhood_mcp_schema_gate.py tests/chaos/brokers/test_robinhood_mcp_schema_drift.py -q`

Expected: FAIL with missing schema gate.

- [ ] **Step 3: Implement schema canonicalization and transport seam**

```python
@dataclass(frozen=True, slots=True)
class DeclaredMcpTool:
    name: str
    description: str | None
    input_schema: JsonValue
    output_schema: JsonValue | None
    schema_sha256: str

class McpToolSession(Protocol):
    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]: ...
    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> McpToolResult: ...
```

The official transport uses Streamable HTTP and the supported MCP OAuth flow only, with SDK credential state under a service-owned mode-`0700` `ROBINHOOD_MCP_OAUTH_STORE_DIR`. Disable raw HTTPX/MCP wire logging; route SDK exceptions through centralized redaction and never serialize request headers, OAuth state, or raw tool results. Never scrape, extract, or repurpose Codex/ChatGPT platform tokens.

- [ ] **Step 4: Verify with a local fake MCP server**

Run: `uv run pytest tests/unit/brokers/test_robinhood_mcp_schema_gate.py tests/integration/brokers/test_robinhood_mcp_transport.py tests/chaos/brokers/test_robinhood_mcp_schema_drift.py -q`

Expected: PASS; no request leaves localhost.

- [ ] **Step 5: Commit generic MCP gate**

```bash
git add src/trading_bot/brokers/robinhood_mcp_transport.py src/trading_bot/brokers/robinhood_mcp_schema_gate.py tests/fixtures/mcp tests/unit/brokers/test_robinhood_mcp_schema_gate.py tests/integration/brokers/test_robinhood_mcp_transport.py tests/chaos/brokers/test_robinhood_mcp_schema_drift.py
git commit -m "feat: add MCP schema drift gate"
```

### Task 5: Add the fail-closed equity MCP capability factory

**Files:**
- Create: `src/trading_bot/brokers/robinhood_equity_mcp.py`
- Create: `src/trading_bot/brokers/robinhood_equity_mapping.py`
- Create: `src/trading_bot/market_data/robinhood_equity_mcp.py`
- Create: `tests/unit/brokers/test_robinhood_equity_lock.py`
- Test: `tests/architecture/test_equity_mapping_evidence.py`

**Interfaces:**
- Produces: `build_equity_read_adapter(manifest, transport) -> BrokerRead`.
- Before verified evidence, returns no adapter and raises `CapabilityNotVerified` with the missing evidence level.

- [ ] **Step 1: Write the failing lock test**

```python
def test_equity_adapter_cannot_build_from_documented_names() -> None:
    with pytest.raises(CapabilityNotVerified, match="schema-declared"):
        build_equity_read_adapter(documented_only_manifest(), fake_transport())
```

- [ ] **Step 2: Run the test and observe failure**

Run: `uv run pytest tests/unit/brokers/test_robinhood_equity_lock.py tests/architecture/test_equity_mapping_evidence.py -q`

Expected: FAIL because factory is missing.

- [ ] **Step 3: Implement the locked factory and empty mapper boundary**

The factory requires schema-declared evidence for tool arguments and authenticated-read-verified evidence for response shapes. `robinhood_equity_mapping.py` contains only shared validation helpers until those artifacts exist. Architecture tests reject provider field mappings with no matching evidence record and schema hash.

- [ ] **Step 4: Run and commit the lock**

Run: `uv run pytest tests/unit/brokers/test_robinhood_equity_lock.py tests/architecture/test_equity_mapping_evidence.py -q`

Expected: PASS; equity readiness is false.

```bash
git add src/trading_bot/brokers/robinhood_equity_mcp.py src/trading_bot/brokers/robinhood_equity_mapping.py src/trading_bot/market_data/robinhood_equity_mcp.py tests/unit/brokers/test_robinhood_equity_lock.py tests/architecture/test_equity_mapping_evidence.py
git commit -m "feat: lock equity adapter behind evidence"
```

### Task 6: Capture authenticated equity shapes and implement read mapping when available

**Files:**
- Create: `scripts/verify_robinhood_equity_reads.py`
- Generate only after successful capture: `src/trading_bot/brokers/schema_snapshots/robinhood_equity_mcp.tools.json`
- Generate only after successful capture: `tests/fixtures/robinhood_equity/sanitized_shapes.json`
- Modify only after successful capture: `src/trading_bot/brokers/robinhood_equity_mapping.py`
- Modify only after successful capture: `src/trading_bot/brokers/robinhood_equity_mcp.py`
- Test: `tests/unit/brokers/test_robinhood_equity_mapping.py`
- Test: `tests/integration/brokers/test_robinhood_equity_read.py`

**Interfaces:**
- Produces verified mappings for only the tools present in the reviewed snapshot.
- Authenticated verifier emits field/type/nullable/enum shape hashes, not values.

- [ ] **Step 1: Verify the external prerequisite without mutating account state**

Run:

```bash
codex mcp list --json
uv run python scripts/capture_mcp_capabilities.py --server robinhood-trading --output /tmp/robinhood-tools.json
```

Expected prerequisite: `robinhood-trading` is configured and authenticated, and capture reports `tools/list` only. If absent, stop this task, keep equity readiness false, record `blocked_unconfigured_mcp` in the capability matrix, and continue only with Crypto and prediction-refusal tasks. Do not fabricate fixtures.

- [ ] **Step 2: Implement the shape-only authenticated verifier**

`scripts/verify_robinhood_equity_reads.py` accepts `--server`, `--output`, and a repeated `--tool` whose values must be members of the reviewed read-only allowlist (`get_accounts`, `get_portfolio`, `get_equity_positions`, `get_equity_quotes`, `get_equity_orders`, `get_equity_tradability`, `get_equity_historicals`, `get_equity_fundamentals`, `get_earnings_results`, and `get_earnings_calendar`). It rejects `review_*`, `place_*`, `cancel_*`, and every unknown name in normal mode.

The recursive sanitizer converts authenticated results directly in memory to field paths, JSON types, nullability, observed enum candidates only for documented non-sensitive status fields, collection cardinality class (`empty`, `one`, or `many`), and a canonical shape hash. It never writes or prints values, raw result text, account IDs, symbols held, quantities, balances, prices, order IDs, timestamps from account activity, or MCP authorization material. The command first writes to a mode-`0600` temporary file, re-reads it through `assert_shape_only_artifact`, and atomically renames only after the secret/account-value scanner passes.

An optional `--non-submitting-review-evidence REQUEST.json` path is a separate explicit operator action. It may call only the schema-verified `review_equity_order`, requires a fixture-sized request with an allowlisted account attestation, confirms from the manifest that the tool is non-submitting, emits shape metadata only, and never calls `place_equity_order`. It is not run by tests, CI, setup, or the default read-verification command.

- [ ] **Step 3: Write mapping tests from reviewed sanitized shapes**

```python
@pytest.mark.asyncio
async def test_equity_account_values_are_decimal_and_masked_in_display(adapter: EquityReadHarness) -> None:
    account = await adapter.get_account_state(adapter.account_id)
    assert isinstance(account.equity, Decimal)
    assert adapter.display_account(account).endswith(str(account.account_id)[-4:])
    assert str(account.account_id) not in adapter.display_account(account)[:-4]
```

- [ ] **Step 4: Run tests and observe mapper failure**

Run: `uv run pytest tests/unit/brokers/test_robinhood_equity_mapping.py tests/integration/brokers/test_robinhood_equity_read.py -q`

Expected: FAIL because verified field mapping is not implemented.

- [ ] **Step 5: Implement only captured mappings**

Prefer MCP `structuredContent`. Accept text JSON only if the captured output schema and authenticated probe prove it. Map account, portfolio/non-margin buying power, positions, quotes, orders, tradability/fractional eligibility, historicals, fundamentals, and earnings only when their evidence records pass. Any incompatible or missing field disables that operation.

- [ ] **Step 6: Verify locally with sanitized fake MCP responses**

Run: `uv run pytest tests/unit/brokers/test_robinhood_equity_mapping.py tests/integration/brokers/test_robinhood_equity_read.py -q`

Expected: PASS; tests contact only the local fake MCP server.

- [ ] **Step 7: Commit evidence and mappings**

```bash
git add scripts/verify_robinhood_equity_reads.py src/trading_bot/brokers/schema_snapshots src/trading_bot/brokers/robinhood_equity_mapping.py src/trading_bot/brokers/robinhood_equity_mcp.py tests/fixtures/robinhood_equity tests/unit/brokers/test_robinhood_equity_mapping.py tests/integration/brokers/test_robinhood_equity_read.py docs/capability-matrix.md
git commit -m "feat: add evidence-backed equity read adapter"
```

If the prerequisite remains absent, commit only the verifier and matrix status with message `docs: record unavailable equity MCP verification`; do not claim adapter completion.

### Task 7: Implement explicit prediction adapter refusal

**Files:**
- Create: `src/trading_bot/brokers/robinhood_prediction.py`
- Test: `tests/unit/brokers/test_robinhood_prediction.py`

**Interfaces:**
- Produces: simulation normalization methods and live methods that always raise `UnsupportedCapabilityError`.

- [ ] **Step 1: Write failing refusal tests**

```python
@pytest.mark.asyncio
async def test_prediction_live_place_always_fails() -> None:
    adapter = RobinhoodPredictionAdapter(default_config())
    with pytest.raises(UnsupportedCapabilityError, match="not verified"):
        await adapter.place_order(make_prediction_intent())
```

- [ ] **Step 2: Run, implement, and rerun**

Run: `uv run pytest tests/unit/brokers/test_robinhood_prediction.py -q`

Expected first: FAIL. Implement the refusal with `PREDICTION_LIVE_ENABLED=false`, then expect PASS.

- [ ] **Step 3: Commit refusal adapter**

```bash
git add src/trading_bot/brokers/robinhood_prediction.py tests/unit/brokers/test_robinhood_prediction.py
git commit -m "feat: fail closed for prediction execution"
```

### Task 8: Compose shadow runtime with real reads and simulated execution

**Files:**
- Create: `src/trading_bot/runtime/shadow.py`
- Create: `scripts/run_shadow.py`
- Create: `scripts/run_shadow_smoke.py`
- Modify: `src/trading_bot/cli/main.py`
- Modify: `Makefile`
- Test: `tests/integration/runtime/test_shadow.py`
- Test: `tests/architecture/test_shadow_no_place.py`
- Test: `tests/replay/test_shadow_journal.py`

**Interfaces:**
- Produces: `build_shadow_application(config, broker_read, market_data, fake_broker, repositories, clock) -> ShadowApplication`.
- No `BrokerPlace` parameter or import exists.

- [ ] **Step 1: Write failing no-place composition tests**

```python
def test_shadow_builder_has_no_place_capability() -> None:
    assert "broker_place" not in inspect.signature(build_shadow_application).parameters

@pytest.mark.asyncio
async def test_shadow_records_proposal_without_official_write(shadow: ShadowHarness) -> None:
    result = await shadow.run_cycle()
    assert result.proposed_orders
    assert shadow.official_transport.write_calls == []
    assert shadow.fake_broker.place_calls == len(result.approved_orders)
```

- [ ] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/integration/runtime/test_shadow.py tests/architecture/test_shadow_no_place.py tests/replay/test_shadow_journal.py -q`

Expected: FAIL with missing shadow runtime.

- [ ] **Step 3: Implement explicit account selection and read-only cycle**

Require configured allowlisted account, display only masked metadata, verify account state/equity ceiling, read positions/orders/buying power, reconcile, validate market data, run the production decision cycle, and route approved intents to the fake broker. Any account change, stale data, schema drift, or reconciliation difference pauses the cycle.

- [ ] **Step 4: Record unique shadow evidence**

Store cycle ID, UTC window, configuration/data/code hashes, provider readiness, strategy-eligibility hash, simulated fills, and reconciliation result. The promotion evaluator counts only unique complete cycles across seven real calendar days when every required asset provider is ready and the exact strategy/config/code version has accepted research evidence. Fixture/local-fake and rejected-strategy runs set `evidence_eligible=false` and can never count toward elapsed shadow evidence.

- [ ] **Step 5: Add CLI and Make target**

```make
shadow:
	uv run trader shadow --config configs/shadow.yaml --once

shadow-smoke:
	uv run python scripts/run_shadow_smoke.py --config configs/shadow.yaml
```

`shadow` uses configured authenticated read providers and exits `2` with `external_capability_missing` when they are unavailable. `shadow-smoke` uses only committed sanitized fixtures plus the local fake MCP/HTTP transports, asserts zero official network writes, and emits non-promotable evidence.

- [ ] **Step 6: Run and commit**

Run:

```bash
uv run pytest tests/integration/runtime/test_shadow.py tests/architecture/test_shadow_no_place.py tests/replay/test_shadow_journal.py -q
make shadow-smoke
set +e
make shadow
status=$?
set -e
test "$status" -eq 2
```

Expected: local smoke passes; because the reproducible Trading MCP prerequisite is currently absent, the operator `shadow` target exits exactly `2`; official write calls remain zero and no fixture cycle counts as shadow evidence.

```bash
git add src/trading_bot/runtime/shadow.py scripts/run_shadow.py scripts/run_shadow_smoke.py src/trading_bot/cli/main.py Makefile tests/integration/runtime/test_shadow.py tests/architecture/test_shadow_no_place.py tests/replay/test_shadow_journal.py
git commit -m "feat: add read-only shadow mode"
```

### Task 9: Document adapter setup, evidence, and limitations

**Files:**
- Modify: `docs/capability-matrix.md`
- Modify: `README.md`
- Modify: `docs/limitations.md`
- Modify: `.env.example`
- Test: `tests/smoke/test_documented_commands.py`

**Interfaces:**
- Documents exact environment variable names, MCP connection command, Crypto credential file names, read-verification command, and shadow command without secret values.

- [ ] **Step 1: Write failing documentation smoke test**

```python
def test_documented_commands_exist() -> None:
    commands = extract_shell_commands(Path("README.md").read_text())
    assert "codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading" in commands
    assert "make shadow" in commands
```

- [ ] **Step 2: Document exact capability states**

For each operation show evidence level, schema hash, supported asset, daemon-auth status, limitations, implemented state, and locked reason. State that no authenticated read evidence exists when capture has not run; do not mark transient app metadata as configured MCP evidence.

- [ ] **Step 3: Run full adapter verification**

Run:

```bash
uv run pytest tests/unit/brokers tests/integration/brokers tests/integration/market_data/test_robinhood_crypto.py tests/chaos/brokers tests/integration/runtime/test_shadow.py tests/architecture/test_shadow_no_place.py tests/smoke/test_documented_commands.py -q
uv run ruff check src/trading_bot/brokers src/trading_bot/market_data src/trading_bot/runtime tests
uv run mypy src
```

Expected: all locally testable checks pass; unavailable authenticated equity checks are reported as external pending, not passed.

- [ ] **Step 4: Commit docs**

```bash
git add docs/capability-matrix.md README.md docs/limitations.md .env.example tests/smoke/test_documented_commands.py
git commit -m "docs: document verified Robinhood adapter status"
```

## Slice Completion Gate

Crypto read operations and signing pass against official-schema fixtures and mock HTTP. MCP schema drift fails closed against a local server. Equity mapping exists only if sanitized reproducible evidence was captured; otherwise it remains explicitly locked. Shadow mode produces proposals and simulated outcomes with zero official write calls. Prediction live always raises. No live order or cancellation occurred.
