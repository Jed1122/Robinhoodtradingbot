# Robinhood Multi-Asset Trading System Design

**Status:** Approved for implementation planning  
**Date:** 2026-07-10  
**Repository:** `robinhood-multi-asset-trading-system`  
**Default operating state:** Paused and unable to submit live orders

## 1. Purpose

Build a deterministic, auditable trading platform for a small account beginning at approximately $100. The platform supports equity research and long-only execution through the official Robinhood Trading MCP, BTC/ETH research and execution through the official Robinhood Crypto Trading API, and broker-independent prediction-market research and simulation.

The system prioritizes capital preservation, correctness, reproducibility, auditability, security, and operational clarity. It does not claim or imply profitability. A strategy that fails its research gates remains in research or shadow mode.

No live order may be placed during construction, automated testing, deployment, or demonstration. Micro-live and normal-live execution require separate user authorization after the completed system and a current preflight report have been reviewed.

## 2. Scope and Explicit Exclusions

### In scope

- Backtesting, historical replay, paper trading, shadow trading, micro-live, and normal-live modes.
- Long-only US equities through the official Robinhood Trading MCP.
- BTC-USD and ETH-USD through the official Robinhood Crypto Trading API.
- Prediction-market metadata, probability research, calibration, simulation, and cost modeling.
- Deterministic strategies, portfolio construction, risk evaluation, order review, execution, reconciliation, and append-only audit records.
- SQLite WAL persistence with SQLAlchemy 2 and Alembic, designed for later PostgreSQL migration.
- A read-only local operations API, metrics, alerts, operator CLI, containerization, and DigitalOcean deployment automation.
- Optional read-only LLM reporting that is disabled by default and isolated from broker credentials and order methods.

### Out of scope or prohibited

- Profitability promises or automated promotion based only on backtest performance.
- Options, futures, margin, leverage, short sales, OTC securities, microcaps, leveraged ETFs, inverse ETFs, and unrestricted illiquid assets.
- Martingale sizing, averaging down, chasing missed entries, increasing risk after losses or winning streaks, hidden size escalation, grid trading without bounded risk, and opaque live decision models.
- Reverse-engineered Robinhood endpoints, private mobile APIs, unofficial session libraries, browser automation, scraping, cookies, captured sessions, password automation, CAPTCHA circumvention, or undocumented prediction endpoints.
- Live prediction-market orders until an official Robinhood programmatic execution interface is published and separately verified.
- LLM participation in live trade selection, sizing, risk approval, execution, or reconciliation.
- Automatic emergency liquidation unless a future, separately reviewed policy explicitly enables it.

## 3. Verified Capability Baseline

The capability matrix will preserve the exact tool and endpoint schemas observed during implementation. The design distinguishes public documentation, session-declared tool metadata, and authenticated behavior:

1. Robinhood documents the Trading MCP endpoint as `https://agent.robinhood.com/mcp/trading` and the Codex CLI connection command as `codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading`.
2. Robinhood currently documents MCP order placement for long equities and options in a dedicated Agentic account. This system will use only the equity subset.
3. The current Codex tool registry declares 44 Robinhood tools and their JSON schemas. The declared equity subset includes account, portfolio, positions, quotes, historicals, fundamentals, earnings, tradability, order review, order placement, cancellation, and order-status tools. No authenticated account or trading call was made during design. `docs/capability-matrix.md` will label each capability as documented, schema-declared, authenticated-read-verified, authenticated-write-reviewed, or unsupported. Broker-specific adapter work is blocked until the relevant authenticated schemas are captured without exposing account data or secrets.
4. Robinhood's Crypto Trading API is a separate official API using Ed25519 request signing with `x-api-key`, `x-signature`, and `x-timestamp` headers. The documented v2 API supports fee-tier crypto orders, client-generated UUID order identifiers, order retrieval, and cancellation.
5. Robinhood prediction markets are currently documented as mobile-app-only for trading. No official REST, websocket, or MCP order interface was verified.
6. Robinhood has not publicly documented guarantees for unattended MCP token refresh, headless reauthentication, rate limits, or continuous daemon operation. Equity shadow and live modes therefore fail closed until authenticated unattended operation is verified through the official MCP transport.

Official references:

- <https://robinhood.com/us/en/support/articles/agentic-trading-overview/>
- <https://robinhood.com/us/en/support/articles/trading-with-your-agent/>
- <https://docs.robinhood.com/crypto/trading/>
- <https://robinhood.com/us/en/support/articles/crypto-api/>
- <https://robinhood.com/us/en/support/articles/trading-event-contracts/>

## 4. Delivery Strategy

The project will be implemented as staged vertical slices. Each slice includes code, migrations, configuration, documentation, unit tests, integration tests, and the narrowest relevant operational check.

