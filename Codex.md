# Codex implementation rules

## Current repository boundary

Only the paper-safe, fail-closed foundation is implemented: domain and configuration
primitives, capability evidence and sanitized schema capture, broker protocols, and safe
structured logging, plus the Alembic-owned async SQLite ledger schema. Persistence
now includes an explicit single-use unit of work, lossless order-intent writes,
secret-screened audit appends, and database-enforced append-only guards for the seven
critical correction tables. A broker-neutral pure order state machine validates lifecycle
events, keeps terminal states closed, and requires explicit reconciliation after detected
active-order drift. Pure sizing and projected-exposure checks use factory-bound canonical
config and instrument inputs, the lesser current/authorized risk-equity reference, and
downward Decimal quantization. Pure loss/drawdown and durable activity gates preserve
entry-blocked exits, hard-stop on drawdown or unverified reset state, and cannot request
liquidation; their evidence is account-bound and, for activity, instrument-bound. The pure
pretrade engine runs the same ordered functions for a 23-check preliminary pass and 24-check
post-review pass, never short-circuits, captures one injected UTC clock value, and binds
exposure projections to the originating intent. Non-live evaluation waives only live-lease
authorization; code, config, research, and alert evidence remain mandatory. An equity-only,
write-incapable connected-shadow composition can construct exactly the reviewed Robinhood
Trading MCP read capability, validate authenticated response shapes, and append identity-bound
probe and promotion-decision evidence. An SDK-session allowlist and a separate transport allowlist
contain no review, cancel, or place operation, and no provider write adapter exists. This incapability
is enforced locally, not by OAuth: the sole official `internal` scope yields a bearer credential
that must be treated as trading-capable. A stolen token or compromised host could trade in the
Agentic account. These Robinhood connected runs require a canonical root-owned, read-only release
attestation that binds the immutable image ID, resolved configuration hash, Compose hash, and release key. The deploy
helper creates it only after the default paused service passes image, configuration, health,
readiness-denial, and live-disabled checks. The default process remains the paused
loopback-published monitoring service and has no host volumes or credential access.
Prediction live execution is unsupported.
No live order has been placed. This code makes no profitability claim.

The main operator CLI implements offline commands, the health-only paused service, explicit OAuth
bootstrap for the locally write-incapable Robinhood client, and a one-shot connected shadow probe.
A separate explicitly invoked `trading_bot.cli.etf_observations` module implements bounded local
Alpaca SPY/SIP WebSocket capture, offline receipt audits and descriptive private cost reports.
Its transport-free execution receipt sink retains immutable private clock-session
checkpoints. The offline `link-costs` command rehashes them, derives quotes from
retained Alpaca frames and preserves incomplete/unfilled outcomes separately from
terminal filled samples. It is not wired to an authenticated execution runtime;
customer provenance and internally consistent clocks remain unattested declarations.
The verified retained-capture reader returns immutable receipt-ordered frames
through the aggregate audit's shared verifier. Its offline `stream-prefix`
command requires both UTC and monotonic receipt cutoffs from one capture and
publishes a private hash/count report. Neither provider timestamp sorting nor
predecessor chaining is allowed; source/execution/promotion/live stay false.
Typed retention denies more than 10,000 observations atomically without changing
the existing aggregate audit bounds or wire format.
Its transport is fixed to `wss://stream.data.alpaca.markets/v2/sip` and SPY quote/status/LULD
subscriptions. It uses only an explicitly selected owner-private Alpaca paper-key file containing
`key_id` and `secret_key`; the market-data-only authority does not establish that the key itself
is unable to trade. The reviewed plan binds the clean capture revision, config, private paths and
limits and is consumed once. Private raw frames and chained receipts remain outside the checkout
and Cloud; public output contains only sanitized hashes, counts and verdicts. The offline audit CLI
requires a clean committed checkout and binds the auditor revision separately from the captured
revision, without opening credentials. The cost CLI likewise binds a clean calibrator revision
before hashing its private report. Initial controls remain unknown, deliberate restarts
record discontinuities, and no broker order, automatic reconnect,
runtime composition or promotion is enabled. The actual customer input has zero orders and its
cost report remains `BLOCKED_INPUTS`; no zero fees or calibrated slippage/latency follow.
See [the standalone workflow contract](docs/alpaca-execution-observations.md).

No CLI provides a live trading application. Nonempty
equity position and order mappings, provider review/place/cancel adapters, complete strategy cycles,
and qualifying elapsed shadow evidence are not implemented. Do not represent planned modules,
modes, commands, cloud resources, elapsed evidence, review, or execution as completed.

## Safety rules

- Keep the default paused and unable to submit.
- Do not add a provider implementation from public prose or a schema declaration alone.
- Do not authenticate, inspect an account, review or submit an order, provision
  infrastructure, or contact an external service without separate explicit authority.
- Keep provider transports out of broker-neutral domain, strategy, risk, and portfolio
  logic.
- Keep read, review, place, and cancel-only capabilities independently injectable.
- Never describe the Robinhood OAuth credential as read-only. Pin the sole official `internal`
  scope, treat its bearer token as trading-capable, and preserve both local read allowlists and the
  absence of provider review/place/cancel adapters.
- Keep the pretrade clock, account allowlist, active code hash, and loaded-config hash
  explicitly injected. Never substitute caller-supplied context time for the evaluation
  clock or reuse an exposure projection across intents.
- Never put credential material, authorization headers, signatures, private keys,
  or account identifiers in logs, fixtures, errors, reports, task prompts, Cloud, or Git.
  Retain provider payloads only within an explicitly authorized owner-private evidence scope
  outside checkouts and Cloud;
  never include them in logs, fixtures, errors, public reports, task prompts, or Git.
- Redact structured event data before JSON serialization and fail closed on unknown
  objects or redaction errors.
- Install logging limits only from the canonical validated config graph. Sanitize stdlib
  formatting inputs and exception arguments before interpolation, normalize existing
  handlers and filters to the single redacting sink, replace raw record-factory and
  last-resort paths, suppress formatting-error diagnostics, and apply the configured
  event-size bound only after redaction.
- Configure logging in the single-threaded entry point before importing modules that
  materialize or bind Structlog loggers and before starting workers. Treat pre-bound or
  custom-processor Structlog objects as unsupported trusted pre-bootstrap code.
- Preserve the capability matrix distinction between implemented, documented, locked,
  externally pending, and unsupported.
- Keep tests deterministic, local, and selected by the default non-authenticated Pytest
  configuration.

## Baseline verification

Use the narrowest relevant test first, then run `make lint`, `make typecheck`, and
`make test`. `make security` includes a dependency audit that may require package-index
access; do not silently skip or weaken its recipe. Record any externally blocked step
explicitly.
