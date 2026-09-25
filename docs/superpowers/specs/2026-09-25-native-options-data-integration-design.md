# Native options data integration for a targeted acquisition manifest

Status: **Design brief approved; written specification awaiting operator review**.
Prepared 2026-09-25 UTC against `8a3a55485a0da66a6645f5703fb4f5e2f596c277`.
This is an architectural specification, not implemented behavior or economic evidence.

## 1. Intent, outcome and authority

The operator wants to make progress toward genuine options economic validation with
the existing Databento data and credits, without buying a broad unusable dataset.
They approved the integrated native-data design brief in this task. The chosen scope
connects native intake, source verification and the existing research shortlist; it
does not implement a new trading strategy, real-data execution simulator or broker.

The deliverable is a reproducible, offline, provenance-bound acquisition manifest:
either verified per-session call/put selections and complete requested quote windows,
or explicit dependency failures explaining why no purchase-ready manifest exists.
No result from this milestone establishes an economic edge or activates trading.

The [current authority and quality checkpoint](../../options-data-validation-handoff-2026-09-25.md)
records permission to spend all existing Databento credits on necessary validation
data. The latest observed balance is $112.68, with $0.00 due. This is not a reserved
balance or a reason to spend it all. Fresh applicable credits, pending charges and
the exact customized-request cost must be checked before each purchase. No repeated
approval is needed for necessary purchases fitting that authority; cash spending,
subscriptions, new agreement acceptance and live operations remain excluded.

Purchases are a separate operator-controlled workflow. Offline code receives no
credential, network client or spending authority. Its manifest always retains
`download_authorized=false`, even when the operator has separately granted purchase
authority. This preserves the existing research/execution capability boundary.

### Alternatives and selected approach

1. **Integrated native provenance path — selected.** More integration than a decoder,
   but it addresses the actual prerequisites to the targeted quote request. Missing
   evidence remains an explicit denial rather than being filled with assumptions.
2. **Bars intake only.** Smaller initial implementation, but cannot verify chains,
   assemble the approved shortlist or produce the complete quote manifest.
3. **Buy broad quotes first.** Can support a separately designed engineering pilot,
   but consumes credits before demonstrating compatible inputs and study coverage.
   It is not the selected approach and cannot substitute for the integrated checks.

The scope is one bounded research-data integration, delivered in separable intake,
verification and assembly stages. Pricing adapters, historical execution replay,
statistical acceptance and durable production lifecycle work remain separate milestones.

## 2. Verified starting point

The existing source and purchased archives provide these starting components:

| Component | Reuse and current limitation |
| --- | --- |
| `databento_batch`, `databento_definitions`, `databento_stage*` | Preserve validated native definition bytes/staging. Their false completeness, availability and enrichment flags remain unchanged. |
| Acquired SPY minute bars | Fresh scan decoded 1,421,744 DBN v1 rows; two undefined-price rows and three provider-degraded dates require handling. Session/availability semantics are not verified. |
| `OptionContract`, `OptionSession`, `Bar` | Retain exact canonical validation. No fabricated multiplier, calendar, deadline or publication timestamp. |
| `OptionsDataRecord`, `point_in_time`, `select_chain` | Reuse provider-neutral records and visible-revision selection after source verification, not as proof of source authenticity or complete membership. |
| `options_shortlist*` | The approved 21–45/30-day prior-close selection exists for synthetic inputs. Imported inputs deliberately deny. |
| `options_parquet`, bundle storage and canonical hashing | Reuse exact serialization and private, immutable storage mechanics. Legacy schemas/hashes stay readable and unchanged. |
| `databento_preflight.CostRequest` | Existing exact-symbol diagnostic is CBBO-1m only, bounded to 100 standard SPY symbols. It cannot currently price event-level CMBP-1 or buy data. |

The existing underlying package covers `[2018-05-01, 2026-01-01)` UTC; option
definitions cover `[2023-01-01, 2026-01-01)`. These are acquired scopes, not an approved
holdout split. The older definition-profile counts are not reverified by the current
bars-only diagnostic. Actual usable sessions, chain coverage and full targeted cost
remain unknown. See the [acquisition record](../../options-underlying-bootstrap-proposal-2026-09-22.md).

## 3. Architecture and trust boundaries

The offline flow is:

