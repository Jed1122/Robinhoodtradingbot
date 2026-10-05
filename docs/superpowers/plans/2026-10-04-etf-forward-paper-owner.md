# ETF forward paper owner implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native execution is the operator's standing choice.

**Goal:** Build a versioned growing forward economic owner with fail-closed joint recovery, then reassess retained source/cost inputs honestly.

**Architecture:** Separate forward models from sealed historical wrappers; reuse the common account reducer. Publish full causal tape and reconstructed economics together under one private single-host owner. No trading-capable or promotion factory is added.

**Tech Stack:** Python 3.12, frozen Decimal/domain models, canonical configuration, existing atomic artifact publisher/flock, pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-etf-forward-paper-owner-design.md`

## Global Constraints

- Preserve historical v1 dates/types/hashes and canonical $100 risk reference/$1,000 ceiling/$50 cumulative trial cap.
- Forward window on/after 2026-01-01 UTC, maximum 31 days; hypothetical cash $500 or $1,000.
- Maximum 1,000 cycles, 10,000 economic events, 8 MiB joint artifact. Tape
  admission includes replayed state and envelope in this unchanged byte budget.
  The bounded journal directory also accommodates one retained crash alias per
  published owner/claim/joint, without adopting aliases or clearing claims.
- Source progress and account mutation have separate cursors; no native data relabeling.
- Always paused/nonqualifying; no broker, credentials, deployment, spending or promotion-store writes.
- All implementation is coordinator-owned; agents only inspect public contracts/tests.

## Review Focus

- Deleted intermediate or final commits must deny against retained expected head, never recreate an empty account.
- An unresolved pre-effect claim must block new inputs even when no commit exists.
- A source-only cycle must survive restart without consuming an economic cursor.
- Changed future suffix must not alter prior joint heads or re-execute prior effects.
- Complete input replay must retain trial-loss and drawdown latches across recovery.

### Task 1: Versioned forward economic cycle contract

**Files:**
- Create: `src/trading_bot/runtime/etf_forward_paper.py`
- Modify: `src/trading_bot/simulation/etf_account.py` (private shared reducer only)
- Test: `tests/unit/runtime/test_etf_forward_paper.py`

**Interfaces:**
- Consumes: `EtfStudy`, `_policy(study)`, `EtfAccountEvent`, common `_run(request, count)`.
- Produces: `ForwardPaperPlan(policy: EtfStudy, starts_at: datetime, ends_at: datetime, initial_cash: Decimal)`; `ForwardPaperCycle(at_ns: int, received_monotonic_ns: int, source_hash: str, strategy_state_hash: str, events: tuple[EtfAccountEvent, ...])`; `ForwardPaperTape(plan, cycles)`; `replay_forward_paper(tape) -> ForwardPaperState`.

- [ ] Write tests: forward 2026 lifecycle cash `499.88`, losses `.12`, sealed `EtfAccountRequest` rejects same events; $1,000 remains $100 risk reference; source-only, duplicate/conflicting fills, pending and unsettled prefixes; future suffix identity stability; malformed/forged values denied.
- [ ] Run `PYTHONPATH=src .venv/bin/pytest -q tests/unit/runtime/test_etf_forward_paper.py`; expected RED for missing forward owner.
- [ ] Implement frozen forward models and protocol-bound private account reducer origin seam; leave public historical validators unchanged.
- [ ] Run same tests plus `tests/unit/simulation/test_etf_account.py`; expected PASS.
- [ ] Commit `feat: add versioned forward paper economic contract`.

### Task 2: Atomic joint-state ownership and restart

**Files:**
- Create: `src/trading_bot/persistence/etf_forward_paper.py`
- Test: `tests/integration/persistence/test_etf_forward_joint_recovery.py`
- Modify/Test: `scripts/check_critical_branch_coverage.py`, `tests/smoke/test_critical_branch_coverage.py` (include both new safety-critical owners in the existing 90% gate)

**Interfaces:**
- Consumes: Task 1 exact models/replay.
- Produces: `advance_forward_paper(root: Path, tape: ForwardPaperTape, *, repository_root: Path, expected_head: str) -> ForwardPaperCheckpoint`; `recover_forward_paper(root, tape, *, repository_root, expected_head) -> ForwardPaperCheckpoint`.

- [ ] Write real-filesystem tests for source/economic joint state, each prefix restart, stale/missing head, conflict, plan drift, pending claim, concurrent flock, symlinks/modes, corrupt and missing commits, publication/sync faults, separate-process recovery and unchanged old namespaces.
- [ ] Run `PYTHONPATH=src .venv/bin/pytest -q tests/integration/persistence/test_etf_forward_joint_recovery.py`; expected RED for missing persistence owner.
- [ ] Implement new descriptor-bound namespace with pre-effect claims and atomic full-prefix commits, mandatory expected head, full replay comparison and recovery without advancement.
- [ ] Run both new test files and account/journal suites; expected PASS.
- [ ] Commit `feat: persist joint forward paper prefixes and recovery`.

### Task 3: Qualification assessment and validated handoff

**Files:**
- Create: `docs/etf-forward-paper-owner-2026-10-04.md`
- Modify: `docs/architecture.md`, `docs/limitations.md`, `docs/disaster-recovery.md`
- Private reports: existing approved evidence root only; never Git/Cloud/agents.

**Interfaces:**
- Consumes: committed Task 1/2 head, retained hashes/archives and existing offline assessment/calibration CLIs.
- Produces: separate source/cost/software/recovery verdicts; no qualification flags or economic acceptance changed.

- [ ] Inspect/reconcile private existing inputs once; rerun native historical coverage qualification and cost calibration. Expected `BLOCKED_INPUTS` when evidence absent; preserve private artifact hashes/modes and current code identity.
- [ ] Document implemented versus blocked boundaries and exact next dependencies.
- [ ] Run Ruff/Mypy/Bandit, both frozen locks, dependency audit, full pytest branch coverage with existing 80%/90% gates and deployment-manifest checks; expected PASS or explicit external/optional skip.
- [ ] Commit documentation; generate exact-base whole-branch review package and dispatch one fresh read-only reviewer. Fix Important/Critical findings RED→GREEN, rerun full regression; retain Minor/ruling record.
- [ ] Publish scoped PR against established integration target under standing authority, inspect current exact-head CI before merge; do not wait for CI to continue independent work.
