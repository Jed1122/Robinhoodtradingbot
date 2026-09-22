# Limitations

- The new offline research bundle and snapshot loader accept only `synthetic-market-v1`
  captures normalized by `synthetic-normalizer-v1`. Stored raw bytes and replay/hash checks
  establish internal consistency, not authenticity, license rights, complete source history,
  or accepted research. Imported data is unsupported. No bundle can create promotion evidence.
- Bundle snapshots require explicit visible complete coverage and visible included membership;
  they reject unavailable bars, interpolation, adjusted/unknown prices, and effective retained
  actions. Date-only corporate actions cause conservative denial, not inferred intraday timing.
  The loader does not supply spreads, real-source ingestion, production runtime wiring, or
  broker-connected outcome coverage. Its decision-cycle integration is an incapable test only.
- Bundle storage is local, private, content-addressed artifact I/O outside the repository,
  separate from production persistence. It requires macOS/Linux no-follow and atomic hard-link
  capabilities and reports failed publication durability rather than assuming success. It does
  not authenticate a compromised same-UID process or host root, provide remote attestation,
  automatically collect orphaned blobs, or validate the deployed host. Existing deployment and
  live-operation blockers are unchanged.

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
  responses, but not the raw response bodies. A deployed connected process verifies the helper's
  root-owned image/configuration/Compose release attestation, but that local host-root assertion is
  not a remotely signed transparency record and cannot validate research data or outcomes.
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
  `data_validated=false` and `outcomes_complete=false`; the deployed profile requires the verified
  release attestation and records `runtime_scope_valid=true`. Without pinned research evidence it
  still records `strategy_eligible=false`. A probe symbol can exercise one
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
- The generic paper-cycle result store is in-memory. The public one-shot `paper` CLI now reaches
  the durable promotion composition boundary, but it fails closed before creating a ledger, lock,
  or observation because no trusted composition supplies an exact accepted research record,
  matching account/provider/strategy/config/code identities, validated market data, clean
  reconciliation, runtime-scope attestation, and a complete simulated strategy cycle. The runtime
  uses the existing SQLite observation/evidence stores and cross-process mutex only after such a
  reviewed composition exists. A complete broker-connected strategy cycle and a recurring evidence
  scheduler are still not implemented.
- Single-host filesystem exclusion does not support multi-host active/active deployment. The
  Terraform and cloud-init templates are not a validated end-to-end provisioning path; manual hosts
  still require operator-supplied immutable images and independent hardening.
