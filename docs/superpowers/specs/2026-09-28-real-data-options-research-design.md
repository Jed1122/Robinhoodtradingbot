# Complete real-data options research path

Status: **Design brief approved; written specification awaiting operator review.**
Prepared 2026-09-28 UTC against `2e3bf74aba14864ae5a43bb518a17c665ea633c4`.
This is a proposed design, not implemented behavior or empirical economic evidence.

## 1. Intent and scope

The operator selected the complete real-data path: provider verification, quote
ingestion, and historical after-cost/uncertainty evaluation, retaining the existing
shortlist, risk limits, and live-trading blocks. The objective is a reproducible
answer about a strategy's admissibility and after-cost evidence, including an honest
NO-GO; it is not to force a trade or select an apparently attractive winner.

Deliver one integrated research system in sequential vertical slices. Start with
SPY directional long calls/puts and the existing fixed 20/100 momentum hypothesis.
The retained shortlist selects one call and one put using the previous completed
regular-session close, nearest strike, and expiration nearest 30 calendar days in
21–45 days, with existing deterministic ties. Do not optimize that shortlist on
subsequent quotes, liquidity, Greeks, returns, or rejected results.

Verticals and condors remain later research families, in the master specification's
order, after single-leg accounting and native package-execution modeling pass their
own review. This design does not represent single-leg quote reconstruction as
verified multi-leg fills. Production lifecycle, broker adapters and deployment are
separate workstreams and do not block credential-free research implementation.

The [master specification](../../options-only-build-spec.md),
[native-data design](2026-09-25-native-options-data-integration-design.md), and
[standing authority](../../operator-authority.md) remain governing inputs. Necessary
data purchases within remaining authorized Databento credits need no repeat approval;
reviewed in-scope merges need no repeat merge approval. Neither permission authorizes
cash spending, subscriptions, new agreements, broker writes, risk changes or live use.

## 2. Alternatives and selected design

- **Complete composed path — selected.** Reuses the native pipeline and canonical
  decisions/risk while explicitly implementing missing real-data consumers and
  statistical reporting. This produces an end-to-end result instead of disconnected
  data files, but has both software and external-evidence dependencies.
- **Provider verification and ingestion only.** Useful infrastructure, but cannot
  establish strategy outcomes, cash conservation or economic uncertainty by itself.
- **Relabel imported data as synthetic or bypass source verification.** Rejected:
  this would invalidate provenance and the existing evidence boundary.

Do not rebuild the repository. Preserve historical schemas/hashes and unrelated
dirty work. The prior native milestone is complete only within its bounded contract:
it can issue explicit dependency denials, not qualify actual source data today.

## 3. Verified starting point and dependency chain

The native bar/definition readers, private Parquet storage, source-evidence models,
session/definition assemblers, v2 shortlist, and acquisition coverage planner exist.
However, `load_reviewed_rules()` returns no actual-source rules, and the verifier
dispatches exclusively to a synthetic parser. `OptionsReplayRequest` also rejects
all imported records. Generic metrics, splits and IID resampling are primitives, not
an imported-data options evaluation path.

```text
source contracts and preserved bytes
  -> real-provider verification + calendar/actions/contract evidence
  -> fixed point-in-time shortlist + preregistered consumer/coverage requirements
  -> credit-bounded acquisition + actual quote normalization/coverage verification
  -> event-driven options study + reconciled cash, positions and reservations
  -> after-cost scorecard, dependent-outcome uncertainty and explicit verdicts
```

Freeze interfaces before isolated fixture, storage, rendering or documentation work
is delegated. The coordinator retains source-authority, strategy, pricing, risk,
execution, accounting and integration decisions. No raw licensed data or credentials
are sent to Cloud agents; fixture-based CI and code review remain separate.

## 4. Real-provider verification

Extend the existing source verifier with explicit code-owned parser dispatch. Keep
the synthetic protocol separate, and reject unknown parser versions rather than
accepting generic JSON assertions. No CLI flag, data-file field or environment
variable may install rules or declare a source trusted.

