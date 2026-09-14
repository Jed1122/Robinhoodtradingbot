# RESEARCH-GAPS-001: research-evidence gap review

## Scope and disposition boundary

This is a documentation-only, point-in-time review of commit
`a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`. It observes existing behavior and proposes
deterministic evidence tests; it does **not** change or approve any interface, threshold, strategy,
promotion requirement, or runtime behavior. No external data or broker API, account or production
data, credential, or external verification was used. Statements labelled **Observed** are supported
by repository evidence below. Statements labelled **Missing** describe evidence not found within the
reviewed paths, not proof that such evidence cannot exist elsewhere.

**Subsystem classification:** partial and promotion-blocked. The repository contains useful
point-in-time universe, corporate-action, PBO, and seeded-fill primitives, but the connected equity
comparison explicitly records all four reviewed areas as unresolved blockers
(`src/trading_bot/research/equity_comparison.py:638-648`). Its exploratory metrics are not acceptance
evidence.

**Dependency chain and critical path:** immutable source/provenance records -> point-in-time universe
and adjusted, interpolation-qualified bars -> leakage-controlled folds and complete candidate-trial
registry -> deterministic execution/exit outcomes -> content-addressed report and independent review.
The critical path begins with provenance because later statistical and outcome evidence cannot make
an unverified dataset eligible. Existing interfaces and configured thresholds remain frozen.

## Traceable blocker matrix

| Gap | Repository evidence | Existing behavior (Observed) | Missing evidence | Bounded proposed owner | Deterministic acceptance-test design | Pass / fail conditions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Point-in-time membership** | The comparison hard-codes `point_in_time_universe=False` and describes its fixed list as present-day knowledge (`src/trading_bot/research/equity_comparison.py:199-215`). The run always adds `point_in_time_universe_unavailable` (`src/trading_bot/research/equity_comparison.py:638-648`). A separate primitive hides membership until both announcement/effective timing permits it, and exposes incomplete history as ineligible (`tests/unit/market_data/test_universe.py:9-19`). Documentation likewise says the four-ETF tuple is not a point-in-time universe (`docs/limitations.md:3-9`). | A generic membership primitive and deterministic boundary tests exist, while the connected comparison uses the configured fixed tuple and rejects its manifest. | A comparison input bound to a complete, source-identified membership-event history; coverage boundaries for every evaluation timestamp; delisting/removal fixtures; and report evidence proving that each candidate was knowable and included at the decision time. No external constituent history was verified in this review. | **Follow-on PIT-MEMBERSHIP-EVIDENCE:** market-data research evidence owner; fixture/tests and design documentation only until an authoritative source and licensing review are separately approved. | With synthetic events covering pre-announcement, announcement, inclusion, removal, re-entry, and an explicit missing-history interval, replay the same immutable fixture twice. Assert membership at each decision timestamp, stable content hash, exclusion before knowledge/effectivity, and an ineligibility reason for any uncovered interval. Add a comparison-level fixture proving symbols are derived from the timestamped universe rather than a present-day tuple. | **Pass:** byte-identical results/hashes on repeat; all expected timestamp memberships match; any incomplete interval fails closed; report binds event hashes and coverage interval. **Fail:** look-ahead membership, silent substitution, fixed-list fallback, missing removal/delisting provenance, nondeterminism, or an eligible result with incomplete history. |
| **Corporate-action and interpolation provenance** | Bar validation rejects `bar.interpolated` (`src/trading_bot/research/equity_comparison.py:186-196`), but the manifest states only provider-requested split adjustment and unverified dividend/distribution and point-in-time action provenance (`src/trading_bot/research/equity_comparison.py:203-220`). The adjustment test demonstrates announcement-aware split arithmetic (`tests/unit/market_data/test_adjustments.py:35-50`). The authenticated shape lacks an explicit interpolation flag; omission remains tainted (`docs/limitations.md:10-13`). | Known interpolated bars are flagged; absent authenticated interpolation status is conservatively tainted. A pure split-adjustment path has a local timing test. The connected report remains rejected and does not establish complete action coverage. | Source identity and immutable raw preimages for every action/bar; as-known/announcement and effective timestamps; dividend/distribution, split, symbol-change, merger/spinoff, and delisting coverage policy; adjustment version/order; explicit provider interpolation semantics; completeness and licensing attestations. Raw-response hashes alone do not establish these facts. | **Follow-on ACTION-PROVENANCE-EVIDENCE:** market-data provenance owner, limited to schemas/fixtures/tests/design; authenticated source verification remains a separate operator-authorized task. | Build local immutable fixtures for late-announced split, cash distribution, same-day competing actions, missing action interval, and bars with `true`, `false`, and absent interpolation status. Replay at timestamps immediately before/at/after knowledge and effectivity; assert exact Decimal OHLCV transformations, ordering, manifest hashes, and taint propagation. Mutate one provenance field and assert the hash and eligibility outcome change. | **Pass:** all transformations are exact and repeatable; manifest binds raw/action/bar identities and coverage; absent/unknown interpolation or incomplete action coverage is ineligible. **Fail:** default-clean omission, future-known action leakage, unsupported action silently ignored, unbound transformation, rounding drift, or incomplete coverage accepted. |
| **Multiple-testing and PBO controls** | The comparison records `multiple_testing_unresolved` and `pbo_unavailable` (`src/trading_bot/research/equity_comparison.py:638-648`). A PBO helper returns `insufficient_sample` below four score pairs and otherwise selects the in-sample winner and compares its out-of-sample score with the median (`src/trading_bot/research/monte_carlo.py:17-39`); its test covers only the insufficient case (`tests/unit/research/test_monte_carlo.py:13-14`). The connected flow does not use purged validation or calculate PBO (`docs/strategy-research.md:30-32`). | Candidate parameter identities and all configured attempts are reported; deterministic opportunity resampling and a small PBO primitive exist. Parameter-neighbor checks and other acceptance checks exist, but they are not evidence that multiplicity/PBO is resolved. | A preregistered, exhaustive trial ledger (including abandoned/repeated analyses); definition of independent folds/opportunities; leakage-safe PBO construction wired to the complete candidate family; deterministic tie/median/missing-value semantics; multiplicity-control method and rationale; minimum-sample treatment; and evidence binding all inputs/outputs. | **Follow-on MULTIPLICITY-PBO-DESIGN:** research-validation owner; design plus synthetic tests only, with no threshold, selection, or promotion decision changes. | On a fixed synthetic score matrix with known winners, ties, reordered candidates, an intentionally overfit candidate, and insufficient folds, enumerate the preregistered trial set and compute a golden PBO/multiplicity result twice. Assert candidate-order invariance, explicit tie handling, full trial retention, purged non-overlapping labels, stable hashes, and fail-closed insufficient/malformed samples. | **Pass:** golden values and hashes match; every attempted trial is counted once; ordering cannot change the result; leakage or insufficient input is rejected. **Fail:** omitted trials, post-hoc family changes, undefined ties, candidate-order sensitivity, unpurged overlap, manufactured PBO, or eligibility while status is unavailable. |
| **Fill and exit outcomes** | The comparison directly moves holdings to next-open targets and charges configured costs (`src/trading_bot/research/equity_comparison.py:352-391`), liquidating at each fold end (`src/trading_bot/research/equity_comparison.py:398-413`). It explicitly says rejection, no-fill, partial-fill, latency, cancel-race, stop/target, maximum-holding, and regime exits are not integrated (`src/trading_bot/research/equity_comparison.py:737-749`). A separate fill model deterministically supports no-same-event, market-closed, rejection, no-fill, liquidity, and partial-fill outcomes (`src/trading_bot/simulation/fills.py:46-65`), with seeded-repeatability coverage (`tests/unit/simulation/test_fills.py:29-37`). | Exploratory comparison accounting assumes complete next-open target fills plus deterministic spread/slippage/commission costs. A separate seeded fill primitive exists, but its outcomes and configured exits are not wired into this comparison. | A single event-timed decision-to-order-to-fill-to-position-to-exit trace; remainder/cancel lifecycle; latency and cancel-race ordering; rejection/no-fill/partial-fill terminal completeness; stop/target/maximum-holding/regime-exit precedence and gap behavior; outcome completeness and identity binding; and equivalence evidence between configured assumptions and simulation inputs. | **Follow-on SIM-OUTCOME-EVIDENCE:** simulation/research integration owner under primary review; local fixtures/tests/design only, without broker, risk, sizing, pricing, or live-runtime changes. | Replay a frozen event tape for full fill, rejection, no fill, partial then remainder, insufficient liquidity, delayed fill, cancel race, price gap through stop/target, maximum hold, regime exit, and fold boundary. Run each seed twice and restart at every event boundary. Assert no same-event fills, conservation of cash/quantity/fees, deterministic precedence, idempotent outcomes, terminal completeness, and a report hash binding every event and configured assumption. | **Pass:** identical traces/hashes across replay and restart; exact accounting; every order reaches an explicitly complete or explicitly ineligible outcome; exit precedence matches the frozen specification. **Fail:** assumed complete fill, dropped remainder, duplicate fill, ambiguous race/exit, unbound cost/input, restart divergence, or eligibility with incomplete outcomes. |

