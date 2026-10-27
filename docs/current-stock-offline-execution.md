# Current-policy offline stock execution

This is an explicitly fictional simulation seam for Task 5. It connects current
research decisions to actual deterministic sizing, risk/reservation and durable
outcome accounting. It creates no Robinhood connection and cannot authorize live
trading. No prospective paper-trading waiting period is required.

`execution.stock_intents` requires a distinct `StockSimulationGrant` bound to the
exact plan, policy, source/analysis/execution identities, report artifact, selected
action, fictional account and before-state hash. Its mode is SIMULATION; account
IDs use the `sim-` namespace. A grant is a caller-supplied simulation receipt,
not a signed real-broker activation or profitable historical qualification.
Fresh executable instrument/quote/session/liquidity/earnings/sector evidence is
supplied separately from indicative research marks. Missing evidence fails closed.

The mapper reproduces the source plan/report identity and checks actual paper
lots, original episode/fill/profit progress, current issuer mappings and complete
held/pending exposure. It creates one stable UUID across the canonical intent,
PaperOrder and official-format argument drafts. Fees/slippage count inside cash
ceilings; tactical stop-risk is explicitly modeled and capped. Long-term entries
receive no invented stop. Neither a tripling scenario nor a relative score becomes
a return forecast or a legacy ResearchAssessment.

`execution.stock_simulation_journal.StockSimulationJournal` is an opt-in owner of
an isolated experimental account on the existing canonical SQLite ledger. Its
required profile and namespaced identity reject unrelated/legacy account adoption.
The default HybridJournal/Account path keeps its wire behavior. Approval, source,
terms, review, attempt and original clock receipts persist with the hash chain.
It reuses the existing pure reserve/fill/settlement/valuation helpers through an
explicit base-account projection; there is no second cash ledger.

The caller sequence is:

1. Explicitly initialize a fictional account. Value it through `mark_market()`
   using complete, fresh supplied marks, then build the next plan/context/grant
   against that exact before-state. New marks invalidate an older state grant.
2. Call `reserve(context, grant=..., selection=...)`. The actual risk checks and
   cash/share encumbrance commit in the same journal transaction. Matching replay
   returns the original preparation without renewing clocks or reserving twice.
3. A deterministic simulated broker reviews the exact intent. Call
   `claim_submission(intent_id, review)` for a one-time, durably recorded simulated
   handoff. A duplicate or restarted owner gets no new ticket. A changed safety or
   account state must be reviewed again; no automatic resubmission is permitted.
4. Record the exact simulated order or a closed ambiguity diagnostic. Unknown
   outcomes keep commitments and pause new work. Bind the known broker order ID
   before applying causal, uniquely identified fill facts. An acknowledgement or
   cumulative order summary alone does not create lots or proceeds.
5. Apply actual simulated fills with `record_fill()`. Only confirmed terminal
   outcomes release the unfilled remainder. A cancellation acknowledgement does
   not release it; reported cumulative fills cannot be erased by a later reply.
   Owned fills can reconcile after the original approval has expired.
6. For sales, retain the caller-supplied explicit future settlement fact. Only
   `settle_due()` credits those proceeds when due. Taxes are estimated on actual
   gains, not gross proceeds. Revalue with `mark_market()` before the next plan;
   loss suspensions stay latched until an explicit operator action.

The only broker driver used for verification is the deterministic FakeBroker in
the test harness. Neither this owner nor the mapper has a BrokerPlace/SDK port.
A simulated handoff ticket is not real-money authority. A crash before handoff
may retain an unsubmitted reservation for explicit review; there is no automatic
absence-based release or restart retry. A cancelled partial principal-value trim
may remain HOLD until its source policy proposes another eligible action; the
bridge does not override source HOLD or reset completed progress.

Run the offline integration checks from a configured development checkout:

```sh
PYTHONPATH=src:. python -m pytest \
  tests/unit/execution/test_stock_intents.py \
  tests/unit/execution/test_stock_simulation_journal.py \
  tests/unit/hybrid/test_journal.py \
  tests/integration/execution/test_current_stock_simulation.py \
  tests/integration/persistence/test_current_stock_execution_source.py -q
```

These checks use temporary migrated SQLite databases and fictional prices/fills.
Actual dedicated-account ingestion, official broker authentication and supported
order/reconciliation mapping, external deployment/monitoring and separate live
activation remain subsequent project work. This seam does not establish durable
investment performance or a continuously operating deployment.