Each actual rule binds provider, dataset/schema, applicable historical era, source
documents, exact preserved input identities, parser/version and tested semantics.
Recompute facts from native bytes. In particular, definition publication facts bind
both raw-record identity and the existing canonical projection hash. Verify dated
instrument mappings, complete membership baselines and visible updates/deletions;
do not use a union of all contracts observed during a day as the opening chain.

Resolve all existing roles independently: calendar, bar publication, corporate
actions, definition state, contract terms, and quote semantics. A successfully parsed
role cannot approve the others. Current reference documents are discovery evidence,
not automatically proof of historical publication or completeness.

The bar archive has interval-start timestamps, not original publication timestamps.
An assumed one-minute or overnight delay cannot pass the current strict bridge.
Obtain sufficiently scoped provider evidence or reconstruct required aggregates from
timestamped source events with validated correction semantics. Price any additional
data before acquisition. If neither route establishes suitability, retain the
diagnostic intake and issue a specific denial; do not silently relax the requirement.

Reference inputs must establish exceptional sessions/early closes/DST, corporate
actions and dividends including explicit empty coverage, standard deliverables,
exercise/settlement conventions, ticks, last trading and settlement schedules.
Adjusted deliverables and unsupported settlement conventions deny. Provider-degraded
intervals need independent resolution; row removal does not resolve a warning.

