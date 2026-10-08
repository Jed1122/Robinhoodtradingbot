# Monthly SPY/cash SMA10 Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one separately versioned, permanently non-promotable monthly SPY/cash research path with shared accounting, deterministic resumption and after-cost DEVELOPMENT reports.

**Architecture:** Keep old 20/100 contracts and preimages unchanged. Select the new offline profile through the existing canonical research-candidate field; add immutable monthly contracts and reuse narrowly extracted lifecycle/economic primitives. Monthly after-close decisions are separate from the old pre-open/five-session scheduler, and no strategy receives transport or credentials.

**Tech Stack:** Existing Python 3.12–3.14, frozen dataclasses, Pydantic, Decimal, Typer, pytest/coverage and immutable owner-private JSON publication. No new dependency, database migration or provider.

**Spec:** [Approved research design](../specs/2026-10-08-etf-monthly-trend-hypothesis-design.md).

**Status:** Prepared for operator review; no implementation or market-outcome run completed. Preserve the already supplied native execution method. Starting committed base: `000e2519b3d60c896cefef932f29a90db8649126`; this plan and approval checkpoint are subsequent human-document changes only.

## Global Constraints

- Policy ID `spy-cash-monthly-sma10-protected-development-v1`; design ID `spy-cash-monthly-sma10-protected-design-v1`. Never reuse an old schema ID for monthly outcomes.
- One unleveraged SPY position or cash; no additions, shorting, options, other assets or parameter search. Equality with SMA10 is cash.
- Exactly ten consecutive completed month-end raw closes, including the decision month. Anchor October 31, 2016, selected by dates alone; validate it as the exact eligible October month-end.
- Adaptive development price window `[2016-01-01, 2024-01-01)`; evaluation starts at the first eligible session after the anchor. Final 2024–2025 outcomes excluded. Prior/external holdout exposure remains unknown, not silently false.
- Latest 100 completed daily bars through the monthly decision for existing ATR convention; stop multiplier 2.0, target 2.0, maximum hold 100 sessions, regime/unselected exits enabled. Entry counts as session one; hold-limit close schedules the next eligible open.
- Next-session adverse opening execution; worse opening stop gaps; favorable target gaps use target; stop first when range is ambiguous. No forced terminal sale or fabricated fill/liquidity/latency.
- $100 risk reference, $0.50 stop-plus-bounded-fee budget, $15/$5 base/micro order and $60/$20 gross caps, 80% cash, $50 non-replenishing trial loss, $1,000 ceiling and all stricter controls stay. Hypothetical $500/$1,000 balances do not enlarge authority.
- Fractional .001 quantity/.000001 price/$1 minimum and T+2 are research assumptions, not verified broker terms. Native whole-share infeasibility remains separately visible.
- Raw/no-splits and calendar-close availability are assumptions. Issuer dividend entitlement/payment enters cash exactly once; missing facts remain unknown/incomplete.
- Keep all 24 scenarios: capital $500/$1,000 × costs 0bps/$0, 5bps/$0.01, 25bps/$0.01 per side/order × monthly data/compute $0/$0, $0/$12, $99/$0, $99/$12. Nonzero-fee episode reserve $0.10.
- Prior-NAV performance returns; nonpositive prior NAV means undefined. Paired fixed-capital P&L uses 20/100-session blocks, 1,000 draws, 95% bounds, seed 20260710. Do not treat proxies/draws as independent evidence.
- Missing/incomplete -> INSUFFICIENT_EVIDENCE; otherwise nonpositive operating profit or risk-reference drawdown >10% -> REJECT; otherwise <30 completed episode proxies, missing uncertainty or either lower bound <=0 -> INSUFFICIENT_EVIDENCE; otherwise PROCEED_TO_FURTHER_RESEARCH only.
- Execution expansion needs a surviving 25bps/$0.01 case AND independently supported operating route recorded before outcomes. No verified route is supplied by this plan: record support as unknown, never let a caller boolean establish it.
- Source/cost qualification, execution, economic admission, promotion and live authorization remain false. Existing quotas/diagnostics and paused defaults remain intact.
- Main owns critical strategy/risk/execution/accounting/reconciliation/release integration and private inputs. Delegate only public-code/fabricated-fixture audits on exact commits with disjoint ownership.
- No private input inspection, credentials, broker/provider calls, acquisitions, billing changes, trades, deployment, risk increase or old-study rerun during implementation. One main-only development study is conditional on the completed reviewed executable freeze and plan authority; no holdout evaluation is included.

## Review Focus

