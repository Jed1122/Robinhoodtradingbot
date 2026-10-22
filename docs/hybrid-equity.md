# Hybrid equity application

This opt-in application extends the existing safety kernel. It has no mandatory
paper-trading period, no 60-day waiting requirement, no live authorization, and no
composed Robinhood order writer. It must not be represented as a live-ready system.

## Run locally

Python 3.12+ and Node 22.12+ are required. From this checkout:

```sh
uv sync --frozen
npm ci --prefix dashboard
npm test --prefix dashboard
npm run build --prefix dashboard
uv run python -m trading_bot.hybrid.cli --state-dir "$HOME/.local/share/hybrid-equity" init
uv run python -m trading_bot.hybrid.cli --state-dir "$HOME/.local/share/hybrid-equity" serve
```

Open http://127.0.0.1:8000. The newly generated dashboard token is in the private
`dashboard.token` file under the state directory. On macOS copy it directly to the
clipboard without printing it: `pbcopy < "$HOME/.local/share/hybrid-equity/dashboard.token"`.
Paste it into the login form. The frontend keeps it only in memory, never browser
storage or URLs. Reloading requires logging in again. This token is for the local
dashboard, **not** Robinhood. No brokerage credentials are requested by these commands.

The service starts with research paused. Resume research in Settings. The kill
switch cannot be cleared from the dashboard. A kill is durable; inspect the reason
offline rather than editing the journal or disabling the control. `/readyz` always
denies live readiness in this release; `/healthz` reports process/journal health.

## Configuration and architecture

`configs/hybrid/policy.yaml` extends the existing canonical Pydantic graph through
`load_config(..., hybrid_policy_path=...)`. It does not change default AppConfig
bytes or legacy live envelopes. The isolated paper envelope permits the 75/15/10
policy but explicitly forbids live mode. Hybrid configuration environment overrides
are rejected; documented CLI arguments select files and binding, not risk authority.
Changes to policy invalidate the journal's bound configuration identity. Do not
adopt an old account under a new policy by replacing its hash.

All monetary values use Decimal. Research, experimental accounting, risk checks,
execution facts, broker capabilities, and UI remain separate. New experimental
account snapshots use the canonical SQLAlchemy engine and Alembic migration 0011,
with one `BEGIN IMMEDIATE` transaction for each coherent state transition. The
append-only, configuration-bound hash chain persists reservations, lots, fills,
threshold progress, settlement, loss references, controls, job outcomes and reports.
It is isolated from production ownership and cannot adopt an actual brokerage ledger.
The 1 MiB per-state/100,000-event bounds deny further writes rather than discarding
history. Journal checkpoint/retention work is required before those bounds approach.

Root profile defaults: $1,000 simulated cash; long-term 75%, tactical 15%, reserve
10%; tactical position 4%; company 10%; company sector 25%; risk per tactical
entry 0.5%. Daily loss freezes tactical entries at 1%, weekly decline requests
review at 3%, high-watermark drawdown suspends tactical entries at 10%. Complete
fresh marks advance the durable references on New York calendar boundaries.
Missing marks block exposure calculations. A risk stop is a sizing assumption,
not guaranteed execution or a maximum realized loss.

## Source-backed research

Start with a permitted local export, not fabricated market history. `import-research`
accepts bounded JSON conforming to `hybrid.inputs.ResearchInputs`:

```json
{
  "provider": "declared_import",
  "source_reference": "licensed-export-id",
  "received_at": "2026-10-21T12:00:00Z",
  "facts": [],
  "prices": {}
}
```

Facts have symbol, metric, Decimal value, period_end, available_at, source_url,
event_id, and optional period_start. Prices map symbols to ordered records containing
completed_at, open, and close. Future receipts/bars/facts, conflicting duplicates,
nonfinite values, invalid symbols and excessive payloads are rejected. Importing is
a declaration, never source authenticity, coverage certification, or strategy approval.

```sh
uv run python -m trading_bot.hybrid.cli --state-dir "$HOME/.local/share/hybrid-equity" \
  import-research --input /absolute/private/permitted-export.json
```

The explicit `fetch-sec --symbol SYMBOL --cik CIK --user-agent 'application contact'`
command fetches bounded official company facts with identified automated access.
It requires the caller's SEC-compliant contact identification, does not use a broker
token, and stores structured facts only. FRED's connector supports an injected key;
no key is bundled and no recurring FRED job is enabled. News, analyst-revision and
full historical universe feeds require qualified inputs. No news tool is invented.

When resumed, persisted jobs evaluate available imported research every 30 minutes,
produce daily reports, and record weekly/monthly reviews. Missing inputs produce
blocked outcomes. These jobs never turn descriptive feature scores into orders.
External sources are untrusted data, never prompts or executable instructions.
Paid model inference is off and additional recurring spending is fixed at zero.

## Simulated execution and comparison

All three exits are independently callable: principal-value retention (+15%), two
partial reductions (+12.5%, +20%), and trailing trend exit (5%). Quantity is rounded
down to supported precision. Progress survives partial fills and cancellation; only
the unfilled threshold remainder can be resubmitted. Contributions must use distinct
allocation episodes. Long-term appreciation alone never invokes tactical exits.

`replay --experimental --input /private/scenario.json` runs explicit quote/order/
fill/cancel/settle events through the reservation and accounting pipeline. The flag
acknowledges fictional experimental execution, not live authorization. The scenario
schema is `hybrid.scenario.Scenario`. It must use advancing UTC time, regular-session
eligible quotes, explicit fill outcomes, and future settlement times supplied by an
appropriate trading calendar. This release does not certify a broker calendar from
a caller's fictional declaration. Replay is durable and idempotent by scenario hash.

`compare-exits --symbol SYMBOL --slippage-bps N --fee N --operating-per-bar N`
compares the three exits to buy-and-hold, full-target and fixed-holding references
using imported prices. Costs must be supplied explicitly. Decision-close signals
execute at the next open; gaps are not replaced with ideal stop prices. Configured
tax assumptions apply to realized gains, never gross proceeds. Without a tax rate,
after-tax results remain unknown. The comparison assumes one fractional full-fill
episode without reinvestment and remains illustrative, not qualifying backtesting.

The seven frozen pure hypothesis policies and their point-in-time observation
contract are documented in [hybrid-policies.md](hybrid-policies.md). They emit
unqualified research proposals and have no order authority. The executed retained
data exit study is recorded in [hybrid-strategy-comparison.md](hybrid-strategy-comparison.md).

## Limits and next steps

The completed, separately retained ETF Task 5 study found insufficient evidence for
all 174 decisions; its $12/month declared-cost overlay rejected every modeled path.
Those results and private source artifacts are unchanged and are not qualification
evidence for the hybrid policy. The declared droplet charge alone is 14.4% annually
of $1,000 starting capital, before any uncounted expenses.

There is no qualified strategy, verified full-universe/point-in-time dataset,
continuous external research feed, complete broker write mapping, or verified
unattended Robinhood runtime in this release. There is no automatic tactical
selection or order generation from the descriptive research scores. Broad-market
total-return benchmarking, multi-episode statistical selection, tax reporting,
cross-account wash-sale completeness and production-account reconciliation remain
qualification/integration work, not implied by green fixture tests.

Next: qualify actual permitted inputs and costs; implement and verify complete
strategy-cycle and official broker mappings; satisfy security/recovery/readiness
checks against the exact deployed revision; then present a separate user-controlled
live authorization package with exact account, capital, strategies and limits.
No paper waiting period is required. If no strategy qualifies, retain cash or report
the passive alternative rather than manufacturing a trading recommendation.
