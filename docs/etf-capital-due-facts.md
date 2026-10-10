# Original-bound assumed due facts

`_capital_due_facts` is a private composition helper for the future original-input
research evaluator. It reconstructs the complete v3 account tape through the same
account/prefix reducer. It accepts no saved cash, quantities, risk latches,
completion assertions, preapproved entries or broker capability. Original risk
observation cursors only establish the next sequence frontier, not approval.

Five original daily/noninterpolated opening bars must match the original calendar
session and all five supplied action archives. Absent actions remain unknown;
duplicate source record identities deny. The helper does not authenticate any
archive or turn a private record into a qualification token.

Research convention: each SELL fill settles at the opening of its second
subsequent original calendar session (assumed T+2). This is not account-specific
broker verification. Weekdays, evaluator-frame offsets and a native simulator's
default are not substitutes for the original calendar. A missed due session
denies instead of silently retiming settlement. No input end creates a payment,
settlement, cancellation, finality declaration or forced sale.

Held split/distribution events bind the reconstructed account, unique original
BUY opening order and symbol. Split quantity/basis and entitlement cash are
computed by the existing reducer. Current raw opening marks are declared
research marks, not fresh quotes. Entitlement plus ex-mark precedes other
same-opening observations, so a cash-settlement fact cannot manufacture a
dividend-related NAV loss. Flat accounts create no fake position-bound actions.
Coincident held split/distribution is unsupported without an independently bound
cross-type per-share convention; active-order actions/payments also deny.

Each original unpaid entitlement pays at the first declared calendar opening
on or after its supplied pay date, including a same-session entitlement/payment.
Amount comes from the original account-prefix receivable delta. Sale does not
erase it; payment cannot reinvest it or create a second NAV gain. Missed payment
deadlines deny. Out-of-range future obligations remain unpaid and incomplete.

Episode final fees bind the original BUY, only after terminal orders, flat
holdings, settled sales and paid entitlements. The exact episode amount is
reconstructed cumulative fees less the prior episode's original prefix fees.
This is execution-model accounting, not proof of genuine broker fee completeness.
Explicit zero model fees do not mean missing actual fees are zero.

New facts have deterministic original-bound identities and increasing cursors
at the current opening. Exact duplicate originals and retries do not double cash
flows. Historical v1/v2/v3 account and public owner-v5 hashes are unchanged.
The existing 90% critical branch gate includes this module.

This helper is not a complete owned daily runner, walk-forward evaluator, full
workload result, executable economic freeze, qualified dataset or accepted study.
No source/cost/execution/economic/promotion/live eligibility is established.
The original-dataset owner must own these invocation-local arguments, consume
each action frontier through shared risk, preserve incomplete outcomes and bind
all original source/config/calendar/action/cost/selection identities. Existing
production risk limits and live blocks are unchanged.
