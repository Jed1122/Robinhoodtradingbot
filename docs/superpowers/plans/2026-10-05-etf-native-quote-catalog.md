# Bounded Native ETF Quote Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish and traverse a separately versioned, receipt-bound native quote
catalog without whole-history quote materialization or a new trading capability.

**Architecture:** Two-level immutable day/study indexes reference original private
captures. Reuse the existing complete receipt reader once per capture and stricter
private storage helpers; emit native quote occurrences, not market controls/orders.

**Tech Stack:** Python, frozen dataclasses, exact Decimal/ns, existing JSON codecs
and descriptor-relative local storage; no dependency changes.

**Spec:** `docs/superpowers/specs/2026-10-05-etf-native-quote-catalog-design.md`

## Global Constraints

- Alpaca-only SPY/SIP latest-vintage source, historical controls/gaps unobserved.
- Day index at most 1,024 captures; study at most 4,000 days; each JSON at most 1 MiB.
- Original native capture/archive/replay/risk/configuration identities remain unchanged.
- Source/cost qualification, execution and promotion remain false; no broker calls.
- Private artifacts outside every Git checkout; owner 0700 directories/0600 files;
  reject symlinks, hardlinks, devices, outward references and unknown wire fields.
- Iterator bounds are explicit half-open nanoseconds; no historical availability
  or OPEN/control events fabricated; selected-prefix failures are incomplete.

## Review Focus

- Corrupt final selected capture denies before first occurrence; later mutation
  must raise rather than certify a completed prefix (Task 2).
- Same-time identical quotes are preserved, not dropped as duplicate prices (Task 2).
- Future/holdout raw captures outside selection are never opened (Task 2).
- Dirty false flags, bool-as-int, unknown schemas and over-limit indexes deny (Task 1).
- Symlink/hardlink/private-root substitution and immutable publication conflicts
  never expose private input or overwrite an artifact (Task 2).

---

### Task 1: Exact new catalog models and codecs

**Files:**
- Create: `src/trading_bot/market_data/etf_quote_catalog_models.py`
- Test: `tests/unit/market_data/test_etf_quote_catalog_models.py`

**Interfaces:** Produces the spec's location/reference/day/catalog/occurrence
models, `encode_day/decode_day`, `encode_catalog/decode_catalog`, `day_hash` and
`catalog_hash`. Consumes existing strict JSON/Decimal/native record/hash primitives.

- [ ] **Step 1:** Write tests for deterministic round-trip, disjoint adjacent/gapped
  intervals, exact ns/Decimal native occurrence, sorted unique days and false flags.
  Assert literal gaps remain accepted-but-unqualified and overlapping bounds deny.
- [ ] **Step 2:** Run `pytest -q tests/unit/market_data/test_etf_quote_catalog_models.py`;
  expected RED because the module/interfaces are absent.
- [ ] **Step 3:** Implement the frozen models/codecs with exact field/type bounds,
  canonical hash domains `etf-native-quote-day-v1` and `etf-native-quote-catalog-v1`.
- [ ] **Step 4:** Run the model tests; expected zero failures. Include dirty nested
  flags, duplicate JSON keys, floats, booleans, invalid paths/counts and oversize bodies.
- [ ] **Step 5:** Commit only the new model/test files and record results in the ledger.

### Task 2: Private catalog publication, reads and bounded iteration

**Files:**
- Create: `src/trading_bot/market_data/etf_quote_catalog.py`
- Test: `tests/unit/market_data/test_etf_quote_catalog.py`
- Create: `docs/etf-native-quote-catalog.md`
- Modify: `PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md`
- Modify: `docs/operator-authority.md` (record the conditional trade grant accurately)

**Interfaces:** Consumes Task 1 models/codecs and existing
`read_etf_native_quote_pages`, strict private file/root helpers and canonical config.
Produces `publish_quote_day`, `publish_quote_catalog`, `read_quote_catalog`,
`iter_catalog_quotes` with the exact spec signatures. No existing consumer changes.

- [ ] **Step 1:** Use complete synthetic native receipt fixtures to write tests for
  two days/two adjacent captures, stable native ties, partial selections and late
  selected corruption before first yield. Expected literal row counts/price/ns
  come from fixture rows, not the catalog builder.
- [ ] **Step 2:** Run `pytest -q tests/unit/market_data/test_etf_quote_catalog.py`;
  expected RED because storage/iterator APIs are absent.
- [ ] **Step 3:** Implement immutable private indexes, receipt/identity validation,
  selected-capture preflight and one-capture-at-a-time reread/iteration. Reject
  metadata/capture mismatch, duplicates, overlap, links/modes/Git-root aliases.
- [ ] **Step 4:** Add and run regressions for all Review Focus cases, credential/network
  denial, missing day/raw files, nonselected future raw corruption, idempotent
  publication and config/live-mode denial; expected all pass with sanitized errors.
- [ ] **Step 5:** Run catalog/native/archive/replay tests, Ruff/Mypy and full default
  pytest with unchanged coverage gates; run frozen locks/Bandit/SBOM/manifests.
  Preserve output under this plan's scratch and report skipped/external checks.
- [ ] **Step 6:** Update docs with callable examples, bounded-not-page-streaming
  limitations and independently unfinished replay/economics/trade gates; commit.
- [ ] **Step 7:** Obtain a fresh whole-branch review, fix Important/Critical findings
  RED-to-GREEN, rerun verification and record exact candidate. Only then reverify
  the existing private five-minute capture with a clean committed catalog candidate.

No task in this plan claims whole-study replay, accepted economics, customer-cost
calibration, runtime readiness, eligible paper/shadow cycles or live trading.