1. Terminal month, pending entry/close and post-window dividend/settlement: preserve incomplete obligations without consuming a holdout price or dropping an intent (Tasks 2/3/5).
2. Old hashes, exact types and literal policy rules: new config selection must not change old canonical schemas/defaults, decoder expectations or old results (Tasks 1/3/4).
3. After-close causality and exit overlap: month-end close may inform only later orders; protection, hold-limit and monthly exit cannot sell twice (Tasks 2/3).
4. Missing/forged monthly input or checkpoint: reject altered identities, shortened/shifted windows, mutations and invalid history; never restore empty cash or skip missing sessions (Tasks 2/3/5).
5. Favorable cost selection and undefined metrics: all cases remain visible, unsupported free budgets never authorize expansion, incomplete cases cannot pass and invalid NAV is not zero (Task 4).

## File Map and Critical Path

`Task 1 policy/config identity -> Task 2 causal intake/signal -> Task 3 lifecycle/resumption -> Task 4 economics -> Task 5 private CLI -> Task 6 integrated release/freeze`.

Reuse the linked `etf-lean-plan` worktree and preserve unrelated state; verify actual HEAD/branch before execution. Do not resume completed PR17/22/23/24 or the paused integration automation.

- Configuration: `src/trading_bot/config/models.py` and `loader.py`, new `configs/etf/monthly/simulation.yaml`; existing fields only. `hashing.py` remains unchanged.
- Study/canonical binding: new `research/etf_monthly_study.py`; one canonical decoder seam in `config/loader.py`, with old `simulation/etf_history.py` delegation retaining exact key/type checks. `EquityComparisonRequest` explicitly rejects the new ID rather than silently creating an empty legacy candidate grid.
- Inputs/signal: new `research/etf_monthly_protocol.py`, `etf_monthly_intake.py`, `strategies/etf_monthly_trend.py`; small shared validation/projection extraction from `research/etf_daily_intake.py` and `etf_latest_vintage.py` to `etf_exploratory_intake.py`.
- Lifecycle: new `simulation/etf_exploratory_lifecycle.py`, `etf_monthly_account.py`, `etf_monthly_screen.py`; narrow extraction from `etf_daily_screen.py`/`etf_account.py`. Legacy public APIs stay exact-old-type-only.
- Economics: new `research/etf_exploratory_economics.py`, `etf_monthly_economics.py`; old `etf_daily_economics.py` delegates arithmetic but retains its original types/preimages.
- CLI: new `cli/etf_monthly_research.py` reuses existing readers, code identity and private publisher; no commands added to live runtime.
- Tests: new config/monthly research/strategy/simulation/CLI fixtures and tests listed below; retain all legacy tests and add literal synthetic compatibility hashes.
- Operations: new `docs/etf-monthly-development-screen.md`, updated authoritative transition report and critical-coverage module list. No deployment manifest behavior changes.

No nullable/default config extension: `hash_loaded_config` serializes all fields, `_restore_value` requires exact nested keys and every graph field is required. Instead extend the existing candidate allowlist with the exact monthly policy ID and select it in a named overlay. Its fixed parameters live in the immutable policy, bound to the canonical candidate selection and code hash; this is not a second loader.

### Task 1: Canonical Monthly Selection and Immutable Study Identity

**Files:** Modify `src/trading_bot/config/models.py` (candidate allowlist and root offline guard), `config/loader.py` (canonical reconstruction), `simulation/etf_history.py` (decoder delegation only), `research/equity_comparison.py` (monthly-ID rejection in `EquityComparisonRequest.__post_init__` only). Create `configs/etf/monthly/simulation.yaml`, `research/etf_monthly_study.py`, `tests/unit/config/test_etf_monthly_config.py`, `tests/unit/research/test_etf_monthly_study.py`, `tests/fixtures/etf/monthly/legacy-hashes.json`. Extend legacy study/config/comparison tests without weakening assertions.

**Interfaces:**

- `restore_loaded_config(canonical_json: bytes, expected_hash: ConfigHash) -> LoadedConfig` in `config/loader.py`: strict existing AppConfig/SafetyEnvelope graph, Decimal restoration, exact key sets, envelope enforcement and rehash; bounded to 1 MiB.
- `EtfMonthlyStudy`: frozen/slotted canonical_config/config_hash, code_hash/source_plan_hash/cost_plan_hash/operating_basis_hash, seed/risk_equity_reference, `holdout_exposure` (`unknown`, `examined`, `operator-disclosed-unexamined`). Fixed `source_requested_start/end` 2016-01-01..2026-01-01 UTC; `requested_start/end` for economic events 2016-01-01..2024-01-01 UTC; `holdout_start/end` 2024-01-01..2026-01-01 UTC; capital_tiers $500/$1,000; `development_previously_examined=True`; all six readiness flags false.
- `freeze_etf_monthly_study(loaded: LoadedConfig, *, code_hash: str, source_plan_hash: str, cost_plan_hash: str, operating_basis_hash: str, holdout_exposure: str) -> EtfMonthlyStudy` and `monthly_policy(study: EtfMonthlyStudy) -> LoadedConfig`. `study_hash` schema `etf-monthly-study-v1`.
- Monthly profile selects singleton `research_candidate_strategy_ids=[spy-cash-monthly-sma10-protected-development-v1]` and `research_universe_symbols=[SPY]`, disables old `etf_pilot`, crypto/prediction/options, uses SIMULATION/start_paused/live_false and existing protection/risk values. Retain the existing account owner's stricter one-position/80%-cash/trial checks from canonical fields; do not add a second sizing calculator. Mode/environment overrides cannot enable this selection in paper/shadow/live or combine it with old candidates. Legacy `EquityComparisonRequest` denies the monthly ID before comparison.

