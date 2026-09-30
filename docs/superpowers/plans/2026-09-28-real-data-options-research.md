# Complete Real-Data Options Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Preserve the operator's selected native execution method; the coordinator implements protected components.

**Goal:** Produce reproducible historical options research with verified sources,
cash-conserving modeled execution, capital feasibility and after-cost uncertainty,
or an explicit evidence-dependent NO-GO.

**Architecture:** Extend the existing native intake, source verifier, fixed shortlist
and coverage planner. Compose a separate imported-study envelope with canonical
strategy/risk/lifecycle helpers, preserving synthetic replay and historical hashes.
Keep acquisition outside the credential-free program and all trading capabilities locked.

**Tech Stack:** Python, Decimal, existing strict config and hashing, locked DBN decoder,
Parquet/DuckDB, existing optional QuantLib backend, pytest/Hypothesis, Typer.

**Spec:** [Approved real-data design](../specs/2026-09-28-real-data-options-research-design.md).
Written specification approved by the operator on 2026-09-28 UTC. The operator
approved this implementation plan on 2026-09-29; native/inline execution proceeds
within the unchanged authority and safety boundaries below.

## Global Constraints

- SPY long calls/puts only for this path; fixed 20/100 hypothesis and previous-close
  ATM shortlist, target 30 days within 21–45, deterministic existing ties.
- One complete unit per entry, one open strategy position, one new position per session.
- $100 live capital assumption and $150 live equity ceiling are not verified balances.
  Preserve $50 non-replenishing trial loss and $50 per-trade outer limits, all stricter
  percentage/cash/daily/weekly/drawdown controls, and all existing promotion clocks.
- Hypothetical tiers: $100, $500, $1,000, $2,500, $5,000, $10,000, $25,000, $50,000.
  At $100 the 0.5% budget is $0.50; a denied unit must remain denied.
- Preserve 3,650-day history, 750 observed daily bars, five folds, 50 test observations
  per fold and 30 independent opportunities. These are not ten years of option quotes.
- One-sided 95% conservative-scenario lower confidence bound must exceed zero,
  in addition to stricter existing acceptance criteria; 95 is whole-percent config.
- No synthetic record may establish genuine economic evidence. No imported data may
  be relabelled synthetic to enter the existing replay constructor.
- No credentials, raw licensed data or production state in Git, logs or Cloud prompts.
  All acquisition remains credit-only and outside CI/offline CLI; no subscriptions,
  cash spending, new agreements, broker writes, deployment or live activation.
- No dependency upgrade is planned. If supported decoding/pricing cannot work with
  current locks, report the exact compatibility issue before changing dependencies.
- Preserve unrelated dirty files. Commit only owned paths/hunks. Review exact current
  CI and diffs before automatic merges; never merge merely because tests started.

## Review Focus

1. Revised or only partially initialized chains must not gain earlier membership
   from a later full snapshot (Task 2).
2. A manifest retained while a raw part is replaced must invalidate consumption,
   including retries/resume (Tasks 3 and 4).
3. An unchanged quote is different from a dead/reset feed; neither may manufacture
   executable freshness (Tasks 4 and 7).
4. Fold changes/restarts and profitable episodes must not replenish the cumulative
   trial allowance or clear latched halts (Task 8).
5. A credit-funded dataset is not a permanently free operating input, and changing
   final-test outcomes must not affect registration/selection/calibration (Tasks 5, 9, 10).

## Dependency order, ownership and file map

One sequential composed plan is appropriate: source identity, event timing, coverage,
execution and uncertainty share causal contracts. The slices below are independently
testable but are not independent strategy implementations.

```text
1 evidence contracts -> 2 provider semantics -> 3 quote intake -> 4 causal stream
                                      -> 5 frozen study -> 6 bounded pilot acquisition
4 + 5 -> 7 historical episode -> 8 account paths -> 9 costs -> 10 uncertainty
                                             -> 11 CLI/reports -> 12 final validation
```

Task 6's external prerequisites may stay blocked while Tasks 7–11 use strictly
synthetic fixtures. Task 12 distinguishes software completion from genuine evidence.
No qualifying dataset purchase precedes a working fixture-tested consumer.

Reuse these existing locations without replacing their APIs:

- `market_data/options_source_*`: role-specific source evidence and code identities.
- `market_data/databento_{bars,definitions,bar_store,stage}.py`: preserved native archives.
- `market_data/options_{session_inputs,definition_inputs,records,parquet}.py`: canonical facts.
- `research/options_shortlist_v2*.py`, `options_acquisition*.py`: shortlist and windows.
- `simulation/options_replay*.py`: synthetic legacy path, regression-only unless a pure
  shared helper is extracted without changing serialized identities.
