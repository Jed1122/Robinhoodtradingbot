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

**Standalone DigitalOcean options runtime: UNVERIFIED.** This work did not inspect or
transfer local OAuth state, register a runtime client, validate unattended renewal,
probe the host, or alter the existing equity-only SDK/transport allowlists. Desktop
authentication cannot be copied into a runtime-verification verdict.

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