## Observations, assumptions, and unperformed verification

- **Observed:** release documentation deliberately rejects the report for all reviewed gaps and keeps
  research-assumption and promotion flags false (`docs/strategy-research.md:47-57`). Live observation
  eligibility separately requires validated data and complete outcomes (`docs/live-activation.md:52-59`).
- **Observed:** the deterministic primitives cited above reduce implementation uncertainty, but their
  existence does not demonstrate comparison-level integration, provenance completeness, or external
  validity.
- **Assumption for proposed tests only:** synthetic fixture event times and golden expected values can
  be frozen without changing production interfaces or thresholds. Choosing authoritative providers,
  licensing terms, statistical policy, or exit precedence is intentionally outside this review.
- **Not performed:** authenticated/provider calls, external dataset or constituent-history checks,
  licensing validation, account/production inspection, empirical calibration, full test suite, and
  any acceptance or promotion decision.

## Suggested non-overlapping follow-on task contracts

Each task must remain based on an exact reviewed commit, retain existing interfaces/thresholds, avoid
external writes and credentials, and return tests, assumptions, risks, blockers, and an explicit
integration disposition.

1. **PIT-MEMBERSHIP-EVIDENCE** — own only new membership fixtures, tests, and a design note; treat
   market-data and comparison code as read-only. Deliver the timestamp/coverage golden test described
   above. Do not select or contact a provider.
2. **ACTION-PROVENANCE-EVIDENCE** — own only new corporate-action/interpolation fixtures, tests, and a
   provenance-schema design note. Freeze adjustment APIs. Do not authenticate or assert provider
   completeness.
3. **MULTIPLICITY-PBO-DESIGN** — own only research-validation tests and a statistical design note.
   Freeze candidate grids and every configured threshold; do not choose a candidate or modify gates.
4. **SIM-OUTCOME-EVIDENCE** — after the preceding data contracts are frozen, own only simulation
   fixtures/tests and an outcome-trace design note. Treat strategy, execution, risk, pricing, sizing,
   configuration, broker, runtime, and promotion code as read-only.

These contracts do not authorize parallel integration where interfaces overlap. The primary
orchestrator retains sequencing, implementation ownership, acceptance, and release decisions.
