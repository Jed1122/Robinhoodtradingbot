# Original-event capital daily owner

This bounded offline increment composes the existing prior-close policy,
daily entry/exit adapters, v3 account/risk reducers and lifecycle replay.
It is not a broker worker, economic study, promotion path or live service.
Release verification and independent review remain pending.

`replay_capital_daily_owner` starts with cash and immutable original frames.
The first completed close may create an instruction but cannot trade its own
opening. A later opening consumes only that prior instruction, with fresh shared
risk/sizing admission and declared adverse price/fee assumptions. Current-session
ranges are used only at the close. Opening stop gaps precede scheduled exits;
ambiguous completed ranges take the adverse stop first. Terminal input never
forces a sale, cancellation, settlement, payment or fee finality.

The owner creates submissions itself. External facts may supply original
controls, fills, actions, settlements and account/opening-order-bound fee finality,
but never preapproved submissions or account balances. Shared account/lifecycle
validation remains authoritative. Active partial/unfilled orders block competing
orders. A unique owned BUY and its first actual synthetic fill bind the original
candidate, holding-session clock and ATR-based protection; later candidate
changes do not rewrite an existing position's policy.

Split declarations adjust that bound protection reciprocally, once per original
event identity, while the same account reducer conserves quantity/basis/cash.
Distribution entitlement/ex-mark and payment reuse the existing atomic NAV and
receivable treatment. Receivables are not spendable cash. Original facts are
observed at their own clocks so later opening marks cannot conceal intermediate
losses. Conflicting action marks fail closed through the shared risk reducer.

Synthetic raw-bar boundaries supply opening/closing clocks. Acceptance at +1s,
fill at +2s and final observation at +3s are explicit daily assumptions, not
measured broker latency, executable quotes or authenticated data availability.
Each supplied frame carries five declared projections and instrument terms.
Later projections must retain the complete owned raw history and append exactly
one session. Missing, rewritten or skipped original sessions fail closed;
split-adjusted feature-price rebasing is permitted without rewriting raw bars.
The caller must supply reset/settlement/finality facts explicitly; there is no
implicit market-calendar, settlement or fee-completeness assertion.

Fixed complete-original input may be replayed through the existing private joint
account/risk checkpoint. Tests cover reconstruction and exact retry of that shared
state. They do not establish durable owner-frame/pending-policy storage, growing
live append, process-worker recovery or selected deployed-runtime recovery.
Full request identity includes the canonical config hash and all original frame
and cost/outcome declarations. No saved balances or approvals are adopted.

Inputs remain bounded by existing account/risk limits as well as the owner's
2,048-frame admission ceiling. That ceiling does not promise that every maximum
trajectory fits the inherited event/observation limits. Full walk-forward workload
performance, train-only selection, dependent uncertainty, economic reporting and
executable study freeze remain subsequent work.

All five source/cost/execution/economic/promotion flags are permanently false.
Tests use fabricated records only; no production limits or broker capabilities
change, and no profitability or live-readiness claim is made.
