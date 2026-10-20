# Task 5 Available-Alpaca Development Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the actual conditional Task 5 development panel using available
Alpaca observations, without reinstating waived history or provider-support gates.

**Architecture:** New exact observed-range admission and a closed short-history
protocol feed the existing shared evaluator. Legacy public admission and
canonical preimages remain unchanged; only an explicit new entry point admits
the observed dataset. MAIN owns private evidence, integration and execution.

**Tech Stack:** Existing Python 3.12+, Decimal/dataclasses, pytest, Ruff/Mypy,
existing private original archives, existing suspend-inclusive execution custody.

**Spec:** `docs/superpowers/specs/2026-10-20-task5-observed-development.md`

## Global Constraints

- New checkout based on b0ff8add9ab809ba174c45fb7196c1ec2860bce9; old MAIN/SECOND
  and all frozen evidence remain intact.
- Range `[2023-01-01,2026-01-01)`; 252 training, 20 purge inside training,
  20 embargo, five 84-session folds, 23 tail; 715 used/420 test sessions.
- Keep 28 candidates, six capital tiers, four whole-percent friction levels,
  24 scenarios, four roles, 2,784 columns and 174 decisions.
- All qualification/promotion/deployment/live flags remain false; unknown
  allocated recurring costs and the whole operating family remain None.
- No broker/account/order calls, paid acquisition, deployment, service changes,
  inferred action dates, silent aggregation, or fabricated provenance.
- Do not repeat unchanged old software/release/synthetic audits. New source
  requires its own proportional regression and repository gates.

## Review Focus

- A valid full archive with an invalid selected date, malformed excluded record
  or forged flag must not become an admitted range view.
- Legacy consumers must reject the new variant rather than silently changing
  date/schedule/hash behavior; mixed record graphs must fail.
- Feature warm-up and rolling selections must never use future rows, reset
  elapsed history, or confuse overlapping local tails with the global halt.
- Unknown costs, action coverage, and accepted terms must remain visible in
  hashed inputs and outputs, not merely a prose disclaimer.
- Process success must include report publication and independent custody;
  a partial result, saved winner, clean exit without dimensions, or stale
  code/input identity is not study completion.

---

### Task 1: Closed study protocol

**Files:** create `src/trading_bot/research/etf_capital_protocol.py`;
create `tests/unit/research/test_etf_capital_protocol.py`.

**Interfaces:** `CapitalStudyProtocol(name)` admits only
`legacy-750x126-v1` and `observed-252x84-v2`; derived read-only properties
`training_count`, `purge_count`, `embargo_count`, `fold_count`,
`test_count_per_fold`, `test_count`, `baseline_index`, `test_start`,
`test_end`, `used_count`, `tail_count`; method
`folds(sessions: tuple[date,...]) -> tuple[CapitalWalkForwardFold,...]`.
No caller-defined dimensions, scores, winners or account state.

- [x] Write real boundary tests: legacy minimum 1423 and date cap; observed
  minimum 715 and exact declared date range; 714 denies; bool/unknown/subclass
  names deny; ordered unique sessions required; literal fold slices distinguish
  20 purge from 20 embargo and 23 overlapping local tails.
- [x] Run the new test file and observe the missing-feature failure.
- [x] Implement the closed descriptor and protocol-aware fold construction.
  Preserve the old fold function until the explicit shared-composition step.
- [x] Run new protocol tests plus existing fold tests; inspect actual output.
- [x] Commit only this new increment after checks pass.

### Task 2: Original-preserving observed source

**Files:** create `src/trading_bot/market_data/etf_capital_observed.py`;
create `tests/unit/market_data/test_etf_capital_observed.py`.

**Interfaces:** `CapitalDailyRangeView(archive,calendar,start,end)` with
`view_hash`; `CapitalObservedDataset` with explicit canonical config, full
original archives/actions/calendar, declared range and immutable conditional
model limitations; `build_capital_observed_dataset(...)`;
`capital_observed_features(dataset,as_of_session=...)`.
All full original archive hashes stay distinct from view/dataset hashes.

- [x] Write fabricated multi-page fixtures spanning both boundaries. Test
  original row identity preservation, request containment, all selected calendar
  dates exactly once, malformed excluded records/flags, incomplete pagination,
  range/hash sensitivity, immutable false flags, complete action dates and
  duplicate ex-date denial.
- [x] Observe new-feature failures, then implement explicit validation and
  independently derived row selection without altering raw pages or requests.
- [x] Add a validated range-source factory supplying selected `raw_rows` to
  the existing private feature arithmetic. Bind original archive hash, window,
  selected row identities and conditional model in enclosing hashes.
- [x] Verify known split arithmetic and earlier-as-of behavior against literal
  expected values; verify old v1 still rejects range mismatch/post-2023 data.
- [x] Run both new tests and affected legacy archive/inventory/feature/dataset
  tests. Commit the source increment after checks pass.

### Task 3: Shared owned-source/preparation boundary

**Files:** modify only the new checkout's
`src/trading_bot/market_data/etf_capital_owned.py`,
`src/trading_bot/research/etf_capital_prepared.py`;
add `tests/unit/research/test_etf_capital_observed_prepared.py`.

**Interfaces:** explicit internal observed ownership factory produces the same
calculation capabilities only after validating/copying new originals; shared
preparation accepts a finite exact owned-type union. Legacy public evaluators
remain v1-only. No caller-supplied prepared cache.

- [x] Write tests that forge original flags/UTC clocks, mutate aliases, alter
  excluded originals, substitute saved preparation, or mix variant identities.
  Require failure before copying can reset init-false flags.
- [x] Observe RED and implement finite type dispatch with distinct observed
  owned-source hash namespace and full before/after identity checks.
