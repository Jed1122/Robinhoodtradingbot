# Options source protocol review

Checkpoint: 2026-09-29 UTC. Task 1 source dispatch is implemented; Task 2 actual-source
qualification is **incomplete**. Every actual role below remains `UNVERIFIED`, and
`load_reviewed_rules()` remains empty. A parser identifier, valid file hash, purchase
receipt, current web page or synthetic fixture is not historical source approval.

## Preserved capture status

The official pages linked below were inspected through public web retrieval. Separate
unauthenticated byte captures of Databento's OPRA, OHLCV and definition URLs each returned
the same 15,008-byte application shell, without the relevant semantic page content.
All three have SHA-256
`d96795c2360476b736cff3ee727a548853119f3c0eeccb9f956ff09ddbe6b6b3`.
These private captures prove only what was received, **not** the displayed protocols;
they must not be installed as semantic document evidence. Usable preserved content
hashes and historical applicability still need verification. No raw licensed records,
credentials or account identifiers were captured or committed.

## Role/era evidence matrix

The test names in the last column are planned Task 2 acceptance work, not completed tests.

| Role and target era | Primary reference / schema | Relevant mapping or limitation | Missing before enablement / planned test |
| --- | --- | --- | --- |
| Bar publication, acquired 2018–2025 XNAS history | [Databento OHLCV](https://databento.com/docs/schemas-and-data-formats/ohlcv), `ohlcv-1m` | `ts_event` is interval start, using trade receive-time bucketing; no record is emitted for a no-trade interval. It is not publication time. | Archive-era publication bound, revisions/breaks and degraded-date coverage; future publication and projection-substitution tests. |
| Definition state, acquired 2023–2025 OPRA | [Definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions) and [OPRA supplement](https://databento.com/docs/venues-and-datasets/opra-pillar), `definition` | Preserve add/modify/delete, dated publisher/instrument/raw-symbol identity and complete baseline separately from later updates. OPRA historical IDs can change. | OPRA-era snapshot identification, completeness, publication and remapping protocol; partial reset, deletion and same-ID reuse tests. |
| Quote semantics, pre-2023-03-28 | [OPRA supplement](https://databento.com/docs/venues-and-datasets/opra-pillar), subsampled history | CMBP-1 is unavailable; receive time is event time and marked unreliable. | Unsupported for the planned event-quote consumer; reject era/schema substitution. |
| Quote semantics, 2023-03-28 onward | [OPRA supplement](https://databento.com/docs/venues-and-datasets/opra-pillar), `cmbp-1` | `ts_event` is consolidator processing time; `ts_recv` is capture receipt. Neither proves an executable fill. | Era-specific initialization/reset/gap/condition mapping, venue semantics and calibration; unknown-era and native/projection binding tests. |
| Calendar, every study and exit session | [Cboe historical holiday notice](https://cdn.cboe.com/resources/schedule_update/2023/Cboe-Holiday-Reminder-Modified-Trading-Hours-on-Thursday-November-23-and-Friday-November-24.pdf), official notices | Underlying and options session identities must be separate, with UTC conversion and eligible expiry sessions. | Complete dated holidays, exceptional closures, early closes and DST; late-reference, DST and early-close tests. This candidate notice is not a complete pinned calendar. |
| Actions/dividends, every warmup/holding interval | [Databento corporate actions](https://databento.com/docs/venues-and-datasets/corporate-actions), PIT reference records | Preserve historical revisions and availability, not only latest values. Coverage begins 2018-05-01. | Exact versioned field mapping, retained revision/coverage evidence and explicit empty intervals; missing/empty coverage and future-revision tests. |
| Contract terms, each series and effective era | [OCC ETF options](https://www.theocc.com/clearance-and-settlement/clearing/etf-options), series/product references | General current product descriptions do not certify historical deliverables, ticks, exercise or settlement. OPRA expiration has date precision, not a trading deadline. | Dated series-level terms, adjustment coverage, actual last session/deadline and settlement convention; unsupported/adjusted deliverable tests. |

The acquired underlying history does not itself establish the plan's 3,650-day
verified-history requirement. Neither passing software tests nor a narrow engineering
pilot can satisfy that requirement by counting option rows or assuming earlier coverage.

## Source-adapter acceptance contract

Before an actual rule is installed, preserve the semantic source bytes with a usable
hash, retrieval time, document version and supported era. Bind the exact native
dataset/schema/decoder version and byte/ordinal identities to canonical projection
hashes. Specify timestamp meaning, availability, sentinels, corrections, mapping
intervals, full baselines, resets and coverage. The caller cannot supply a trusted
projection or `verified` flag. Unknowns deny only their dependent source work.

Task 1 already preserves literal legacy fixture hashes and reuses one hash-bound
read for verification. Known native/reference IDs currently fail closed; native
DBN content must later be consumed through verified bounded manifests, not loaded
as an unbounded reference blob.

No Task 2 adapter or its acceptance suite is claimed complete. Existing synthetic
session/definition tests cover useful boundary cases but are not real-provider evidence.

## Archived technical questions — do not send

On 2026-09-29 the operator instructed that these questions must not be sent and
reports affirmative answers. No support response was received, and support outreach
is no longer a pending action. Preserve this as operator-provided information;
the field-level protocols and historical applicability remain to be established
from available documentation and data before enabling actual-source rules.

1. For historical XNAS.ITCH minute bars covering 2018–2025, what documented bound
   establishes when each stored bar was first available, and how are later trade
   breaks/corrections represented? If this cannot be established from OHLCV files,
   what exact trade/revision inputs support point-in-time reconstruction?
2. For historical OPRA definitions during 2023–2025, how is a complete baseline
   identified, timestamped and distinguished from later add/modify/delete updates?
   How are historical instrument-ID remaps and partial resets represented?
3. For historical OPRA CMBP-1 from 2023-03-28, what initializes a request beginning
   mid-session, and how are feed gaps, resets, halts and non-firm quotes represented?
   Which flags or external records are required to invalidate/reinitialize state?
4. Which versioned reference sources support dated SPY-series deliverables, ticks,
   actual trading deadlines and settlement conventions, with point-in-time actions
   and explicit no-event coverage? Please identify existing documentation or required
   data products; do not initiate a purchase or subscription.

No support message has been sent. Do not send this archived draft unless the operator
later changes the instruction. It remains a checklist for documentation/data review,
not a questionnaire awaiting operator approval or a verified historical guarantee.

## Next work

Resolve and pin each actual-source protocol independently using available documentation
and preserved data, without support outreach. Fixture-only native quote
decoding/storage and causal-stream work can proceed without enabling source trust.
Then freeze the study and complete quote coverage, verify total cost against fresh
remaining credits, and acquire only a necessary package the working consumer can use.
Historical execution/accounting and after-cost uncertainty follow. Economic validation,
broker/runtime readiness and live authorization remain separate incomplete outcomes.