- `strategies/options/momentum.py`, `risk/options_economics.py`,
  `domain/order_state_machine.py`, `lifecycle/options_expiry.py`: primary-owned rules.
- `config/models.py`, `config/loader.py`, `config/hashing.py`, base/envelope YAML:
  one canonical configuration graph, never a second loader.

New modules are listed under the task that owns them. Paths below are relative to
`src/trading_bot/` unless they begin `tests/`, `docs/`, `configs/`, or `.github/`.
All new public records are immutable, strictly validated and versioned. Do not add
opaque `dict` fields in place of the named identities/times/amounts below.

Before delegation, record the exact committed SHA, frozen interfaces, one owner and
exact file ownership. Delegable: fixture parsers/tests, isolated storage tests,
rendering/docs and independent audits. The coordinator owns provider trust, strategy,
pricing, risk, execution, accounting, acquisition decisions and integration. No
parallel worker may edit this branch or protected modules.

## Task 1: Versioned source dispatch without opening trust

**Files:** Modify `market_data/options_source_models.py`, `options_source_verify.py`,
`options_source_rules.py`; create `market_data/options_source_dispatch.py`;
test `tests/unit/market_data/test_options_source_dispatch.py`.

**Interfaces:** Keep `verify_source_bundle(bundle, *, context, loaded,
repository_root) -> SourceVerification`. Add `ParsedSourceFacts` containing sorted
native-envelope/canonical-fact hash pairs and `SourceInvalidation` records.
`parse_source_claim(claim: SourceClaim, rule: SourceRule, artifact: PrivateArtifactRef,
*, context: VerificationContext, loaded: LoadedConfig, repository_root: Path)
-> ParsedSourceFacts` selects an installed parser by closed verifier ID.
New IDs: `databento-native-v1` and `reviewed-reference-v1`; retain `synthetic-records-v1`.
An ID names code, not approval. Extend code-hash dependency lists for every new parser.

- [x] Write tests `test_unknown_verifier_denies`, `test_synthetic_rule_cannot_approve_native`,
  and `test_original_synthetic_claim_hash_unchanged`; assert denial or literal stored
  pre-change synthetic hashes, never expected hashes computed by the new parser.
  Representative assertion: `assert verification.status == "denied"`.
- [x] Run `PYTHONPATH=src uv run --project research --frozen --no-sync pytest tests/unit/market_data/test_options_source_dispatch.py -q`; verify the missing dispatch fails.
- [x] Implement dispatch and existing synthetic adapter; stream native artifacts via
  their verified manifests rather than loading multi-gigabyte bytes into `_snapshots`.
  Keep native/reference rules uninstalled until Task 2 supplies reviewed era evidence.
- [x] Run that file plus `tests/unit/market_data/test_options_source_verify.py` and
  `test_options_source_contracts.py`; expect all pass and empty actual rulebook still denies.
- [x] Commit only the listed files: `feat: add closed options source parser dispatch`.

Task 1 checkpoint: commit `8ab401b`, 57 source tests passed. The existing verifier's
mutation-during-read test followed the extracted read helper without changing its
assertions. Actual native/reference adapters and rules remain Task 2 work; Task 1
does not claim to decode or qualify them.

## Task 2: Independently reviewed actual-source roles

**Files:** Create `market_data/databento_source_facts.py`,
`market_data/options_reference_facts.py`, `docs/options-source-protocols.md`;
modify Task 1 modules and existing session/definition assemblers only where required;
test `tests/unit/market_data/test_databento_source_facts.py` and
`tests/unit/market_data/test_options_reference_facts.py`.

**Interfaces:** Both adapters implement Task 1's signature and `ParsedSourceFacts`.
Native outputs bind source ordinal/native bytes to exact existing canonical projection
hashes. Reference outputs bind preserved provider/exchange source bytes to
`SessionReferenceInput`, `ContractReferenceInput` and current corporate-action facts.
No caller-supplied canonical projection, `verified` flag or document title is proof.

- [ ] Record a role/era matrix in the source-protocol document for calendar,
  bar publication, actions/dividends, definition state, contract terms and quotes.
  For each role record official source URL, capture hash, era, native schema, exact
  field mapping/correction rules, missing evidence and the adapter test. Preserve
  private archives separately. Unknown protocols remain `UNVERIFIED`.
- [ ] Write tests for native/projection substitution, publication after decision,
  partial-chain reset, deletion and same-ID remapping, explicit empty actions, DST,
  early close and unsupported deliverables. Assert no later contract enters an earlier
  chain and wrong-source/unknown-era inputs yield no verified facts.
  Representative assertion: `assert later_contract_id not in earlier_chain.contract_ids`.