- [ ] **Step 1 — Pin old public synthetic preimages and write RED tests.** Before source edits, compute current canonical/config/study/daily protocol/request/result/economic hashes using existing fabricated fixtures with fixed synthetic code/source/cost hashes, not dynamic current-code hashing; print them, then retain literal expected values through `apply_patch`. Add `test_monthly_profile_uses_existing_graph_and_preserves_legacy_hashes`, `test_monthly_selection_denies_nonoffline_or_mixed_candidates`, `test_monthly_study_cannot_be_passed_as_legacy_study`, `test_monthly_profile_cannot_feed_legacy_equity_comparison`, `test_monthly_graph_seed_risk_and_flags_cannot_be_forged`. Assert old `windows==(20,100)` and cadence 5; monthly risk reference Decimal("100"), dates/flags above, wrong SHA/preimage/reconstituted config denied.

```python
assert old_study.windows == (20, 100) and old_study.rebalance_sessions == 5
assert monthly_study.risk_equity_reference == Decimal("100")
assert monthly_study.development_previously_examined is True
assert monthly_study.execution_enabled is False
with pytest.raises(ValueError):
    _policy(monthly_study)  # Existing strict legacy study reconstruction.
```

- [ ] **Step 2 — Observe RED.** Run `uv run pytest tests/unit/config/test_etf_monthly_config.py tests/unit/research/test_etf_monthly_study.py -q`; missing monthly API/profile must fail, not an unrelated harness error. Existing captured compatibility assertions must pass before extraction.
- [ ] **Step 3 — Implement the named profile and validated study.** Add only the candidate ID/root offline validation to existing graph and the explicit legacy comparison rejection. Use the existing `load_config`/envelope; overlay may tighten but never relax risk. Factor the strict canonical decoder; old `_restore_value`/`_policy` remain compatible and still require exact EtfStudy. No default field or serialization omission. Validate same 2.0/2.0/100 exit settings, fixed seed, inventory/evaluation dates and all false flags on reconstruction, including forged model/dataclass copies.
- [ ] **Step 4 — Verify GREEN and compatibility.** Run the two new files plus `tests/unit/config tests/property/config tests/unit/research/test_etf_study.py tests/unit/research/test_etf_daily_protocol.py tests/unit/research/test_etf_daily_protocol_adversarial.py tests/unit/research/test_equity_comparison.py`. Require original golden hashes/required-field/null/unknown-key checks unchanged.
- [ ] **Step 5 — Commit only this task's files.** `git commit -m "feat: add versioned offline monthly ETF study contract"`; record exact task head and passing commands.

### Task 2: Bounded Month-End Intake and Pure Signal

**Files:** Create `research/etf_monthly_protocol.py`, `etf_monthly_intake.py`, `etf_exploratory_intake.py`, `strategies/etf_monthly_trend.py`, `tests/unit/research/test_etf_monthly_protocol.py`, `test_etf_monthly_intake.py`, `tests/unit/strategies/test_etf_monthly_trend.py`, `tests/fixtures/etf/monthly/` fabricated calendar/price fixtures. Modify `research/etf_daily_intake.py`/`etf_latest_vintage.py` only to reuse verified validation/projection primitives while preserving old preimages.

**Interfaces:**

