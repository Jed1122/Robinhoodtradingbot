# Durable offline options ledger design

Status: **proposed written specification; awaiting operator review**.
Inspected implementation base: `e9eb0948cddf6f4bc47d93901891a70dd8f92b4a`.
The operator approved writing this design on 2026-09-22, with the durable ledger
prioritized before native historical-data normalization. This document does not
authorize implementation, broker access, production migration, or live activation.

## 1. Intent and success boundary

Build the missing durable, independently reconstructed local options book. Retain
local intent/ownership facts separately from external-style observations, recover
cash, obligations, reservations and incidents after restart, and supply the existing
reconciliation and expiry monitor without copying the comparison snapshot into the
local book. The first implementation is credential-free and synthetic-only.

A successful milestone demonstrates identical uninterrupted and restarted economic
state, deterministic source-bound comparisons, and truthful incomplete outcomes.
It is not full options pretrade composition, genuine economic evidence, a connected
paper service, or production lifecycle certification.

Governing requirements remain the [master specification](../../options-only-build-spec.md)
and [approved migration plan](../plans/2026-09-18-options-only-migration.md), including
the subsequent stricter one-unit, one-position, one-new-position-per-session trial
restrictions. Preserve the $100 capital assumption, $150 live-equity ceiling, 0.5%
per-trade limit, $50 outer per-trade ceiling and non-replenishing $50 cumulative
trial-loss ceiling. Other applicable stricter controls remain unchanged. A research
fixture's hypothetical starting cash cannot change any live authorization.

All public results keep `source_kind=synthetic`, `production_eligible=false`,
`evidence_promotable=false`, `live_authorized=false`, and `paused=true`. A clean
reconciliation never changes those fields.

## 2. Current code and reuse decisions

| Existing component | Reuse | Missing responsibility |
| --- | --- | --- |
| `domain/options.py` and `options_account.py` | Contracts, structures, normalized observations and section completeness | Independent local facts and their durable economic history |
| `domain/order_state_machine.py` | Exact existing order transition table and enum spellings | Durable linkage from an options intent to outcomes and accounting |
| `risk/options_economics.py` | `TrialEpisode`, `TrialLossState`, necessary capital filter | Event-derived episode cash flows and finality, not caller assertions |
| `risk/options_loss_history.py` / `persistence/options_risk.py` | Flow-neutral loss evaluation and latched history | New book linkage to independently supplied liquidation observations |
| `persistence/options_trial.py` | Existing synthetic reservation history and fencing rules | Atomic linkage to the local ledger transaction |
| `runtime/options_recorded_session.py` | Compatibility reference for paused recovery | Independent multi-episode book; existing immutable-script evidence stays readable |
| `reconciliation/options.py` and `lifecycle/options_expiry.py` | Comparisons, incidents, conservative explicit-calendar deadlines | Retained inputs and reproducible reconstruction |
| `runtime/options_monitor.py` | Paused scheduling, observation freshness, alerts, result storage | A durable offline observation source |
| `persistence/base.py`, lease repository and Alembic | Exact values, WAL/FULL policy, constraints, one fenced writer | Additive tables and atomic append API |

Do not edit the pre-existing dirty main CLI, architecture document, equity replay
work, or SBOM as part of implementation without resolving that separate ownership.
New options operator composition remains in its own module. No dependency purchase,
new service, parallel risk policy, replacement configuration loader, or replacement
order state machine is required.

Three approaches were considered:

- **Append-only local facts plus separately retained observations — selected.**
  Rebuildable, auditable, and compatible with existing journals; requires explicit
  transaction and source-link contracts.
- Broker snapshot mirrored into local tables — rejected. Matching the broker to a
  copy of itself cannot establish independent ownership, cash accounting or recovery.
- Expanding the immutable-script replay into the production book — rejected for
  this slice. Its single-script identity and legacy hashes serve a different purpose;
  preserve it as a fixture/replay facility instead of reinterpreting old evidence.

## 3. Scope

Included:

- A private synthetic ledger initialized once from an explicit flat genesis.
- Single-leg standard-deliverable long calls/puts, complete integer units; no
  fractional options or admission beyond the existing trial limits.