```text
immutable local archives + exact request descriptors + reviewed reference sources
    -> bounded native observations and quarantine/coverage records
    -> independently replayed source verification for a requested decision window
    -> canonical prior-session close and point-in-time option chain
    -> existing fixed ranking policy, with versioned imported-evidence envelope
    -> immutable selections/denials and deduplicated quote-coverage requirements
```

Keep four separate facts: acquisition permission, byte/schema integrity, historical
source suitability and economic acceptance. A provider receipt, plausible data,
caller boolean, successful parser or SHA-256 hash cannot establish the other facts.

### Proposed components

- **Native intake:** bounded streaming OHLCV intake beside the existing definitions
  scanner. Shared framing/decompression helpers may be extracted only with unchanged
  definition regressions. Do not route equities through `DefinitionRequest` or relax
  its OPRA/schema restrictions. Preserve source ordinal, DBN version, raw bytes/hash,
  native nanosecond timestamps and exact fixed-point financial fields.
- **Reference/source verification:** a versioned, coordinator-reviewed rule registry
  and evidence envelope for identity, timestamps, sessions, actions and chain coverage.
  This is data validation, not a trading configuration loader or new broker manifest.
- **Canonical assembly:** constructs only fully supported `ShortlistClose`,
  `OptionContract`, `OptionSession` and `OptionsDataRecord` inputs, for bounded requested
  sessions. Unknown facts remain native observations with reasons, not canonical guesses.
- **Verified shortlist bridge:** checks evidence against the exact assembled inputs
  and invokes the shared deterministic ranking policy. No duplicate ranking formula.
- **Coverage assembler:** unions required exact-symbol/time windows without consulting
  quote prices, liquidity, returns, Greek estimates or trade outcomes.

Suggested module ownership is `market_data` for intake/reference verification,
`research` for the shortlist bridge and coverage assembly, and the existing offline
options CLI for orchestration. The general `cli/main.py` is already dirty and stays
untouched. Coordinator owns canonical types, verification, policy and integration.
No parallel or Cloud work is part of this specification's current execution.

## 4. Native intake, precision and immutable storage

Validate exact dataset, schema, symbology, symbols, bounds and limit before accepting
an archive. Verify all declared file hashes and sizes, compressed and DBN EOF, record
type/length, timestamp bounds, native sentinels and mapping consistency. Unsupported
versions/fields, framing failures or identity ambiguity deny publication of a verified
bundle. A late failure invalidates all provisional streamed output.

Use integer nanoseconds and fixed-point integer prices in native storage. Convert
prices through exact Decimal scaling by `10**9`; never float conversion. Preserve
nanoseconds when checking record order and visibility. At the existing microsecond
datetime boundary, ceil availability to the next representable microsecond if needed,
and retain the native timestamp as evidence; never round availability earlier. Preserve
the distinction between provider event, receive, interval, publication and local
retrieval times. Local retrieval time must never be backdated.

No source file is repaired or overwritten. A rejected row has a private immutable
reason and raw identity. Undefined OHLC fields, nonpositive prices, invalid OHLC
ordering and conflicting duplicates are unusable for an underlying close. Identical
duplicates may be recognized as duplicates but cannot double-count volume. Unsupported
types and non-finite/boolean-as-integer values fail closed. Quarantined data and
provider-degraded coverage are not silently deleted from coverage accounting.

For each bar request, every decoded row is accounted for as accepted native input,
rejected native input or exact duplicate. Session aggregation later accounts for
regular-session inclusion versus excluded extended-hours observations. No discarded
row vanishes from the audit. Empty/no-trade intervals are not automatically feed gaps;
conversely, an absent row does not prove that no trade occurred.

Keep bulk observations outside SQLite using partitioned Parquet and immutable native
archives. Extend the existing storage/codec implementation with explicitly new native
underlying-bar part/manifest schemas; do not pretend a `Bar` is an `underlying_quote`
or add fields to `options-data-record-v1`. Canonical supported options records continue
through the existing Parquet format. Bar provenance is carried by a versioned
research envelope referencing the unchanged `Bar` and its exact native inputs.

Use existing private-root traversal/publication rules: owner-only directories/files,
outside every Git checkout, no symlinks/hard-link surprises, no overwrite, atomic
content-addressed publication and post-publication verification. Disable DuckDB
external access/extension loading as in the existing implementation. Bounded reads,
parts and session slices prevent whole-history arrays. Reuse current native stream
limits and the stricter shortlist's 25,000-record/16-MiB/one-session limits. Additional
resource controls belong in the canonical config graph and release envelope, not
environment-only bypasses. Do not enlarge limits without a recorded benchmark/review.