- Reuse `EtfDailyBar` as a policy-neutral raw/feature daily observation, `EtfBenchmarkDistribution`, archive/calendar/issuer readers and unchanged `FeaturePipeline` ATR; never reuse old daily request/protocol.
- `EtfMonthlyError(ValueError)` emits only `etf_monthly_invalid`; `_MonthlyRecord` validates source_qualified/cost_qualified/execution_enabled/economic_admitted/evidence_promotable/live_authorized are literally false even after nested mutation. Wrong concrete record types deny.
- `EtfMonthlyProtocol(study, sessions, calendar_hash, source_hash, distribution_hash, per_side_cost_bps, side_fee, episode_fee_bound, price_basis)` with literal monthly ID, ten months, anchor 2016-10-31, ATR100/T+2/fractional terms and all false markers. At most 10,000 pre-2024 sessions/bars and 96 monthly observations, no caller cadence/window override.
- `EtfMonthlyRequest(protocol, bars, distributions, initial_cash)`; `EtfMonthObservation(month: date, session_date: date, ends_at: datetime, close: Decimal, source_hash: str)` uses month's first date as month identity; `EtfMonthlySignal(decision_at, month_ends, average_close, latest_close, regime, source_hashes, signal_hash)`. Regime literal `LONG_ELIGIBLE` or `CASH`.
- `select_etf_month_ends(sessions: tuple[date, ...]) -> tuple[date, ...]`; `compute_etf_monthly_signal(observations: tuple[EtfMonthObservation, ...], *, decision_at: datetime) -> EtfMonthlySignal` requires exactly ten consecutive completed months. Missing data raises the sanitized monthly error; the scheduler records unknown/incomplete, not a cash signal.
- `etf_monthly_source_plan_hash(archive, calendar, issuer) -> str`, `make_etf_monthly_request(study, archive, calendar, issuer) -> EtfMonthlyRequest`. Schema `etf-monthly-development-intake-v1`; protocol/request schemas `spy-cash-monthly-sma10-protected-development-v1` / `etf-monthly-request-v1`.
- `validate_etf_exploratory_archive(archive: EtfNativeBarsArchive, *, start: datetime, end: datetime) -> None` factors current latest-vintage record/count/positive-price/exact-local-midnight/UTC-window checks. `project_etf_exploratory_inputs(archive, calendar, issuer) -> tuple[tuple[date, ...], tuple[EtfDailyBar, ...], tuple[EtfBenchmarkDistribution, ...]]` factors current full-calendar/quarter checks and bounded pre-2024 raw projection. These are validated arithmetic/projection seams, not a new qualification loader.

- [ ] **Step 1 — Write independent RED fixtures.** `test_sma10_equality_is_cash` asserts closes ten × Decimal("100") -> SMA Decimal("100"), CASH; `test_sma10_ten_consecutive_closes` asserts closes 1..10 -> Decimal("5.5"), LONG_ELIGIBLE. Test missing exact month-end (no substitute), duplicate/reordered month, missing tenth month, future-close/as-of rejection, anchor mismatch, first evaluation after anchor, DST/holiday/leap/early-close and exact last-100 ATR slice. `test_monthly_projection_excludes_holdout_and_preserves_full_source_identity` changes only fabricated 2024 prices: source identity differs, pre-2024 projection unchanged, monthly evaluation cannot see them. Test incomplete full inventory denial and Dec2023 pending-next-date metadata without 2024 prices.

```python
signal = compute_etf_monthly_signal(equal_months, decision_at=after_close)
assert signal.average_close == Decimal("100") and signal.regime == "CASH"
signal = compute_etf_monthly_signal(closes_one_to_ten, decision_at=after_close)
assert signal.average_close == Decimal("5.5") and signal.regime == "LONG_ELIGIBLE"
with pytest.raises(EtfMonthlyError):
    compute_etf_monthly_signal(equal_months[:-1], decision_at=after_close)
```

- [ ] **Step 2 — Observe RED.** Run the three new unit files; require failures for absent monthly behavior. Retain old intake tests as controls.
- [ ] **Step 3 — Implement causal aggregation and bounded projection.** Use explicit calendar dates/times, not last available bar or weekday inference. Reuse current full-source hash/date/quarter checks, raw projection and 40-quarter inventory validation through the extracted helper; no old EtfStudy constructed to label a monthly run. Monthly request contains pre-2024 prices/sessions and ex-date distributions only; later payment dates stay obligations. Native factories still deny incomplete inventory; missing-observation fixtures remain incomplete downstream. Decisions are at calendar close + one microsecond, using data ended at/before close. Retain raw price/corporate-action/availability limitations and monthly attempt/adaptive labels.
- [ ] **Step 4 — Verify GREEN/old identity.** Run new files plus `tests/unit/research/test_etf_daily_intake.py tests/unit/research/test_etf_latest_vintage.py tests/unit/strategies/test_features.py tests/property/strategies/test_feature_determinism.py`; compare saved old source/protocol hashes.
- [ ] **Step 5 — Commit task files.** `git commit -m "feat: add causal bounded monthly ETF signal intake"`.

### Task 3: Shared Lifecycle, Monthly Scheduling and Pure Resumption

**Files:** Create `simulation/etf_exploratory_lifecycle.py`, `etf_monthly_account.py`, `etf_monthly_screen.py`, `tests/unit/simulation/test_etf_monthly_account.py`, `test_etf_monthly_screen.py`, `test_etf_monthly_resume.py`; modify `simulation/etf_account.py` and `etf_daily_screen.py` only for reviewed shared primitives. Add explicit discovery for `simulation/etf_exploratory_lifecycle.py`, `simulation/etf_monthly_*.py`, `research/etf_monthly_*.py`, `research/etf_exploratory_economics.py`, `strategies/etf_monthly_trend.py` to `scripts/check_critical_branch_coverage.py` without removing existing gates.

**Interfaces:**

