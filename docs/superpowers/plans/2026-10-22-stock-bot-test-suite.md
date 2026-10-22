# Stock Bot Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task, with one fresh whole-branch review after integration. Steps use checkbox syntax. The operator already authorized implementation and autonomous routine work; no additional handoff approval is required.

**Goal:** Remove obsolete asset-specific test suites and make local/CI verification cover the current stock bot and its shared safety components.

**Architecture:** Preserve the verified producer baseline, use the existing isolated checkout on a new branch, separate reused loss-state types, physically retire obsolete tests/fixtures, then align standard pytest/coverage and CI. Do not delete production strategies or change application behavior.

**Tech Stack:** Python3.12, Pytest, coverage.py/pytest-cov, TOML, GitHub Actions, existing locked tools.

**Spec:** `docs/stock-bot-test-scope.md`

## Global Constraints

- Work in hybrid-stock-sec-submissions on codex/stock-bot-test-suite, basee2960a4d77ea2383f1eac1601b6fc82c50fc2b54; preserve original branch and evidence.
- No provider, credential, native Docker, deployment, live-mode or brokerage operations.
- No risk arithmetic/fields/defaults/authorization/schema changes; retain former loss-type import aliases.
- Preserve80% aggregate,90% critical per-file branch and95% combined stock-host coverage gates.
- Physical retirement is auditable in Git; do not hide obsolete suites behind pytest deselection.
- Root owns shared risk/integration and coverage decisions; independent inventories are read-only. One final review, one Important/Critical fix pass with observed RED/GREEN; defer minors.

## Review Focus

- A legacy filename can contain a current loss/finality safeguard: Task1 neutral loss-state and equity-projection tests must preserve it.
- A retained test can import a retired test module: Task2 collection and orphan-reference guards must fail before acceptance.
- Coverage can become green by omitting unexecuted stock modules or lowering a gate: Task2 membership, missing-module and counter tests must deny that.
- A default or CI command can still invoke a retired options environment/test: Task3 workflow/default-command tests must reject that.
- Benchmarks and unsupported-asset rejection are part of the stock bot despite ETF/options names: Task2 retention guards must keep them.

## Task 1: Preserve shared loss accounting

**Files:** Create `src/trading_bot/risk/trial_losses.py`, `tests/unit/risk/test_trial_losses.py`; modify `risk/options_economics.py`, `accounting/owned_economic_projection.py`.

**Interfaces:** Preserve exact TrialEpisode/TrialLossState fields, validation/properties/remaining behavior and original import aliases; equity projection consumes the neutral module.

- [ ] Write tests for profits not refilling consumed loss, unsettled/pending reservation, invalid/duplicate episodes and identical old/new class aliases; run and observe missing-neutral-module RED.
- [ ] Move the two unchanged types and update the equity projection import, retaining legacy reexports.
- [ ] Run neutral loss tests plus owned economic/accounting/persistence and stock/hybrid risk checks; expected pass with no behavior/default changes. Run targeted Ruff/mypy.
- [ ] Commit owned files and record actual result.

## Task 2: Retire legacy suites and align coverage

**Files:** Retire audited legacy tests/fixtures; modify mixed service/prediction/checker tests, `pyproject.toml`, `scripts/check_critical_branch_coverage.py`; add `tests/smoke/test_stock_bot_test_scope.py`.

**Interfaces:** pytest/default tests root remains tests; standard coverage sources include retained stock/shared Python and host modules, documented legacy exclusions; checker keeps its report/root API and fail-closed validations.

- [ ] Write scope/membership and retained-safety guards; observe RED against existing legacy files/coverage discovery. Preserve generic checker invalid/missing/duplicate/path/branch/counter cases.
- [ ] Materialize and inspect the exact retirement manifest; remove legacy suites/helpers and the mixed ETF observer/positive prediction cases; keep asset-denial and benchmark tests.
- [ ] Replace legacy coverage membership with stock/shared membership; preserve80/90/95 gates and include entire stock modules, not imported lines alone.
- [ ] Run collection without providers and narrow scope/checker/loss tests; expected no legacy test collection or missing imports, passing integrity checks. Fix actual ownership/import failures without suppressing them.
- [ ] Commit scoped changes and record exact collected/removed counts and actual checks.

## Task 3: CI, documentation and final stock verification

**Files:** Modify `.github/workflows/ci.yml`, remove `options-research.yml`, update relevant smoke tests, README/AGENTS/current testing docs; retain historical result labels.

**Interfaces:** CI and documented default use the same retained suite and coverage configuration; dashboard checks remain; no options research install/append or inactive old deployment checks.

- [ ] Write/update workflow assertions; observe old options append/environment contract RED before changing CI.
- [ ] Align CI and documentation, marking legacy operational test commands historical. Retain locked dependency/security and applicable configuration checks.
- [ ] Run the complete NEW retained stock/shared suite once with branch JSON coverage and unchanged gates, then run the critical/host checker. Expected pass; inspect skips/warnings and disclose scope/time/count.
- [ ] Run Ruffall, strict mypy, expanded Bandit, offline lock and diff checks; expected pass, record actual evidence.
- [ ] Commit and obtain one fresh review of e2960a4..HEAD against this spec and all root rulings; fix Important/Critical with observed RED/GREEN and relevant full retained suite, without another legacy run.
- [ ] Preserve final evidence and complete the engineering audit. Keep branch local under current no-push/no-deployment scope; report remaining operational/investment gates and next steps.
