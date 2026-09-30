# Focused ETF Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the primary-owned safety-critical tasks; isolated parser/fixture/report work may use superpowers:subagent-driven-development after interfaces are frozen. Steps use checkbox syntax for tracking.

**Goal:** Build a reproducible, offline SPY-plus-cash pilot with qualified-source
admission, causal after-cost account outcomes and truthful benchmark/NO-GO reports.

**Architecture:** A separately registered study composes existing features, momentum,
risk and lifecycle primitives through one authoritative replay owner. Source trust,
economic results, paper/shadow eligibility and live authority remain independent.
The existing options implementation and four-ETF comparison remain unchanged.

**Tech Stack:** Existing Python 3.12–3.14, Decimal, Pydantic, SQLite/Alembic,
Parquet/DuckDB, pytest, canonical configuration and content-addressed evidence.
No new dependency or paid service is required by the offline implementation.

**Spec:** `docs/superpowers/specs/2026-09-30-focused-etf-research-design.md`
(written specification approved by the operator on 2026-09-30).

**Status:** Operator approved this implementation plan on 2026-09-30 and retained
native execution. No task below is implemented by writing this plan. Existing CI
repairs are a separate change.

## Global Constraints

- SPY or cash only; long-only, unleveraged, one position and one outstanding entry.
- Fixed 20/100-day momentum using the latest 100 eligible completed daily bars;
  five-session rebalance cadence, no parameter optimization.
- Requested `[2016-01-01, 2026-01-01)` history; 2024–2025 untouched final holdout.
  At least 3,650 calendar days and 750 observed daily bars; incomplete data denies.
- Five purged folds, at least 50 test bars per fold, at least 30 independent
  opportunities, configured embargo plus overlap horizon; existing acceptance
  thresholds remain. Use 1,000 seeded dependent resamples and 95% intervals.
- $500/$1,000 hypothetical cash tiers do not increase the $100 risk reference,
  absolute order/gross caps, percentages, $50 cumulative trial-loss boundary or
  $1,000 account ceiling. Keep the stricter applicable constraints and one new
  position per session. No deposits/profits replenish trial loss.
- Canonical risk/default live state, broker capabilities and promotion gates never
  change to make a run succeed. Synthetic and incomplete runs never promote.
- Protect unrelated dirty work, including CLI/intake and documentation changes.
  Do not stage whole directories or deploy/migrate production state.
- No credentials, raw licensed data or account identifiers in Git/Cloud/logs.
  Existing data spending authority remains credit-only and requires an exact
  usable package, current available credits, pending-cost reconciliation and no
  cash exposure. The operator subsequently offered to pay for a suitable data
  account; evaluate paid plans as well, but present the exact product, recurring
  cost and material terms before committing to a subscription or new agreement.

## Dependency chain and file responsibilities

Tasks 1 → 2 → 3 → 4 → 5 → 6. Task 2 has an external evidence gate: fixture-backed
parsers can finish while actual-source qualification remains blocked. Task 6 cannot
produce genuine results from an unqualified dataset. None of these tasks starts
the 100-paper-cycle/seven-UTC-date promotion clocks or implements broker writes.

- `config/models.py`, base/envelope YAML: one disabled research profile, no parallel loader.
- `research/etf_study.py`: immutable study identity, chronology and holdout seal.
- `market_data/etf_source.py`: bounded source qualification and typed visible events.
- `research/etf_costs.py`: effective-date cost/cash/operating evidence, not assumed zeros.
- `simulation/etf_history.py`: one causal owner joining common decision/risk/lifecycle.
- `simulation/etf_history_state.py`: typed reconstructible account/run state.
- `persistence/etf_history_store.py`: additive private research event/cursor storage.
- `research/etf_economics.py`: matched benchmarks, resampling, independent verdicts.
- `cli/etf_research.py`: offline CLI and private reports, no transport capability.

## Review Focus

1. A corrected old bar/dividend published later must not change an earlier decision;
   Task 2 pins original/revision visibility and Task 3 the decision hash.
2. A dataset ending with an open position must not acquire an invented liquidation;
   Tasks 3/5 pin incomplete exposure and conservative valuation separately from fills.
3. A crash after a partial fill but before cursor advancement cannot duplicate cash
   or replenish the trial allowance; Task 4 injects the crash at each transaction edge.
