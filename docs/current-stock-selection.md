# Current stock selection and portfolio planning

This opt-in layer selects research candidates for long-term investment and
one-to-two-month tactical holdings. It does not require a profitable backtest or
a 60-day paper wait. Returns remain unproven. Rankings express relative research
priority and analytical eligibility, not a probability of profit or tripling.

## Data and selection

The collector discovers individual stocks across the configured market-cap
partitions. Numerical screening precedes deeper company research. The new worker
profile is `stock-worker-current-provider-v1`; the original worker remains the
default, with its existing requests and retained reports unchanged.

The current-provider profile uses positive quality/growth features, positive
reported net income and revenue, P/E, P/FCF, positive total stockholders' equity
and a separately named assets/equity proxy. Its initial proxy range of 1–3 is an
experimental rule, not a reported debt/equity ratio or an optimal threshold.
Unknown statement dates and unavailable financial-report currency remain visible.
Financial businesses require a separate suitable profile and currently get REVIEW.

Tactical research compares the current provider price with the provider's regular
session historical close-20 and average-close-50 features. These are snapshot
signals, including potentially intraday information. They are not exact
completed-close historical paths. Every such feature binds to one original
scanner row. Missing inputs stay missing; negative or insufficient evidence may
produce no investment candidate.

The additional columns and single-/multi-symbol filter shapes were verified in
bounded official read-only previews during development. That proves those tested
requests worked; it does not establish profitable stock selection, complete
coverage, background authentication or deployment.

The current source facade does not include a news tool. Filing indexes and earnings
records do not establish that every filing's contents or every material news event
has been analyzed. Do not describe this release as comprehensive news monitoring.

## Source integrity and held stocks

`stock_investment_inputs` reopens the source ledger and manifest-committed archive,
recomputes the reports, and preserves original receipt times. It joins discovery
and targeted enrichment snapshots by exact symbol/instrument identity. A changed
shortlist without matching company reports is a visible research gap. Contradictory
identities and same-time conflicting scanner rows fail closed.

The bounded `StockResearchWatch` API gives held names first priority, then
watchlisted names, within the configured enrichment capacity, even when they leave
the discovery shortlist. Remaining slots rotate through discovered candidates
using completed enrichment cohorts from the same configuration/code identity.
With no free slots, discovery still runs but deeper research covers the priority
names; this does not promise immediate research of every discovered stock.

The private watch store is implemented: `publish_stock_research_watch` atomically
publishes a source-bound inventory and `read_stock_research_watch` validates its
bytes, ownership and original expiry. The collector CLI can read it with
`--watch-dir`. Missing, expired, conflicting or over-capacity watches fail closed.
The collector does not gain brokerage account capability to discover holdings.

Watch publication remains a caller-owned library dependency. An external
portfolio owner supplies a current reconciled `StockAllocationContext` to
`stock_research_watch_from_portfolio`, then publishes it directly or supplies
`watch_output_dir` to `run_current_stock_planning_cycle`. That cycle also requires
the exact owned `held_sleeves` inventory. It does not infer ownership from ranks,
pending buys or a ticker list. Original context clocks are retained; the owner
must refresh valid evidence before expiry rather than extending old receipts.
The planning CLI has no account/watch-publication fixture or automatic account
lookup. The portfolio proposal layer checks that actual positions match the
research-held symbols, instruments and sleeves. Missing coverage blocks new
capital proposals.

## Cadence and the small-account call budget

Explicitly pair these examples in a separate selected configuration graph:

- `configs/hybrid/stock-research-current-provider.example.yaml`: nine-name capacity.
- `configs/hybrid/stock-worker-current-provider.example.yaml`: the current-provider
  profile with a 60-minute enrichment refresh.

The loader reads the canonical names `hybrid/stock-research.yaml` and
`hybrid/stock-worker.yaml` under the chosen config root. Select the example
contents there without overwriting an installed default configuration. The new
canonical configuration hash requires matching source/control identities.