Public starting points checked on 2026-09-28 include
[OHLCV semantics](https://databento.com/docs/schemas-and-data-formats/ohlcv),
[instrument definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions),
[timestamp conventions](https://databento.com/docs/standards-and-conventions/common-fields-enums-types),
and the [OPRA migration](https://databento.com/blog/opra-migration).
The latter documents consolidated quote history starting March 28, 2023, so January
2023 definitions do not prove matching consolidated quotes exist. These references
do not themselves install a rule or qualify the user's private archives.

## 5. Study preregistration and acquisitions

Create one versioned immutable study specification before outcome inspection. It
binds hypothesis, exact decision dates, warmup, fixed construction, exit policy,
parameters, data/consumer/config/code identities, costs and fill scenarios, capital
tiers, splits, embargo, uncertainty procedure and all rejection criteria. Keep every
attempt, amendment and failed study; a changed study gets a new identity.

Freeze date windows from source availability and calendar facts, not observed P&L.
Use the canonical five walk-forward folds and minima, then a distinct untouched
chronological final test. Exact boundaries must be in the study before quote outcomes
are read. Development/calibration cannot access final-test outcomes. Do not change
the holdout dates because results, missing fills or costs are disappointing.

Reuse `StudyCoverageRequirements` and the current manifest assembler. Both shortlisted
contracts require compatible initialization and full quote coverage through monitoring,
possible exit, expiry and settlement obligations, even when only one direction is
signalled. Include underlying observations, reference events and warmup. Deduplicate
overlaps and already acquired bytes; never purchase only winning or filled episodes.

For event-age evaluation prefer consolidated option events (CMBP-1) and an explicitly
identified compatible underlying quote feed. Minute CBBO can support a separately
labelled interval diagnostic but cannot establish five-second executable freshness.
An exchange-specific underlying feed is not national NBBO. An alternative feed needs
verified semantics and explicit lineage, not a silent splice.

The coordinator checks the entire missing package's customized-request cost against
fresh applicable credits after pending charges, retains private reservations and
receipts, and reconciles uncertain acceptance before retry. If the complete package
does not fit, stop acquisition and report the gap. Any engineering pilot must be
frozen independently and remain non-qualifying; do not shrink a qualifying study
after examining outcomes. No new purchasing client or spending capability is exposed
to the offline CLI.

Stage acquisition by evidentiary value: first verify the complete narrow vertical
slice and capital feasibility using calendar-selected pilot inputs, then price the
larger preregistered study. If observed premiums make every full-policy tier
inadmissible, report that result before consuming credits on further performance
data. A hypothetical unit-payoff study would not cure that account-feasibility failure.

## 6. Quote intake and canonical event stream

Add bounded native option/underlying quote readers beside the existing native readers.
Retain raw DBN bytes, metadata, source ordinal, native nanoseconds, fixed-point prices,
sizes, flags, action and dated instrument identity. Reject unsupported DBN/schema
versions, truncation, contradictory duplicates and unknown mandatory flags. Source
archives are immutable. Preserve rejected observations in quality accounting.

Reuse private atomic Parquet publication and dataset manifests. Introduce explicit
versioned native quote schemas; do not reinterpret bars as quotes or rewrite v1
records/hashes. Reverify all data parts before consuming a requested window, enforce
bounded memory/work, and prohibit DuckDB external access and extension loading.

Construct canonical quotes only after terms and semantics are verified. Zero bid is
a valid observation but normally denies entry and does not imply a sale can fill.
Locked quotes obey existing configuration; crossed, stale, incomplete or inconsistent
quotes deny. Track bid/ask sizes and quote timestamp quality explicitly.

Maintain stream initialization, clears, corrections, gaps and session changes.
Do not carry a quote across an unverified reset, halt, missing coverage or session
boundary. Distinguish an unchanged quote in a healthy stream from absent data; neither
freshness nor no-trade coverage is inferred from a later successful download.
Synchronize option and underlying observations with the canonical age/skew limits.

Tie processing order to verified source semantics. Ambiguous same-time data cannot
grant an earlier fill. No resampling may timestamp an aggregate before it is known.
Late corrections create attributable revisions/invalidations; they cannot rewrite
earlier as-known decisions without invalidating the dependent result.

## 7. Shared decision and research execution composition

Introduce a distinct imported-study request/result envelope. Retain the current
synthetic replay constructor and rejection rules unchanged. Extract only genuinely
shared pure helpers where necessary, with legacy hash and behavior regression tests;
do not create a second strategy/risk algorithm.

At each eligible session, use only previously completed, verified underlying history
and the existing momentum implementation. A mixed/absent signal is no candidate, not
an implicit put. Price and record both fixed shortlist candidates before choosing the
signalled side. Missing inputs are explicit denials, not omitted opportunities.

Proposed first-study exit policy: evaluate signal invalidation using completed history
at each next eligible session; initiate a close when the held direction is no longer
supported. Independently initiate expiry-risk closure at the start of the preceding
eligible options session, with that session's verified close as the latest permitted
deadline, or an earlier applicable deadline. No optimized profit target, stop grid,
rolling or same-session re-entry is added initially. This is a research hypothesis,
not validated execution policy. Its parameters belong in the canonical config graph.

Use LIMIT/GFD simulated intents and next-eligible-event execution. A new entry limit
uses the observed ask; a requested close uses the observed bid, subject to verified
tick alignment. Execution cannot precede the canonical latency and a later eligible
event, exceed the limit, ignore quote size, or reuse consumed liquidity. No automatic
market fallback or optimistic midpoint fill is introduced. Unfilled orders and missed
exits remain genuine modeled outcomes; the final input record never forces a fill.

Conservative/base/optimistic scenarios bind explicit latency, rejection, no-fill,
liquidity participation, cancel-race, slippage and fee assumptions. Reuse canonical
settings where semantically applicable; do not apply equity commission/spread defaults
to options. Missing empirical calibration is disclosed and prevents qualification.
Even an optimistic scenario requires actual subsequent eligible observations and
cannot fabricate liquidity, a settlement, or a favorable exit.

One complete unit per entry, one open strategy position and one new position per
session remain initial limits. A one-contract order cannot partially fill a fraction
of a contract. Multi-unit fixture tests exercise integer partial fills without raising
the study/trial limits. Duplicate events never double-charge fees or consume capital.

Keep the execution composition credential-free and incapable of constructing broker
write capabilities. Broker acceptance and paper/shadow promotion clocks are not
simulated as real operational evidence.

## 8. Risk, cash and lifecycle accounting

Reuse the multiplier-aware options economics, canonical configuration/envelope,
order transition machinery, trial-loss logic and reconciliation/expiry primitives.
Full premium plus bounded fees is reserved before admission; narrow stops are not
risk denominators. Preserve reservations through partial fills, pending cancellation,
ambiguous outcomes, expiry and incomplete settlement. Cash becomes available only
after its modeled settlement event, not merely a terminal order status.

Use exact Decimal cash flows and integer quantities, with source/event/episode
identities and an independently reconciled journal. Retain the $50 cumulative
non-replenishing completed-episode trial-loss ceiling and the $50 per-trade outer
limit, subordinate to all stricter percentage limits. Profits, deposits, dates,
restarts, rolling and new study files do not replenish a continuing trial's capacity.

Separate two explicitly identified research cohorts: full-policy capital-feasibility
paths including the trial stop, and standardized hypothetical unit-payoff observations
used to study the underlying hypothesis. The latter are not admissible account trades,
do not omit rejected opportunities, and cannot establish account-level feasibility or
override a trial stop. Qualification requires the full-policy account result as well.
Fold boundaries cannot reset the continuing account's losses, reservations or halts.
Distinct hypothetical tier/scenario paths have separate identities and starting
conditions; they are not deposits or new authorizations for a stopped live trial.

Evaluate the master specification's $100, $500, $1,000, $2,500, $5,000, $10,000,
$25,000 and $50,000 hypothetical tiers without changing live assumptions. At $100,
0.5% is $0.50; zero admissible contracts stays zero. Keep authorized risk capital
separate from current marked equity so gains cannot silently increase risk limits.

Weekly/drawdown halts remain latched in each account path; a new day cannot clear
them. Entry halts do not manufacture exits or cancel protective management. Missed
deadlines, uncertain settlements, unexpected shares, exercises and broker closeouts
are incidents. Do not automatically exercise or remediate stock in research as if an
unsupported production route existed. Incomplete episodes stay incomplete; report
conservative bounds rather than dropping them from a favorable denominator.

## 9. Costs, baselines and uncertainty

Fee schedules must be effective-date-, side-, leg- and contract-aware, with official
source identity. Unknown fees are not zero. Distinguish a historical schedule from
today's forward-deployment cost scenario. Spread and slippage already embedded in
fills are attributed but never subtracted a second time.

Report trading P&L, operating profit and cash-baseline excess separately. Operating
costs include data, hosting, monitoring and any approved service/model costs; show
actual cash outlay and sustainable replacement cost separately when credits subsidize
data. Do not assume the credit grant recurs. Cash-yield inputs need dated provenance;
zero-yield cash is an explicitly labelled reference scenario, not an asserted broker
rate or conservative evidence of excess return. Qualification requires the
preregistered, appropriately sourced cash baseline. Any underlying benchmark is
analytical only, not a stock-trading path.

Compute full-account returns, net dollars, drawdown/depth/duration, expected shortfall,
utilization, turnover, denied/unfilled/incomplete opportunities, cost attribution and
confidence intervals. Keep model values, broker-style marks and executable liquidation
marks distinct. Existing QuantLib pricing is date-granularity, bounded and theoretical;
unsupported intraday/dividend assumptions deny analytics, not silently approximate
required exposure. Pricing formulas are not physical expected-return estimators.

Reuse split/metric primitives behind strict options adapters, but replace IID outcome
resampling for this path with seeded block resampling of chronological session-level
outcomes and account paths. Group overlapping exposures and the paired call/put
observations; neither legs nor alternate fill scenarios increase independent sample
count. Blocks and embargo must cover the preregistered maximum outcome horizon,
including unresolved settlement, and be fixed without looking at final-test returns.
Retain no-trade and halted periods when computing full-account performance.
Unbounded unresolved settlement cannot be assigned a convenient outcome horizon:
retain explicit censoring and qualification denial until the obligation is resolved.

Proposed uncertainty threshold: a one-sided 95% lower confidence bound on after-cost
out-of-sample expectancy must exceed zero in the conservative scenario, in addition
to every existing stricter criterion. Add this explicit whole-percent setting through
the canonical config/envelope; no ad hoc CLI weakening. Preregister dependence/block
length sensitivity, tail treatment and finite-sample limitations. If enough effectively
independent blocks or episodes are not available, the interval is unavailable for
acceptance, not silently replaced by an IID or normal-approximation interval.

The initial strategy parameter set is one fixed hypothesis, not a large optimized
grid. Keep all attempts, and treat later parameter/exit changes as additional tests
with preregistered multiplicity control. A single-candidate study does not justify
inventing a PBO value. Any required but unavailable overfitting assessment remains
a blocker. Do not claim stability if neighbor/ablation tests have not been run.

## 10. Reports and verdicts

Add a versioned options-study report that binds all source/coverage/study preimages,
normalizer and consumer code, config, causal features/decisions, intents, lifecycle
events, cash flows, trial state, costs, split membership and seeds. Reuse hashing and
private storage conventions while keeping legacy bar-only reports readable. A hash
is integrity evidence, not source authenticity or an external approval signature.

Distinguish `BLOCKED_INPUTS`, `INCOMPLETE_SIMULATION`, and a completed modeled study.
Every state contains explicit reasons and opportunity/coverage counts. Separate
technical, source/data, economic, account/capability and operator-authorization
verdicts. Economic qualification requires actual history/sample adequacy, calibrated
assumptions, after-cost uncertainty and all canonical minima; an engineering pilot
cannot pass by choosing a different label. Missing evidence yields `ECONOMIC_NO_GO`.

Retain the 3,650-day history request, 750 daily observations, five folds, 50 test
observations per fold and 30 independent opportunities. Verify actual attainment;
declared windows and planned session counts do not suffice. The retained history span
does not require or prove ten years of option quotes. The v1 planner cannot establish
observed-history adequacy and must keep qualification blocked until this path supplies
reviewed evidence. Do not claim the current 2018–2025 underlying acquisition satisfies
the larger history request.

Even a future favorable economic assessment never sets live authorization. During
this milestone production eligibility, promotion, download capability and live
authorization remain false on the offline command surface. A later independently
reviewed integration would be needed to consume accepted research operationally.

Expose bounded offline commands through the existing options CLI for source
verification, quote import/verification, study freeze, backtest, walk-forward,
cost/stress and capital-feasibility reports. Reuse existing commands where possible;
freeze exact command/serialization contracts in the implementation plan. Do not add a
parallel config loader, production database migration, network client or daemon.

## 11. Delivery slices and acceptance

1. Real-provider parsers and independently pinned source/era rules. Native-byte
   derivation and wrong-source/time/projection adversarial tests must pass. Missing
   external evidence leaves the affected rule uninstalled, not approximated.
2. Quote storage/normalization and initialized causal consumers, tested with synthetic
   DBN fixtures before any study acquisition. Verify
   corruption, gaps, flags, limits, DST/holidays, locks, resets and timestamp ties.
3. Immutable preregistration and complete coverage/credit workflow, including fake
   receipt/cost tests. No external submission occurs in CI or the offline program.
4. A single genuine-data historical episode with independent expected cash/fees,
   denial at infeasible capital, cancellation races and truthful incomplete outcomes.
5. Multi-episode full-policy paths, reconciled accounting and capital tiers, preserving
   trial history and loss halts. Add continuity/restart tests without production state.
6. Purged walk-forward/final-test evaluation, dependence-aware uncertainty, operating
   costs/baselines, private reports and adversarial no-lookahead/holdout tests.

Use failing tests first, narrow checks, then full main and locked research suites.
Retain 80% overall coverage and 90% branch coverage for critical risk/execution/lifecycle
modules. Run Ruff, Mypy, Bandit, lock checks, authorized dependency audits, SBOM
reproducibility and manifest checks. Keep optional backend and missing-system-tool
skips explicit. No test can load trading credentials, make a broker write, buy data
or promote synthetic fixtures.

Completion means reproducible software and either genuine, appropriately scoped
economic findings or a precise externally blocked evidence report. It does not mean
profitability, live readiness, deployment, or that the remaining credits are sufficient.

## 12. Review handoff

This written specification requires operator review before an implementation plan is
prepared. The approved brief permitted writing it, not implementing unreviewed new
interfaces. After written-spec approval, prepare the dependency-aware plan and execution
handoff. Existing merge and credit-only acquisition grants remain in effect throughout;
do not request them again.
