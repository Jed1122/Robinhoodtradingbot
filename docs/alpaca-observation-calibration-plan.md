# Alpaca execution observations and cost calibration

Base: `b64f996c658c378f4ae34bbecee8fc69dfa5642d`, integration target
`codex/robinhood-system-implementation`. Existing execution coverage and costs
are blocked; native historical parsing and offline economic mechanics are partial.

Dependency chain: documented stream syntax -> lossless forward observations ->
private bounded capture receipts -> offline receipt revalidation -> descriptive
cost measurements from explicitly supplied execution records -> source/customer
qualification -> genuine after-cost testing. Historical controls, broker execution
records and elapsed paper/shadow operation cannot be created by software tests.

The primary owner implements private transport/storage, cost measurements, CLI,
integration and release review. A separate parser worktree owns only
`market_data/alpaca_observations.py` and its synthetic unit tests; its frozen
interface is `parse_alpaca_observation_frame(body, frame_index, received_at_ns)`.
The full delegation contract is recorded in the task conversation. Other agents
perform read-only reviews. No credentials or private market/customer data enter
Cloud or Git. No strategy, risk, production ledger, runtime mode or broker write
is in scope. Alpaca remains the sole ETF market-data source; Robinhood remains
the execution broker.

Capture is a standalone opt-in local command, fixed to SPY/SIP quote/status/LULD
subscriptions, with explicit private key/output paths, bounded duration/bytes,
no automatic reconnect and no broker endpoint. A restart creates a new segment
and records a discontinuity; initial state and transport continuity remain
unverified. Retained bytes, UTC receipts and local monotonic timings are evidence
of observations only. Market-data delivery delay is not broker order latency.

Calibration is a separate offline private-input command. It measures explicitly
declared fill prices, whole-order charged fee components and local order timings.
Partial fills are grouped before fees; spread is already in price. Paper and
synthetic records cannot become customer measurements. Source hashes do not prove
authenticity. Missing roles stay missing; the v1 cost engine and pinned hashes
remain unchanged. No result enables execution or research promotion.

Verification: parser/collector/calibration adversarial tests, CLI private-I/O
checks, Ruff, Mypy, full local regression/branch coverage, locked-dependency and
security checks; inspect exact-head hosted checks without blocking ongoing work.
The reconnected Mac completed two real forward segments and their private raw-byte
audits. Customer calibration remains blocked: the bounded local record search
found no usable execution/billing evidence. After separately authorized browser
sign-in, both current-year and unfiltered bounded history reads returned zero
orders and no next page for the existing intended account. The private offline
cost assessment completed with `BLOCKED_INPUTS`; customer calibration is not
claimed complete without actual execution and operating-cost records.