- Sequential episodes with durable local intent/structure ownership, order events,
  fills, bounded fee allocations, settlement obligations and external cash flows.
- Separate retained synthetic observation snapshots, calendars and valuation inputs.
- Transactional append, duplicate handling, fencing, paused reconstruction, durable
  incident history, and a source adapter for the existing monitor.
- Temporary-database migrations, corruption/failure tests and offline operator reports.

Excluded:

- Broker SDK/transport changes, provider parsers, account access, credentials,
  order review/place/cancel/replace, exercise/DNE, stock remediation and live service wiring.
- Paid data, native data normalization, historical strategy selection or new exit rules.
- Multi-leg package execution, short-option admission, margin borrowing and automatic
  collateral netting. Unexpected short/multi-leg observations must still be retained
  as incidents; absence of support is not permission to discard them.
- Manual incident clearance, automatic resume, real production migrations, destructive
  downgrades, deployment, off-host backups or hardware changes.

This slice does not make the necessary capital filter a complete options pretrade
engine. Scripted synthetic acknowledgements/reviews are labeled simulation events,
never authenticated broker review or production risk approval.

## 4. Authorities and data flow

```text
explicit synthetic genesis + local intent/ownership facts
                  + attributed synthetic execution events
                  + explicit fees/settlement/external flows
                                   |
                       fenced atomic local ledger
                                   |
                         deterministic projection ------+
                                                       |
retained comparison observations + calendars ----------+--> existing monitor
                                                       |      |
separate broker-style / liquidation valuation inputs --+      +--> paused report
                                                              +--> durable incidents
```

The local book consumes attributable event-level execution facts, not aggregate
broker positions or balances. A known local intent is required before a fill can
be attributed to owned exposure. An external order, unmatched fill or aggregate
snapshot cannot create ownership. No reconcile-to-broker overwrite/reset command
is provided.

Keep three distinct identities: the immutable local ledger head, the retained
comparison observation hash, and the monitoring run identity. Repeated polling may
create a new monitoring run but must not refresh the observation time or change
economic history. Source hashes prove content binding, not provider authenticity.

## 5. Versioned records and exact boundaries

Introduce closed, immutable records in new domain/codec modules. Proposed public
concepts are `OptionsLedgerScope`, `OptionsLedgerEvent`,
`RetainedOptionsObservation`, and `OptionsLedgerProjection`. Reuse the existing
contract, leg, intent, account-observation and cash types inside their appropriate
envelopes; do not duplicate their financial validation.

The scope binds a synthetic account ID in a reserved namespace, ledger ID, canonical
configuration hash, schema version, genesis cash and explicit history start. One
genesis is permitted per ledger/account. Initial holdings, obligations and orders
must be empty; importing existing positions is a different future workflow. Changing
the ledger ID, account, config or date cannot reset an existing account's trial history.

Each event binds event ID/type, account/ledger/config, sequence, predecessor hash,
writer fencing token, producer code identity, recorded UTC time, economic occurrence
time, typed payload and referenced evidence hashes. Payloads carry no arbitrary
Python objects, arbitrary paths, credentials or raw provider response dictionaries.
Decimal values are canonical strings; quantities are exact bounded integers, never
booleans/floats. Unknown fields/versions, duplicate JSON keys, invalid UTC or over-limit
payloads deny processing with sanitized reason codes.

Recording time follows the trusted injected clock and may not regress. Economic
occurrence time is distinct: late evidence is retained rather than backdated or
silently sorted into previously published history. Automatic booking only accepts
attributable, causally valid events; unsupported late/corrected/conflicting facts
produce an unresolved incident and retain their observation preimage. No history
rewrite or terminal-order reopening is allowed in v1.

Use existing canonical replay/input limits, never scenario overrides. V1 event payloads
are capped at the lesser of 16,384 bytes and `options.replay_max_bytes`; retained
observation/scenario documents and aggregate canonical bytes examined by one recovery
are capped at `options.replay_max_bytes` (currently 4,194,304). Event/row collections
are capped at `options.replay_max_records` (currently 5,000) and JSON nesting at
`options.replay_max_json_depth` (currently 16). Nested collection counts share the
same total budget rather than receiving a fresh allowance per section. Count/size
checks precede decoding or accumulation. This intentionally bounds small rehearsals;
exceeding a bound denies completion, never drops old losses or increases the limit.

