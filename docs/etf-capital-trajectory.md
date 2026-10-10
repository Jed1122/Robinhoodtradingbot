# Original-dataset capital trajectory

This is an offline, assumption-based execution path. It is not a broker adapter,
qualified economic study, paper/shadow service, or permission to trade. All
source, cost, execution, economic-admission and promotion flags remain false.

`simulation.etf_capital_trajectory.replay_capital_trajectory` accepts an original
`CapitalResearchDataset`, a configured research capital tier, an exact contiguous
calendar schedule of `CapitalTrajectoryDay`, five declared `Instrument` records,
explicit fees/bounds and one approved round-trip friction level. It owns the
source records and prepares features internally. Prepared features, saved cash,
reservations, risk latches, account events and callbacks are not public inputs.

Each day specifies its candidate or `None` for cash, plus denial-only decision
and submission controls. A flat cash day has `policy=None`; no artificial cash
candidate is introduced. A held position keeps its original candidate, holding
deadline and split-adjusted ATR protection even if the scheduled selection
changes. Changing selection invalidates an old unsubmitted entry, not an existing
position or its protective monitoring. A split between signal and order also
invalidates the stale unsubmitted distance rather than inventing a flat split.

The original-dataset frontend and existing owner-v5 frontend use one private
execution loop and the same account, risk, loss, sizing and lifecycle machinery.
The old public request/result shapes and v5 hash preimage remain unchanged.
The new `capital-dataset-trajectory-v1` identity separately binds source,
preparation, schedule, instrument terms, costs and execution assumptions.

## Clocks and assumptions

Signals use completed original daily bars. A close signal can first submit at
the next original opening, after a fresh shared risk/sizing check. Synthetic
account observations end at close plus three seconds; this separate model
clock is not a measured broker receipt or market-quote timestamp. No OHLCV bar
is relabeled as an executable quote. Adverse half-round-trip prices and fees
are applied once by the shared execution adapters.

Daily reconciliation is an explicit model assumption, not an attestation.
`CapitalTrajectoryDay.weekly_review_assumed` defaults to false. A caller may
explicitly declare a dated research-only review assumption; the entire schedule
is hashed. The owner never invents a review because a trade would otherwise be
denied. Default-absent review blocks entries and applicable exits through the
unchanged shared gate. Even an explicit true declaration cannot erase a
same-week loss maximum or permanent drawdown latch. A research study must freeze
its review assumptions before outcomes; these declarations cannot qualify live
manual review or authorize recovery of an operational account.

Original action archives drive split, distribution entitlement and payment
events. Receivables count once in NAV but are not spendable cash. Original sale
fills drive the declared T+2 settlement model. Zero-dollar obligations retain
their identities. Bound fee finality cannot occur before all original settlement
and distribution obligations complete. Missing tails are left incomplete; no
terminal sale, cancellation, payment or settlement is forced. Unsupported
coincident held actions and in-flight action rewrites deny rather than guess.

Fractional instrument terms, fees, daily fills, T+2, reconciliation and review
are assumptions. They do not verify Robinhood support, customer costs, source
publication/correction chronology, account restrictions, or deployed recovery.
Production limits and the $1,000 live-account ceiling are unchanged.

## Remaining work

The original-dataset trajectory is not the walk-forward evaluator. The evaluator
must derive all 28 training outcomes itself, preserve continuous selected
account/opening policies, and distinguish opening versus close selection clocks.
It still needs the complete comparison/statistics/report composition, full
28×6×4×5 workload measurement, exact-source release verification and executable
freeze. Real economics requires separately qualified, authorized inputs and
explicit cost limitations; no economic result is asserted here.
