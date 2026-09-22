# Options evidence checkpoint — 2026-09-22 UTC

This checkpoint separates observed connection facts from unfinished engineering and
economic evidence. No order review, placement, cancellation, exercise, account upgrade,
credential change, data acquisition, credit spending, production migration or deployment
was performed. No live authorization or risk limit changed. Account identifiers, balances,
provider response bodies and licensed market-data rows are deliberately absent from Git.

## Broker evidence

The operator authorized read-only Agentic account verification. The installed Robinhood
app connector twice returned a reauthentication error. The separately configured
`robinhood-2` MCP server then successfully returned `get_accounts`, `get_portfolio`,
`get_option_positions` (including zero-quantity rows), `get_option_orders`,
`get_equity_positions` and `get_equity_orders`. The account selected was the unique
account eligible for this agent, not a nickname or arbitrary default. Position/order
responses were empty collections without continuation pages. These observations prove
that those reads worked in this Codex session; they do not validate nonempty row mappings,
fills, fees, settlement completion or every account restriction. Private account results
were reported only to the operator, not embedded here or sent to coding agents.

Current declarations differ by connection. The app connector describes single-leg
options; `robinhood-2` declares native one-to-four-leg limit orders for eligible Level 3
accounts, explicitly excluding cash and retirement accounts from multi-leg orders.
Those declarations are not behavioral verification, account upgrades or permission to
expand the initial long-call/put scope. The current project's multi-leg live lock remains.
No order-changing or order-review operation was invoked.

