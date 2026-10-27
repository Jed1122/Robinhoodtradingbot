# Task 5 current-policy offline execution bridge

The final requirement audit found that the current proposal layer does not yet
connect an explicit current-research policy approval to order sizing, independent
risk/reservation and restart-safe outcomes. This is required software work.
Actual official-account integration, runtime deployment and live activation remain
separate. A pure argument serializer or unrelated execution tests do not satisfy
this seam.

Use the existing isolated multi-stock experimental Account/HybridJournal as an
explicitly fictional simulation owner. Reuse its transactional hash chain,
reserve_order, fill_order, cancellation and settlement semantics. Do not adopt an
actual brokerage account into that model, create one full-cash ledger per stock,
fabricate historical ResearchAssessment/eligibility, invent return forecasts or
force a tactical stop onto a long-term entry. No mandatory prospective paper wait.

Implementation order and disjoint ownership:

1. Engine worker freezes and implements pure manual-policy approval, current-plan
   selection and source-bound intent sizing in execution/stock_intents.py
   plus unit tests. It supports entries, sourced holding exits and profit
   reductions; ordinary payload preparation has no transport authority.
2. Persistence worker adds an opt-in simulation account/attempt model and journal
   owner without changing default Account wire bytes. Explicit initialization and
   namespace/config binding prevent adoption of an existing unrelated ledger.
   Exact original approval, source/report identities, terms and clocks persist.
3. Root composes actual source-plan preparation and existing risk/reservation in
   one journal transaction, a durable pre-transport claim and explicit simulated
   outcome/reconciliation application. Duplicate/restart requests never receive a
   new transport ticket. No official SDK/broker connection is constructed.
4. Root tests the complete path from current fictional research through immutable
   plan, approval, sizing, real risk/reservation, simulated rejection/partial/
   ambiguous outcomes and restart reconciliation. An independent reviewer checks
   the frozen implementation against these requirements before release.

Required invariants:

- Default and persisted live/execution-authority claims remain false; the only
  supported execution scope is simulation and its account identity is explicit.
- The separate manual grant binds exact plan/policy, analysis/source/execution
  config, fictional account, sleeve, before-state hash and original expiry.
  Recheck inside reservation and immediately before a one-time simulated handoff.
- Caller-supplied current executable quote/instrument/session/liquidity/earnings
  and complete exposure evidence stays distinct from indicative research marks.
  Missing or stale evidence, kill/pause, unknown ownership or inconsistent context
  fails closed. No inferred issuer mapping, borrowing or short sale.
- Whole/fractional quantities, fees/slippage, cash ceilings, company/issuer/sector/
  sleeve caps, cross-sleeve duplication and actual pending commitments are checked
  against the transaction's current state. Tactical risk is at most0.5%; long-term
  holds do not gain an invented stop or fixed-profit liquidation.
- One stable UUID binds PaperOrder, canonical OrderIntent and review/place terms.
  Persist source/report/approval/intent identities before any simulated handoff.
- A durable submitting/ambiguous state retains cash/share encumbrances. An
  observation timeout, disconnect, acknowledgement or absent result cannot release
  a hold or authorize another submission. Reconcile using exact owned identity.
- Only confirmed terminal rejection/cancellation/expiry releases an unfilled hold;
  partial fills preserve remaining commitments. Cancellation ACK is not terminal.
- Fill IDs/terms/quantities and causal clocks are verified. Actual simulated fills
  alone update cost basis, gains, taxes and settlement; estimates never credit
  cash. Replays are idempotent and conflicting reuse fails closed.
- Existing generic historical/forecast approval paths remain unchanged. Software
  tests prove this seam only, not profitable stock selection or live readiness.

Keep bfa6134 and its ongoing CI source frozen in the prior worktree. This isolated
successor starts at that commit; merge verified slices without restarting old runs.
