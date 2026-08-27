# Limitations

- Historical and public data may contain gaps, licensing limits, survivorship bias, delayed
  corporate actions, or incomplete point-in-time membership. Missing evidence makes research
  ineligible rather than triggering substitution.
- The configured `SPY`/`QQQ`/`IWM`/`DIA` tuple is a present-day research candidate list, not a
  point-in-time universe and not an execution allowlist. Robinhood historical requests ask for
  split adjustment, but complete dividend/distribution adjustment and corporate-action provenance
  are not verified.
- The authenticated equity historical shape does not include an explicit interpolation flag.
  Omission is conservatively recorded as tainted rather than defaulted to clean. Tainted bars may
  appear only in an explicitly rejected exploratory report and cannot satisfy market-data or
  promotion validation.
- Simulated spread, slippage, fees, latency, fills, and rejects cannot reproduce every market
  condition. Small accounts are especially sensitive to minimum order sizes and costs.
- The connected ETF comparison currently assumes complete next-open target fills. It does not yet
  integrate configured rejection, no-fill, partial-fill, latency, cancel-race, stop/target,
  maximum-holding, or regime-exit policies, so this is an explicit promotion blocker.
- The private report retains cleaned bars, its complete manifest, and hashes of raw provider
  responses, but not the raw response bodies. The executing process also cannot independently prove
  that the caller-supplied image digest identifies its own container. Both limitations are recorded
  as promotion blockers.
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
  An independent `connected-research` profile can make four bounded single-symbol historical reads,
  write a private comparison report, append its rejected assessment, and exit. Neither profile
  schedules itself or constructs place, review, or cancel adapters.
- Robinhood exposes the sole official OAuth scope `internal`; it is not a read-only broker scope.
  The connected client limits itself to reads with two local allowlists, but the bearer credential
  must be treated as trading-capable. A stolen token or compromised host could trade in the Agentic
  account outside this client.
- SQLite triggers and content hashes make promotion records append-only and tamper-evident within
  the application/database boundary; they are not signed proof against a database owner or host
  compromise.
- The generic paper-cycle result store is in-memory. A cross-process-locked wrapper can now avoid
  re-execution after finding an exact durable paper promotion observation and can append a derived
  observation after a completed simulated cycle. The public paper CLI does not yet compose that
  wrapper with an accepted strategy, validated current data, or a recurring worker. Verified
  build-to-image identity, a complete broker-connected strategy cycle, and a recurring evidence
  scheduler are still not implemented.
- Single-host filesystem exclusion does not support multi-host active/active deployment. The
  Terraform and cloud-init templates are not a validated end-to-end provisioning path; manual hosts
  still require operator-supplied immutable images and independent hardening.
