# Incremental ETF replay and protected cost recording

## Authority and outcome

Continue the merged quote intake at `8c4edc57cfc1af5c023d8d6f98ad1afd1a1e7071`.
The user requests native implementation without repeated approval rounds and has
authorized one Robinhood Agentic diagnostic trade, conditional on existing safety
gates. This design does not authorize bypassing them. Alpaca remains the sole
market-data channel. No deployment, credential replacement or additional sampling
trades are included.

Deliver a working incremental research consumer and a protected execution-owner
recording seam. Real execution remains a separate acceptance condition, not a
consequence of this code passing fixture tests. The current adapter is read-only;
nonempty reconciliation, authenticated write evidence, a live lease and trusted
runtime/promotion composition are absent. No provider write implementation may be
invented from a declaration or routed around the common owner.

## Shared account reduction

Extract the existing account loop into a suspended one-event reducer. Both legacy
replay and `EtfAccountStepper` use it; retain exact canonical JSON-array prefix
hashes, risk arithmetic, duplicate semantics, loss latches and dictionary order.
Each accepted fact is reduced once during advancement. The public 10,000 physical
account-fact bound stays unchanged. An invalid advancement poisons that reducer;
its last committed output remains available but cannot authorize continuation.
Reconstruction from the verified bounded fact tape creates a fresh reducer.
Pending-intent preview remains isolated and uses the existing admission owner;
infrequent admission may reconstruct its tape, never a second risk calculator.
Do not hold a Decimal context across generator suspension.

## Versioned chunked source replay

Keep v1 request/result validators and hashes unchanged. Add a v2 research consumer
bound to the legacy study/config/cost/instrument/schedule context and an explicit
catalog identity. Its source is an ordered iterator, not a whole-history tuple.
Chunks contain at most 10,000 events, total source delivery at most 100,000,000;
account facts remain bounded at 10,000. Retain at most 10,000 detailed decisions
with exact aggregate reason counts thereafter. Retain all bounded daily/account
outputs; do not call an exhausted bound a complete economic result.

Reuse the existing native lifecycle loop across chunk boundaries. A boundary is
not end-of-input: do not finalize a session, force a sale/settlement, reset
capacity or acknowledgement/cancel schedules, or add end-of-source reasons.
Release capacity keys only when the native quote frontier advances; older native
quotes remain denied. Native bars/calendar/distributions form a bounded baseline;
merge catalog quotes lazily with the existing availability/kind-priority tie rule.
Preserve quote duplicates and provider receipt/native identities. The catalog is
capture-bounded, not page-streaming.

A v2 checkpoint binds context, catalog, consumed count and canonical source-prefix
hash. Recovery re-verifies/reduces that prefix once, checks the complete checkpoint,
then continues the same owners; it does not trust a caller-supplied output or jump
to an unverified cursor. This is bounded-memory replay with verified-prefix recovery,
not constant-time recovery or a serialized closure. Source failure after a yielded
prefix denies completion. The untouched 2024–2025 holdout is not evaluated.

The historical-control/publication waivers allow exploratory latest-vintage
research, not invented observed controls or complete quote coverage. Existing
unverified quote/control/size reasons stay visible and deny simulated fills where
the existing execution owner lacks admissible inputs. No zero costs or qualified
economic verdict follows. All new results remain paused, execution-disabled and
non-promotable.

## Protected recording

Add an optional execution-owner observer, absent by default, to the existing
persisted-before-place service. Record the decision after initial risk approval
and before review; record submission immediately before placement, only after
the final risk evaluation and committed submission reservation. Recorder failure
before placement means zero placement calls; the durable reservation remains
unresolved. Record a matched accepted/rejected response, never a fabricated
acknowledgement after timeout or an unmatched response. Failure after transport
must preserve the durable broker outcome and may not trigger retry.

The observer receives domain objects internally and projects only hashes/safe
economic terms to the owner-private receipt sink. It uses the sink's UTC and
monotonic clock session; provider timestamps are not local arrival clocks.
Alpaca frames and selected decision quote must be retained in that same sink.
This seam cannot construct a broker or a live execution service.

Add an additive receipt-v2 final-fee event: only after a terminal order without
fees; bind to the exact terminal receipt and order hash, retain its source, require
explicit reconciled components, allow an exact duplicate idempotently, reject
conflicting or repeated finalization. Legacy v1 receipts remain readable; absent
fees remain absent, explicit zeros remain zeros. Source linkage does not attest
broker semantics, customer provenance or fee completeness. Corrections after a
declared finalization require new evidence handling, not silent overwrites.

## Acceptance and non-goals

Test every account prefix against unchanged hand-checked lifecycle expectations,
chunk boundaries, duplicate/conflicting facts, failure poisoning, restart prefix
substitution, holdout exclusion, late source failure, receipt-storage failures,
ambiguous response, response mismatch and delayed final fees. Run focused tests,
Ruff, Mypy, full default pytest, unchanged coverage gates and independent review.
No authenticated tests in CI. No credentials/customer records delegated.

This does not supply missing historical spans, genuine fills, accepted economics,
write-capability/account/runtime attestations, paper/shadow clocks or deployed
recovery. A single eventual genuine trade cannot establish a strategy edge or
full historical execution-cost distribution. Report these separately.