- `EtfMonthlyAccountRequest(study: EtfMonthlyStudy, initial_cash: Decimal, events: tuple[EtfAccountEvent, ...])` with run schema `etf-monthly-account-run-v1`; reuses immutable account-event/order/result types. Public old request/replay/stepper/admission remain exact-old-type-only.
- `EtfMonthlyAccountStepper(request)`, `replay_etf_monthly_account(request) -> EtfAccountResult`, `admit_etf_monthly_pending_intent(request, candidate: EtfAccountEvent) -> EtfPendingAdmission`. Share one existing `_steps` economic reducer; exact old/monthly study dispatch validates each canonical policy, not caller callbacks or arbitrary LoadedConfig.
- `EtfExploratoryLifecycle(request: EtfDailyRequest | EtfMonthlyRequest)` validates exact approved request type and derives its canonical account wrapper. Factor its `price`, instrument, pending-intent execution, protection, settlement/dividend and point projection methods once. Keep old scheduler/order/time/hash labels unchanged through the legacy adapter; monthly uses its own intent/decision labels. No generic strategy plug-in, transport, risk bypass or duplicate reducer.
- `EtfMonthlyDecision`, `EtfMonthlyAttempt`, `EtfMonthlyExit`, `EtfMonthlyPoint` remain typed monthly records. `EtfMonthlyResult(request, decisions, attempts, exits, points, events, account, incomplete_reasons, checkpoint)` has schema `etf-monthly-result-v1`; distinguish scheduled intent from account admission/reservation, and unattempted terminal intent from an executed order. Owner publishes the checked checkpoint with each prefix result; it is not guessed later from final cash.
- `EtfMonthlyCheckpoint` binds full request/protocol/config/code identity, consumed source prefix, next session index, ten-month window, last100 daily rows, last decision, pending intent, original stop/target/entry index, obligations/entitlements, account event tape and retained result prefix. Limits: input <=10,000, event tape <=10,000, monthly window <=10. No mutable aliases or invented clocks.
- `run_etf_monthly_screen(request: EtfMonthlyRequest, *, through_session: date | None = None) -> EtfMonthlyResult`; `checkpoint_etf_monthly_screen(result: EtfMonthlyResult) -> EtfMonthlyCheckpoint`; `resume_etf_monthly_screen(request: EtfMonthlyRequest, checkpoint: EtfMonthlyCheckpoint) -> EtfMonthlyResult`; `verify_etf_monthly_result(result) -> None`. Prefix simulation is a fixture/recovery facility, not a CLI outcome-selection parameter.

- [ ] **Step 1 — Write RED lifecycle/compatibility tests.** Retain exact old result/event hashes. New fixtures assert no monthly entry before ten months, no same-close fill, no midmonth re-entry/addition, monthly CASH exit, unchanged 100-session holding convention, protection before pending opening action, stop-gap/target-gap/stop-first prices and one sell on overlapping exits. Pin a hand-calculated episode: qty .100, assumed buy 100/sell 98, fees .01 each -> cash 499.78 from 500, fees .02, consumed trial .22 only after settlement; a later .100 buy100/sell102 profit +.18 does not erase that loss. This checks the common reducer independently; no forced quantity through the scheduler. Test full-notional cash/trial reservation, fee-bound denial, ceiling/equity-loss halts, duplicate events, zero whole-share admissibility and unchanged old public type rejection.

```python
state = replay_etf_monthly_account(loss_then_profit_fixture)
assert state.cash == Decimal("499.96") and state.fees == Decimal(".04")
assert state.trial.consumed_loss == Decimal(".22")
assert resumed.events == uninterrupted.events
assert resumed.result_hash == uninterrupted.result_hash
assert terminal.incomplete_reasons and terminal.checkpoint.pending is not None
```

- [ ] **Step 2 — Observe RED.** Run three new simulation files and old compatibility control before extraction; absent monthly APIs fail for expected reasons.
- [ ] **Step 3 — Extract/reuse economic and execution mechanics.** Extend only internal economic input typing/policy dispatch. Factor stepper advancement and pending-admission checks once, preserving failed-owner latching and reconstruction-before-admission. Monthly processing order: due settlement/dividend entitlement+opening mark -> existing protective opening action -> prior valid pending action -> intraday stop-first protection -> closing mark -> holding-age check -> valid monthly after-close decision. Protection never waits for a new signal. After a daily protection/hold exit, a later valid month-end can propose entry; no earlier retry. Keep common cash/trial/risk canonical checks and original stop/target unchanged.
- [ ] **Step 4 — Implement checked pure checkpoint/resumption.** Reconstruct retained economic tape once; verify prefix/output identity before future advancement. Reject altered source/config/tape/pending/window/cursor or impossible state before mutation. Missing required daily session stops safe advancement and preserves obligations; missing monthly/ATR observation denies entry and records incomplete. Final Dec2023 intent and post-window receivables/settlements stay pending/incomplete; no holdout fill and no force-close.
- [ ] **Step 5 — Verify GREEN and failure boundaries.** Require resumed/uninterrupted synthetic events, cash, consumed/reserved trial, decisions/results/hashes equal at splits before decision, before entry, after fill, after exit, before settlement and terminal boundary. Run new files plus `tests/unit/simulation/test_etf_daily_screen.py tests/unit/simulation/test_etf_account.py tests/unit/simulation/test_etf_account_incremental.py tests/unit/runtime/test_etf_forward_paper.py tests/integration/persistence/test_etf_forward_joint_recovery.py`. Both old/new critical modules must satisfy >=90% branch coverage.
- [ ] **Step 6 — Commit scoped files.** `git commit -m "feat: add monthly ETF lifecycle with checked resumption"`.