- [ ] Run the two new test files; observe failing mapping/causality cases before implementation.
- [ ] Implement only mappings justified by the recorded protocol. OHLCV interval start
  cannot stand in for publication time. If actual publication cannot be bounded,
  leave this role denied; if trade reconstruction is needed, price it under Task 6
  and add a separately reviewed concrete parser mapping before enabling that route.
- [ ] Run both files plus existing source/session/definition/shortlist tests. Verify
  incomplete roles deny independently and exact original shortlist ranking remains unchanged.
- [ ] Commit fixture-tested adapters and sanitized protocol evidence. Install only
  code-reviewed actual rules whose entire role/era contract is supported. Missing
  external evidence blocks rule enablement, not subsequent fixture work.

## Task 3: Bounded native quote archive and schema

**Files:** Create `market_data/databento_quote_models.py`, `databento_quotes.py`,
`databento_quote_store.py`, `databento_quote_wire.py`;
test `tests/unit/market_data/test_databento_quotes.py` and
`tests/integration/market_data/test_databento_quote_store.py`.

**Interfaces:** `NativeQuoteRequest(dataset, schema, stype_in, symbols, start_ns, end_ns)`
binds the exact batch request. `NativeQuoteRow` preserves instrument/publisher IDs,
event/receive nanoseconds, source ordinal, fixed-point bid/ask, sizes, flags and action.
`stage_quotes(source: Path, output_root: Path, *, expected: NativeQuoteRequest,
loaded: LoadedConfig, repository_root: Path) -> Path` returns a manifest path.
`verify_quote_stage(manifest: Path, *, loaded: LoadedConfig, repository_root: Path)
-> VerifiedQuoteStage` returns hash, request, part identities and quality counts,
not economic eligibility. Wire schema: `native-quotes-v1`.

- [x] Write literal fixtures for zero bid, lock, cross, sentinel price, schema mismatch,
  duplicate/conflict, bad timestamp/book flags, truncation, nanosecond ties and reset.
  Assert exact retained integers and rejected counts; never convert prices through float.
  For a zero-bid fixture: `assert row.bid_px == 0` and
  `assert profile.rejected_count == 0` (entry eligibility is tested separately).
- [x] Run the two files and see decoder/storage failures before writing the implementation.
- [x] Implement OPRA consolidated event quote and explicitly identified underlying
  quote schema adapters only; unsupported schemas deny. Reuse native I/O limits,
  private directory/file and atomic publication primitives without changing bar archives.
  Respect the existing 10,000-row/part and other configured caps; split larger acquisitions
  into bounded native datasets instead of increasing limits implicitly.
- [x] Test part replacement, alias/symlink/hardlink rejection, disk-full/interrupt retry,
  idempotent publication, bounded decompression and DuckDB network/extension denial.
- [x] Run both files and native bar/store regressions; commit `feat: preserve native options quote archives`.

## Task 4: Causal initialized quote stream

**Files:** Create `market_data/options_quote_stream.py`;
test `tests/unit/market_data/test_options_quote_stream.py`.

**Interfaces:** `QuoteStreamRequest` binds verified quote manifests, source bundle,
contract/session references and a start/end window. `iter_quote_events(request:
QuoteStreamRequest, *, loaded: LoadedConfig, repository_root: Path)
-> Iterator[OptionsMarketEvent]` rechecks source/part identities before iteration.
`OptionsMarketEvent` carries event/available nanoseconds, source identity, state
(`quote`, `reset`, `gap`, `halt`, `session_boundary`), optional canonical
`OptionsDataRecord`, and quality reasons. Canonical datetime projection uses ceiling,
never truncation that makes data available early; ordering retains native nanoseconds.

- [x] Write `test_reset_does_not_carry_last_quote`, `test_missing_feed_is_not_unchanged_quote`,
  `test_same_timestamp_cannot_fill_earlier`, and `test_mutated_part_invalidates_resume`.
  Assert no executable quote before complete initialization or after an unresolved gap.
  Representative assertion: `assert after_reset.record is None`.
- [x] Run the new test file; confirm the missing stateful stream fails.
- [x] Implement deterministic ordered merge, explicit initialization/reset semantics,
  canonical age/skew checks and original source identities. An exchange-specific
  underlying quote remains labelled exchange-specific. Do not infer NBBO.
- [x] Run stream and Task 3 tests plus `tests/unit/market_data/test_options_records.py`;
  verify future corrections cannot alter earlier visible event decisions.
- [x] Commit `feat: build causal verified options quote streams`.

