# Capital-Constrained ETF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved capital-specific research path, proceeding to operational composition only for a supported survivor.

**Architecture:** Preserve legacy contracts and canonical configuration. Add a versioned offline configuration extension, reuse sizing/accounting/economic machinery, then compose multi-symbol data and strategy research. Treat research, broker, operational and live authority independently.

**Tech Stack:** Python, Decimal, Pydantic, Typer, pytest, existing SQLite/journals.

**Spec:** docs/superpowers/specs/2026-10-08-capital-constrained-etf-design.md

## Global Constraints

- No broker/provider calls, credentials, spending, live activation or deployment in the first increment.
- Preserve original data, earlier studies, other scratch and worktrees.
- Canonical whole-percent units; six exact capital tiers; research only/paused.
- Existing production configuration and exact historical hashes unchanged.
- All old diagnostic eligibility flags stay false; no second risk/config loader.
- Native coordinator owns critical paths; fixture-first and one fresh whole-candidate review before release.
- Keep unchanged80%overall/90%critical gates and full exact-source verification.
- Record rulings/checkpoints; recoverably archive only this plan's audit scratch.

## Review Focus

- New profile cannot authorize production or accept enabling environmental overrides.
- Equality-equivalent booleans/floats/Decimals cannot forge risk or report identities.
- Low cash, fees and rounding never over-admit a fractional order.
- Missing inputs/costs/routes remain unknown, not zeros or qualification.
- Old serialization and risk limits do not change by importing new contracts.

### Task 1: Offline canonical capital-policy extension

**Files:** config/capital_research.py; config/loader.py; configs/etf/capital/policy.yaml; tests/unit/config/test_capital_research.py.

**Interfaces:** extend load_config with optional keyword research_policy_path, producing LoadedConfig with opt-in CapitalResearchAppConfig/CapitalResearchSafetyEnvelope and shared existing risk classes. restore_loaded_config recognizes only this exact versioned extension and preserves old shape otherwise.

- [x] Write behavior tests for six-tier equity-scaled limits, clean legacy hashes, canonical restore and denial of non-offline/live/unpaused/unsafe configuration.
- [x] Run tests RED: absent research extension/profile.
- [x] Implement strict frozen policy using existing configuration parsing/enforcement/hashing; no production YAML changes.
- [ ] Run config/property/legacy monthly golden regressions, Ruff/Mypy; full baseline before completion.
- [ ] Commit scoped files and record exact result.

### Task 2: Capital feasibility and fee-aware sizing

**Files:** research/etf_capital_feasibility.py; tests/unit/research/test_etf_capital_feasibility.py.

**Interfaces:** capital_budgets(loaded,equity) -> immutable CapitalBudget; size_capital_entry(loaded,instrument,equity,settled_cash,entry_price,stop_distance,fee_bound,position_open,daily_loss) -> immutable research-only decision; capital_feasibility(loaded) -> six-tier report.

- [x] Literal RED tests:20/.50/40 budgets at100,200/5/400 at1000; fee/cash/increment/minimum/position/daily-loss denies and net notional/risk bounds.
- [ ] Reuse SizingRequest/size_position with declared research instrument terms; explicit fee/cash final guards; no broker/execution factories.
- [ ] Test ambient Decimal context independence, altered nested records and unknown costs/routes.
- [ ] Run relevant sizing/config/economic suites and commit.

### Task 3: Executable capital-plan and reviewed foundation release

**Files:** cli/etf_capital_research.py; tests/integration/cli/test_etf_capital_plan.py; docs/etf-capital-research.md.

**Interfaces:** python -m trading_bot.cli.etf_capital_research capital-plan prints bounded, sanitized canonical report. No capture, credentials or write transport.