### Task 4: Frozen After-Cost Monthly Scorecards

**Files:** Create `research/etf_exploratory_economics.py`, `etf_monthly_economics.py`, `tests/unit/research/test_etf_monthly_economics.py`, `test_etf_monthly_economics_adversarial.py`; narrowly modify `research/etf_daily_economics.py` to delegate policy-neutral arithmetic with old golden output preserved. Reuse benchmark/paired/performance primitives unchanged.

**Interfaces:**

- `EtfExploratoryTrace` is an immutable projection of validated offline result: canonical policy, initial/risk capital, dated raw prices/points, distributions, account/events/attempts, scheduled-entry count and incomplete reasons. No source qualification, scheduling or broker capability.
- `score_etf_exploratory_trace(trace: EtfExploratoryTrace, *, cost_name: str, budget_name: str, data_monthly: Decimal, compute_monthly: Decimal) -> EtfExploratoryScore` owns shared performance, sizing, fees, renewal costs, reference and paired calculations. Old/monthly typed adapters convert explicitly; no dynamic field copying/getattr or duplicate arithmetic.
- `EtfMonthlyEconomicReport`/`EtfMonthlyScore` retain all 24 cases plus separate price-policy/economic-plan hashes, first evaluation/renewal anchor, raw-source/config/code/calendar/distribution/operating-basis identities, adaptation/limitations, terminal obligations and native sizing diagnostics. Schemas `etf-monthly-economic-development-protocol-v1` / `etf-monthly-economic-development-report-v1`.
- `etf_monthly_cost_plan_hash() -> str`, `etf_monthly_operating_basis_hash() -> str`, `etf_monthly_economic_plan_hash(protocol: EtfMonthlyProtocol) -> str`, `run_etf_monthly_economics(request: EtfMonthlyRequest) -> EtfMonthlyEconomicReport`. Operating-basis schema `etf-monthly-operating-basis-v1` fixes each of four budget support statuses to unknown and validated route IDs to empty; no caller support claim can change it.
- `monthly_expansion_disposition(report: EtfMonthlyEconomicReport) -> Literal["STOP_CANDIDATE", "BLOCKED_OPERATING_EVIDENCE", "REQUIRES_SEPARATE_REVIEW"]`. Nonzero-fee 25bps survival is necessary. This implementation records operating support as unknown in the preregistration and cannot grant expansion or economic admission; a future verified route needs separate review, not a CLI flag.

- [ ] **Step 1 — Write RED independent economic tests.** Assert exact scenario tuple/order and fees .01 once per fill; two budget renewals at first-evaluated anchor and next corresponding month date, no proration/outcome-selected anchor. Compare equal-date references and candidate; opening exposure-matched allocation capped at canonical limit. Assert conventional returns for NAV 500->550->495 are .10 then -.10, while fixed-capital increments are .10 then -.11; zero/negative prior NAV is undefined. Every incomplete/pending case -> INSUFFICIENT; operating_profit==0 -> REJECT; drawdown==10 is not >10; episode count29 insufficient/30 only a proxy; lower bound==0 insufficient; non-survivor/stress/unsupported-free-only expansion denied. Use fabricated paired/economic inputs, never private data.

```python
assert len(report.scores) == 24
assert incomplete_score.screening_verdict == "INSUFFICIENT_EVIDENCE"
assert zero_operating_score.screening_verdict == "REJECT"
assert thirty_episode_zero_bound.screening_verdict == "INSUFFICIENT_EVIDENCE"
assert monthly_expansion_disposition(only_five_bps_survives) == "STOP_CANDIDATE"
assert monthly_expansion_disposition(stress_survives_unknown_route) == "BLOCKED_OPERATING_EVIDENCE"
```