Task 4 checkpoint: `3944ad9`, 198 relevant tests passed. Immutable models are in
`options_quote_stream_models.py`; real native-to-stream integrity regressions are
in `tests/integration/market_data/test_options_quote_stream_native.py`. Initialization
is fixture-protocol-qualified only; native flags do not install actual-source trust.

## Task 5: Frozen study, history counts and complete coverage

**Files:** Create `research/options_study_models.py`, `options_study_wire.py`,
`options_study_registration.py`; modify `research/options_acquisition*.py`,
`config/models.py`, `config/loader.py`, `configs/base.yaml`, `configs/safety-envelope.yaml`;
create `configs/options/study/simulation.yaml` as the explicit offline study profile;
test `tests/unit/research/test_options_study_registration.py` and
`tests/unit/config/test_options_study_config.py`.

**Interfaces:** `OptionsStudySpec` has closed version `options-study-v1`, purpose,
registration time, exact ordered decision sessions, warmup/source hashes, fixed
strategy/shortlist identity, exit policy, config/code/consumer hashes, scenario/cost
hashes, capital tiers, split membership, embargo/outcome horizon, seeds and rejection
criteria. `VerifiedHistoryCoverage` binds actual canonical daily bar/session hashes
and availability/coverage rather than caller-entered counts. `freeze_options_study(
spec: OptionsStudySpec, *, history: VerifiedHistoryCoverage, loaded: LoadedConfig,
output_root: Path, repository_root: Path) -> DataHash` is immutable local publication.
`plan_options_study_coverage(spec, *, shortlists: tuple[VerifiedShortlistResult, ...],
history: VerifiedHistoryCoverage, loaded: LoadedConfig) -> CoverageManifest` uses
versioned v2 coverage requirements; keep v1 qualification denied and readable.

- [x] Write tests for 749 versus 750 distinct observed daily bars, insufficient folds,
  overlapping observation identities, shortened declared history, changed consumer,
  duplicated coverage, holdout mutation and late registration. Assert missing facts
  produce explicit denial, not `requirements_complete` from session counts alone.
  Representative assertion: `assert "research_history_insufficient" in manifest.reasons`.
- [x] Run both new files; observe failure before adding schema/configuration.
- [x] Add `options.research_study` to the existing graph: disabled by default,
  `exit_policy=signal_invalidation_or_prior_session_expiry`,
  `confidence_level_pct=95`, and immutable false execution/promotion flags. Existing
  study resource ceilings come from native/shortlist config; scenario numbers must be
  explicit immutable inputs, with no guessed calibrated defaults. Enforce whole-percent units.
  Enable the new subtree only in the new simulation profile, alongside native intake
  and shortlist; stock/crypto/prediction entries and live remain disabled. Base and
  production profiles keep the new study feature disabled.
- [x] Freeze the data-availability-selected decision range before quote outcomes are
  read. Require five chronological walk-forward tests of at least 50 sessions each,
  followed by a distinct untouched final test of at least the same configured minimum.
  Warmup must satisfy 750 actual prior daily bars and the 3,650-day declared/verified
  history requirement; folds do not substitute for feature warmup. Purge/embargo by
  complete outcome horizon. If availability cannot meet this, issue a non-qualifying pilot.
- [x] Derive both shortlisted candidates' initialization/entry/monitoring/exit/expiry/
  settlement windows plus underlying/references. Preserve gaps and all missing/denied
  sessions. Run registration/config/acquisition/shortlist suites and legacy hash tests.
- [x] Commit `feat: freeze options studies with observed history coverage`.

## Task 6: Credit-bounded narrow pilot and capital evidence

**Files:** Create `docs/options-real-data-acquisition.md`; private receipts and raw
downloads remain outside the repository. No new purchase API/client.

**Interfaces:** Consume Task 5 coverage manifests, actual source role findings,
Task 3 `NativeQuoteRequest`, existing acquired manifests and current portal cost/credit
observations. Produce immutable private receipt identities and `VerifiedQuoteStage`
artifacts. The offline consumer never receives purchase authority.

- [ ] Before spending, verify Tasks 3–5 fixture consumers work and choose an engineering
  pilot by calendar/availability only. Freeze both candidates and complete monitoring/
  exit tails; no selection from observed premium or P&L.
- [ ] Reconcile existing acquired scopes and uncertain/pending jobs. Obtain exact full
  missing-package estimates, fresh applicable credits and no-cash confirmation. Treat
  portal rounding discrepancies conservatively; never count original grant as remaining.
- [ ] Buy/download only if the necessary complete package fits remaining credits, under
  the existing standing grant. Otherwise record `CREDIT_PACKAGE_INFEASIBLE` and stop this
  external slice. No new subscription, agreement, provider switch or cash charge.