Reuse canonical 512-character Decimal bounds and SQLite integer storage bounds.
Perform monetary arithmetic in a fixed 2,048-digit local context with inexact results
rejected, independent of ambient precision. Validate computed outputs again before
persisting; no implicit rounding, cent truncation or binary float conversion.

Supported local event families:

| Family | Required meaning |
| --- | --- |
| Genesis | One flat synthetic starting state, explicit currency and cash |
| Intent/ownership | Durable immutable opening or closing intent, exact structure/episode links and reserved capacities |
| Order transition | Existing `OrderEvent`/`OrderState` rules, attributed source, no inferred acceptance |
| Fill | Unique fill/order/contract/side/effect identity; whole quantity, exact premium and explicit fee allocation |
| Fee finality | Complete attributed fee evidence, distinct from a fee estimate or a zero observed so far |
| Settlement obligation / completion | Signed receivable or payable and explicit due/completion facts; no calendar arithmetic shortcut |
| External flow | Explicit deposit/withdrawal, excluded from trading P&L and trial replenishment |
| Observation / incident | Retained comparison inputs, unresolved lifecycle/liability facts, and append-only incident evidence |

Existing v1 trial/replay/risk payloads, hashes and serialization remain unchanged.
Schema/version readers preserve historical access; a new writer must not silently
reinterpret an old ledger under a changed config. Producer code identity is retained
as evidence, not rewritten to the reader's revision.

## 6. Accounting, reservations and finality

Distinguish four amounts: settled cash, unsettled receivables/payables, unspent cash
commitments, and trial/payoff-risk reservations. They are not interchangeable.

- A new entry reserves full premium risk and bounded round-trip fees before any
  synthetic transport outcome is processed. Canonical percentage, absolute, activity,
  whole-unit and trial limits remain necessary conditions. Zero admissible units stays zero.
- Bind the authorized research risk-equity reference to genesis; gains/funding cannot
  enlarge it. Apply the lesser current/authorized reference where required while
  retaining the current-equity basis of the cash floor. Never substitute one balance
  for both just to reuse a filter; missing required capital evidence denies admission.
- An entry fill moves the attributable cash commitment into a payable; settlement
  later debits settled cash. Do not debit cash at both fill and settlement. Unused fee
  commitments remain reserved until the corresponding uncertainty is resolved.
- A closing fill creates a receivable net of explicitly attributed fees; it is not
  available settled cash until a matching settlement-completion event. The risk
  reservation remains until the entire episode is final.
- Cash commitment and payable portions of the same obligation are mutually exclusive;
  payoff/trial risk is a separate constraint and must not be deducted a second time
  from cash. Fee rows cannot also be counted inside a net amount and charged again.
- Orders, contracts, strategy positions and episodes have separate identities.
  Opening rejection/unfilled cancellation can complete a zero-fill episode only
  after all possible outcomes, fees and obligations are explicitly final.
- A cancellation request, timeout, ambiguous acceptance, stale observation, pending
  settlement or end of input cannot release the trial reservation.
- Completion is derived: flat, all related orders terminal with reconciled outcomes,
  and fees/settlements final with no unresolved episode incident. Callers cannot set
  `complete=true` or inject completed P&L. Reuse `TrialEpisode`/`TrialLossState` once
  those conditions have been derived.
- Completed losses accumulate as `sum(max(0, -episode_net_cash_flow))`. Profitable
  episodes, funding, restarts, calendar changes and a later roll never reduce that sum.
  A roll is a separate closing episode and newly evaluated entry, not a loss reset.

Cost basis, realized cash-flow P&L and valuation are separate. Document the local
premium cost-basis convention; do not call it verified broker tax-lot treatment.
Spread/slippage embodied in recorded fill prices is not deducted again. A late fee
or economic correction after declared finality is retained as an incident and
blocks new simulated admissions; v1 does not silently reopen/rewrite a completed
trial episode or advertise a repaired loss budget.