4. Fractional eligibility alone cannot establish a permitted limit order or fill;
   Tasks 2/3 deny unknown increment/minimum/order-type evidence.
5. A single fixed candidate cannot fabricate parameter-neighbor or effective-sample
   evidence to satisfy acceptance; Task 5 preserves those explicit blockers.

---

### Task 1: Freeze the canonical ETF study and contamination boundary

**Files:** Modify `src/trading_bot/config/models.py`, `configs/base.yaml`,
`configs/safety-envelope.yaml`, and corresponding config/hash tests. Create
`src/trading_bot/research/etf_study.py`,
`src/trading_bot/research/etf_costs.py`,
`tests/unit/research/test_etf_study.py`, and the immutable-record cases in
`tests/unit/research/test_etf_costs.py` (Task 5 extends the same module/test file).

**Interfaces:**
- Consume `LoadedConfig`, `hash_loaded_config`, `content_hash` and exact UTC checks.
- Add `EquityStrategySettings.etf_pilot: EtfPilotSettings` with literal policy
  identity `spy-cash-momentum-20-100-v1`, disabled by default, execution and promotion
  permanently false. Store research scope inside this canonical graph only.
- Produce frozen `EtfStudy`: study/config/code identities, requested window,
  holdout window, fixed candidate, risk-reference/starting-cash tuple, seed,
  cost/source evidence hashes and contamination declarations.
- Its public fixed-policy properties are `symbols: tuple[str, ...]`,
  `windows: tuple[int, int]`, `rebalance_sessions: int`,
  `risk_equity_reference: Decimal`, `capital_tiers: tuple[Decimal, ...]`,
  `execution_enabled: Literal[False]`, and `evidence_promotable: Literal[False]`.
- Produce frozen `EtfCostEvidence`: immutable source hashes, valid/known-at
  windows, commission/fee rules, spread/slippage attribution, cash rates,
  operating-cost intervals and calibration status. Each interval binds currency,
  units, Decimal values, effective UTC range, availability time and source hash.
  Missing actual evidence is not replaced by zero-valued rules; synthetic records
  are explicitly tagged and cannot qualify a study. Task 5 adds its bounded loader.
- `freeze_etf_study(loaded: LoadedConfig, *, code_hash: str,
  source_plan_hash: str, cost_plan_hash: str, holdout_previously_examined: bool)
  -> EtfStudy`. Invalid identity/type/window denies; previous examination is a
  retained non-promotability reason, never silently reset.

- [x] Write tests: disabled defaults cannot construct execution; unknown/bool/NaN
  financial inputs deny; study hashes bind each source/cost/split/reference value;
  four-ETF config/identity stays unchanged; hypothetical cash never replaces risk
  reference; prior holdout access stays blocked; old evidence bytes remain readable.

  ```python
  assert study.symbols == ("SPY",)
  assert study.windows == (20, 100)
  assert study.rebalance_sessions == 5
  assert study.risk_equity_reference == Decimal("100")
  assert study.capital_tiers == (Decimal("500"), Decimal("1000"))
  assert study.execution_enabled is False
  assert study.evidence_promotable is False
  ```