1. Capability and repository foundation.
2. Domain, persistence, audit, configuration, and safety kernel.
3. Market-data normalization, research engine, simulation, and paper mode.
4. Read-only broker adapters and shadow mode.
5. Locked live execution, reconciliation, and operator controls.
6. Monitoring, container hardening, DigitalOcean infrastructure, backup, restore, and incident operations.
7. Evidence collection for paper, shadow, micro-live, and normal-live promotion gates.

Creating files is not evidence that a gate passed. Time-based and account-dependent gates remain incomplete until real observations are recorded and reviewed.

## 5. Architecture and Dependency Rules

The source package is `src/trading_bot/` with these boundaries:

- `domain/`: broker-neutral immutable value objects, enums, identifiers, and events.
- `config/`: one strict Pydantic configuration graph and mode overlays.
- `market_data/`: provider protocols, normalization, validation, quality events, and recorded-data adapters.
- `brokers/`: official Robinhood MCP, official Robinhood Crypto API, prediction simulation, and fake adapters.
- `strategies/`: deterministic feature-to-signal policies only.
- `portfolio/`: target construction, position sizing, correlation groups, and cash allocation.
- `risk/`: pretrade rules, loss limits, drawdown controls, stale guards, account restrictions, and kill-switch checks.
- `execution/`: order intents, broker review, state-machine transitions, submission, cancellation, partial-fill policy, and recovery.
- `reconciliation/`: broker/local comparison and drift classification.
- `persistence/`: SQLAlchemy models, repositories, transactions, migrations, leases, and append-only audit storage.
- `monitoring/`: health, readiness, metrics, alerts, heartbeat, and read-only HTTP endpoints.
- `reporting/`: performance, incident, tax-lot export, and optional read-only LLM summaries.
- `cli/`: operator commands and explicit acknowledgement workflows.

Dependency direction points inward toward `domain` and protocols. Strategy, portfolio, and risk modules never import a Robinhood client. Broker adapters do not choose trades or alter risk decisions. The execution service is the only component allowed to call broker write methods.

## 6. Core Data Flow

Every decision follows one deterministic path:

1. Ingest market and account data.
2. Validate schema, timestamps, instrument identity, and data quality.
3. Persist the normalized snapshot and data-version hash.
4. Compute versioned features.
5. Produce a deterministic strategy decision.
6. Construct a target portfolio and candidate order intent.
7. Evaluate every configured risk rule and persist all allow/deny reasons.
8. If approved, request broker review and persist the reviewed request and response.
9. Confirm that the reviewed order matches the persisted intent.
10. Recheck live authorization, account identity, freshness, buying power, limits, and reconciliation immediately before submission.
11. Submit through the broker adapter with a durable deduplication key.
12. Persist the broker response before any retry decision.
13. Track partial fills and terminal state.
14. Reconcile broker and local state.
15. Append the final audit outcome.

No exception, retry, recovery path, administrative endpoint, or scheduler path bypasses this sequence.

### Mandatory final pretrade checklist

After broker review and immediately before any live broker submission, the execution service reevaluates and persists all 24 checks. Every check must pass. Simulation and paper use the same evaluator with live-authorization checks explicitly marked not applicable and a broker adapter that has no network write capability.

1. The requested live mode has a current stage-specific lease.
2. The kill switch is inactive.
3. The exact account is allowlisted and unchanged.
4. Broker health passes.
5. Required market data is fresh.
6. The symbol is allowlisted and currently tradable.
7. Fractional eligibility is verified when the order requires it.
8. The current market session is permitted.
9. No halt is detected.
10. Current authoritative non-margin buying power for the asset class is sufficient: equity unleveraged buying power for equities and crypto buying power for crypto.
11. The configured cash reserve remains intact after the order.
12. The position cap remains satisfied.
13. The correlation-group cap remains satisfied.
14. The crypto exposure cap remains satisfied.
15. Daily and weekly loss limits remain satisfied for new entries.
16. Daily, symbol, and interval activity limits remain satisfied.
17. Current spread is within the configured maximum.
18. Estimated slippage is within the configured maximum.
19. Estimated edge remains positive after spread, slippage, fees, and commission.
20. No duplicate or conflicting order exists locally or at the broker.
21. A versioned protective-exit policy exists and is monitorable.
22. The broker-reviewed order exactly matches the persisted intent.
23. Quantity and notional satisfy current broker minimums and increments.
24. Local account, position, order, and fill state matches reconciled broker state.

The final checklist uses fresh account, quote, order, and health reads within configured age limits. Failure produces a machine-readable denial and prevents submission. A broker review older than the configured review lifetime is discarded and cannot be reused.

## 7. Domain and Arithmetic