## 5. Source evidence required before historical selection

A new source-verification envelope binds raw file/part hashes, exact query, record
identities, source semantics/version, normalizer and verifier identities, config,
coverage ranges, reference-document identities and every limitation. Reverification
must recompute derived facts from the preserved local inputs. Deserialized assertions
alone are not trusted; callers cannot set `verified=true` to enter the bridge.

Rules are specific to source, schema and historical era. Changes produce new
identities and revalidation, not edits to historical manifests. The registry is
implemented/reviewed code, not arbitrary executable content supplied by a data file.
External-source authenticity, rights and historical claims remain explicit evidence
dependencies; byte hashes authenticate neither a vendor nor a publication date.

### Underlying sessions and closes

Use a reviewed historical exchange calendar with explicit regular-session dates,
closures, exceptional closures, early closes and DST. Underlying and option sessions
are distinct. Provider available-date statuses or a weekday calendar are not enough.
Retain source/effective/publication evidence for the calendar. A present-day calendar
file is not automatically evidence of what was announced before a historical open.

Aggregate unadjusted minute bars wholly within the exact underlying regular session:
first usable open, maximum high, minimum low, last usable close, exact summed volume.
The bar boundaries remain the actual regular-session boundaries. Extended-hours
records cannot supply a missing regular-session close. Keep the result labeled
Nasdaq-source `source_last_trade`, not official consolidated close or national volume.