- [ ] Run private receipt/hash checks, native import, source and quote verification.
  Missing semantics or bad rows stay explicit. Never repair prices or infer publication.
- [ ] Feed observed pilot premiums/verified fee bounds into existing `long_option_feasibility`
  across all eight tiers. If all full-policy tiers deny, report that before acquiring
  a larger performance dataset. Hypothetical unit-payoff results cannot cure infeasibility.
- [ ] Record only sanitized scope, cost, counts, hashes and disposition in the document;
  commit no raw data, request identifiers, account details or local secret paths.

## Task 7: Complete imported historical episode

Continuation checkpoint (2026-09-30): the public source-reverified single-episode
runner and immutable request/result now exist, together with shared-feature/canonical
entry-budget composition, signal-invalidation/expiry close generation, independent
cash reconciliation, and both active-clock and source-reverified prefix recovery.
Native manufactured fixtures exercise both call and put, mixed-signal denial, the
$100 denial case, exact -$2.00 round-trip cash/$1.00 fees at an explicitly hypothetical
$10,000 tier, rejected/unfilled/ambiguous orders and incomplete settlement. The
unchanged $15 order cap still prevents the $25-premium example from being a policy
acceptance case. Current source files are `options_historical.py`,
`options_historical_policy.py` and `options_historical_restart.py`; no actual-source
rule, broker write or production capability was enabled. Public replay rejects a
stream exceeding the frozen outcome horizon. Private checkpoint bounds remain intact.
Independent review found and verified fixes for completed-checkpoint recovery,
result/checkpoint resource-limit coupling and the missing frozen-horizon check.
Final current-tree verification is recorded in `docs/options-real-data-validation.md`.
Task 8 full-policy continuity, genuine costs/uncertainty and actual-source qualification
remain incomplete; these episode tests do not accept those milestones.

Execution checkpoint (2026-09-29): **in progress**, not accepted. The immutable
order helper and independent journal are joined by an internal
`simulation/options_historical_clock.py` composition, tested in
`tests/unit/simulation/test_options_historical_clock.py`. It adds chronological
cancel/expiry/settlement timers, atomic event application, shared observation
liquidity and independently reconciled execution cash/fees. Expiry assessments
identify required exits and preserve missed-deadline incidents; closing strategy
intents are not yet generated. The public historical request/runner, fresh source
preimage composition and full-policy decision owner remain unimplemented. Task 8's
continuous path and active-order cursor/restart contract remain incomplete.
The $25-premium example below is accounting-only: the unchanged $15 order cap
denies it even at $10,000. Use an admissible smaller-premium case for the complete
policy-positive acceptance test; do not relax the cap to satisfy that example.

**Files:** Create `simulation/options_historical_models.py`,
`simulation/options_historical.py`, `simulation/options_historical_execution.py`;
test `tests/integration/simulation/test_options_historical_episode.py` and
`tests/unit/simulation/test_options_historical_execution.py`.

**Interfaces:** `HistoricalOptionsRequest` binds `OptionsStudySpec`, one session's
verified shortlist/history, a `QuoteStreamRequest`, fee/scenario identities and
`OptionsAccountPathState` (Task 8; begin with the same immutable initial-state contract).
`HistoricalOptionsResult` contains status, causal decisions/intents, transitions,
Decimal cash journal, positions/reservations/unsettled obligations and reason codes.
Its exact summary fields include `net_cash_flow: Decimal` and `fees: Decimal`.
`run_historical_options_episode(request: HistoricalOptionsRequest, *,
loaded: LoadedConfig, repository_root: Path) -> HistoricalOptionsResult` processes
stream events and canonical transitions; it has no broker/transport argument.
`StudyScenario` contains explicit latency, reject/no-fill, participation, slippage,
cancel-race and fee-bound inputs with calibration references; define it in
`options_study_models.py`. Unknown calibration cannot qualify a result.

- [ ] Write a hand-accounted fixture: 100-multiplier contract, buy at 0.25 plus 0.50
  fee, sell at 0.20 minus 0.50 fee gives cash flows -25.50/+19.50 and episode loss 6.00.
  Use the explicitly hypothetical $10,000 tier; the $100 case must deny.
  Assert entry/exit/settlement occur only at their later eligible events.
  Representative assertions: `assert result.net_cash_flow == Decimal("-6.00")` and
  `assert result.fees == Decimal("1.00")`.
- [ ] Run both new files; see missing lifecycle behavior fail before implementation.
- [ ] Implement with existing momentum/features, quote validation, feasibility,
  order transitions, trial economics and expiry helper. Never change the synthetic
  request guard. If extracting a pure shared helper, capture old serialized/output
  regression hashes before changing either consumer.
