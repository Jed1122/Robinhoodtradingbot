# Stock Strategy Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete Task 5's actual stock-strategy/portfolio evaluation and auditable
economic decision, not only the initial price-only probe.

**Architecture:** Pure Decimal traces and policy/uncertainty components feed a
source-bound offline study/report command. Monetary portfolio replay remains a
separate evidence-admitted composition of existing lot, risk, settlement and tax
modules. Research cannot grant trading authority.

**Tech Stack:** Existing Python3.12–3.14, frozen dataclasses, Decimal, pytest,
standard-library statistics/random; no new dependency or service.

**Spec:** `docs/superpowers/specs/2026-10-26-stock-strategy-evaluation-design.md`

## Global constraints and review focus

- Live/account/order/credential/deploy/subscription operations remain disabled.
- Preserve actual source clocks and all original member denominators.
- Preserve50/200,dates,per-legcosts and the16-comparison family before outcomes.
- Future-price edits cannot affect prior targets; next-open gaps must remain real.
- Training/holdout slicing must carry state and charge terminal exit only once.
- Missing dividend/currency/filing/revision evidence cannot become zero or qualified.
- Price-only metrics cannot become after-tax wealth, actual fills or source-wide edge.

## 1. Continuous normalized execution trace

Files: create `research/stock_price_trace.py`, `tests/unit/research/test_stock_price_trace.py`.
Consumes immutable `PriceBar` tuples plus calendar open timestamps and Decimal
targets. Produces `PriceTrace`/`PriceTraceRow` via
`trace_price_targets(bars, opens_at, targets, *, one_way_cost_bps, terminal_policy)`.
Each row retains preopen NAV, posttrade NAV, marked close, terminal NAV, target,
stock/cash values, cost and turnover. Use fixed50-digit arithmetic.

- [x] Write/run failing tests for exact flat `(1-c)^2`, next-open gap, future-target
  independence, final signal ignored, fractional self-financing and invalid inputs.
- [x] Implement trace plus `slice_price_trace(trace, *, first_session,last_session)`
  with a prior-close boundary NAV, no state reset or new liquidation.
- [x] Pass focused tests, compare binary endpoints to existing comparator,
  independently review and commit.

## 2. Metrics and paired uncertainty

Files: create `research/stock_study_statistics.py` and its unit tests.
Consumes Decimal NAV/return vectors. Produces explicit defined/undefined metrics
and deterministic shared-index block-bootstrap intervals; no qualified/live flag.

- [x] Write/run failing fixtures for Sortino all-return downside RMS, drawdown
  carry versus segment reset, zero variation/no trades, dependent paired draws,
  fixed seed and16-family adjustment.
- [x] Implement `summarize_price_path(...)`, `paired_block_intervals(...)` with
  the exact spec's constants and evidence hashes; do not reuse iid trade bootstrap.
- [x] Pass tests and independent rational/statistical examples; commit.

## 3. Source-bound first study and actual run

Files: create `research/stock_price_study.py`, `runtime/stock_price_study.py` and tests.
Use existing raw-content parsers/calendar admission and exact frozen handoff.

- [x] Validate source/hash/request/clock and all9original slots; derive prefix-only
  trend targets through the existing50/200policy, with current receipts separate.
- [x] Construct eight traces plus declared passive/causal exposure controls;
  derive train/holdout from one continuous path and training-only sensitivity.
- [x] Test prefix mutation, row gaps, altered payloads, no denominator shrink,
  changed protocol and permanent nonpromotion.
- [x] Freeze remaining manifest/source identity; run actual development then
  final holdout once with durable native exit, exact input hashes and no retries
  that optimize the holdout. Independently reconstruct all reported findings.

## 4. Economic data and monetary replay

Files/adapters follow verified actual schemas; inspect existing `hybrid/accounting`,
`execution`, `capital`, `exits` before introducing another ledger.

- [ ] Freeze bounded permitted data requests; obtain/admit dated currency/identity,
  complete cash distributions and original publication-aware factors/events.
- [ ] Test entitlement/receivables/payments, original versus split-adjusted amounts,
  unsupported action lifecycle, source pagination and tax-lot conservation.
- [ ] Implement/reuse75/15/10risk-constrained replay with$1,000initial simulation,
  repeated entries/exits, reserves, lot/tax/settlement/capital recycling.
- [ ] Compare7families,3exitmodels and named controls on eligible actual evidence;
  keep unavailable data/model outcomes explicit. A missing required comparison
  leaves this workstream incomplete, not automatically a completed study.

## 5. Full statistical/reporting and completion audit

- [ ] Produce actual benchmark/strategy/exit/reinvestment comparisons, chronological
  walk-forward, training parameter/cost/stress sensitivities, regime/attribution,
  dependent uncertainty and multiple-comparison accounting.
- [ ] Write `docs/stock-strategy-comparison.md`, machine-readable reports and an
  exact requirement/evidence audit. Accept a legitimate no-go; never force profit.
- [ ] Run focused, integrated/default stock regressions and static/security checks
  at frozen code; preserve terminal receipts and independently review results.
- [ ] Integrate/merge routinely authorized repository changes. Complete the goal
  only after the full Task5scope is genuinely achieved; otherwise continue work
  on concrete missing requirements. Deployment/live activation remain separate.

## Verified first increment

At code86f35b21,338focusedtests passedPython3.12/3.14; defaultstock/shared
regression12758passed,36warnings,91.53%combinedcoverage;criticalgatepassed.
Actualfirstpriceprobeexit0/sourceunchanged; independentprice-onlyacceptance
PASS2000489checks/0errors. This completesTask1–3only, notfullTask5.
Nativeinput/runtime/exit/coverage/auditreceipts remain private. The firsttrend
rule has no demonstratededge; see docs/stock-strategy-comparison.md.
Task4monetaryadmission/replay andTask5fullfamily/reporting audit remain pending.

## Subsequent accounting and measurement increments

The [monetary-input increment](2026-10-26-stock-monetary-inputs.md) is integrated
through PR 57 with exact-source CI: 12,896 tests pass on each Python version and
all unchanged coverage gates pass. It adds panel validation and the dividend book,
including reviewed reservation, settlement and exit-history protections.

The [economic-kernel increment](2026-10-26-stock-economic-kernel.md) adds the pure
session/accounting loop and AXP annual measurement types. Focused and independent
verification is complete; its own frozen full regression and CI remain pending.
These are prerequisites for section 4, not completion of its actual-source
admission, seven-family monetary comparisons or section 5's statistical audit.