Minute bars label interval starts and can reflect vendor aggregation/revisions.
An interval cannot be available at its start. Historical availability requires an
evidence-backed publication/revision rule; adding one minute is only a lower bound,
not proof. Retrospective archives lacking this evidence remain useful for diagnostics
but cannot be upgraded into point-in-time selection. Hypothetical delays may be
reported as research assumptions separately; they do not pass this verified bridge.
[Databento OHLCV specification](https://databento.com/docs/schemas-and-data-formats/ohlcv).

An unresolved invalid row inside a session or unresolved degraded coverage denies
that session. A bad extended-hours row is excluded from the regular-session aggregate,
but does not clear a day-wide provider warning. Only independently supported
interval-scoped evidence can resolve that warning. Never forward-fill prices, fall
back to an older session or substitute a future revision. Later-discovered source
quality failures invalidate affected accepted artifacts without rewriting the earlier
as-known decision or claiming that the failure itself was historically knowable.

### Corporate events and dividends

Require explicit coverage for splits, distributions/dividends and relevant
symbol/deliverable changes, including supported evidence when the event list is empty.
Retain announcement, effective, record/pay dates where supplied and revision/retrieval
times separately. An ex-date alone is not an announcement time. Unknown action
coverage denies affected requests; do not infer an empty history from a missing file.

For the shortlist, preserve its current unadjusted-prior-close rule: discontinuities
between the prior close and current open deny; visible cash dividends remain context,
not a price adjustment or alternative contract filter. Warmup/event coverage needed
by later 20/100 research and pricing extends beyond this one-session comparison and
must be reported separately. This milestone does not relax the existing adjustment
or dividend-related research restrictions.

Use existing permitted sources or historically scoped official reference material
where sufficient. No provider reference subscription is presumed included in credits.
If source publication, completeness or retention cannot be established, return the
specific missing dependency before purchasing quotes meant to rely on it.

### Options definitions, identity and complete chains

Join historical instrument IDs through their dated raw-symbol mappings, not today's
instrument ID or symbol alone. Resolve definitions and update/delete events under a
reviewed source rule. Retain exact duplicate observations; reject contradictory
same-version identities instead of choosing file order. Do not treat a union of
contracts seen during a day as a chain known at that day's open.

Require supported baseline membership and visible additions/deletions, reconciled
request coverage and no unresolved relevant gaps. A partial-symbol declaration is
not proof of either failure or complete coverage; explain the affected interval from
native mappings and source rules. Unknown initial membership, unexplained deletion,
missing pages or incomplete relevant definitions deny chain construction.

Only standard SPY USD contracts enter the current canonical model: verified premium
multiplier and deliverable of 100 SPY shares, American exercise, physical/PM settlement,
historically applicable tick and eligible sessions. Validate OCC identity against
native strike/type/expiration rather than relying on symbol syntax to prove terms.
Adjusted/ambiguous deliverables remain unsupported. Do not copy a generic raw
`contract_multiplier` field into premium economics without documented semantics.

OPRA expiration is date-granularity midnight, not a last-trading or settlement time;
those require historical contract/session/reference evidence. Historical instrument
mappings and pre-2023-03-28 quote coverage have source-specific limitations.
[OPRA source specification](https://databento.com/docs/venues-and-datasets/opra-pillar).
Settlement expectations in a research contract do not certify account cash settlement
or broker handling. Unknown deadlines are not filled with a universal T+1/PDT rule.

Keep current chain and input-size ceilings. Do not truncate to nearby strikes or
selected expiries and relabel that subset a complete `ChainSnapshot`. If verified
whole-chain representation exceeds bounds, report the resource blocker for a separate
review; do not silently shrink membership or weaken the proof of nearest-strike choice.

## 6. Versioned verified shortlist bridge

Preserve all v1 input/result serializers, hashes and the unverified-import denial.
Introduce an explicit v2 imported-input/result envelope and separate verified entry
point. It checks source evidence and exact visible-input binding before sharing the
existing ranking implementation. Direct v1 imported calls continue to deny. New
identities identify new evidence semantics; they do not reinterpret old results.

Retain every selection rule from the
[approved shortlist design](2026-09-22-options-research-shortlist-design.md): immediate
prior completed session, previous unadjusted close, common expiry closest to 30 days
within inclusive 21–45 DTE, earlier-expiry/lower-strike ties, and exactly one call and
one put or no pair. No option quote, return, future survival, liquidity, account
balance or Greek input enters selection. Both directions remain in the acquisition
manifest even if later unaffordable, unquoted or losing.

Unknown or mismatched evidence returns stable per-session reasons, including existing
`source_evidence_unverified`, `calendar_unverified`, `prior_close_unavailable`,
`action_coverage_unverified`, `reference_discontinuity` and `chain_unavailable`.
Add versioned intake/coverage-specific reasons only in the new wire contract.

Full dataset hashes can change when later files arrive; the causal decision hash
includes only policy and visible selected evidence. Future records and file-order
permutations cannot change an earlier selection. A separately reported retrospective
audit invalidation can change usability, never the saved as-known selection.

All shortlist outputs remain `production_eligible=false`, `evidence_promotable=false`,
`download_authorized=false`, `live_authorized=false`. This bridge verifies acquisition
inputs, not genuine economic performance. The existing synthetic-only execution
replay remains synthetic-only; it is not opened by this milestone.

## 7. Quote-coverage manifest and credit handoff

Require an explicit requested decision range and preregistered coverage requirements,
not dates selected after observing returns. Keep all selected and denied sessions,
not just the sessions with attractive quotes. Preserve the configured 3,650-calendar-
day request, 750-bar minimum, five folds, 50 test bars/fold and 30 independent
opportunities wherever applicable. The acquired 2,802-day underlying range cannot
establish that longer request. An engineering pilot is not a qualifying study.

The coverage requirements identify which later research consumer needs option and
underlying observations, entry/monitoring/exit windows, expiry/deadline handling,
necessary state-initialization lookback and settlement follow-through. A consumer's
planned maximum holding period alone cannot prove settlement completion. No study
split, new holding rule or assumed settlement lag is chosen by this specification.
Absent preregistered requirements yield `coverage_requirements_missing`, not a
purchase-ready quote list.

Produce exact dataset/schema/symbol/start/end requests by deduplicating overlapping
windows for the same schema and symbol while retaining reverse links to every
selection and requirement. Include complete intended exit/expiry follow-through;
do not cut at year end merely because existing definitions stop there. Missing tail
definitions, references or underlying coverage become explicit additional requirements.
No quote-price filter may change a frozen selected symbol. Incomplete later execution
outcomes must remain incomplete, with no forced final fill.

Price data of equivalent suitability. CBBO-1m can support separately labeled interval
screening, but its timestamps and carried-forward components do not establish original
quote age or an intervening execution path. Prefer pricing targeted event-level
CMBP-1 when those semantics are required; even that does not prove simulated fills.
[CBBO semantics](https://databento.com/docs/schemas-and-data-formats/bbo).
Do not buy both resolutions automatically if one supplies the needed information.
Matching underlying prices and, where required, fresh underlying quotes are separate
coverage items; the acquired bars do not automatically satisfy every future consumer.

The existing cost diagnostic remains estimate-only and CBBO-1m restricted. Use verified
portal scopes for other schemas or a separately reviewed extension; this milestone
does not add acquisition APIs. Before any purchase, validate the complete dependent
package's coverage and budget, then execute the approved necessary requests once.
Refresh exact quotes and usable credits; account for accepted-but-unsettled jobs and
existing local data. If scope/semantics/budget cannot support the intended test,
record a feasibility failure instead of exhausting credits on partial coverage.

## 8. CLI, privacy and failure behavior

Add commands only to the offline options research composition: native intake,
source-coverage verification, verified shortlist assembly and coverage-manifest
assembly. Names and exact arguments will be finalized in the implementation plan.
Inputs are explicit local paths and canonical config, never ambient credentials.
Defaults remain disabled/write-incapable. Public stdout contains status, counts,
fixed reason codes and artifact hashes, not raw prices, symbols, account IDs,
provider payloads or private paths. Detailed evidence remains private.

Malformed input/resource/storage errors return sanitized nonzero failures. A valid
but unsupported/unselectable session is a durable denial, not a parser exception.
Aggregate reports distinguish complete verified manifests, partial findings and
blocked dependencies. Disk-full, interrupted writes and source mutation cannot
publish success or overwrite prior immutable artifacts. No production ledger
migration, deployment, scheduler integration or account call is introduced.

## 9. Acceptance and verification

Use synthetic credential-free fixtures in CI; never copy the acquired data into
tests or Cloud tasks. Private real-data profiling is separate evidence, not an
authenticated CI test. Implementation uses failing tests first and narrow checks
before the full baseline.

- Native DBN v1/v2/v3 framing where supported; unsupported version/schema/type, late
  truncation/checksum failure, multi-frame compression and bounded expansion.
- Exact nanosecond/Decimal handling; undefined OHLC sentinel, invalid ordering,
  duplicate/conflicting rows, ID reuse, half-open mapping intervals and missing symbols.
- Row-count conservation, deterministic partition identities, immutable publication,
  reconstruction after interruption and rejection of mutated inputs or forged reports.
- Regular-session versus extended-hours boundaries, early closes, exceptional holidays,
  DST and missing last/no-trade intervals. No UTC-date aggregation or fabricated gaps.
- Absent/revised source availability, future event/action/definition publication,
  unknown empty-action coverage and unresolved degraded-day evidence all deny as scoped.
- Chain baseline/update/delete coverage, adjusted contracts, missing term evidence,
  midnight-expiration misuse, resource overflow and consistent v1 denial compatibility.
- Verified-input substitution, copied verification from another scope/config/source,
  forged booleans and later code/rule changes cannot pass the imported bridge.
- Future data/permutations leave earlier causal decisions unchanged; no future
  liquidity/returns affect pair selection; all missing/unaffordable outcomes remain.
- Coverage union/reverse links, exact request limits, initialization/exit/expiry tails,
  missing study requirements and deterministic full-package budget accounting.
- Network, credential access, DuckDB external I/O, broker clients and write capabilities
  are denied in offline tests. All promotion/authorization flags remain false.

Run Ruff, Mypy, pytest with existing 80% overall coverage and applicable 90% critical
branch checks, Bandit, locked-dependency audit, SBOM validation and deployment-manifest
checks in proportion to changed paths. SBOM generation targets a temporary destination;
the already-dirty tracked artifact and other user work remain untouched. Performance
benchmarks measure streaming resource use without proposing production hardware changes.

Success is a tested integration plus an accurate real-input readiness report. It may
correctly conclude that the current archives cannot establish historical availability
or sufficient study coverage. Report `ECONOMIC_NO_GO`/insufficient evidence through
the applicable downstream assessment; never invent market evidence or a selected winner.
Buying more data is not proof that this conclusion will change.

## 10. Review checkpoint and next gate

The operator approved the integrated design brief on 2026-09-25. This written spec
is prepared for review and has been checked for scope, version compatibility, missing
source claims and acquisition-authority separation. Product implementation has not
started. Written-spec approval permits preparation of the implementation plan; review
that plan before Native implementation. The earlier Native workflow preference is
retained, not treated as approval of an unwritten new plan.

All capital assumptions and limits remain unchanged: $100 assumed capital, $150 live
equity ceiling, 0.5% per-trade risk ($0.50 at $100), $50 outer per-trade ceiling,
$50 non-replenishing cumulative trial loss and all stricter rules. The acquired data,
this specification and research-only evidence grant no broker/runtime or live authority.