- [ ] Implement the approved signal-invalidation/preceding-session expiry exits:
  initiate expiry close at the preceding eligible session's open, latest deadline its
  close or earlier stricter rule. LIMIT/GFD only; ask entry/bid close limits, verified
  ticks, canonical latency and later eligible events, quantity/consumed-liquidity caps.
- [ ] Test rejection, no fill, one-contract integer fills, cancellation race, unknown
  outcome, zero bid, fee bounds, delayed settlement, missed expiry and no forced end
  fill. Multi-unit partial-fill fixtures must not relax one-unit study limits.
- [ ] Run both files plus legacy options replay/expiry/economics suites; commit
  `feat: simulate verified historical options episodes`.

## Task 8: Continuous full-policy account paths and independent journal

**2026-09-30 checkpoint:** exact-time loss observations, journal-bound risk latches,
mark/flow checkpoint replay and independent review are implemented in the
[account-risk foundation](../../options-account-risk-checkpoint.md). This does not
complete this task: the source-bound shared-clock strategy coordinator and its
overlapping-window/session-close integration remain required. The dated
[source audit](../../options-actual-source-readiness-2026-09-30.md) and
[broker audit](../../options-broker-runtime-readiness-2026-09-30.md) retain independent
NO-GO boundaries; successful read-only diagnostics do not grant live capability.

**Files:** Create `research/options_account_paths.py`,
`research/options_account_journal.py`; test
`tests/integration/research/test_options_account_paths.py` and
`tests/unit/research/test_options_account_journal.py`.

**Interfaces:** Define `OptionsAccountPathState` in `options_historical_models.py`:
path/study/tier/scenario identities, authorized capital, cash, marked equity,
positions, reservations, unsettled obligations, `TrialLossState`, session entry
counts, latched halts and last event identity. `run_options_account_path(spec:
OptionsStudySpec, episodes: tuple[HistoricalOptionsRequest, ...], *,
loaded: LoadedConfig, repository_root: Path) -> OptionsAccountPathResult` carries
one state through chronological episodes. `reconcile_research_journal(result:
OptionsAccountPathResult) -> tuple[str, ...]` independently reconstructs exact cash,
fees, quantities, reservations and obligations, returning discrepancies.
Define `OptionsAccountPathResult` beside the path runner: bound study/tier/scenario,
ordered episode results, final state, independent journal, daily equity/cash series,
opportunity counts, incidents and incomplete-outcome reasons.

- [ ] Write tests: loss 6 followed by profit 10 leaves consumed trial loss 6; repeated
  event changes no totals; fold/day/restart does not clear a weekly/drawdown latch or
  reservation; a deposit does not replenish trial capacity. Assert raw journal sums
  against hand-derived amounts, not the simulator's aggregation helper.
  Representative assertion: `assert result.final_state.trial.consumed_loss == Decimal("6.00")`.
- [ ] Run both files; confirm missing account continuity fails.
- [ ] Implement one ongoing state per tier/scenario, canonical risk/expiry decisions
  and conservative liquidation marks. Separate full-policy account paths from labelled
  hypothetical unit-payoff observations; all-policy denials remain in opportunity counts.
  Authorized risk capital stays separate from marked equity: gains cannot silently
  increase the sizing base, and losses cannot be hidden by retaining a higher base.
- [ ] Test unknown ownership, unmatched leg, unexpected shares, negative cash, assignment,
  broker-style closeout and unresolved settlement as incidents/incomplete outcomes.
  No exercise or stock-remediation instruction is synthesized. Resume only from exact
  bound event prefix; no production ledger schema or state mutation.
- [ ] Run account tests and relevant trial/risk/lifecycle/reconciliation suites; commit
  `feat: reconcile continuous historical options account paths`.

## Task 9: Effective-date costs and truthful benchmarks

**Files:** Create `research/options_study_costs.py`;
test `tests/unit/research/test_options_study_costs.py`.

**Interfaces:** `StudyCostSchedule` binds effective intervals, official fee-source
hashes, side/contract fees, operating costs, subsidy/replacement costs and dated cash
yield inputs. `cost_options_path(result: OptionsAccountPathResult, schedule:
StudyCostSchedule) -> OptionsCostReport` emits trading P&L, actual-cash operating
profit, replacement-cost operating profit and cash-baseline excess independently.

- [ ] Write exact round-trip fee and schedule-boundary tests. An already embedded
  spread/slippage cost must not be deducted twice. For a 6.00 trading loss and 2.00
  allocated hosting cost, assert operating loss 8.00, not another spread adjustment.
  Representative assertion: `assert report.actual_cash_operating_profit == Decimal("-8.00")`.