- [x] Reuse feature/preparation kernels; test history readiness at 199/200 bars,
  33/117/201/232/232 eligible training closes, and future-mutation independence.
- [x] Run new tests and existing owned/prepared/projection-serialization tests;
  preserve literal legacy preimages. Commit only these changes.

### Task 4: Explicit observed walker/panel

**Files:** modify new checkout's
`src/trading_bot/research/etf_capital_signals.py`,
`src/trading_bot/simulation/etf_capital_walk_forward.py`,
`src/trading_bot/research/etf_capital_panel.py`,
`src/trading_bot/research/etf_capital_panel_models.py`;
add observed-specific tests adjacent to existing walker/panel tests.

**Interfaces:** add `replay_capital_observed_walk_forward(request)` and
`evaluate_capital_observed_economic_panel(request)` with exact new dataset
admission and fixed observed protocol. Existing wrappers choose only legacy.
Extract shared private composition rather than copying the evaluator.
Add explicitly registered observed training/fold/scenario/report record types
with distinct hash namespaces and exact 252-point training admission.

- [ ] Write tests for 715 used, baseline271, tests272:692, tail692:715,
  420-point columns, 84-session fold profits, 37 unused dates in a 752 fixture,
  24 scenarios and 174 decisions; preserve old literal v1 tests unchanged.
- [ ] Observe RED, then replace hardcoded internal slices with the privately
  selected protocol at every scheduling/retention/statistics/report boundary.
- [ ] Test close/open handoffs, purged-close denial but earlier pending entry
  submission, global-tail halt, held-policy continuity and incomplete tails.
- [ ] Test exact 252-vs750 training retention and mixed-v1/v2 graph denial.
  Keep closed field-reader capabilities; no reflection fallback.
- [ ] Test trading family with operating None; no GO; unchanged 20/100 blocks,
  seed/draw count and criteria; all unknown-support criteria stay unknown.
- [ ] Run affected selection/walker/panel/statistics/account consumers and
  architecture tests. Commit only the completed coherent variant.

### Task 5: Verification, preregistration, one real evaluation and report

**Files:** public report
`docs/etf-capital-observed-development-results.md`; new ignored same-plan
execution directory; MAIN-only private derived-archive and preregistration
directory outside Git. Do not alter old execution specs or originals.

**Interfaces:** original-byte imports use existing parser/writer APIs and bind
new derived manifests to original native receipts. Derived archives are not
new provider captures. The observed panel accepts original inputs only.
The new fixed execution owner binds exact code/input/config/protocol identities.

- [ ] Run new exact-source Ruff, Mypy, full default suite/coverage, critical
  gates, Bandit, lock/dependency checks and applicable native checks. Retain
  actual per-stage exits; old same-source receipts are not new-source evidence.
- [ ] Conduct one independent public-code/fabricated-fixture review of the
  complete change. MAIN rules each finding, reproduces/fixes Important or
  Critical issues through RED/GREEN and verifies affected regression tests.
  No private evidence is delegated.
- [ ] MAIN compiles available original bytes into separately labeled derived
  archives/actions, checks only the new selected input contract, and writes
  a read-only immutable preregistration binding all identities, dates and
  explicit fee/fill/instrument/review/cost assumptions before outcomes.
- [ ] Implement/test a new fixed invocation of the existing reviewed
  suspend-inclusive custody mechanism. Bind 96 hours/2 GiB including setup,
  serialization/validation/publication. Tests use tiny fabricated subprocesses,
  not another full synthetic workload.
- [ ] Launch ONE real development evaluation, retain actual child and
  independent controller exits, validate dimensions/flags/identities and
  stream-hash the original new report. No automatic retry/resume/stitch.
- [ ] Write the readable research result, including all rejections/insufficiency,
  cash/settlement/tail effects, comparison limitations, trading-only sensitivities
  and whole operating-profit unknown. Reconcile Task 5 requirements explicitly.
- [ ] Update only this plan's progress, MAIN/SECOND handoff pointers and existing
  heartbeat. Task 5 completes only after actual study validation; Tasks 6–8
  remain gated and no automatic paper/live activation follows.

## Pre-flight rulings

1. History and provider-contact waivers are binding; they remove gates, not
   uncertainties. Cost if misread: false qualification. Keep explicit flags.
2. 2023 range and shorter protocol are chosen before outcomes from metadata.
   Cost: reduced statistical support and different research question; report it.
3. Existing MAIN is frozen. A separate same-repository checkout is necessary
   despite the generic worktree skill's reuse preference. The app's native
   creation tool cannot target this sibling repository from the unrelated chat
   cwd, so repository-explicit Git creation is used. No old worktree is removed.
4. Existing b0 software baseline is already verified; do not rerun unchanged
   baseline suites or install dependencies merely for setup. New-source gates
   remain mandatory before completion. No network package upgrade.
5. The operator's explicit amend-and-proceed goal supplies execution direction;
   do not add a generic skill approval loop. MAIN implements shared critical
   composition; independent agents review only public code/fixtures.
6. Preserve all plan workspaces and logs. Generic skill cleanup is superseded
   by the operator's preservation requirement. No destructive cleanup.

## Self-review

Shared interfaces: protocol → fold/walker/panel; range → ownership → preparation;
prepared original source → shared account engine; observed retention → statistics
and report; immutable preregistration → fixed custody invocation. Exact variant
admission and hash binding are required at each edge. The five Review Focus
items map to increments 2, 3/4, 3/4, 2/4/5 and 5 respectively.
The original Task 5 behavior is retained except the explicitly amended source
range, study schedule, conditional-evidence prerequisite and record namespaces.