Discovery uses 17 calls and a full nine-name current enrichment uses 25, including
same-session filter verification and a targeted scanner refresh. Twenty-four
hourly alternating slots, or 12 discovery/enrichment pairs, budget
`12 × (17 + 25) = 504` calls against the shared 512/day limit. The cycle limit
remains 32; these are planning counts, not a promise of successful responses or
uninterrupted service. Retries and additional work cannot bypass the same quota.
Ten names would use 528 calls for that cadence and do not fit this daily budget.

At most nine unique held/watch priority names fit the paired example. Additional
priorities are rejected rather than silently omitted. Reserve space for discovery
if new-name research is wanted; only remaining slots rotate. More capacity or a
different cadence requires an explicit shared-budget decision, not a second
independent daily allowance.

## Planning and reports

The planning cycle reads existing research, applies the current evidence policy,
and publishes a separate private report. `CurrentStockPlan` v2 and the schema 2
report include separate rankings, entry cash ceilings when available, owned
holding reviews and optional tactical profit reductions. Every execution/live/
order/reservation flag remains false.

With a caller-supplied reconciled account context, current issuer identity
mappings and planning controls, it can produce portfolio cash ceilings. Without
those inputs it still reports research results and explicit gaps. Source hashes
bind supplied facts; they do not authenticate an account. It never invents buying
power or counts proposed sale proceeds as cash.

The allocation planner applies the default 75% long-term / 15% tactical / 10% cash
targets, company/tactical/sector limits and existing/pending/local cash commitments.
Cash ceilings are not orders, atomic reservations or execution approval. Issuer
identity must not be inferred from a share-class instrument ID.

The caller supplies owned fill/lot/episode evidence for held-position reviews.
Tactical one- and two-calendar-month anniversaries are clamped in New York time.
Before month one, a weakened entry predicate alone does not force an early exit;
protective exits and partial profit reductions remain possible. At the month-one
review, positive owned episode price P&L and known active continuation permit
holding toward month two. Known inactive continuation or nonpositive price P&L
proposes exit; missing evidence produces REVIEW without an approved extension.
A supported month-two review proposes exit at the next eligible market
opportunity, without inventing a future open or fill price. Missing completed
session evidence and delayed review remain explicit; the helper does not prove
that the supplied close was the first eligible session. Long-term holdings have
no monthly deadline or fixed appreciation-based liquidation.

Current reviews use a labeled indicative receipt snapshot, not an executable
quote or a completed-close price. Freshness is bounded by the original source
expiry and the declared snapshot-age limit. Episode price P&L combines actual
owned realized price gains and remaining-lot marks after known sale-cost
assumptions; it does not double count dividends or taxes as price gains.

The pure profit helper supports principal-value retention, two partial-profit
rungs and a trailing-price method. The caller explicitly chooses at most one
method per owned episode per cycle and supplies the policy, original allocation,
actual pending/fill progress, lots, fractional eligibility and relevant cost/tax
assumptions. Unknown facts stay unknown. Completed thresholds come from actual
fills, not recommendations. A quantity-verified protective/terminal full exit
suppresses the optional trim. Estimates separate proceeds, disposed basis, gain,
remaining basis and tax provision; they neither reserve money nor credit cash.
Principal-value retention does not guarantee or protect the original principal.

## Local offline planning and external scheduling

This wrapper is a concrete invocation template for an external scheduler. Replace
the absolute paths with an existing clean verified checkout, selected config,
migrated private source ledger/archive and matching running research-control
grant. Create the separate output directories as private 0700 directories first.
The wrapper only reads retained research and writes analytical reports/projection;
it does not collect market data, accept credentials, look up an account or trade.

```sh
#!/bin/sh
set -eu
umask 077
cd /absolute/verified-checkout
exec /absolute/verified-checkout/.venv/bin/python \
  -m trading_bot.runtime.stock_investment_cycle \
  --config-root /absolute/private/selected-configs \
  --database /absolute/private/state/stock.sqlite \
  --archive-dir /absolute/private/research \
  --output-dir /absolute/private/investment-reports \
  --decision-export-dir /absolute/private/decision-view \
  --control-dir /absolute/private/controls
```