- Monetary values, prices, quantities, fees, percentages, and profit and loss use `Decimal` with explicit instrument-specific quantization.
- All timestamps are timezone-aware UTC. User-facing conversion happens only in presentation code.
- IDs are strongly typed and distinguish local intents, broker orders, client order IDs, fills, runs, authorizations, reconciliations, and configuration versions.
- Raw provider payloads remain outside domain models and are stored only in sanitized form when needed for audit or replay.
- Nonfinite, negative, malformed, or precision-incompatible numeric inputs are rejected.
- Every strategy and policy has an immutable version string included in its decisions.

## 8. Configuration and Precedence

There is one Pydantic v2 configuration graph. The precedence order is:

1. `configs/base.yaml` safe defaults.
2. Exactly one mode overlay: backtest, simulation, paper, shadow, micro-live, or normal-live.
3. Environment overrides for deployment-specific nonsecret values and secret references.
4. CLI arguments for a single operator action, never for silently weakening a risk limit.
5. A signed live authorization artifact that can enable only the stage and bounded limits already allowed by the validated configuration.

An environment variable alone cannot activate live trading. Configuration is canonicalized and hashed at startup. The hash is stored with every run, decision, authorization, order, and report.

All thresholds live in configuration, including data-age limits, clock tolerance, anomaly bounds, spread limits, slippage limits, reconciliation tolerances, authorization lifetime, preflight lifetime, cooldowns, and safe override bounds. Logic modules contain no strategy or risk thresholds.

`configs/safety-envelope.yaml` contains the release-level maximum permissions and cannot be overridden by environment variables, mode files, or CLI flags. Changing that file requires a code change, review, a new configuration hash, and invalidation of prior live authorizations. Mode configuration may only reduce permissions within this envelope.

Initial live freshness defaults are five seconds for executable quotes, 30 seconds for broker health and account snapshots, 30 seconds for a broker order review, five minutes for a signed preflight, and two seconds maximum detected clock drift. The safety envelope permits these windows to become shorter, not longer. Interval-based research data uses an explicit maximum age in whole bar intervals and cannot substitute a quote for an order-time price check.

Secrets are referenced by environment variable or restricted file path and are never serialized into the configuration snapshot. Unknown keys, duplicate aliases, inconsistent mode flags, and unsafe values fail validation.

## 9. Operating Modes

The process accepts exactly one mode:

| Mode | Historical data | Live market/account reads | Broker writes | Authorization |
|---|---:|---:|---:|---:|
| Backtest | Yes | No | No | None |
| Simulation | Recorded replay | No | No | None |
| Paper | Current/delayed or recorded | Optional public reads | No | None |
| Shadow | Current | Yes | No | Read-only credentials |
| Micro-live | Current | Yes | Locked by default | Micro authorization |
| Normal-live | Current | Yes | Locked by default | Normal authorization plus evidence gates |

All long-running broker-connected processes start paused. One-shot backtest and simulation commands may run immediately because they construct offline simulated adapters and cannot reach a broker. Paper constructs a simulated broker; shadow uses read-only adapter capabilities and rejects all writes. A previously live process may construct a least-privileged recovery capability after authenticated account verification; it exposes reads and cancellation of positively identified, locally recorded unfilled entry orders but has no placement method. Micro-live and normal-live placement capabilities remain unreachable until preflight and authorization verification.

## 10. Live Authorization and Account Protection

Live activation requires every gate below:

- `LIVE_TRADING_ENABLED=true`.
- The exact broker account is allowlisted.
- A valid local authorization artifact exists.
- Reconciliation succeeds.
- The risk-engine self-test succeeds.
- Clock synchronization is within configured tolerance.
- No database or filesystem kill switch is active.
- The exact CLI acknowledgement is supplied.
- A recent signed preflight report matches the configuration and account.
- No unresolved critical alert exists.

Preflight displays the selected account number and linked account metadata with all but the last four characters masked. It verifies account state, restrictions, asset permissions, authoritative non-margin buying power, positions, open orders, and equity before signing. The initial expected equity is $100 and the default live account equity ceiling is $150. Exceeding the ceiling pauses live operation and requires a new preflight and authorization. An account identifier change, account deactivation, unexpected restriction, or permission change activates a hard pause.

Operator bootstrap creates an Ed25519 authorization key pair outside the repository. The private key remains on the operator workstation with mode `0600` and is never copied to the Droplet or trading container. The service host stores only the public verification key. The operator-side CLI signs a current preflight report, and the resulting short-lived artifact is transferred through the authenticated administrative channel. Preflight and authorization artifacts are canonical JSON and include:

- account identifier and authorized live stage;
- configuration hash and code version;
- preflight hash;
- issued, not-before, and expiration timestamps;
- acknowledgement hash and unique nonce;
- micro-live bounds when applicable.

The one-time activation artifact expires after 15 minutes and can authorize only one process start. A successful start exchanges it for a bounded live lease recorded in the database. The default live lease is eight hours and its release-level maximum is 24 hours. Renewal requires a fresh preflight and a newly signed operator artifact; the service cannot renew itself. Health, reconciliation, account, risk, and kill-switch failures revoke the lease immediately. Restarting also requires a new activation artifact. Metrics and alerts begin warning before either activation or live-lease expiration.