- [ ] **Step 2 — Observe RED.** Run the two new files; require new missing behavior failures and unchanged old score golden controls.
- [ ] **Step 3 — Implement shared arithmetic and typed monthly wrapper.** Extract existing renewal/fixed-capital/prior-NAV/benchmark/paired calculations without changing daily semantics. Reuse `_money_context`, common performance and paired routines; costs are not deducted twice. Only valid economic points after Oct2016 anchor determine comparison periods and budget anchor. Report no-data/undefined/zero separately, terminal economic cash only if complete, unknown sunk expense/yield/support, and no native execution equivalence. Preserve old schema and economic `protocol_hash` meaning; new wrapper names price/economic identities explicitly.
- [ ] **Step 4 — Verify GREEN and all legacy math.** Run new files plus `tests/unit/research/test_etf_daily_economics.py tests/unit/research/test_etf_daily_economics_adversarial.py tests/unit/research/test_etf_benchmark.py tests/unit/research/test_etf_paired_economics.py tests/unit/research/test_etf_resampling.py tests/property/research/test_metric_invariants.py`. Assert old economic hash golden remains identical, all monthly readiness fields false even on synthetic positive scenarios.
- [ ] **Step 5 — Commit scoped files.** `git commit -m "feat: add frozen monthly ETF development scorecards"`.

### Task 5: Private Research CLI and Honest Handoff

**Files:** Create `cli/etf_monthly_research.py`, `tests/integration/cli/test_etf_monthly_screen_cli.py`, `docs/etf-monthly-development-screen.md`; update only current transition checkpoint. Reuse `cli/etf_research.py` read/reference/code-hash/publish primitives without altering its old commands. No live CLI integration.

**Interfaces:**

- `python -m trading_bot.cli.etf_monthly_research screen-run --capture-dir ... --manifest-hash ... --reference-dir ... --calendar-hash ... --issuer-hash ... --report-dir ... --config-dir ...`. Use canonical base/safety paths with fixed monthly overlay; no capital/date/cost/window/holdout/live/support override or credential argument.
- `_publish_report_fd` is reused with a monthly pre-encoding bound of 8 MiB. Preregistration/result schemas `etf-monthly-screen-preregistration-v1` / `etf-monthly-screen-report-v1`; immutable hash filenames, current-owner0700 roots/0600 files outside Git, descriptor-bound no-overwrite publication and fsync.
- Preregistration binds actual code/config/source/calendar/distribution/cost/operating-basis/request/price-policy/economic-plan identities, fixed anchor/first evaluated date, unknown holdout exposure, adaptive attempt history and all false flags BEFORE evaluation. Result links the preregistration hash. Public output only hashes/counts/false flags/disposition; private prices/cash/paths never enter public logs/Cloud.

- [ ] **Step 1 — Write RED public fixture CLI tests.** Fake archive/reference fixtures only; observe preregistration publish before evaluator callback. Check failure-before-preregistration cannot evaluate; failure-after-preregistration cannot publish a result; retained immutable descriptor/inode used; symlink/ownership/permission/inside-repo/conflict/oversize denies; output lacks prices/account/private paths; no unsupported override is accepted. Assert monthly ID cannot unlock old commands/production and pending terminal obligations remain incomplete in private result.

```python
assert observed_call_order == ["preregistration", "evaluation", "result"]
assert result_doc["preregistration_hash"] == preregistration_hash
assert result_doc["holdout_evaluated"] is False
assert result_doc["live_authorized"] is False
assert after_freeze_failure_published_schemas == ["etf-monthly-screen-preregistration-v1"]
```

- [ ] **Step 2 — Observe RED.** Run `uv run pytest tests/integration/cli/test_etf_monthly_screen_cli.py -q`; the absent CLI is expected to fail.
- [ ] **Step 3 — Implement fixed invocation and report contract.** Rehash saved original bytes through existing bounded readers; filter all outcome projections before2024. Validate clean committed code identity before freeze; canonical monthly loader has no hidden enabling environment. Publish prerequisite first, evaluate once, publish linked result, close descriptor on every failure. Holdout exposure defaults conservatively to unknown, not an unexamined assertion. Documentation lists assumptions, limits, exact fixed command and independent gates; no automatic recurring execution, diagnostics or promotion.
- [ ] **Step 4 — Verify GREEN and old CLI.** Run new CLI file plus `tests/integration/cli/test_etf_daily_screen_cli.py tests/integration/cli/test_etf_benchmark_screen_cli.py tests/integration/cli/test_etf_research.py tests/integration/cli/test_paused_service.py`; no customer/source inspection and no real source invocation. Update transition report with software-only test facts, never planned economics as results.
- [ ] **Step 5 — Commit scoped files.** `git commit -m "feat: expose private monthly ETF development screen"`.

### Task 6: Integrated Verification, Executable Freeze and Conditional Study

**Files:** This plan's local execution ledger under `.superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/`; human status/transition documentation. Private captures/reports remain outside the checkout and are main-only. Do not touch older scratch or study originals.

**Interfaces:** Exact committed candidate/review/check identities and private preregistration-before-result hashes. No new transport, qualification or promotion interface.