Single-contract ordinary orders cannot legitimately have a fractional partial fill.
Exercise partial-fill handling using observed multi-unit/unmatched anomaly fixtures
without admitting a multi-unit strategy under the one-unit trial profile. A whole
contract fill during `CANCEL_PENDING` uses the existing race transition. A conflicting
fill after terminal cancellation is retained and escalated, not discarded or forced
through a forbidden order-state transition.

## 7. Valuation, losses and snapshot projection

The new accounting reducer does not price options or invent buying power. Retain
independently supplied, timestamped synthetic valuation inputs with explicit mark
kind: broker-style comparison mark versus conservative liquidation mark. A last fill,
theoretical value or broker mark cannot silently become an executable liquidation mark.

The projected local ledger can always report its exact booked balances and known
obligations. Construction of a complete `OptionsAccountSnapshot` additionally requires
all existing required fields and a documented synthetic cash-account policy for
derived buying power/equity. That policy is fixture semantics, not a statement about
Robinhood cash or limited-margin accounts. V1 admits no margin collateral; any
unexplained nonzero collateral or borrowing is an incident, not netted protection.

Missing comparison marks, valuation coverage, account-field semantics or section
coverage yields an explicitly incomplete projection/result. Do not fill mandatory
fields with fabricated zeroes and call it complete. Until a full snapshot is available,
the projection reports a typed incomplete result to the offline coordinator. The
observation source raises a sanitized incomplete-source error instead of returning an
invalid `OptionsMonitorInput`; the existing monitor's failure path stays unclean.
Do not change its protocol to accept fabricated partial snapshot values.

When complete independently sourced liquidation observations exist, derive the
`OptionsLossPoint` input from the current ledger head, retained valuation hash,
explicit session boundaries and cumulative external flows. Reuse existing flow-neutral
loss evaluation and risk-journal latches. No mark or session means no completed loss
evaluation. Absence of a risk report never permits an entry. Weekly/drawdown latches
survive recovery and cannot be cleared by this milestone.

The legacy reconciler compares broker-style marks, cost basis and buying power exactly.
Preserve those conservative denials. If a real provider later uses different semantics,
that requires a separately reviewed mapping/comparison policy; do not weaken this
comparator to make synthetic recovery or future broker snapshots appear clean.

## 8. Persistence and transaction contract

Add Alembic-owned tables after the current head (`0007_options_risk_history`), using
existing exact column types and append-only guard patterns. Conceptually retain:

- A ledger scope/genesis record and ordered, hash-chained local events.
- Normalized immutable intent/strategy-leg and fill-to-episode links.
- Reservation movements, fee allocations and settlement facts, each uniquely bound
  to its causal ledger event and account. These are journal-derived facts, not another
  independently editable balance store.
- Canonical retained observation preimages with hashes, section completeness,
  history windows, original observation time and source labels.
- Incident records and monitor-run links to the exact local head and observation hash.

Small normalized observation preimages live in the same transactional SQLite database,
within explicit bounds. This avoids a new non-atomic database/file commit protocol.
Bulk market history stays in Parquet outside the ledger. Raw authenticated provider
payload retention is not introduced; the first envelope contains only synthetic,
closed normalized records. A future authentic adapter must establish its own supported
mapping/retention contract and authority.

One account-scoped transaction uses `BEGIN IMMEDIATE`, the existing durable lease and
fencing token, explicit expected head, and validated session factory. Validate the
leader after lock acquisition/awaits, after reconstruction and immediately before
commit. Reject expiry, takeover, account mismatch and backward clocks. Persist intent
and all reservation evidence before synthetic submission can be observed.

The local event, normalized rows and any resulting existing trial/risk journal append
must commit together or not at all. Do not nest separately committing `append()` calls.
Introduce narrowly scoped transaction-internal journal helpers under coordinator
ownership while preserving current public APIs and old payload/hash formats. Existing
callers continue to own their original transactions. Tests prove no helper bypasses
the same identity, lease, chronology, CAS and duplicate checks.

