# Verified Alpaca Observation Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native execution is the standing preference.

**Goal:** Expose reverified receipt-ordered Alpaca records and causal prefixes without granting source or runtime qualification.

**Architecture:** One private verifier serves the unchanged aggregate audit and a bounded typed reader. Pure immutable models own visibility; the existing offline CLI owns private report publication.

**Tech Stack:** Python 3.12+, Decimal, existing frame parser and descriptor-bound private store; no dependencies.

**Spec:** docs/superpowers/specs/2026-10-04-alpaca-observation-reader-design.md

## Global Constraints

- Qualification/execution/promotion/live remain false. No broker, network, credentials or deployment changes.
- Typed retention: at most 10,000 observations, existing 10,000 frames and 32 MiB raw bounds; no truncation.
- Preserve audit-v2 wire and hashes; status/LULD remain raw and provider time is never receipt visibility.
- Use existing private 0700 roots and 0600 files; commit only synthetic tests and public code/docs.

## Review Focus

- A readdressed contradictory receipt must still fail semantic verification.
- Provider timestamps can arrive out of order without moving records into an earlier receipt prefix.
- Empty frames and failed/v1 collection windows must not manufacture observations or clock evidence.
- Different capture segments must never share monotonic clocks or gain continuity from predecessor hashes.
- Oversized typed retention must fail atomically while the aggregate audit keeps its prior bounds.

### Task 1: Shared verified typed reader

**Files:** Create `src/trading_bot/market_data/alpaca_observation_capture.py`; modify `src/trading_bot/diagnostics/alpaca_observe.py`; extend `tests/unit/diagnostics/test_alpaca_observe.py`.

**Interfaces:** `read_observation_capture(root: Path, result_hash: str, repository_root: Path) -> AlpacaObservationCapture`. `AlpacaObservationFrame` and `AlpacaObservationCapture` exact schemas from the spec. `capture.visible_frames(*, received_at_ns: int, received_monotonic_ns: int) -> tuple[AlpacaObservationFrame, ...]`.

- [ ] Write reader/visibility tests first: literal q/s/l field and clock expectations; preserved receipt order; both clocks required; limits/forgery/private/tampered bytes denied; existing audit behavior unchanged.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/diagnostics/test_alpaca_observe.py`; expect missing reader failures before implementation.
- [ ] Implement immutable bounded models and shared `_verify_observation_capture(..., retain_frames: bool)`; existing audit requests no retention. The reader requires a completed verified capture result and never reads credentials.
- [ ] Rerun the task test file, existing stream parser and receipt tests; expect all pass, including unchanged audit-v2 outputs.
- [ ] Commit only owned source/test paths.

### Task 2: Offline prefix report and documentation

**Files:** Modify `src/trading_bot/cli/etf_observations.py`, `docs/alpaca-execution-observations.md`, `Codex.md`; create `tests/unit/cli/test_alpaca_stream_prefix_cli.py`.

**Interfaces:** Consume Task 1 reader/visibility. Command `stream-prefix --input-root PATH --result-hash SHA --received-at-ns N --received-monotonic-ns N --report-dir PATH` publishes `alpaca-observation-prefix-report-v1` through the existing private publisher.

- [ ] Write tests for missing command, exact dual-clock selected counts/hashes, deterministic private report, empty prefix, tampering and clean-revision-before-read.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/cli/test_alpaca_stream_prefix_cli.py`; expect missing command failures.
- [ ] Implement command with sanitized errors/status-only stdout, exit 2 for valid unqualified results and no credential/network operations.
- [ ] Rerun new and existing observations CLI tests; update docs with truthful use and remaining prerequisites.
- [ ] Run Ruff/Mypy/full pytest/Bandit/lock checks and independent exact-diff review before integration. Preserve skipped/external checks explicitly.
- [ ] Commit only owned paths; integrate only after current required CI passes. No deployment follows the merge.
