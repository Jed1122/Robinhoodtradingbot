# Live activation

Live trading is disabled by default. Run `make live-preflight`, obtain stage-specific promotion
evidence, then create the signed operator artifact with the exact loss acknowledgement. Startup
remains paused; authorization never automatically resumes execution. Prediction and equity live
remain unavailable pending exact evidence and a separately implemented provider write composition.


Before requesting a signed activation artifact, run `make live-readiness`. The command is a
local fail-closed audit only: it checks that live mode was explicitly enabled by the operator,
that Crypto credential and runtime verification files are present with restrictive modes, and
that the runtime process was not given an operator signing-key path. It does not place orders,
does not print secret values, and exits non-zero until every prerequisite is satisfied.


A Robinhood Agentic browser connection (for example, the Robinhood web page showing ChatGPT
as connected) is not by itself a runtime credential for this service. If an operator wants the
bot to use a reviewed Robinhood Trading MCP OAuth store, expose it through
`ROBINHOOD_MCP_OAUTH_STORE_DIR` as a service-owned directory with mode `0700` or stricter;
the live path still requires the signed activation and promotion gates above before trading.
`ROBINHOOD_MCP_OAUTH_STORE_DIR` is the readiness-check file reference; the Compose bind override
for the one-shot connected profile is `TRADING_BOT_OAUTH_DIR`. OAuth and authenticated reads are
not live authorization. The OAuth client requests and pins the sole official `internal` scope, but
that scope is not a broker-enforced read-only grant. Its bearer credential must be treated as
trading-capable: a stolen token or compromised host could trade in the Agentic account. The current
connected client is write-incapable only because an SDK-session allowlist and a second transport
allowlist admit seven reads and no review, place, or cancel adapter exists.

The release envelope sets these non-reducible promotion minimums; deployment configuration may
make them stricter but cannot lower them:

- Paper requires 100 unique eligible paper cycles.
- Shadow requires eligible observations on seven distinct UTC calendar dates.
- Micro live requires both paper and shadow thresholds plus current security-clearance and manual
  acknowledgement evidence and a current attestation to the configured micro limits, alerts, and
  unknown-state pause controls.
- Normal live retains the 100-paper-cycle and seven-shadow-date prerequisites and additionally
  requires at least 100 eligible combined paper, shadow, and micro observations across 30 distinct
  UTC dates, at least one micro-live observation, a current micro-order review summary matching the
  configured interval and covering every completed ten-order boundary, and current
  security-clearance, manual-acknowledgement, runtime-control, slippage, and drawdown evidence.

Normal-live observations cannot bootstrap or add to normal-live eligibility. Their latest dirty
state still blocks re-promotion, and a later normal-live observation cannot mask dirty qualifying
paper, shadow, or micro evidence. Every observation is bound to
the exact account fingerprint, provider-evidence hash, strategy version and eligibility hash,
configuration hash, and code hash; identity drift creates a separate evidence population. Future
observations do not count, conflicting evidence for one stage/cycle is quarantined, and a latest
ineligible observation blocks stale progress. Re-persisting the same aggregate evidence does not
renew its expiry.

Observation eligibility is derived rather than caller-selected. It requires verified identity and
provider evidence, an eligible strategy, authenticated reads for connected stages, validated data,
complete outcomes, clean reconciliation, non-fixture data, a valid runtime scope, and known order
state. The shipped connected preflight is diagnostic only: release configuration disables research
promotion, and every run records invalid strategy data, incomplete outcomes, and an unverified
runtime scope. It is durable connection evidence but not qualifying promotion evidence. External
promotion attestations carry explicit observed and expiry times; missing, future-dated, expired,
mismatched, or incomplete evidence blocks promotion.