Preserve a source conflict: `robinhood-2`'s `trading://feature-availability` resource still
states options are app-only, while its tool declarations and Robinhood's current public
[tool list](https://robinhood.com/us/en/support/articles/trading-with-your-agent/) describe
options operations. The read successes establish only the specific reads above. Do not
discard this negative resource or promote untested writes on the strength of prose.

The public guide distinguishes cash settlement from limited-margin reuse of proceeds.
It does not establish all selected-account intraday restrictions. The runtime must use
fresh account-specific evidence, not universal PDT or same-day-settlement assumptions.

**Standalone DigitalOcean options runtime: UNVERIFIED.** The separately authorized
read-only host inspection below verified the existing paused service, not options
authentication or execution. No OAuth state was read or transferred, runtime client
registered, unattended renewal validated, or SDK/transport allowlist changed. Desktop
authentication cannot be copied into a runtime-verification verdict.

## Read-only DigitalOcean checkpoint

The operator separately approved inspection of the existing deployment. DigitalOcean
reported the existing Ubuntu 24.04, NYC3, one-vCPU/2-GB/50-GB Droplet active. An initial
SSH attempt using the deployment-service username was denied. The existing administrator
SSH alias then authenticated successfully using its existing key with strict known-host
verification. No key/access setting or deployment changed; OAuth credentials and
production-ledger contents were not read.

At approximately 18:47–18:51 UTC, the running container reported:

- `/healthz`: HTTP 200, process check healthy with reason `paused`.
- `/readyz`: HTTP 503, `ready=false`, denials `paused` and `external_capability_missing`.
- `/metrics`: `trading_bot_live_enabled 0.0`.
- Command: shadow-mode `serve --paused`; non-root UID/GID 10001; read-only root filesystem;
  all Linux capabilities dropped; no-new-privileges; loopback-only port 8080; no mounts.
- Limits: 768 MiB memory, 0.75 CPU and 256 processes. No resource benchmark was performed.

Executing image ID:
`sha256:1a259e1a559c2ecb2ae0277e8f7fa2733e7e9f0c2b90ff418f5baa1c527e9d25`.
The configured image, last-good release pointer and root-owned mode-0444 attestation
agreed with that ID. The paused container's read-only configuration-hash command returned
`f617b11838362eccf5ea0e4e18e274974f347cb12f5e01006a1c1b7a3255f224`, matching the
attestation. Deployed Compose SHA-256
`6ad9422f7d5e10280fcccef97a6703edb6deeb422e7fcd64f9e6d3d2c5a55c54`
matched the release record and local reviewed manifest. The installed deployment-helper
hash also matched the local helper. Docker Compose 2.40.3 was present on the host;
neither a new Compose render nor a deployment was performed.

Hashes of the installed MCP SDK, transport and equity-evidence source files matched
their local reviewed counterparts. Their installed SDK allowlist contains the seven
existing account/equity reads, not options reads or order-changing operations. No
connected profile, OAuth flow, broker call or strategy loop was launched on the host.
An empty mount list applies to this running paused container only; it does not prove
the host contains no credentials or other private state.

**Paused deployment checks: PASS within the scope above. Options production lifecycle,
runtime authentication/renewal and operational recovery: still NOT VERIFIED.** A healthy
process endpoint is not broker reconciliation, a strategy heartbeat or economic evidence.
The newly tested local options changes were not deployed.

## Historical data estimates, not acquisition

The operator authorized Databento portal availability and cost inspection only. The
download center showed the existing SPY option definitions request and unrelated example
files, not acquired SPY option bid/ask history. Current remaining credits were inspected
privately. Usage-based access displayed no spending limit; nothing was changed.

| Estimate scope | Displayed estimate | Important limitation |
| --- | --- | --- |
| OPRA.PILLAR, SPY.OPT, CBBO-1m, 2023-01-01 00:00 through 2025-12-31 24:00 UTC | $396.34; 212.78 GB | Above available credits; sampling is not fill or queue evidence. |
| EQUS.MINI, SPY, BBO-1m, 2023-03-28 00:00 through 2025-12-31 24:00 UTC | $0.14; 38.17 MB | Partial underlying interval; does not cover January–March 2023 or establish national consolidated BBO. |

Portal sources: [SPY options](https://databento.com/portal/catalog/opra/OPRA.PILLAR/options/SPY),
[SPY underlying mini feed](https://databento.com/portal/catalog/us-equities/EQUS.MINI/etf/SPY).
The [SPY summary feed](https://databento.com/portal/catalog/us-equities/EQUS.SUMMARY/etf/SPY)
displayed history beginning 2024-07-01 and daily OHLCV/definition/statistics schemas, not a
matching multi-year intraday quote substitute. Nasdaq TotalView displayed history from
2018-05-01, but it is a separate single-venue source and was not priced or acquired here.

These are rounded, time-sensitive estimates, not a hard charge cap or a complete research
package. No request was submitted. A smaller causal contract-selection scope must be
frozen before reviewing outcomes; it cannot cherry-pick winners or lower the existing
history, effective-sample, untouched-holdout or uncertainty requirements to fit credits.
Underlying warm-up/history, sessions, dividends/corporate actions, adjusted-deliverable
detection, actual fees and source completeness still require validation.

**ECONOMIC_NO_GO — insufficient evidence.** Genuine price-based testing cannot run from
the definition archive. The two estimates do not themselves form a complete matched
dataset and are not an authorization to acquire either feed.

## Engineering checkpoint

The local audit confirms working normalized options reconciliation, expiry assessment,
paused observation scheduling, and synthetic trial/loss journals. These remain partial
against production requirements: there is no independent durable local lifecycle ledger
feeding retained authentic broker observations into a verified standalone composition.
Clean reconciliation must not be manufactured by copying broker state into local state.
Source hashes without retained source artifacts do not prove reproducible recovery.

Task 24 hardens the existing synthetic trial journal against lease-clock rollback,
expiry during duplicate reads and returning obsolete heads after intervening events.
It preserves event hashes, trial reservations, percentage limits and production locks.
It does not complete durable broker lifecycle integration. Follow-on dependency chain:

1. Versioned retained observations plus independently owned local lifecycle/ownership facts.
2. Fenced append-only persistence and incident restoration with reproducible restart.
3. Strict real-source parsing, explicit completeness and reconciliation/expiry integration.
4. Separately verified runtime authentication, operation contracts and failure drills.
5. Suitable acquired history and preregistered economic evaluation; independent live approval.

Two local read-only audits assisted this checkpoint. No Cloud execution was performed.

## Local verification

Task 24 code checkpoint: `bc9cf25`. Eleven added regression cases followed observed
RED failures before the fix. Final focused trial/recorded-session/risk-journal selection:
56 passed. Full non-authenticated suite: **5,563 passed**, no skips, one existing
Starlette/httpx deprecation warning, **89.83% overall coverage**, 351.25 seconds.
The **90% per-file critical branch gate passed**. Ruff, Mypy (238 source files), Bandit,
root offline lock consistency, locked-dependency audit, temporary CycloneDX 1.5 schema
validation (104 components), DigitalOcean shell syntax and diff checks passed. The audit
found no known dependency vulnerabilities; it is not proof of absence of all risks.
Local Docker Compose remains unavailable. No remote CI or production failure drill ran.

A fresh independent read-only review of `2421153..bc9cf25` found no Critical or Important
issues. Deferred minor: add a sequenced-clock test isolating the final exact-duplicate
return check; existing tests already cover expiry/regression during history reads.
This is a test-coverage suggestion, not an observed defect or a live-readiness approval.
Pre-existing staged lockfile, dirty SBOM and unrelated work remain unchanged.