The activation command requires the exact acknowledgement `I ACCEPT THAT THIS SYSTEM CAN LOSE THE ENTIRE TRADING BALANCE`. Authorization and preflight artifacts are excluded from Git, backups, logs, and remote reporting.

Micro-live defaults are $5 maximum order notional, $20 maximum gross exposure, and two new orders per UTC day. Normal-live cannot be authorized until the evidence ledger proves the promotion requirements in Section 22.

## 11. Risk Policy

The initial validated defaults are:

- $100 expected starting equity and a $150 live account equity ceiling.
- 60% maximum gross exposure and 40% minimum cash reserve.
- Five maximum open positions.
- 0.50% maximum account-equity risk per trade.
- 15% maximum position notional and 25% maximum correlated-group exposure.
- Minimum reward-to-initial-risk ratio of 2.0.
- No averaging down and no pyramiding.
- Daily, weekly, and peak-to-trough loss limits of 2%, 5%, and 10%.
- Pause after three consecutive losses for 240 minutes.
- Three maximum new orders per day, one per symbol, with at least 30 minutes between entries.
- Equities enabled, long-only, with margin, short sales, options, leveraged ETFs, inverse ETFs, OTC securities, and microcaps disabled.
- Equity maximum spread of 0.35%, minimum price of $5, minimum average daily dollar volume of $50,000,000, and no new entry during the two trading days before or one trading day after earnings.
- Crypto enabled with 20% maximum total crypto exposure, 10% maximum single-crypto exposure, a BTC-USD and ETH-USD allowlist, a 0.60% maximum spread, and no leverage.
- Prediction simulation enabled and prediction live disabled, with future limits of 2% maximum single-contract risk and 10% maximum total prediction exposure.

Risk-sized quantity is `(verified account equity × maximum risk per trade) / validated per-unit stop distance`. Notional-capped quantity is `maximum position notional / validated entry price`. Approved quantity is the lesser of those two quantities, then quantized downward to current broker precision. The final notional and risk are recomputed after quantization and must still pass every limit.

An order is denied if it lacks a reliable protective-exit policy, violates a broker minimum, uses invalid stop distance, fails data or account verification, breaches any exposure or activity limit, or loses its expected edge after configured costs.

Protective exits are classified as `REDUCE_EXPOSURE`. They still pass risk review but may remain available when new entries are paused only if they cannot increase absolute position size or gross exposure. Emergency liquidation is disabled by default.

Any daily loss breach cancels unfilled entries, blocks new entries, preserves approved protective exits, alerts the operator, and requires next-session reconciliation. Weekly breach blocks entries through the configured week boundary and requires review. Drawdown breach activates the kill switch, cancels unfilled entries, generates an incident report, and requires manual reauthorization.

### Runtime state and broker-write policy

“Protective monitoring” is read-only unless the following matrix explicitly permits a broker write:

| Runtime state | New entry | New or replacement reduce-only exit | Cancel known unfilled entry | Cancel existing protective exit |
|---|---:|---:|---:|---:|
| `RUNNING_LIVE` with valid lease | Risk-approved | Risk-approved | Allowed | Only by deterministic replacement or explicit operator action |
| `ENTRY_BLOCKED` with valid lease | Blocked | Allowed only when it cannot increase absolute quantity or gross exposure | Allowed | Never automatically |
| `PAUSED` or expired lease | Blocked | Blocked | Allowed only for a known order when cancellation reduces exposure risk | Never automatically |
| `KILL_SWITCH_ACTIVE` | Blocked | Blocked | Required for known unfilled entry orders when broker health permits | Never automatically |
| `RECONCILIATION_REQUIRED` | Blocked | Blocked | Allowed only for a positively identified local entry order | Never automatically |
| `SHUTTING_DOWN` | Blocked | Blocked | Governed by the last reconciled order state | Never automatically |

Existing broker-held protective orders remain resting and are monitored during paused, kill-switch, reconciliation-required, and shutdown states. Cancel-only actions do not require a live-entry lease, but they require authenticated account identity, positive order ownership, current broker state, an audit event, and confirmation that cancellation cannot increase exposure. No state automatically liquidates a position.

Ordinary entries and exits prefer limit orders. A market order is allowed only when the broker's documented semantics are verified, the instrument passes liquidity checks, slippage has a configured bound, risk explicitly approves it, and the action is enabled for that order purpose. A failed limit order is never converted to a market order without a new intent, broker review, and risk evaluation. Emergency market orders remain disabled by default.

## 12. Order State Machine and Idempotency

The persisted states are:

