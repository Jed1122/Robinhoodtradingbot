# ETF Execution Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record local execution-observation receipts and verify causal linkage to exact Alpaca quote bytes without enabling broker writes.

**Architecture:** A private durable transport-free sink owns sampling and hash chains. A pure offline verifier derives existing cost inputs from retained sources and a separate CLI publishes unqualified reports.

**Tech Stack:** Existing Python, Decimal, canonical JSON and owner-private bundle storage; no new dependencies.

**Spec:** docs/superpowers/specs/2026-10-04-etf-execution-receipts-design.md

## Global Constraints

- Preserve existing cost-observations-v1 schema and old hashes.
- No credential/network/broker/deployment calls, risk changes or live activation.
- No account/order identifiers in receipts; raw sources private only.
- 1 MiB bodies, 8 MiB total retained sources, 10,000 events.
- Explicit maximum quote age; preserve unverified, nonpromotable output.

## Review Focus

- Storage uncertainty must poison the writer rather than create apparently complete evidence.
- Equal clock values must not permit future event-order lookahead.
- Duplicate execution deliveries must not double-count fees or fills.
- Mutated source bytes and cross-session receipts must fail closed.
- Pending/rejected/unfilled outcomes must remain distinct from completed filled samples.

### Task 1: Pure receipt verifier and quote linker

**Files:** Create `src/trading_bot/research/etf_execution_receipts.py`; test `tests/unit/research/test_etf_execution_receipts.py`.

**Interfaces:** `link_execution_receipts(session: bytes, receipts: tuple[bytes, ...], sources: dict[str, bytes]) -> dict[str, object]` returns an existing cost input plus counts and permanently false readiness flags. Session fixes quote-age bound and provenance. Receipt and source schemas are defined by the spec.

- [ ] Write failing fixture tests for exact decision/arrival quote derivation, partial-fill VWAP and reconciled terminal fees.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/research/test_etf_execution_receipts.py`; expect missing module/implementation failures.
- [ ] Implement strict hash/clock/sequence/lifecycle checks and existing-parser quote derivation.
- [ ] Add adversarial tests for five Review Focus classes plus quote/fee boundaries; run them green.
- [ ] Commit only this task's code/tests.

### Task 2: Durable contemporaneous receipt sink

**Files:** Create `src/trading_bot/diagnostics/etf_execution_receipts.py`; test `tests/unit/diagnostics/test_etf_execution_receipts.py`.

**Interfaces:** `EtfExecutionReceiptRecorder(root: Path, repository_root: Path, *, code_revision: str, maximum_quote_age_ns: int, provenance: str = "paper", utc_now: Callable[[], datetime], monotonic_ns: Callable[[], int], nonce: str | None = None)`. `retain_source(body: bytes) -> str`, `record(kind: str, payload: dict[str, object]) -> str`, `checkpoint() -> str`, `close() -> None`. `read_execution_receipts(root: Path, manifest_hash: str, repository_root: Path) -> dict[str, object]` consumes Task 1.

- [ ] Write failing private-directory tests for clock sampling, immutable checkpoints and reconstruction of incomplete prefixes.
- [ ] Run the new diagnostics test; expect missing implementation failures.
- [ ] Implement using existing `_open_root`, `_read`, `_publish`; poison after failures and never resume a prior session.
- [ ] Test regression, source limits, symlinks, unsafe modes, conflicting publication and failed writes; run both task suites green.
- [ ] Commit only this task's code/tests.

### Task 3: Offline command and integrated handoff

**Files:** Modify `src/trading_bot/cli/etf_observations.py`, `docs/alpaca-execution-observations.md`, `Codex.md`; test `tests/unit/cli/test_etf_execution_receipts_cli.py`.

**Interfaces:** `link-costs --input-root PATH --manifest-hash SHA --report-dir PATH` binds clean code, reads Task 2, publishes normalized input/reference sources and descriptive report. Intentional unqualified exit 2; invalid input exit 1.

- [ ] Write failing CLI tests for deterministic private publication, incomplete samples, invalid manifest and no credential/network access.
- [ ] Run the CLI test red; implement the command via existing calibration/report helpers; run all receipt/calibration/CLI tests green.
- [ ] Update limitations and usage without claiming customer or paper qualification.
- [ ] Run Ruff, Mypy, full tests with branch coverage, Bandit, lock check and diff check. Expect all applicable gates pass; report external blockers accurately.
- [ ] Commit, obtain fresh whole-diff review, fix material findings test-first, and finish integration without bypassing required checks.