- [ ] RED CLI tests for six exact tiers, realistic recurring-cost sensitivity and unchanged production/admission flags; output unknown customer costs as unknown.
- [ ] Implement CLI from Task1/2 contracts; document actual capabilities and remaining stages.
- [ ] Full exact-head suite/native coverage/80+90 gates, Ruff/Mypy/Bandit/locks/SBOM/manifests and independent whole-candidate review. Preserve partial/failed runs as non-certification.
- [ ] Review findings RED→GREEN, commit, integrate only after all exact-head required checks pass under standing merge authority.

### Task 4: Multi-symbol daily intake

**Interfaces:** new versioned bounded requests/archive manifest/dataset contracts; preserve SPY v1 readers/hashes and receipts. Consumes frozen capital policy/universe; produces visible per-session raw bars, normalized features and distribution facts with explicit limitations.

- [ ] Fixture-first pagination, duplicates, missing sessions, symbol mismatch, calendar/DST, actions/distributions and availability/basis tests.
- [ ] Generalize only new namespace; reuse raw capture/receipt and private publication primitives. No acquired bytes rewritten.
- [ ] Verify free historical SIP access only through separately authorized bounded capture; absent access blocks capture, not fixture work. Never buy a plan or substitute IEX as SIP.
- [ ] Verify source/protocol hashes and integrated regressions; freeze source coverage before outcome evaluation.

### Task 5: Single-position strategies and walk-forward economics

**Interfaces:** typed capital study/scenario/fold/selection/report, one shared account reducer, no live factories. Reuse existing MomentumStrategy, protection/accounting/metrics where behavior is compatible; do not unlock legacy study classes.

- [ ] Fixture-first literal independent entries/exits, switches, costs, settlement, partial/unfilled events, gap protections, no terminal fills, prefix recovery and deterministic identities.
- [ ] Implement approved momentum pairs, RSI2 thresholds, volatility-adjusted rotation and holding2/5/10/20; no unregistered candidates.
- [ ] Add five126-session purged folds, rolling750 train/20-session embargo, train-only selection and position-policy carryover.
- [ ] Add four round-trip friction levels, six independent account trajectories, operations/tax/benchmark separation and dependent/selection-adjusted statistics.
- [ ] Freeze exit-only tail using maxhold20 + next-eligible-order event + maximum historical settlement delay before outcomes; unresolved tails remain incomplete.
- [ ] Exact-source integrated review/verification and immutable preregistration before one development evaluation. Historical independence remains unverified.

### Task 6: Conditional regime study

- [ ] Only when standalone families have supporting evidence, add the spec's one preregistered regime composition using training-selected family winners.
- [ ] Fixture-first prior-data regime/volatility/median controls, no absent-family fallback or holdout selection.
- [ ] Separately freeze/evaluate; compare incremental uncertainty against simpler candidates. If none survive, record NO-GO and skip unnecessary operations expansion.

### Task 7: Conditional trusted paper/shadow and recovery

- [ ] Only a survivor can justify this task. Implement durable one-writer paper owner and recorded genuine observations using existing journal/reservation/reconciliation seams.
- [ ] Verify documented/account/session/runtime capabilities separately; real adapters remain locked without corresponding authority/evidence.
- [ ] Test rejection/partial/cancel races/ambiguous acceptance, stale quotes/leaders, restart, actual alert delivery and backup restoration without extra exposure.
- [ ] Distinguish Alpaca paper, fake execution and Robinhood assumptions. Keep existing promotion quotas and startup paused.

### Task 8: Prospective final test and handoff

- [ ] Freeze one candidate for126 eligible future sessions; do not start until exact source/config/data/operation identities are established.
- [ ] No early statistical acceptance, automatic extension, forced trades or parameter changes. Unknown/missed observations stay unknown.
- [ ] Produce capital-specific separate economic/data/broker/operations/authority verdicts, artifact identities, limitations and next steps. No survivor => cash/passive consideration; live remains separately authorized.

## Execution status

Approved conversational plan materialized without another approval round. Task1
profile has14focused and534regression passes; its full suite is still running.
Task2 contract tests were watched RED for the absent module, without changing
product source during Task1 verification. No economic result or authenticated
integration is established. Tasks4–8 remain planned and conditional.