- [ ] Run the new file; observe failures before implementing the cost adapter.
- [ ] Implement event-date fee application, transparent deterministic operating-cost
  allocation by actual study time, credit subsidy disclosure and source-qualified cash
  comparison. Unknown fees or benchmark inputs deny the affected economic conclusion.
- [ ] Add tests where grant-funded data has zero current cash outlay but positive
  replacement cost; zero-yield reference cannot masquerade as a sourced acceptance
  baseline. Run cost and existing metrics tests; commit `feat: attribute options study costs once`.

## Task 10: Purged evaluation and dependent-outcome uncertainty

**Files:** Create `research/options_study_validation.py`,
`research/options_block_resampling.py`; test
`tests/unit/research/test_options_study_validation.py`,
`tests/unit/research/test_options_block_resampling.py` and
`tests/integration/research/test_options_holdout_isolation.py`.

**Interfaces:** `evaluate_options_study(spec: OptionsStudySpec, paths:
tuple[OptionsAccountPathResult, ...], costs: tuple[OptionsCostReport, ...], *,
loaded: LoadedConfig) -> OptionsStudyAssessment` enforces all canonical acceptance
criteria without projecting options data into a misleading legacy bar-only report.
`resample_options_blocks(paths: tuple[OptionsAccountPathResult, ...], *,
block_sessions: int, iterations: int, seed: int, confidence_level_pct: Decimal)
-> OptionsUncertainty` emits interval/loss/tail estimates or explicit unavailability.
All these named records are defined in their owning module and carry input identities.
`OptionsStudyAssessment.economic_verdict` is an explicit GO/NO-GO value independent
of immutable false production/promotion/live fields; `OptionsUncertainty` contains
the confidence level, lower expectancy bound and effective unit count or missing reasons.

- [ ] Write tests: paired call/put/scenario rows do not multiply independent count;
  overlapping held exposures remain grouped; fewer than 30 independent units denies;
  future holdout mutation cannot change training outputs or study identity.
  Representative assertion: `assert assessment.economic_verdict == "ECONOMIC_NO_GO"`
  when only 29 independent opportunities remain after grouping.
- [ ] Run all three files and observe failures before implementing the evaluator.
- [ ] Adapt existing purged split/metric primitives to whole session/account paths.
  Use seeded contiguous non-circular blocks; block horizon covers the preregistered
  maximum holding plus settlement horizon and existing embargo. Preserve no-trade/
  halted periods. Unbounded unsettled outcomes remain censored and cannot qualify.
  Iterations/seed use canonical research settings; sensitivity lengths are frozen
  before outcomes and never shorter than the necessary dependence horizon.
- [ ] Require one-sided 95% conservative lower expectancy bound >0, sample adequacy,
  benchmark excess, drawdown/tail criteria, required positive folds, concentration,
  neighbor/ablation stability, calibrated assumptions and edge-persistence rationale.
  Keep all attempts/amendments; absent PBO/multiplicity evidence remains a blocker,
  not an invented number for a single hypothesis. Do not enable promotion flags.
  Reuse economic criteria, not the legacy report's requirement to enable promotion:
  economic and promotion verdicts stay independent. Validate calibration from bound
  evidence, not a caller's `assumptions_validated=true` assertion.
- [ ] Test deterministic seeds, confidence quantile boundaries, all-zero/negative paths,
  missing calibration, infinite/unavailable metrics and untouched final-test isolation.
  Run all new files and existing validation/metrics tests; commit
  `feat: evaluate dependent historical options outcomes conservatively`.

## Task 11: Private reports and offline operator commands

**Files:** Create `research/options_study_report.py`, `research/options_study_io.py`,
`cli/options_study.py`, `docs/options-real-data-research.md`;
modify `cli/options_research.py`; test
`tests/integration/cli/test_options_study.py` and
`tests/unit/research/test_options_study_report.py`.

**Interfaces:** `OptionsStudyReport` binds registration/source/coverage/code/config
hashes, causal decisions, account journals, costs, splits/seeds, explicit coverage
counts and separate technical/source/economic/capability/authorization verdicts.
`write_options_study_report(report: OptionsStudyReport, output_root: Path, *,
loaded: LoadedConfig, repository_root: Path) -> DataHash` uses private atomic publication.
Wire schema: `options-study-report-v1`. Existing reports remain readable unchanged.

- [ ] Write CLI tests for closed fields, replaced private inputs, public output path,
  credential-bearing environment, network/write import denial and disk-full publication.
  Console output must contain only status/counts/reason codes/hashes, never raw rows/paths.
  Representative assertion: `assert payload["live_authorized"] is False`.