`PROPOSED`, `RISK_REJECTED`, `RISK_APPROVED`, `REVIEW_REQUESTED`, `REVIEWED`, `SUBMISSION_PENDING`, `SUBMITTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `EXPIRED`, and `UNKNOWN_REQUIRES_RECONCILIATION`.

Transitions are validated by a pure state-machine function and persisted in the same transaction as the initiating event. Each transition records UTC time, actor, immutable reason code, configuration hash, prior state, next state, and correlation ID. Rejected orders cannot transition to submission states.

Every order intent has a stable local deduplication key. Crypto uses the documented `client_order_id`. Equity uses an MCP-supported client reference only if capability discovery confirms one; otherwise the system persists the complete reviewed intent and reconciles broker state before any ambiguous retry. A timeout after submission is never treated as proof that an order failed.

Replacement requires confirmed cancellation or a reconciled terminal state. Partial fills update the actual position and remaining risk before deterministic leave, cancel, or replace policy runs. No retry can increase exposure without a new risk evaluation.

On startup the process remains paused, restores the durable ledger, reads broker accounts, positions, open orders, and recent terminal orders, records every difference, resumes protective monitoring, and refuses new entries until all material drift is resolved.

The default reconciliation tolerance is zero except for explicitly configured broker precision quantization. Unknown external orders, positions, fills, or account changes are always material.

## 13. Broker Adapters

Broker capabilities are split into read, review, place, and cancel-only protocols. Dependency injection can provide the recovery service with read and cancel-only capabilities without exposing placement. Cancel-only accepts only a broker order identifier already linked to a persisted local entry intent and re-verifies account ownership and current open state before sending the cancellation.

### Robinhood equity MCP

The adapter uses the official MCP SDK and Streamable HTTP endpoint. It discovers tools and schemas at startup and compares their hash with the documented capability snapshot. An incompatible schema change disables affected operations.

The adapter supports the verified account, portfolio, position, quote, historical, tradability, order review, order placement, cancellation, order lookup, and fill concepts. Exact provider names and response shapes remain inside the adapter.

The session-declared account schema includes an `agentic_allowed` field, but authenticated behavior remains unverified. Adapter implementation must confirm the authenticated response field and official semantics before relying on it. Write operations require a verified dedicated Agentic account accessible to the connected agent, explicit account number, successful tradability and fractional checks, current unleveraged buying power, no duplicate order, a persisted broker review, and a reviewed order matching the intent. Options tools are documented but excluded from the execution interface.

If official OAuth token storage, refresh, or unattended reauthentication cannot be verified, the deployed equity adapter remains read-only and equity live readiness fails.

### Robinhood Crypto Trading API

The adapter uses official v2 endpoints when the account is eligible. The Ed25519 message is exactly `api_key + timestamp + path + HTTP method + body`, with the body omitted for a bodyless request and no additional separators. The adapter signs the UTF-8 bytes, Base64-encodes the signature, and sends `x-api-key`, `x-signature`, and `x-timestamp`. It checks synchronized time before signed calls and never logs the message or headers when they contain secret material.

The adapter implements supported account, holding, trading-pair, best-price, estimated-price, order, cancellation, and status operations. It reads minimum amount, maximum size, increments, status, and `is_api_tradable` from the trading-pairs endpoint. It does not hard-code product precision.

Retries are limited to proven read-only operations and write operations whose idempotency can be established by `client_order_id` plus reconciliation. Signatures, keys, headers, and secret-bearing payloads are redacted.

### Prediction markets

The adapter implements contract metadata, Yes and No bid/ask prices, time to settlement, settlement criteria, exchange and platform fees, position state, estimated fair probability, uncertainty, calibration, Brier score, maximum loss, maximum payout, and expected value after spread, commission, fees, slippage, and probability uncertainty. A configurable margin of safety is mandatory. `PREDICTION_LIVE_ENABLED` is false by default and live methods always raise `UnsupportedCapabilityError`. A future unlock requires an official programmatic capability, authenticated schema verification recorded in the capability matrix, security and compliance review, passing integration tests, a versioned configuration migration, explicit enablement, and a separate prediction-specific live authorization token. Equity or crypto authorization can never authorize prediction execution.

## 14. Market Data and Quality

The broker-neutral `MarketDataProvider` covers quote, bars, market clock, corporate actions, earnings calendar, instrument metadata, and spread estimates. Provider-specific omissions are explicit capability failures rather than fabricated values.

Validation rejects or quarantines:

- stale timestamps;
- bid above ask;
- nonpositive or nonfinite prices;
- missing required fields;
- unexpected symbol or instrument identity;
- interval mismatches;
- conflicting market clocks;
- unconfirmed changes beyond the configured anomaly threshold;
- interpolated data where the strategy forbids it.

Every rejected input creates a data-quality event. Affected strategies and instruments are blocked. Raw, cleaned, feature, signal, order, fill, and result datasets are separate and content-hashed.

The initial providers are recorded fixtures/replay data, official MCP equity market data where suitable, and official Crypto API data. Point-in-time universe, survivorship, corporate-action, or licensing gaps are disclosed in each research report. Missing research-grade data prevents live eligibility.

## 15. Research and Backtesting

The event-driven simulation engine uses the production feature, strategy, portfolio, risk, order-state, and reconciliation interfaces with a simulated clock and broker. It prevents same-bar fills from using information unavailable at decision time and models rejection, no fill, partial fill, spread, slippage, fees, session rules, and latency.

Equity research includes medium-term time-series momentum, cross-sectional relative strength, trend with market-regime filtering, and disabled-by-default conservative mean reversion. Crypto research includes daily and four-hour trend following, volatility-scaled momentum, breakout models, and cash regimes for negative trends. Parameter grids remain small and economically motivated.

Each candidate records its rationale before optimization and undergoes in-sample development, untouched out-of-sample evaluation, rolling walk-forward analysis, purging or embargo where observations overlap, nearby-parameter stability checks, regime analysis, Monte Carlo trade-sequence resampling, probability-of-backtest-overfitting estimation where the sample permits, stressed costs, and comparison with cash and appropriate passive benchmarks.

Every report includes total return, CAGR, annualized volatility, Sharpe, Sortino, Calmar, maximum and average drawdown, drawdown duration, win rate, average win, average loss, payoff ratio, profit factor, expected value per trade, median trade result, turnover, gross exposure, net exposure, time in market, slippage cost, spread cost, fees, independent opportunity count, longest losing streak, tail losses, and performance by year and regime. It also records every attempted strategy family, including rejected candidates. Strategy selection never relies on Sharpe ratio alone. A strategy is not live-eligible without positive after-cost out-of-sample expectancy, parameter stability, adequate independent opportunities, acceptable stressed drawdown, no single-trade dependency, no unresolved leakage, and a written persistence rationale.

## 16. Persistence and Audit

SQLite runs in WAL mode with foreign keys and explicit transaction boundaries. SQLAlchemy domain repositories hide database-specific behavior so PostgreSQL migration does not alter business logic. Alembic owns all schema changes.

The database includes accounts, instruments, market snapshots, bars, features, signals, strategy decisions, risk evaluations, order intents, broker reviews, orders, transitions, fills, positions, portfolio snapshots, equity curve, realized profit and loss, drawdowns, alerts, reconciliation events, configuration versions, live authorizations, kill-switch events, heartbeats, leases, and audit events.

Critical audit and state-transition tables are insert-only through application repositories and guarded against update/delete by database triggers. Corrections are new compensating events. Every decision preserves strategy version, configuration hash, data hash, inputs, output, risk result, rejection reason, broker action, and final position effect.

Operational logs are structured JSON with UTC timestamps and centralized redaction before serialization. They record machine-readable allow and deny reasons for data quality, strategy decisions, risk, authorization, order review, execution, reconciliation, and promotion without logging secrets, full authorization headers, private keys, or sensitive destination data.

## 17. Scheduling and Single-Leader Operation

The server may run continuously, but strategies run only at configured intervals. Default scheduling reconciles equity accounts every 60 seconds while markets are active and less often outside active sessions, evaluates equities daily or at another research-approved low frequency, reconciles crypto every 60 seconds, evaluates crypto on four-hour or daily bars, runs risk checks around every execution event and heartbeat, produces performance reports daily, creates backups daily, and runs dependency and security reports weekly.

A durable database lease with owner ID, expiration, fencing token, and heartbeat prevents overlapping strategy runs. Only the holder of the current account-specific execution lease can submit. A stale process cannot write after lease takeover because every submission validates the latest fencing token.

## 18. Operations, Monitoring, and CLI

The administrative FastAPI service is read-only and binds to `127.0.0.1`. It exposes `/healthz`, `/readyz`, and Prometheus-compatible `/metrics`. It cannot activate live mode, clear the kill switch, or place orders.

Metrics cover process uptime; last successful market-data update, broker health check, and reconciliation; database health; account equity and cash; gross and crypto exposure; daily and weekly profit and loss; current drawdown; open orders; unknown order states; API error and rate-limit counts; clock drift; memory, CPU, and disk use; restart count; kill-switch state; and activation and live-lease expiration.

The optional generic webhook emits redacted alerts for process start and stop, live activation and deactivation, order submission and rejection, partial and complete fills, failed cancellation, broker disagreement, stale data, account restriction, drawdown threshold, kill-switch activation, authentication failure, database error, repeated API failure, and unexpected restart.

The `trader` CLI implements status, preflight, pause, resume, reconcile, positions, open orders, proposed orders, decision explanation, journal export, kill-switch activation and clearing, live enabling and disabling, and incident reports. Mutating commands require explicit acknowledgements, recorded reasons, and successful prerequisite checks. `resume` cannot enter a live mode without a valid stage-specific authorization and a fresh preflight.

The filesystem kill switch defaults to `/var/lib/trading-bot/KILL_SWITCH` and is checked at startup, before every order, every scheduler cycle, after broker errors, and after reconciliation. Clearing it requires the breach to be inactive, successful reconciliation, explicit acknowledgement, and an audit reason.

## 19. Security and Deployment

Secrets never enter Git, logs, traces, metrics, fixtures, reports, LLM requests, deployment output, or backups without encryption. Deployment uses environment references, Docker secrets, or files owned by the service user with mode `0600`. Redaction is applied before structured serialization.

The container runs as a non-root user, uses a read-only root filesystem, drops Linux capabilities, sets CPU and memory limits, has a graceful shutdown deadline, and writes only to declared data, log, configuration, and temporary volumes.

DigitalOcean infrastructure uses Terraform and cloud-init with required variables for region, a verified current Ubuntu LTS image, SSH keys, trusted SSH CIDRs, backup destination, and alert targets. There are no permissive defaults for trusted networks. Provisioning creates or attaches a Cloud Firewall, disables password SSH and direct root login, configures UTC and time synchronization, creates modest swap, installs DigitalOcean monitoring, enables controlled security updates without uncontrolled application restarts during active trading, configures log rotation, creates restricted application/data/backup/configuration directories, installs Docker Engine and Compose, sets resource and disk alerts, and uses `restart: unless-stopped`. The database and admin API are not publicly exposed. Administrative access requires SSH tunneling, VPN, or an equivalent private channel. Practical egress controls permit only required DNS, NTP, official broker, alert, package, and encrypted-backup destinations. First deployment starts paused and cannot generate a live authorization.

Daily database and nonsecret configuration backups are encrypted to an operator-controlled public key, checksummed, retained by policy, and periodically restore-tested. Broker secrets are excluded. Rollback restores a pinned image, migration-compatible database backup, and configuration version while leaving trading paused.

The threat model covers broker credential theft, dependency and supply-chain compromise, Droplet compromise, unauthorized activation, prompt injection, malicious provider fields, log injection, replay, duplicate submission, database corruption, stale authorization, account substitution, denial of service, and time synchronization attacks.

On `SIGTERM`, deployment restart, or operator shutdown, the service enters `SHUTTING_DOWN`, blocks new intents, stops lease renewal, completes or rolls back database transactions, persists state, reconciles in-flight requests, discards unsubmitted proposals, handles submitted orders according to their actual broker state and the runtime action matrix, records the shutdown reason, and exits only after durable confirmation or the configured deadline. Restart never triggers blanket liquidation.

## 20. Optional LLM Reporting

The reporting interface receives only redacted, read-only report data. It cannot import broker adapters, access secret providers, or obtain an execution-service reference. It is disabled by default, bounded by daily and monthly token budgets, and nonessential. Any failure returns control to deterministic local reporting without affecting trading.

Tax-record export produces deterministic CSV and JSON files containing broker account reference, instrument, side, quantity, fill time, fill price, fees, broker order and fill identifiers, and available cost-basis or lot references. Missing broker basis data is marked unknown rather than inferred. The export is an operational record, not a replacement for official broker tax documents or tax advice.

## 21. Testing and Quality Gates

Tests use fakes, sanitized fixtures, local HTTP/MCP test servers, and deterministic clocks. CI has no live credentials and no route to a real broker write operation.

- Unit tests cover arithmetic, sizing, stop distance, loss and drawdown calculations, exposure, spread, staleness, deduplication, configuration, state transitions, prediction refusal, and kill-switch enforcement.
- Hypothesis tests prove that approved quantity never exceeds configured quantity or notional limits; approved loss at the stop never exceeds the risk budget; cash reserve cannot become negative; total or asset-class exposure cannot exceed its cap; a rejected order cannot transition directly to submission; a disabled market cannot call a live broker; duplicate external order or fill IDs cannot create duplicate economic effects; and negative or nonfinite prices are always rejected.
- Integration tests cover full lifecycle, partial fills, rejection, cancellation, timeouts, rate limits, auth expiry, restarts, account mismatch, changed buying power or quote, and provider unavailability.
- Replay tests prove identical decisions for identical data, clock, code, and configuration.
- Chaos tests cover termination around submission, lost responses, broker/local ambiguity, duplicate events, database locks, disk full, stale clock, schema changes, unexpected positions/orders, and reboot during partial fill.

Risk and order-state modules require at least 90% branch coverage; overall coverage requires at least 80%. Formatting, Ruff, static typing, Bandit, dependency audit, tests, coverage, and SBOM generation run in CI. A failed check blocks promotion.

## 22. Promotion Gates

1. **Local simulation:** complete automated suite, deterministic replay, no unresolved critical security finding, and successful failure injection.
2. **Paper:** at least 100 recorded decision cycles, expected risk rejections, no duplicate orders, no unreconciled state, and complete journal.
3. **Shadow:** at least seven calendar days of authenticated read-only operation, validated live data, accurate simulated state, and zero unexplained account differences.
4. **Micro-live:** separate manual authorization, $5 order and $20 gross limits, two new orders per day, immediate alerts, review every ten orders, and automatic pause on any unknown state.
5. **Normal-live:** never automatic; requires at least 30 combined calendar days across paper, shadow, and micro-live, at least 100 valid observations, no unresolved reconciliation or critical security issue, acceptable configured slippage, drawdown within the researched range, and renewed manual acknowledgement.

Evidence is stored in a promotion ledger and verified by a pure eligibility evaluator. The 30-calendar-day minimum, 100-observation minimum, reconciliation clearance, critical-security clearance, current manual acknowledgement, and unknown-order-state pause are non-overridable. Configurable limits may only become stricter than the release safety envelope, and every accepted change is audited. The implementation can collect evidence but cannot claim elapsed gates before they have actually occurred.

## 23. Repository Deliverables

The completed repository includes `Codex.md`, `README.md`, `Makefile`, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `Dockerfile`, `docker-compose.yml`, the source layout, base and mode configs, CI, DigitalOcean Terraform and cloud-init, migrations, tests, fixtures, reports, and an SBOM.

The Makefile provides `setup`, `format`, `lint`, `typecheck`, `test`, `test-unit`, `test-integration`, `test-chaos`, `security`, `backtest`, `simulate`, `paper`, `shadow`, `live-preflight`, `build`, `deploy`, `status`, `logs`, `backup`, and `restore-test`. `make test` cannot access a live trading endpoint.

Documentation includes `README.md`, `docs/implementation-plan.md`, `docs/architecture.md`, `docs/capability-matrix.md`, `docs/threat-model.md`, `docs/risk-policy.md`, `docs/strategy-research.md`, `docs/live-activation.md`, `docs/incident-response.md`, `docs/disaster-recovery.md`, `docs/operations-runbook.md`, and `docs/limitations.md`. The README clearly distinguishes implemented, verified, locked, unsupported, and externally pending capabilities and covers local setup, MCP and Crypto API setup, secrets, all modes, live preflight, micro-live activation, kill switch, deployment, monitoring, backup, incident handling, tax-record export, limitations, and the no-profit-guarantee disclosure.

The final implementation report will state that no live prediction-market execution was implemented unless official support changes, and that no live order was placed during development without separate explicit authorization.

## 24. Requirements Traceability

| Original requirement area | Normative design sections | Primary artifact |
|---|---|---|
| Platform verification and supported interfaces | 2, 3, 13 | `docs/capability-matrix.md` |
| Deterministic system philosophy and LLM isolation | 5, 6, 20 | Architecture and dependency tests |
| Operating modes and live gates | 9, 10, 22 | Mode configs, preflight, promotion ledger |
| Small-account risk policy and prohibited behavior | 6, 10, 11 | `docs/risk-policy.md`, risk tests |
| Equity, crypto, and prediction research | 14, 15 | `docs/strategy-research.md`, reports |
| Backtesting and validation | 14, 15, 21 | Backtest engine and reproducibility reports |
| Market-data quality | 6, 14 | Provider contracts and quality-event tests |
| Broker adapters | 3, 13 | Official adapters and fake integration suites |
| Execution, partial fills, restart, and deduplication | 6, 11, 12 | State machine, ledger, chaos tests |
| Database and auditability | 16 | Alembic migrations and append-only audit tests |
| Repository structure and dependencies | 5, 23 | Package tree, lockfile, SBOM |
| Security and threat model | 10, 18, 19 | `docs/threat-model.md`, security scans |
| DigitalOcean deployment, backup, and shutdown | 19 | Terraform, cloud-init, Compose, restore tests |
| Monitoring and alerting | 18 | Read-only API, metrics, alert tests |
| Operator CLI and kill switch | 10, 11, 18 | CLI integration tests and runbook |
| Scheduling and single-leader execution | 17 | Lease and fencing-token tests |
| Unit, property, integration, replay, chaos, and coverage | 21 | CI workflow and coverage reports |
| Staged live-trading evidence | 22 | Promotion ledger and eligibility evaluator |
| Implementation workflow | 4, 23 | `docs/implementation-plan.md` |
| Makefile and operating commands | 23 | Makefile smoke tests |
| Documentation and handoff | 23 | README, runbooks, limitations, final report |

## 25. Definition of Done

Implementation is complete only when Sections 1 through 23 are implemented and verified, quality checks pass or failures are explicitly documented, live paths remain locked by default, unsupported capabilities fail closed, and operational commands are exact and tested.

Elapsed-time evidence, account eligibility, authenticated broker access, cloud provisioning, and separate authorization are external operational milestones. They remain visibly pending rather than being simulated or claimed as complete.