Exact current-tip retries return the durable receipt without new economic effects.
Conflicting duplicates and superseded retries deny automatic replay; a read-only lookup
may explain the original receipt but cannot authorize a subsequent action. A timeout
around commit is an unknown outcome: read and validate the original event/head before
considering another append. Never turn uncertainty into a new event ID or reservation.

Every derived cache must bind the ledger prefix and reducer version and be disposable.
Recovery recomputes and checks financial history; caches cannot override it. Invalid
sequence/hash/reference/fencing chronology, truncation or excessive history halts
recovery without deleting or repairing evidence. Hash chains and triggers do not
protect against a privileged database owner rewriting all data and anchors; external
attestation remains a separate production prerequisite.

No production database is migrated. Downgrade refuses to erase nonempty new history.
Offline rollback compatibility means an old reader either reads its supported old
schema unchanged or explicitly refuses the newer schema; never delete new evidence
to make old code start. Reuse online SQLite backup for temporary synthetic restore
tests. A restored database does not renew a lease, refresh observations or clear incidents.

## 9. Recovery, monitoring and incidents

Startup sequence is: verify scope/schema -> verify complete bounded history ->
reconstruct local state and trial/risk history -> restore unresolved incidents ->
report paused/incomplete until independently retained comparison inputs are usable.
Acquiring a new lease grants ledger-writing exclusivity only, not entry permission.

An `OfflineLedgerObservationSource` supplies the existing `OptionsMonitorInput` from
the local projection and a separately selected retained observation/calendar set.
Account, config, history window and as-of identities must match; inputs cannot refer
to a future local head or refresh their timestamps on reload. Persist monitor-run
input linkage before evaluating; append the result/incident link afterwards. A crash
between these operations leaves a pending run, never a saved clean verdict. A repeated
evaluation can be explicitly linked as a retry without duplicating ledger economics.

Retain normalized exercise, assignment, expiration, broker-closeout and unexpected
share observations without auto-applying guessed cash, option or stock effects.
Missing impact evidence leaves the local state incomplete and the incident latched.
Existing expiry assessment uses retained complete calendars and the preceding eligible
session deadline; no weekday approximation, automatic exercise, fictional close or
guaranteed broker intervention. Monitoring continues where safe during entry halts.
Database/alert failures remain visible and cannot be called healthy reconciliation.

## 10. Offline operator surface and privacy

Use a separate `python -m trading_bot.cli.options_ledger` module. Proposed operations:

- `rehearse`: bounded synthetic scenario -> private dedicated ledger -> paused report.
- `inspect`: verify/reconstruct an existing dedicated synthetic ledger read-only.
- `resume-rehearsal`: continue an explicitly identified synthetic input prefix with
  expected durable head, after recovery; this does not resume production entries.

No broker endpoint, account-number input, auth flag, live flag, arbitrary transport,
production database target or reset/clear command. Writer paths are scoped to a new
private output root and dedicated synthetic ledgers; reject unrelated/existing database
content before migration. Use descriptor-relative no-follow protections and inode
ancestry checks against repository paths, including aliases on case-insensitive systems.
Inspection cannot automatically migrate or book writes to the inspected source database.
Use SQLite's read-only source connection/consistent online snapshot machinery, with
unavailable WAL state a denial; never blindly copy active WAL files or apply the
writer engine's mutating PRAGMAs to an inspection source. Any validation needing the
ordinary writer engine runs on the consistent private temporary snapshot, not the source.

Stdout contains sanitized counts, ledger/report hashes, paused state and reason codes,
not payloads, sensitive identities or private paths. Detailed synthetic artifacts use
0700 directories and 0600 files. Tests substitute temporary identities/SQLite files
and block network and credential access. No production credentials or broker-client
imports are reachable through this composition.

Complete, internally consistent rehearsal exits 0 while retaining false eligibility
flags. Invalid input, incomplete history, unresolved incidents or uncertain persistence
exit 2 with explicit reasons. End-of-input outstanding exposure is incomplete, not
an artificial closing fill. Repeated inspection is non-mutating and deterministic.

## 11. Acceptance evidence

Write failing tests before implementation and independently calculate expected values.

