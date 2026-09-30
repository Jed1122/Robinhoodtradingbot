# Actual-source readiness audit — 2026-09-30

**Disposition: `NOT_READY` / `BLOCKED_INPUTS`; genuine qualification remains NO-GO.**
Read-only code/document audit against `f2ff32219ffc017b8da63c3b8a8177bcb8c6ee65`,
supporting approved real-data research plan Tasks 2 and 6. Public primary sources below
were checked on 2026-09-30; current documentation is not historical archive approval.
This checkpoint does not establish profitability, deployment readiness or live authority.

## Verification boundary

No licensed rows, private downloads, credentials, accounts, portal balances, broker state
or host state were inspected. No downloads, purchases, support messages, actual-source
tests or economic study were performed. Acquisition counts below come from sanitized
repository documentation, not fresh archive verification. No semantic capture hashes
were created. The [existing capture limitation](options-source-protocols.md#preserved-capture-status)
remains: prior HTTP captures contained application shells, not the protocol content.
Implementation, risk thresholds, shortlist, frozen interfaces and empty actual rulebook
are unchanged. Source integration remains under the primary orchestrator.

## Exact implementation blockers

1. `options_source_rules.load_reviewed_rules()` returns `()`;
   `options_source_dispatch._parse_source_snapshot()` accepts only the synthetic parser.
   Reserved native/reference parser IDs do not grant source trust.
2. Native dispatch alone cannot unlock definitions: `options_definition_inputs._facts()`
   separately requires `synthetic-source-records-v1` and a `synthetic.*` source. Task 2
   needs code-owned verified reference-fact consumption, preserving public interfaces.
3. The acquired definitions report 217,732 partial-symbol declarations.
   `databento_metadata.scan_metadata()` preserves the count but not their identities;
   `options_definition_inputs._state()` requires one coverage item per declaration yet
   requires `partial == 1` and `symbol == "SPY.OPT"` for every item. That implementation
   cannot accept the documented acquired archive. Bounded native metadata reparsing and
   verified per-symbol/date coverage are needed; a parent-wide assertion is insufficient.
4. `QuoteFeedBinding` permits only `snapshot_last_v1`. `options_quote_stream._run()`
   initializes on clean `F_SNAPSHOT | F_LAST` inside the session and clears state at
   session boundaries and stale deadlines. No reviewed OPRA CMBP-1 protocol establishes
   this exact initialization/recovery contract. Do not manufacture snapshot flags or
   substitute natural refresh under the frozen policy.

## Role/era matrix

Mappings below support bounded parser work, not installed historical qualification.

| Role / target era | Supported mapping and primary source | Missing before enablement |
| --- | --- | --- |
| XNAS bars, acquired 2018–2025 | `ohlcv-1m.ts_event` is interval start using trade receive-time bucketing; prices scale by `1e-9`; no-trade intervals emit no row. [OHLCV](https://databento.com/docs/schemas-and-data-formats/ohlcv) | Original publication/revision bound, complete interval/no-trade coverage and degraded-date resolution. No assumed minute/overnight delay. Trade reconstruction needs a separately reviewed correction-aware parser and priced package. |
| OPRA definitions, acquired 2023–2025 | Preserve native identity/ordinal/hash, timestamps, symbol, add/modify/delete action, strike and expiration; recompute projection hashes. Daily snapshots exist for publishers without complete daily lists. [Definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions) | OPRA-era baseline identification/completion/publication, visible updates, deletion/remapping, partial symbols and missing/degraded coverage. A complete 24-hour response is not an opening-chain union. |
| OPRA quotes before 2023-03-28 | CMBP-1 is unavailable; older data is subsampled, receive time substitutes event time and timestamp quality is marked unreliable. [OPRA supplement](https://databento.com/docs/venues-and-datasets/opra-pillar) | Unsupported for this event consumer; reject CBBO-1m substitution. |
| OPRA CMBP-1 from 2023-03-28 | `rtype=177`; retain prices/sizes, action/flags and venue attribution. Event time is consolidator processing; receive time is capture receipt; delta is zero. Non-trade publisher is 30; trades identify execution venue and side `N`. [CMBP fields](https://databento.com/docs/schemas-and-data-formats/cmbp-1), [OPRA supplement](https://databento.com/docs/venues-and-datasets/opra-pillar) | Session initialization, reset/gap recovery, halt/non-firm representation, publisher-era membership and historical correction/coverage semantics. CMBP has no sequence/depth; timestamp tuples do not prove uniqueness or completeness. [Migration](https://databento.com/blog/opra-migration) |
| Quote flags, each supported era | `128` event end; `32` replay/snapshot origin; `8` unreliable receive timestamp; `4` unrecoverable channel gap; `2` publisher-specific. `R` clears instrument state. [Flags/actions](https://databento.com/docs/standards-and-conventions/common-fields-enums-types) | These justify rejection/control mappings, not restoration of trust. Generic MBO/MBP snapshot statements do not establish OPRA CMBP initialization. |
| Matching XNAS quotes, pilot windows | `XNAS.ITCH/mbp-1`, SPY, publisher 2, exchange-specific scope. Preserve times, prices/sizes, sequence, depth and counts. Event time is matching-engine time; delta is receive minus event. Normalized records may share sequence. [XNAS](https://databento.com/docs/venues-and-datasets/xnas-itch) | Initialization/recovery and historical completeness. A sequence jump in a filtered stream is not sufficient gap evidence. Do not label this underlying feed NBBO. |
| Calendar, warmup through settlement | Dated notices support separate underlying/options sessions and explicit closed dates, with DST-aware ET conversion. Historical Thanksgiving notice distinguishes 13:00 equities and 13:15 options closes. [Cboe 2023 notice](https://cdn.cboe.com/resources/schedule_update/2023/Cboe-Holiday-Reminder-Modified-Trading-Hours-on-Thursday-November-23-and-Friday-November-24.pdf) | Complete dated venue/product coverage, exceptional closures, publication and expiry sessions. This notice is not a complete calendar or XNAS-specific authority. |
| Actions/dividends, every covered interval | Retain PIT revisions with `pit=True`; preserve event IDs, `ts_record`, `ts_created`, action and event-specific date/rate fields. Dates are listing-local; timestamps UTC. [PIT behavior](https://databento.com/docs/venues-and-datasets/corporate-actions), [Fields](https://databento.com/docs/schemas-and-data-formats/corporate-actions) | Exact domain mapping, effective/publication bounds, cancellations, full query coverage and explicit empty intervals. Latest-only default cannot replace history; these timestamps do not automatically establish issuer publication. |
| Contract terms, every series/era | OSI identifies root/date/call-put/strike; OPRA expiration has UTC-midnight date precision. Current OCC describes standard ETF 100-share, American-style physical delivery. [OPRA](https://databento.com/docs/venues-and-datasets/opra-pillar), [OCC ETF terms](https://www.theocc.com/clearance-and-settlement/clearing/etf-options) | Dated SPY-series deliverables, adjustments, ticks, last trading time and settlement convention. Generic current ETF descriptions cannot certify all 2023–2025 terms; an unchanged root does not prove unadjusted terms. |

Condition metadata maps `date`, `condition` and `last_modified_date`; the last field
describes generation/modification of **any schema** for that dataset/day, not original
record publication. `available` means no known issues, not a complete-chain guarantee.
[Condition metadata](https://databento.com/docs/api-reference-historical/metadata/metadata-get-dataset-condition).
Historical A/B-side reprocessing can repair gaps; bind acquired bytes to version and
retained conditions rather than retroactively applying a later clean status.
[Reprocessing announcement, 2025-05-14](https://databento.com/blog/opra-improvements-coming-soon).

## Already acquired versus still needed

The [native intake checkpoint](options-native-data.md#previously-acquired-bar-definition-intake)
and [definition acquisition record](databento-acquisition-next-steps.md#supplied-local-download--2026-09-22)
report:

- XNAS SPY minute bars `[2018-05-01, 2026-01-01)`: 1,421,744 records; two rejected
  undefined-OHLC observations; three provider-degraded dates.
- OPRA SPY definitions `[2023-01-01, 2026-01-01)`: 6,821,768 records; 217,732 partial
  symbols; conditions include two degraded and three missing dates.
- Neither archive establishes actual-source qualification. No qualified genuine
  CMBP-1/matching XNAS MBP-1 pilot package is established by these documents.
- Earlier CBBO-1m/EQUS.MINI estimates are not compatible substitutes. Existing underlying
  history does not satisfy the frozen 3,650-day requirement; 750 observed warmup bars
  remain a separate requirement. A narrow engineering pilot does not clear either gate.

## Conditional smallest usable pilot — not acquisition-ready

1. Choose one eligible session by verified calendar/availability only. Freeze both
   unchanged call/put shortlist candidates before viewing premiums or outcomes.
2. Reuse qualified existing bars/definitions where possible. Include complete baseline,
   visible updates, prior close and required observed warmup; do not repurchase blindly.
3. Scope both candidates' OPRA CMBP-1 and matching SPY XNAS MBP-1 through evidenced
   initialization, entry, monitoring, exit/expiry and settlement—not entry-only samples.
4. Bind corresponding calendars, series terms, PIT actions/empty coverage, conditions,
   per-schema availability and immutable source-version evidence.
5. Resolve bar publication and the exact initialization contract before calling this
   package usable. Separately specify and price any additional trade/control route.
6. Reconcile existing/pending acquisitions, applicable remaining credits, charges and the
   complete exact quote before purchase. No current price, balance or no-cash boundary
   was verified here; stale estimates or original grants cannot establish affordability.
7. Run native/source/quote verification, then observed premium and verified fee feasibility
   across all eight tiers before expanding acquisition. A pilot is not economic approval.

## Next implementation and acceptance work

Implement bounded native/reference factual adapters with the actual rulebook still empty.
Fix synthetic-only reference consumption and multiple-partial-symbol coverage under the
existing interface contract. Preserve semantic documents with hashes, retrieval dates,
versions and supported eras; unknown evidence must remain a role-specific denial.

Required fixture tests: native/projection substitution; nanosecond-late publication;
partial baseline/reset; future additions; deletion and same-ID remapping; multiple partial
symbols; empty actions versus absent coverage; DST/early close; adjusted deliverables;
wrong source/era/schema; snapshot/gap/stale recovery. Synthetic fixtures are engineering
tests, not actual-source evidence. Run Task 2 tests plus source/session/definition/shortlist
and quote regressions before integrated review; this audit ran none of those checks.

Install an actual rule only after its complete role/era contract is supported and reviewed.
Do not alter thresholds, shortlist, native observations or live gates to make inputs pass.
Tasks 2/6 remain incomplete; full-policy software, after-cost economics, account/broker
verification, paper/shadow operation and explicit live authorization are separate stages.
