# Capital research signal and fold contracts

This is a synthetic-tested research component, not a completed backtest,
executable study freeze or accepted economic result. Source, economic,
execution and promotion flags remain permanently false. No broker interface
or risk/order factory is exposed.

`capital_candidates()` returns exactly28 immutable candidates: three momentum
pairs, two RSI thresholds and two rotation lookbacks, each with2/5/10/20-session
maximum-hold policy labels. The labels do not themselves implement exits.

`capital_strategy_signal` consumes all five existing split-only projections at
one common completed original session grid. Fewer than200 completed bars yields
no candidate; malformed, mixed-symbol or future input denies. Supplied calendar
and action facts remain unqualified. Validation of dates is not proof of market
coverage. No daily bar is turned into a quote.

Momentum reuses the existing feature pipeline and full positive-return/short
average above long average/price above long average predicate on the exact long
window. Mean reversion uses WilderRSI2 seeded by the first two changes of the
latest200-bar window and updated over that same window, entry below5/10 with
close above SMA200, and an RSI>=50 exit signal. Flat RSI is50; only gains100;
only losses0. The fixed200-bar research warmup does not change any legacy/global
750 warmup setting;750 remains the rolling training length.

Rotation uses20/60-session non-reinvested total return divided by the sample
standard deviation of20 simple split-price daily returns. Distribution cash is
included once for ex-dates after the starting price through the ending price,
normalized into the current split feature basis using the ex-date feature/raw
close ratio. Nonpositive return or zero volatility produces no candidate.
Highest score wins; exact ties use lexical symbols. Decimal arithmetic has an
owned64-digit half-even context; score comparisons do not round in caller context.

`capital_walk_forward_folds` constructs five126-session test folds from supplied
strictly ordered2016–2023 development sessions, with750 rolling training sessions
and20 embargo sessions. Training selection excludes its last20 decision dates.
First test starts at declared session index770, then126-session stride.23
exit-only sessions per fold reserve maxhold20, next event and assumedT+2 tail;
missing later execution/settlement is still incomplete, never a forced fill.
The caller must establish complete calendar/data inputs; this helper cannot.

Next: implement and review the account/risk-gated daily execution adapter,
train-only selection with policy carryover, dependent selection-adjusted
uncertainty, operating-cost and benchmark reports. Bind code/config/source/
calendar/actions/cost/protocol identities before a development study. These
contracts alone do not supply any of those results or qualify paper/shadow/live.
