# Lean daily ETF development screen implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax; the operator selected native execution and waived repeated approval questions.

**Goal:** Produce a separately frozen, bounded daily-price strategy simulation, then a private development comparison; never economic admission or broker execution.

**Architecture:** A new immutable research protocol binds the existing canonical ETF study, session/source/distribution/code identities and explicit daily execution assumptions. A primary-owned daily scheduler reuses FeaturePipeline, MomentumStrategy, sizing and EtfAccountStepper; it emits assumed account facts, not fabricated market quotes. Existing benchmarks/statistics remain independent descriptive references.

**Tech Stack:** Python, Decimal, frozen dataclasses, existing canonical configuration and synthetic fixtures. No dependency changes.

**Spec:** `docs/etf-lean-delivery-plan-2026-10-07.md`, task 2, and `docs/operator-authority.md`, October 7 amendment.

## Global constraints

- First decision anchor 2016-05-26, 100 completed prior session bars, fixed five-session cadence. Preserve the full 20/100 predicate and canonical ATR multiplier 2.0, reward multiplier 2.0, maximum holding 100 and regime exits. Legacy 750-bar contract unchanged.
- No 2024–2025 outcome inputs. Sessions and bars must be bounded, increasing and identity-bound. A missing execution session interrupts the simulation, not an invented fill or shifted schedule.
- Keep raw execution prices separate from feature normalization; initial supported projection explicitly assumes unadjusted prices/no splits. Unknown price/action basis cannot support screening conclusions.
- Next-session adverse open execution; stop gaps use worse opens; stop wins ambiguous daily ranges. Fees once. No terminal forced sale, additions, or invented settlement. T+2 is an explicit conservative research assumption, not verified brokerage timing.
- Retain $100 risk reference, $0.50 stop-risk budget, $15 order cap, full premium/cash and whole-episode fee reservations, 80% cash and $50 cumulative trial ceiling. Shared owner may deny a proposed generic size; never resize around its denial.
- All source/customer-cost/execution/economic/promotion/live flags remain false. Hypothetical fractional terms are unverified, not broker capability.

## Review focus

- Prefix changes and future rows must not change earlier decisions, fills or reservations.
- Fee reserve must remain whole-episode and must deny even when fee-exclusive sizing allows.
- Ex-date entitlement must precede same-day entries; outstanding payments/settlements prevent episode completion and reentry.
- Missing sessions and terminal open positions remain incomplete rather than cash-equivalent completed results.
- Ambient Decimal precision and unsafe dataclass mutation must not change results or eligibility flags.

### Task 1: Frozen daily protocol and input contracts

**Files:** create `src/trading_bot/research/etf_daily_protocol.py`; test `tests/unit/research/test_etf_daily_protocol.py`.

**Interfaces:** consumes `EtfStudy`, canonical `_policy`, `Bar`, `EtfBenchmarkDistribution`; produces `EtfDailyProtocol`, `EtfDailyBar`, `EtfDailyRequest`, and sanitized `EtfDailyError`.

- [ ] Write failing tests for fixed anchor/warmup/holdout denial, hashes, full canonical identity, bounded OHLC/paired feature bars, fractional assumptions and permanent false markers.
- [ ] Run `PYTHONPATH=src uv run --frozen pytest -q tests/unit/research/test_etf_daily_protocol.py`; expected missing module failure.
- [ ] Implement immutable contracts with exact type/value revalidation, no independent config loader. Accept a distinct explicit raw/no-splits assumption, never qualify it.
- [ ] Rerun same command; expected all pass. Commit protocol/tests.

### Task 2: Daily strategy/account vertical slice

**Files:** create `src/trading_bot/simulation/etf_daily_screen.py`; test `tests/unit/simulation/test_etf_daily_screen.py`.

**Interfaces:** consumes task 1 request; produces `run_etf_daily_screen(request) -> EtfDailyResult` with decisions, marked points, assumed account event tape and final shared account state.

- [ ] Write failing exact-cash fixture tests: next-open entry, stop-gap, stop-first ambiguity, whole-episode fees/reserves, distributions, T+2, no terminal sale, missing input, no additions, fixed cadence, max hold/regime exits, prefix invariance and restart reconstruction.
- [ ] Run the new tests; expected missing runner failure.
- [ ] Implement using shared features/strategy/sizing/account and explicit assumed pending/ack/fill events. Probe admission without poisoning the active stepper. Reconstruct every final account from its event tape.
- [ ] Run protocol/runner/account/history/sizing subsets; expected all pass. Commit runner/tests.

### Task 3: Private economic comparison and publication

**Files:** new `src/trading_bot/research/etf_daily_economics.py`; scoped CLI addition in `src/trading_bot/cli/etf_research.py`; fixture and CLI tests.

**Interfaces:** consumes frozen protocol and task 2 result; produces separate trading/operating profit, matched cash/constrained buy-hold, turnover/drawdown/cost stress, paired uncertainty and screening verdict REJECT/PROCEED_TO_FURTHER_RESEARCH/INSUFFICIENT_EVIDENCE.

- [ ] Freeze costs (0/5/25bps, explicit fees/reserve), $500/$1000 tiers, recurring/sunk separation, zero cash yield, effective-opportunity limitations and criteria before outcome evaluation. Reuse canonical stricter research thresholds; dependent daily counts alone never establish independent opportunities.
- [ ] Fixture-first tests for costs once, comparisons, incomplete/unknown inputs, deterministic uncertainty and non-admission. Expected RED then GREEN.
- [ ] Add bounded private CLI capture projection using existing receipt/calendar/distribution validators; no network, credentials or holdout price evaluation. Publish preregistration before report, content-addressed0600 outside Git.
- [ ] Verify relevant regression, Ruff/Mypy/Bandit/locks, full suite/coverage/critical gates and fresh integrated review. Only then evaluate the private development inputs. Record remaining gaps explicitly. Commit scoped changes.

Tasks 1–2 are independently useful fixture-backed software; completing them is not completing task 3. No real outcomes will be read during task 1–2. No eligibility, deployed recovery or profit claim follows from any task.
