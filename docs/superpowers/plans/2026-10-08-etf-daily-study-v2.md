# Corrected-evaluator ETF development study execution plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Native execution is retained; steps are bounded operation/verification, not new product-code implementation.

**Goal:** Complete one newly identified private DEVELOPMENT screen of the unchanged fixed SPY/cash candidate under economic protocol v2.

**Architecture:** Reuse the existing canonical loader, receipt readers, daily request, strategy/account owner and economic evaluator. The existing CLI publishes preregistration before evaluation and private content-addressed reports; no production behavior changes.

**Tech Stack:** Existing frozen Python environment, Decimal and owner-private JSON reports.

**Spec:** `docs/superpowers/specs/2026-10-08-etf-daily-study-v2-design.md`.

## Global constraints

Use exact source baseline bc49e1104a5c3c3d2498df6ea39ecc6f008e9bc1. Keep all source/config/tests/locks/workflows byte-identical, unchanged risk/criteria/scenarios, no holdout outcome evaluation and all eligibility false. No broker/provider/credential/customer/spending/deployment operations. Old reports are immutable and invalid for current-code economics. This is a fresh authorized study, not revival of old integration follow-ups.

## Review focus

Apply all five focus items in the spec: identity separation, holdout exclusion, frozen criteria/costs, truthful missing/incomplete fields, and private input/report boundaries.

### Task 1: Freeze the operation and validate existing contracts

**Files:** this plan and its spec; main-only own scratch/ledger.
**Interfaces:** consumes the approved lean plan and fixed existing `daily-screen-run` contract; produces committed freeze and a passing fresh synthetic verification record.

- [ ] Verify clean isolated branch and current compatible merged source; hash input identities and original reports without reading prior outcomes.
- [ ] Commit the unchanged-rule operation freeze. Expected: human documentation only; source/config/tests/locks/workflows identical to baseline.
- [ ] Run `env PYTHONPATH=src uv run --frozen pytest -q tests/unit/research/test_etf_daily_protocol.py tests/unit/research/test_etf_daily_protocol_adversarial.py tests/unit/research/test_etf_daily_intake.py tests/unit/research/test_etf_daily_economics.py tests/unit/research/test_etf_daily_economics_adversarial.py tests/unit/simulation/test_etf_daily_screen.py tests/unit/simulation/test_etf_account.py tests/unit/simulation/test_etf_account_incremental.py tests/unit/simulation/test_etf_history.py tests/unit/risk/test_sizing.py tests/integration/cli/test_etf_daily_screen_cli.py tests/smoke/test_critical_branch_coverage.py tests/architecture/test_broker_imports.py`. Expected: all pass, no authenticated calls.
- [ ] Independently review the public freeze/existing contract with fabricated fixtures only. Resolve any substantive defect before market outcomes; source changes require a new freeze and regression, never holdout tuning.

### Task 2: Run and privately verify the frozen study

**Files:** a fresh private report directory outside all repositories; main-only verification record.
**Interfaces:** consumes frozen input hashes/config and existing CLI; produces new preregistration and all24 scenario reports with their code/config/input/protocol identities.

- [ ] Create a new current-user0700 private report directory; do not reuse the old study root.
- [ ] Invoke the documented `daily-screen-run` once with exact hashes/private paths in the main-only record. Expected: exit0, preregistration then report, sanitized stdout, all eligibility false.
- [ ] Independently verify hashes/ownership0600/0700, identity links, date boundaries, all24 scenario combinations, Decimal costs/fees/sizing conservation and verdict criteria. Compute expectations from this report, not old verdict counts.
- [ ] Rehash original reports and input reference bytes after evaluation. Expected: unchanged identities. No private source/report is delegated.

### Task 3: Record the truthful decision and handoff

**Files:** new sanitized study-status documentation, authoritative transition checkpoint and private derived summary.
**Interfaces:** consumes verified study results; produces a completion/rejection/insufficiency handoff and conditional next steps, never economic admission.

- [ ] Keep monetary results private; publish only code/hash/verification/status/limitation metadata in Git.
- [ ] Update the authoritative checkpoint with actual completion and current verdict. Stop candidate expansion if no scenario proceeds; do not repeat evaluation to select a winner.
- [ ] Verify documentation/diff and unchanged executable identities; record review exclusions and any rulings/cost-if-wrong. Preserve the ledger and all reports recoverably.

No failing production test is invented for an already implemented operational command. If a feature/bug fix becomes necessary, TDD and full exact-candidate release checks apply before outcomes. No private study rerun follows a changed source without a separately frozen identity.