Arrange the external scheduler to call this wrapper after a successful collection
cycle, with only one planning invocation active at a time. For example, the
collection job's successful-completion step can invoke this offline wrapper; the
wrapper itself installs no schedule or service. Do not treat a fixed wall-clock
delay as proof that collection succeeded. The command returns 0 only for a
published plan and 2 for a blocked invocation; retain its JSON receipt and alert
on failures. It does not start persistent operation or demonstrate deployment.

`--decision-export-dir` is optional. The full immutable report is published first;
the minimal view is then linked to that report's byte hash and evidence hash.
Publication checks control, source, portfolio and issuer expiries before and
after writes. A blocked final result does not erase an already written immutable
report: inspect its receipt and original timestamps rather than treating file
existence as current success. Dirty code is rejected unless the supported
verified-image identity path is used; do not bypass startup checks.

The CLI is research-only even when ranks meet the criteria. Owned account,
issuer, sleeve, lot, profit-state and watch-publication integration use the typed
library API, not an executable fake-account configuration. Until a real portfolio
owner provides those facts, cash ceilings or holding/profit outputs may remain
unavailable and the report says why.

## Dashboard and retained evidence

The v3 dashboard correction uses decision export schema 2. It shows long-term and
tactical ranks, rationale, gaps, method limits, source clocks and explicit
execution-disabled/unproven-performance labels. The bounded view shows at most 20
ranked and 20 other rows per horizon, with full assessed/eligible/omitted counts.
Its earliest eligible expiry covers all source rows, including omitted rows.
The presenter adds a source-age/action deadline; the UI suppresses cached actions
and eligibility during a pending/failed/stale refresh or after expiry using its
existing clock. This is current research visibility, not a live portfolio balance
or an approval/order screen. Owned monthly/profit details remain in the full
private report rather than being implied by the rank table.

The existing dashboard server accepts the distinct
`--stock-decision-export-dir` option to read that minimal projection. Only the
projection directory is needed for this reader, mounted read-only; do not give it
the acquisition archive, source database, OAuth store or full-report directory.
The decision reader takes no write lease. Other existing paper dashboard balances
remain labeled simulation and must not be described as actual account values.

Keep report and acquisition directories separate, nonnested, private (0700),
with private report files (0600). Reports preserve exact decimal text, source
clocks, rationale, missing requirements, analysis/acquisition code identities and
component hashes. The report evidence hash and the serialized artifact hash are
different identities. Readback verifies retained bytes and scope; it does not
authenticate arbitrary supplied input dataclasses or authorize execution.

Full reports are content-addressed and immutable; the minimal view and watch are
separate current projections. Report storage is bounded at 1024 directory entries
(including its lock), 64 MiB total and 9,000,000 bytes per report. It stops on full,
corrupt or unexpected storage instead of deleting evidence. An external owner
must archive verified reports outside the active report directory before those
limits, preserving original bytes/hashes, and monitor storage. No automatic
retention service or indefinite report capacity is claimed.

## Next steps and scope boundary

Complete the integrated current-workflow release audit and connect the external
portfolio owner that supplies/reconciles real account, issuer, mandate, lot and
watch evidence. Keep the paired cadence, coverage capacity, freshness and report
retention constraints explicit. Exhaustive historical seven-family comparisons
and a mandatory paper waiting period are deferred; missing current evidence,
deterministic risk, authentication and execution authorization remain essential.

After Task 5's research/decision/proposal workflow, finish official Robinhood order
review/transport, actual pending-order/fill/position/tax-lot reconciliation,
atomic reservation and duplicate protection, operational deployment verification
and separate user-controlled live activation. These are not completed by a green
research report or dashboard. No local test, saved report, credential, schedule or
deployment procedure enables live trading.
