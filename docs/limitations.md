# Limitations

- Historical and public data may contain gaps, licensing limits, survivorship bias, delayed
  corporate actions, or incomplete point-in-time membership. Missing evidence makes research
  ineligible rather than triggering substitution.
- Simulated spread, slippage, fees, latency, fills, and rejects cannot reproduce every market
  condition. Small accounts are especially sensitive to minimum order sizes and costs.
- Strategies are long-only, deterministic candidates and make no profitability claim.
- Tax treatment varies by jurisdiction and requires professional review.
- Prediction contracts are research-only; live prediction placement is unsupported.
- Paper evidence is non-promotable unless exact strategy, configuration, code, and research
  acceptance evidence matches. Live execution remains separately locked.
- Crypto adapters have only fixture and mock-HTTP verification in this repository. Seven equity
  reads have authenticated, value-free shape evidence, but nonempty order and position row shapes
  have not been observed and are rejected.
- Shadow smoke evidence is explicitly non-promotable. The authenticated connected preflight is
  also deliberately non-promotable: it records `strategy_eligible=false` and
  `outcomes_complete=false`; without a probe symbol it additionally records unvalidated live data.
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
- Single-host filesystem exclusion does not support multi-host active/active deployment. The
  Terraform and cloud-init templates are not a validated end-to-end provisioning path; manual hosts
  still require operator-supplied immutable images and independent hardening.