- [ ] **Step 1 — Run narrow combined synthetic verification.** Run all new task tests plus old config/study/intake/account/daily/economic/CLI compatibility controls. Every RED must have been observed and repaired for its intended behavior; every old golden hash and exact public type boundary stays intact. Verify no altered dependencies, risk values, transport/write capability or deployment default.
- [ ] **Step 2 — Run full local release gates at one unchanged source head.** Use the exact commands below and record actual exit summaries. Keep primary/research advisory exports/audits and native/backend checks on the exact frozen locks; no installs/upgrades or optional-backup-to-deployed-recovery claims. Preserve failed/partial logs as non-certification.

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80 --cov-report=json:.superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/final-coverage.json
PYTHONPATH=src uv run --project research --no-sync pytest tests/integration/simulation/test_options_historical_episode.py --cov=trading_bot --cov-branch --cov-append --cov-fail-under=80 --cov-report=json:.superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/final-coverage.json
uv run python scripts/check_critical_branch_coverage.py --report .superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/final-coverage.json
uv run bandit -c pyproject.toml -r src
uv lock --check
uv lock --project research --check
uv export --locked --all-groups --no-emit-project --output-file .superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/primary-requirements.txt
uv export --project research --locked --all-groups --no-emit-project --output-file .superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/research-requirements.txt
uv run pip-audit --requirement .superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/primary-requirements.txt --no-deps --disable-pip
uv run pip-audit --requirement .superpowers/sdd/2026-10-08-etf-monthly-trend-hypothesis/research-requirements.txt --no-deps --disable-pip
uv run pytest tests/smoke/test_sbom_reproducible.py tests/deployment -q
for script in infra/digitalocean/*.sh; do sh -n "$script"; done
docker compose config --quiet
```

If local `docker compose` is unavailable but the already installed compatible
`docker-compose` binary exists, use that binary's `config --quiet` and record
the exact binary/version; unavailable tooling is a gap, not a passing check.

- [ ] **Step 3 — Obtain one independent whole-candidate public-code/fixture review.** Use the most capable available model per preserved native execution workflow; reviewer receives exact range and public/fabricated inputs only. Main fixes current-change findings with watched regressions; revalidate affected checks/source identity. Record excluded private/source/account/runtime/qualification evidence and explicit unresolved rulings; never call a skipped hosted review approval.
- [ ] **Step 4 — Resolve exact-current integration checks if publishing.** Under standing merge authority, inspect actual compatible target/base, local/remote head/tree, all required current Python3.12/3.13/3.14/research/security/dependency/configuration jobs and substantive findings. Missing/pending/cancelled is not passing. Attach any created PR to this chat. Never bypass checks or call merge deployment; preserve unrelated dirty checkouts.
- [ ] **Step 5 — Freeze executable study before a conditional private outcome run.** Main verifies actual reviewed source/config/protocol and original private receipt/hash/mode/ownership, creates a fresh0700 report root, records all identities/costs/criteria/anchors/adaptive history and operating support unknown in immutable0600 preregistration. Do not invent future hashes, reuse old study bytes or expose private inputs in Git/Cloud/agents. If any authority/identity/input bound differs, stop its dependent study; continue only safe independent checks.
- [ ] **Step 6 — Evaluate exactly one newly frozen DEVELOPMENT study, only after the preceding gates and applicable operator plan authority.** Main alone invokes the fixed monthly command against retained inputs, never2024–2025 outcomes. Independently verify all24 Decimal accounting/cost/verdict calculations and completeness, original-byte hashes and report linkage/permissions without rerunning market outcomes. Preserve failed/incomplete runs rather than changing dates, costs or parameters to pass. No accepted economics or execution expansion follows automatically, even if a descriptive case proceeds.
- [ ] **Step 7 — Publish a sanitized disposition and next steps.** Record candidate/study identities, verification counts, all24 verdict counts, source/cost/execution/economic/runtime/paper-shadow/live limitations and stop/blocked/further-review disposition. If the candidate fails or is insufficient, stop its expansion; no holdout tuning/calibration trade/acquisition. A surviving stress case with unresolved operating evidence remains blocked. Preserve private originals and recoverably archive only this plan's scratch after handoff; do not resume old integration automation.

## Self-Review and Handoff

The plan covers approved spec sections1–2 in Task1/attempt recording; sections3–4 in Tasks2–3; section5 in Tasks3/5; section6 in Task4; section7 in Tasks1–6; section8 in the conditional handoff. Five Review Focus conditions have explicit owning task tests. The shared interfaces above define each name before consumption, and old protocol/config/hash guards remain controls rather than casualties of extraction.

This is a written plan, not completion evidence. Required next action: operator reviews it; preserve native execution and use `superpowers:executing-plans` after that review. Main implements critical paths; independent agents may audit public contracts/fixtures only. Only reviewed, verified software and a later exact executable freeze can precede market outcomes.

Project completion remains conditional: surviving development -> eligible sources/defensible costs -> untouched final evaluation -> protected broker worker -> genuine qualifying paper/shadow/recovery/backups/alerts -> separately authorized bounded live pilot. No stage automatically promotes the next or promises profitability.
