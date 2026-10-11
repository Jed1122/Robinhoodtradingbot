# Capital research signal and fold contracts

## Private all-candidate preparation foundation

The private `_capital_strategy_signals` helper validates a complete five-symbol
projection set and hashes each complete projection once per invocation, then
calculates all28 fixed candidates using the SAME numerical kernel as the public
single-candidate API. It accepts no cached hashes, prepared results, balances,
risk decisions or enabling flags. Every invocation validates originals anew;
there is no global cache. Public single-candidate identities and results retain
their existing preimage and semantics.

Fixture verification includes six pre-extraction literal all28 output hashes,
199/200/201-bar warmup boundaries, RSI reversal, rising/falling/flat series and
metadata/clock/mutation denials. Five projection hashes rather than140 is an
operation-count result, not wall-time or full-workload certification. This
wrapper remains unconsumed. The implemented prepared-input/DEVELOPMENT panel
instead calls the SAME `_calculate_capital_signal` numerical kernel directly
through private preparation. Original-owner carryover and complete panel
composition exist; accepted inputs, full workload and economic freeze do not.
All source/cost/execution/economic/promotion/live eligibility remains false.

## Retained signal release history

Current PR34 correction: latest-bar Eastern session must equal the declared
as-of session, and each projection permits only one bar per Eastern date.
Action-aware entry admission must consume the complete supplied original tape;
historical-prefix risk replay remains supported for analysis, not stale entry.
Four regressions were watched RED before these admission fixes. The earlier
82c6457 full/native certification below is historical after this source change;
Fresh corrected-source9,826 full/20 native tests,92.11% combined coverage and
unchanged80overall/90critical gates passed. All14 exact-head hosted jobs passed;
PR34 merged atf1326c9 with the reviewed treea652f3f. These checks do not qualify
the supplied source data or prove economic/execution readiness.

This is a synthetic-tested research component, not a completed backtest,
executable study freeze or accepted economic result. Source, economic,
execution and promotion flags remain permanently false. No broker interface
or risk/order factory is exposed.

Exact executable source82c6457 passed9,822 full tests,20 native tests and92.11%
combined coverage, with unchanged80overall/90critical gates. Ruff/Mypy373/
Bandit, frozen locks, SBOM and shell/Compose checks passed. Independent review
identified duplicate distributions and non-daily/interpolated input admission;
watched failing fixtures and the corrected full suite cover both fixes. These
are local software checks, not hosted release or market-data qualification.

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

The account/risk-gated daily owner, train-only carryover and dependent whole-family
cost/benchmark [panel](etf-capital-panel.md) are implemented and reviewed; this
signal helper alone is not their qualification. Next: corrected-source release
verification and actual full workload, then immutable code/config/source/calendar/
actions/cost/protocol/selection/statistics/criteria freeze before a qualified
authorized DEVELOPMENT study. No paper/shadow/live qualification follows.
