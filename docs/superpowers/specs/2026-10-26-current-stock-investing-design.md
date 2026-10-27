# Current research decisions for long-term and tactical stocks

## Human scope and completion

The latest human instructions supersede the exhaustive historical Task5 launch
gate. The requested product researches stocks around the clock and selects
investments using current evidence. Demonstrating profitable outperformance,
completing seven historical strategy families, the old full monetary grid and a
mandatory60-day paper wait are deferred research, rather than release criteria.
Their existing reports, missing data, false qualification flags and conclusions
remain truthful. Nothing in this change proves an edge or enables live trading.

Required first-release behavior is current research -> explicit decision ->
sleeve-aware proposed allocation -> independent deterministic risk -> separately
authorized official broker execution -> actual fill/position reconciliation.
Research and execution remain separate processes/capabilities. Preserve the
existing dedicated-account restriction, cash-only trading, stale-data protection,
idempotency, ambiguous-order recovery, audit log and manual kill switch.

## Two stock-selection tracks

Long-term selection evaluates financial quality, growth, cash generation,
balance-sheet condition, valuation and sourced business risks over years.
Maintain a durable thesis and periodically review held companies. No automatic
10/15/20%tactical profit liquidation applies to long-term holdings.

Tactical selection targets one to two calendar months. Anchor anniversary dates
to the first actual fill's New York date, clamp end-of-month dates and review at
the first supported completed close on/after one month. Continue toward two
months only with positive owned price P&L net defined fees and known continuation
evidence. Earlier protective exits/partial profit reductions remain permitted.
An entry predicate becoming false alone must not recreate a three-day holding
rule. At two months propose disposal at the next eligible session; market closure,
halts, minimum quantities or broker constraints can delay fills. Missing calendar
support and horizon-censored positions remain explicit.

The original75%long-term/15%tactical/10%liquidity targets and existing approved
company/sector/tactical limits remain defaults. No overlapping symbol across
sleeves, borrowing or allocation of the same cash to competing proposals.

## Current evidence and research

Reuse the official bounded individual-stock scanner, archived observations,
normalized current financials/dossiers, verified manifests and quota/controls.
The historical fixed eight-stock frame is a study sample, not the discovery
universe. Rank current eligible stocks across the existing broad scanner.

Add a distinct current-evidence decision report with symbol/instrument identity,
source dates/references, horizon, rationale, bullish/bearish evidence, missing
requirements, ordinal ranking, proposed enter/hold/reduce/avoid and policy hash.
Separate current evidence sufficiency, unproven performance and execution
authorization. Old research-only objects stay research-only; do not fabricate a
profitable ResearchAssessment or loosen generic assess_research.

Use measurable, explicitly versioned fundamental and tactical rules before
optional bounded LLM summaries. Missing values stay missing. Require comparable
periods/units for calculations and current data adequate for its present use;
absence of a complete historical universe is not a reason to reject current
company research. Unreviewed leverage, facts, identity or price risks remain
visible and block affected proposals where required.

A potential threefold value is a clearly labeled scenario with explicit growth,
valuation, share-count and horizon assumptions. Do not invent a probability,
expected return, future financial statement or analyst consensus. Relative
research scores are not forecasts. Allow hold/cash/no candidate decisions.

Monitor held names even when they leave the discovery shortlist. Plan bounded
held/watch refresh before deeper new-candidate calls. Retain actual source clocks
and current quotas; changing freshness schedules requires an explicit new policy,
not relabeling an old stale export. The current13-tool facade has no news tool:
do not claim unsupported news coverage or invent a provider connection.

## Architecture and independent workstreams

Use the existing Python package and database. No new framework/service or
subscription is required to implement the pure initial decision/proposal layer.

1. Pure current company decision/assessment contracts, separate long-term and
   tactical criteria, source/gap/claim handling, relative ranks and scenario
   algebra. Preserve the existing scanner/dossier implementation and evidence.
2. Pure calendar-month holding/mandate evaluation reusable by the actual
   portfolio owner. Use exact owned episode P&L and source clocks. No simulated
   Account becomes a broker ledger merely through type relabeling.
3. A runtime adapter reopens verified archive/report inputs, persists immutable
   decisions and exposes proposal/status output. A later bounded watch-manifest
   seam supplies held symbols without giving account capability to the collector.
4. An explicit research-policy approval basis and sleeve-aware target/intent
   mapping reuse existing sizing, quote, risk, exposure and reservation checks.
   User-controlled activation remains separate from analytical eligibility.
5. Official adapter/nonempty reconciliation and controlled execution composition
   require current supported schemas and deterministic offline failure tests.
   No broker review/place/cancel/transfer call or live activation during development.

Root integrates and owns docs/config/runtime composition. Disjoint modules/tests
may be delegated after their concrete contracts are frozen; no source mutation
in C's running CI or the historical source/adapter worktrees.

## Acceptance

Critical short fictional tests must cover source freshness/identity/period/unit
gaps, contradictory facts, prompt injection as untrusted data, deterministic
ranking/hold behavior, both holding tracks, month-end/leap/DST/session boundaries,
net-profit accounting, long-term/tactical separation, cash reservations/exposure,
kill/stale/auth gates, partial/rejected/ambiguous orders and restart reconciliation.
Use focused dual-Python and necessary integrated regression/static checks.
Backtests remain useful descriptive follow-up; they do not become a hidden
profitability launch gate. No fabricated results or claim of operational
deployment/continuous research/live trading without actual verification.

## Current provider profile amendment (2026-10-26)

Ruling: two closed, bounded official scanner-datapoint metadata captures confirmed
current P/FCF, total stockholders' equity, assets/equity, report currency and
historical-close/average expressions. Implement an explicit opt-in current-provider
profile using these declared fields rather than requiring a new third SEC-facts
acquisition phase for every current decision. No issuer values or executable
preview results have yet been obtained for the additional columns.

Preserve the existing statement-matched assessment and default worker behavior.
The new profile must have a distinct policy identity, request/config hashes and
source labels. Use positive P/FCF and its reciprocal for the cash-flow valuation
factor; never divide an unknown-currency cash-flow/share value by a price. Use
positive totalStockEquity and 1 <= totalAssetsEquityRatio <= 3 as a separately
named conservative liability-leverage proxy, not total debt/equity. The provider's
commonStockEquity is par value and cannot substitute for totalStockEquity. Do not
derive total debt or invent a statement period/report ID. Retain reporting
currency where supplied, and explicitly disclose unknown balance-sheet dates.
Retain current actual net-income/revenue sign checks and supported period/freshness
checks. Financial sectors remain review-only without a suitable separate profile.

For tactical entries, use an explicitly labeled current-provider price signal:
latest scanner price / close(candleCount=20,candlePeriod="1d",session="regular") - 1
and latest scanner price / closeAvg(candleCount=50,candlePeriod="1d",session="regular") - 1.
These are current/intraday research features, not an exact completed-close path or
historical point-in-time qualification. Missing/nonpositive denominators are gaps.
No guessed trade timestamp epoch units or fabricated interpolation indicators.
Require a bounded actual preview verification before claiming provider usability.

All thresholds remain configurable experimental selection criteria, not forecast
probabilities or established profitable rules. Reuse the two-phase archive,
source ledger, quotas and restart controls. Held-symbol coverage remains required
and bounded; do not silently claim watch coverage from the top-candidate feed.
Task5 acceptance includes current research-to-proposal integration and offline
safety checks. Actual official brokerage execution/reconciliation verification,
deployment and explicit live activation remain separately tracked project work.