- [ ] Run both files; verify new commands fail before registration.
- [ ] Register `native-quotes-import`, `native-quotes-verify`, `options-study-freeze`,
  `options-study-backtest`, `options-study-walk-forward`, `options-study-cost-stress`
  and `options-study-capital-feasibility` under the existing options CLI. All consume
  explicit local input paths and `--output-root`; import additionally takes exact
  request identity. Reuse the existing `load_config` graph with base YAML, the new
  `options/study/simulation.yaml` profile, safety envelope and an empty environment.
  No command accepts a credential, live flag or purchase option.
- [ ] Use exit 1 for malformed/storage failure, exit 2 for truthful blocked/incomplete
  outcome, exit 0 for completed diagnostic output; a zero exit is not economic GO.
  Preserve `BLOCKED_INPUTS`, `INCOMPLETE_SIMULATION`, completed-model status, and
  immutable false production/promotion/download/live authority on every output.
- [ ] Render per-tier full-policy versus hypothetical results, uncertainty limitations,
  incomplete episodes and data/operating costs. Run CLI/report/architecture/no-network
  suites; commit `feat: expose private real-data options research reports`.

## Task 12: Adversarial verification and genuine-evidence handoff

**Files:** Create `tests/integration/research/test_options_real_data_pipeline.py`,
`tests/chaos/research/test_options_study_failures.py`,
`docs/options-real-data-validation.md`; modify `.github/workflows/options-research.yml`
to include mandatory new fixture suites and `scripts/check_critical_branch_coverage.py`
to include the new historical execution/account-journal critical modules.

**Interfaces:** Use the frozen prior-task APIs only. No new research/trading policy.

- [ ] Add end-to-end fabricated fixtures for successful accounting, economic rejection,
  missing roles, zero contracts, boundary quotes, cancellation/settlement failures,
  tampered manifest, interrupted report write and deterministic prefix restart.
  Assert all synthetic runs remain economically ineligible, even with positive P&L.
  Representative assertion: `assert report.economic_verdict == "ECONOMIC_NO_GO"`.
- [ ] Run new tests RED, implement only necessary integration repairs, then run narrow
  tests GREEN. Obtain an independent secret-free whole-branch review; the coordinator
  evaluates and fixes findings before release. Never send licensed rows to reviewers.
- [ ] Run full verification from a scoped exact committed tree:
  `uv run --frozen --no-sync ruff check .`; `uv run --frozen --no-sync mypy src`;
  `PYTHONPATH=src uv run --frozen --no-sync pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80 --cov-report=json:/tmp/options-study-coverage.json`;
  `uv run --frozen --no-sync python scripts/check_critical_branch_coverage.py --report /tmp/options-study-coverage.json`;
  `uv run --frozen --no-sync bandit -c pyproject.toml -r src`; both main/research
  `uv lock --check`; authorized locked-dependency audit and existing SBOM/manifest
  tests. Run the complete locked research CI list, including every new native test.
  Expect 80% overall and 90% critical branch floors; disclose missing-system-tool skips.
- [ ] If Task 6 prerequisites cleared, run the fixed private pilot and independently
  verify its cash journal. Freeze/price the complete qualifying study only after that
  consumer and full-policy feasibility work. Use remaining credits only for a necessary
  complete package. Run the locked study without adapting the holdout to outcomes.
- [ ] Publish an evidence-backed validation report: software pass/fail, actual source
  coverage, economic result or exact external blocker, tests/skips, resource measurements,
  assumptions and limitations. Live/account/runtime verdicts remain independently blocked.
  Refresh the authoritative transition report with only owned hunks.
- [ ] Commit sanitized outputs, push, inspect exact-head CI/review, and merge in-scope
  work using the standing grant. Do not deploy, buy a connectivity trade, migrate
  production state, or mark future economic evidence complete because fixtures pass.

## Plan self-review and execution handoff

Spec sections 1–4 map to Tasks 1–2; sections 5–6 to Tasks 3–6; sections 7–8 to
Tasks 7–8; section 9 to Tasks 9–10; sections 10–11 to Tasks 11–12. All five review-focus
conditions have explicit owning tests. Existing stricter risk/acceptance conditions
are retained. Source evidence and qualifying-data cost remain external prerequisites;
the plan does not invent usable source protocols, a sufficient credit balance or returns.

Recommended execution: **native**, preserving the operator's prior selection and the
single-owner protected-component boundary. Independent fixture/documentation reviews
may run in parallel only after their exact interfaces and owned paths are committed.
The operator approved this plan on 2026-09-29. Standing merge and credit-only
purchase grants do not need to be requested again within their recorded bounds.