- [x] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/research/test_etf_study.py -q`.
  Expected: new contract tests fail before implementation.
- [x] Implement exact-type immutable records and canonical registration. Preserve
  historical hash versions; do not rewrite expected legacy hashes to new settings.
- [x] Run the new tests plus `tests/unit/config`, `tests/unit/risk`, and historical
  research compatibility tests. Expected: pass without enabling a runtime.
- [x] Commit only this task's exact paths: `feat: register locked focused ETF study`.

Task 1 local verification: 6,276 passed / 33 skipped on Python 3.12, 3.13 and 3.14;
70 native/ETF cases passed; 88.62% overall coverage and the existing critical-branch
gate passed on 3.14. The scoped independent review finding was reproduced and fixed.
Ruff, Mypy, Bandit and both lock checks passed. Hosted CI is separate and remains
required before merge. Tasks 2–6 and genuine economic validation remain outstanding.

### Task 2: Qualify sources and freeze a usable acquisition package

**Files:** Create `src/trading_bot/market_data/etf_source.py`,
`tests/unit/market_data/test_etf_source.py`, and
`tests/integration/market_data/test_etf_source_history.py`. Reuse existing
`databento_bar_store.py`, recording/provenance and Parquet infrastructure unchanged
unless a failing adapter test requires a narrowly reviewed extension.

**Interfaces:**
- Consume `EtfStudy` and content-addressed private input manifests.
- Produce exact frozen event records `EtfObservedBar`, `EtfObservedQuote`,
  `EtfActionEvent`, `EtfSessionEvent`, `EtfControlEvent`; each binds source record
  hash, ordinal, event/availability nanoseconds and instrument identity. Payloads
  use existing validated domain records, not arbitrary mappings or floats.
- `qualify_etf_source(study: EtfStudy, *, manifest_path: Path,
  allowed_root: Path) -> EtfSourceAssessment`; assessment has status/reasons,
  role/era evidence hashes and `dataset: QualifiedEtfDataset | None`.
- `iter_etf_events(dataset: QualifiedEtfDataset, *, starts_at: datetime,
  ends_at: datetime) -> Iterator[EtfSourceEvent]`; the event type is the closed
  union of the five exact records. No caller-supplied `verified=True` or provider
  label constructs a qualified dataset.

- [ ] Write independent fixtures for complete and absent/empty coverage, raw-byte
  substitution, late corrections, publication without receipt proof, wrong eras,
  split/dividend revisions, DST/closure/early close, truncated pagination, stale/
  crossed/locked quotes, source-order collisions, missing fractional terms and
  unsupported IEX→SIP substitution. Earlier decision inputs remain byte-identical
  when irrelevant future revisions are added. Synthetic fixtures always deny
  actual-source promotion even when parser mechanics pass.
- [ ] Run both new files in the locked research environment. Expected: failing
  missing contract/qualification tests, not invented data access.
- [ ] Implement bounded no-symlink/no-overwrite input validation, exact Decimal
  projection and visible-event ordering. Reference facts come from reviewed
  code-owned rules with retained primary evidence, not untrusted manifest claims.
- [ ] Run source/record/Parquet plus new fixture suites. Expected: parser tests
  pass; absent actual evidence returns `BLOCKED_INPUTS` and `dataset is None`.
- [ ] Separately inventory existing authorized archives/receipts, select a provider
  package by coverage rather than outcomes, and preserve a source qualification
  report. Alpaca paper-only SIP is excluded by the inspected reply. Never acquire
  a substitute feed under the old diagnostic approval.
- [ ] For a necessary Databento credit-only package, verify fresh credits/pending
  jobs, original versions/conditions, complete bars/actions/quote/control coverage
  and exact all-in quote before purchase. Unknown no-cash exposure or a new
  agreement blocks acquisition only; fixture work continues. Reuse existing data.
- [ ] Commit parser/tests/public semantic references only. Raw inputs, receipts
  and personal correspondence remain private. Do not mark actual qualification
  complete unless the retained package passes all role/era/coverage checks.

### Task 3: Compose causal strategy, economic risk and historical execution

**Files:** Create `src/trading_bot/simulation/etf_history.py`,
`src/trading_bot/simulation/etf_history_state.py`,
`tests/unit/simulation/test_etf_history.py`, and
`tests/integration/simulation/test_etf_history_account.py`.

**Interfaces:**
- Consume Task 1 study and Task 2 qualified event stream; reuse FeaturePipeline,
  MomentumStrategy, existing sizing/exposure/activity/loss functions and lifecycle
  transitions/accounting. Keep synthetic replay public APIs locked and unchanged.
- Produce `EtfHistoryRequest(study, dataset, costs, initial_cash, fill_scenario)`
  and immutable `EtfHistoryResult` containing input/result identities, chronological
  decisions, admissions/denials, cash flows, terminal/residual positions,
  reservations, trial-loss history, completeness and non-promotability reasons.
- `run_etf_history(request: EtfHistoryRequest) -> EtfHistoryResult`.
- Costs consume Task 1's frozen `EtfCostEvidence` contract; until real evidence
  exists, synthetic cost fixtures are explicitly synthetic and non-promotable.
- In `etf_history_state.py`, produce frozen `EtfHistoryEvent` with run/event IDs,
  prior cursor, source ordinal/hash, event/availability nanoseconds, event kind,
  exact typed decision/order/fill/cash-flow/settlement payload and state hash.
  Payloads compose the existing domain records; no arbitrary mutable mapping.
- In the same module, produce frozen `EtfHistoryCheckpoint` with run/study/config/
  dataset/cost identities, cursor, fencing token, last event/state hashes, paused
  status and the complete reconstructible positions/cash/reservations/loss state.
  Task 4 persists these exact records; it must not introduce another state owner.

- [ ] Write red tests for the exact 100-bar predicate, five-session entry cadence,
  missing ATR, full canonical risk denials, unauthorized risk-reference escalation,
  fractional restrictions, loss baselines, one-position/one-entry policy, no same-
  event fill, positive latency, capacity bounds, unfilled/rejected/partial orders,
  cancel races, stop gaps, missing bars, future corrections and end-of-input.
- [ ] Add exact cash accounting fixture: initial 500, buy 0.1 shares at 100 plus
  fee 0.01, receive eligible dividend 0.02, sell 0.1 at 101 less fee 0.01 gives
  final cash 500.10. This isolates accounting, not full strategy/risk eligibility.
  A later losing episode consumes trial capacity; the gain cannot offset it.
- [ ] Run new narrow suites. Expected: fail before implementation.
- [ ] Implement one causal owner. Use observed bid/ask and capacity; keep gap/reset
  and pending-cancel state unfillable until properly re-established. Do not use
  historical high/low order, optimistic fills, fold-end liquidation or a looser
  parallel risk calculator. Stop/target/holding/regime policies remain canonical.
- [ ] Run new suites and equity decision/risk/lifecycle regression suites.
  Expected: deterministic exact outcomes and denial of all missing critical state.
- [ ] Commit exact paths: `feat: add causal locked ETF historical account replay`.

### Task 4: Make replay restart-safe and verify monitoring failure behavior

**Files:** Create `src/trading_bot/persistence/etf_history_store.py`, an additive
Alembic revision after the current head, and
`tests/integration/persistence/test_etf_history_store.py`;
`tests/chaos/runtime/test_etf_history_restart.py`. Extend Task 3 only at this seam.

**Interfaces:**
- `EtfHistoryStore.append_event(run_id: str, expected_cursor: int,
  event: EtfHistoryEvent) -> EtfHistoryCheckpoint` performs one transaction.
- `EtfHistoryStore.restore(run_id: str, study: EtfStudy) -> EtfHistoryCheckpoint`.
  Both use existing unit-of-work/audit conventions, append-only event identities,
  ownership and exact state reconstruction, never production account data.
- `resume_etf_history(request: EtfHistoryRequest, checkpoint:
  EtfHistoryCheckpoint) -> EtfHistoryResult` validates identity before advancing.

- [ ] Write red tests for transaction failure before/after partial fill, repeated
  same-ID events, conflicting duplicates, cursor regression, changed source/config,
  pending cancellation/settlement, backward clock, stale writer/fence, disk/store
  failure and failed alert persistence. No failure creates extra shares or releases
  a reservation/consumed loss. Resumed output equals uninterrupted exact output.
- [ ] Run new persistence/chaos tests. Expected: fail without the durable seam.
- [ ] Implement additive private research storage and transactional restart; paused
  reconstruction and reconciliation precede entries. Never migrate production.
- [ ] Run migration/append-only/reconciliation/monitor tests plus new tests.
  Expected: pass; injected failures preserve reservations and historical losses.
- [ ] Commit exact paths: `feat: persist restart-safe ETF replay history`.

### Task 5: Add effective-date costs, matched benchmarks and uncertainty

**Files:** Extend `src/trading_bot/research/etf_costs.py` and
`tests/unit/research/test_etf_costs.py` from Task 1. Create
`src/trading_bot/research/etf_economics.py` and
`tests/unit/research/test_etf_economics.py`. Reuse common metrics/validation without
relaxing their acceptance checks.

**Interfaces:**
- Consume Task 1's exact `EtfCostEvidence` record without redefining it.
  `load_etf_cost_evidence(manifest_path: Path,
  allowed_root: Path, study: EtfStudy) -> EtfCostEvidence` denies missing roles.
- `evaluate_etf_economics(study: EtfStudy, results: tuple[EtfHistoryResult, ...],
  costs: EtfCostEvidence) -> EtfEconomicReport`; requires both cash tiers and all
  three fill scenarios with identical approved identity/date coverage.

- [ ] Write red tests for dates/units/currency, fee minima, dividends once only,
  spread once only, missing rates, operating versus trading profit, incomplete
  outcomes, zero trades/denominators, matched constrained versus fully invested
  benchmarks, fold/holding overlap, deterministic dependent resamples, contaminated
  holdout and insufficient effective sample size. Hand-check candidate gain 0.10
  minus allocated operating cost 0.25 produces operating result -0.15.
- [ ] Run new tests. Expected: missing cost/economic contract failures.
- [ ] Implement conservative/base/optimistic attribution and independent benchmark
  runs. Preregister moving-block resampling of daily marked return/cash-flow series
  with fixed 20- and 100-session block lengths, 1,000 draws per scenario and shared
  seed; report both intervals and use the less favorable supported result. Count
  independent completed opportunities separately, never count bootstrap draws as
  observations. Retain the final holdout seal until the complete protocol is frozen.
- [ ] Preserve all canonical acceptance criteria; fixed-candidate stability evidence
  not measured by this pilot remains unavailable. All economic/report transport
  objects are unable to enable execution or emit accepted paper/shadow observations.
- [ ] Run new tests and common metrics/report/purged-split/acceptance suites.
  Expected: exact benchmark/cost identities and `ECONOMIC_NO_GO` for every
  incomplete, unqualified, uncalibrated or statistically unsupported case.
- [ ] Commit exact paths: `feat: report constrained ETF after-cost economics`.

### Task 6: Offline operator commands, genuine run and evidence handoff

**Files:** Create `src/trading_bot/cli/etf_research.py`,
`tests/integration/cli/test_etf_research.py`, and `docs/etf-research.md`.
Register the commands in `src/trading_bot/cli/main.py` only after deliberately
accounting for its pre-existing equity-replay changes; do not stage those changes.
Extend `scripts/check_critical_branch_coverage.py` with the new risk/lifecycle owner
modules rather than claiming they are covered by the old list.

**Interfaces:** Offline commands `etf-study-freeze`, `etf-source-verify`,
`etf-history-run`, `etf-history-resume`, `etf-economic-report`; each invokes the
typed interfaces above and emits a sanitized result path/verdict, never raw data,
credentials or provider access. Use exclusive private output creation and bounded
input parsing consistent with the existing offline CLI.

- [ ] Write red CLI tests for fixture replay, qualification refusal, both tiers,
  interrupted/resumed equality, missing/corrupt evidence, symlink/overwrite denial,
  oversized input, secrets in exceptions, no-network/no-broker capabilities, and
  immutable production/promotability flags. Assert the operator cannot supply
  `--assumptions-validated` or a live-enable flag to bless the results.
- [ ] Run new CLI tests; expected failures before command integration.
- [ ] Implement commands and concise operator documentation. Run complete fixture
  path to prove wiring, labeled synthetic and non-promotable.
- [ ] Only with qualified actual data and frozen costs/protocol, execute the genuine
  development/validation run, then the untouched final test exactly once. Retain all
  outcomes and an explicit source/economic limitation report; do not retune after
  failure or relabel an exploratory screen as validation.
- [ ] Run Ruff, Mypy, supported-Python full pytest with 80% overall/90% critical
  branch coverage, Bandit, both locked audits, SBOM and deployment-manifest checks.
  Authenticated tests remain excluded. Complete independent integrated review.
- [ ] Commit only owned source/tests/docs. Push/merge only under existing authority
  and genuine current hosted checks; never bypass billing or protections.

## Completion and external gates

The offline deliverable is complete only when commands, restart, tests, docs and
truthful reports work. Genuine economic validation additionally needs the actual
qualified package, cost/calibration evidence and sufficient independent results;
a NO-GO is an honest result, not a promise of a viable strategy.

Qualifying paper/shadow operations are a subsequent integration milestone using
accepted research, account-bound provider/runtime evidence, complete outcomes and
durable reconciliation. They require the existing elapsed observations. The
currently paused DigitalOcean image and interactive empty broker reads prove only
their recorded scopes, not this milestone. Live remains independently blocked.

**Self-review:** All eight specification sections map to Tasks 1–6; source and
cost evidence are explicit dependencies, not permissive flags. Task 1 defines
the cost record before Task 3 consumes it; Task 5 implements its loader/evaluation.
Task 3 defines event/checkpoint state before Task 4 persists it. The primary
owns shared risk/execution/persistence integration. No interface authorizes a
provider operation or changes the historical four-ETF comparison.
