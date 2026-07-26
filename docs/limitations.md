# Limitations

- Historical and public data may contain gaps, licensing limits, survivorship bias, delayed
  corporate actions, or incomplete point-in-time membership. Missing evidence makes research
  ineligible rather than triggering substitution.
- Simulated spread, slippage, fees, latency, fills, and rejects cannot reproduce every market
  condition. Small accounts are especially sensitive to minimum order sizes and costs.
- Strategies are long-only, deterministic candidates and make no profitability claim.
- Tax treatment varies by jurisdiction and requires professional review.
- Prediction contracts are research-only; live prediction placement is unsupported.
- Paper cycles are local diagnostics only. Even when exact strategy, configuration, code, complete
  terminal outcomes, and persisted research acceptance match, they do not create a durable
  `PromotionObservation` and remain non-promotable.
- Crypto adapters have only fixture and mock-HTTP verification in this repository. Seven equity
  reads have authenticated, value-free shape evidence, but nonempty order and position row shapes
  have not been observed and are rejected.
- Shadow smoke evidence is explicitly non-promotable. The authenticated connected preflight is
  also deliberately non-promotable. Its exact-build research-binding path is disabled by both the
  shipped base configuration and immutable safety envelope. The diagnostic records
  `data_validated=false`, `outcomes_complete=false`, and `runtime_scope_valid=false`; without
  pinned evidence it also records `strategy_eligible=false`. A probe symbol can exercise one
  historical-data read but cannot upgrade that diagnostic into validated strategy data.
  It therefore does not start the configured seven-distinct-UTC-date promotion clock.
- The default deployable container is a paused monitoring process. An explicit `connected-shadow`
  profile can authenticate for one locally write-incapable probe, persist evidence, and exit.
  Neither service runs complete strategy cycles or constructs place, review, or cancel adapters.
- Robinhood exposes the sole official OAuth scope `internal`; it is not a read-only broker scope.
  The connected client limits itself to reads with two local allowlists, but the bearer credential
  must be treated as trading-capable. A stolen token or compromised host could trade in the Agentic
  account outside this client.
- SQLite triggers and content hashes make promotion records append-only and tamper-evident within
  the application/database boundary; they are not signed proof against a database owner or host
  compromise.
- The paper-cycle store is in-memory and has only single-process overlap protection. Durable
  cross-process claiming, durable paper promotion observations, verified build-to-image identity,
  a complete broker-connected strategy cycle, and a recurring evidence scheduler are not
  implemented.
- Single-host filesystem exclusion does not support multi-host active/active deployment. The
  Terraform and cloud-init templates are not a validated end-to-end provisioning path; manual hosts
  still require operator-supplied immutable images and independent hardening.