| Case | Required observation |
| --- | --- |
| $100 hypothetical cash, $0.10 premium, multiplier 100, $1 fee bound | $11 full risk does not fit $0.50 per-trade budget; zero admitted units |
| $2,500 hypothetical tier; buy $0.10, sell $0.16, 100 multiplier, $0.50 fee each side | Once both settlements are complete: cash $2,505; episode net +$5; trial loss consumed $0 |
| A separate later-session episode buys $0.10 and sells $0.04 with the same explicit fees | Episode net -$7; cash $2,498 after both episodes; cumulative consumed loss $7, not $2 |
| Entry filled but not settled | Payable and residual cash commitment conserved; no double debit; full trial reservation retained |
| Flat after closing fill, closing receipt still unsettled | Receivable retained; no replenished settled cash; episode/trial still incomplete |
| Exact duplicate event or interrupted commit retry | One fill, one fee allocation, one settlement and one reservation effect only |
| Unknown acceptance, cancel request/race, unsupported partial/unmatched observation | No automatic retry or premature release; evidence retained; unresolved status truthful |
| Independent broker-style snapshot changed but local facts unchanged | Mismatch/incident; no local balance or ownership repair |
| Restart at each order/fill/fee/settlement boundary | Same head-derived balances and reservations as uninterrupted replay; status still paused |
| Deposit, profit, new session, config mismatch, attempted new genesis | No replenished trial capacity or cleared weekly/drawdown latch |
| Assignment, unexpected shares, negative cash, deadline miss | Persisted incident; no exercise, stock order, automatic liquidation or silent flattening |

The numerical examples use invented fee/price inputs, not current market quotes,
broker fees, an economic forecast or permission to increase the account balance.
The $2,500 scenarios still face all applicable existing necessary filters, including
the retained order-notional cap; they do not certify the unimplemented full pretrade path.

Additional tests must cover account/config substitution, fee finality conflicts,
same fill under different delivery IDs, duplicated settlements, missing source artifacts,
zero versus missing values, invalid Decimal contexts, all schema/type/resource bounds,
stale clocks and leases during waits, competing writers/CAS, database lock/corruption,
disk-full/flush/commit failures, bounded recovery overflow, mutation/REPLACE guards,
failure to alert, stale evidence on restart, backup/restore and denied destructive
downgrades. Test old v1 hashes and public journal APIs unchanged.

Retain the 80% overall coverage gate and add every new ledger reducer, codec,
persistence and recovery module to the explicit 90% per-file branch gate. Run Ruff,
Mypy, non-authenticated pytest, Bandit, locked audit when authorized, temporary SBOM
validation and deployment-manifest checks. Authenticated tests stay excluded; fixture
success cannot set evidence/promotion flags. Encrypted restore tests may report a
missing local cryptographic tool as a skip, never as a successful encryption test.

## 12. Implementation boundaries and next handoff

Implementation planning follows operator review of this written spec. Dependency
order: frozen versioned record/transaction contracts -> exact reducer and independent
cash fixtures -> additive atomic persistence -> retained observation/recovery source
-> monitor/CLI integration -> fault, compatibility and restore validation. The first
vertical slice must already demonstrate an entry, closing fill, delayed settlement
and restart through the real temporary SQLite ledger; no placeholder success path.

Coordinator retains ownership of schema design, accounting, reservations, risk,
execution transitions, reconciliation, recovery and integration. Once interfaces
are frozen, isolated agents may handle synthetic codec fixtures, documentation,
CI checks and independent adversarial tests with exact bases and file ownership.
No Cloud dispatch is implied by local agent work.

Native data work remains separate: the existing importer retains provider-native
definitions but does not expose a verified normalization stream or establish contract
enrichment/availability. The imported shortlist remains denied. An independent local
read-only inventory confirmed these boundaries; no raw dataset was shared. Genuine
economic testing, complete live pretrade composition, verified broker/account/runtime
capabilities and separate operator activation remain later gates.

Review checklist: no duplicated monetary authority; no reservation release on mere
terminal order status; no source snapshot copied into local ownership; no invented
valuation/settlement; no historical hash rewrite; no new live-capable composition.
