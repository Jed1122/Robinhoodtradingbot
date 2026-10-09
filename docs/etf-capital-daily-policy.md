# Prior-close capital-research policy

Local release evidence belongs to executable b2dc8f8:9,918 full passes,
33 optional skips/one existing warning;20 native passes;92.17% combined coverage
and unchanged80overall/90critical gates. Ruff/Mypy376/Bandit, locks and SBOM
passed. Hosted exact-head checks/integration remain pending; this is not a fresh
full run at a later human-document head. The known-holding-deadline correction
was watched RED-to-GREEN before this certification.

`capital_daily_policy` recomputes the fixed five-symbol signal using completed
original projections. It emits research instructions only, not orders, risk
permission, authoritative balances or a brokerage route.

Entry stop distance uses existing FeaturePipeline ATR over the last100 completed
feature bars, the canonical ATR multiplier, and the latest raw/feature close
ratio. This raw-unit conversion is an explicit split-basis assumption. Signals
retain their200-bar warmup and independently configured approved family windows.
Zero ATR or insufficient history cannot manufacture an entry.

A declared `CapitalOpeningPolicy` retains the original candidate, symbol, entry
session and stop distance. A future owner must bind this record to its unique
original BUY/fill; caller declarations alone do not establish ownership. A new
fold candidate never changes the existing position's policy. Entry session counts
as1 toward maximum holding2/5/10/20; a completed-close exit instruction belongs
to the next eligible session, not a retrospective same-close fill.
Known maximum-holding deadlines are evaluated before signal warmup: missing
feature history cannot extend an already-due position. Unavailable regime
signals and entries remain unavailable, without invented replacement values.

Momentum exits on original-candidate invalidation, mean reversion on RSI>=50 or
price at/below SMA200, and rotation when its original candidate selects another
symbol or cash. Canonical regime-exit configuration applies; maximum holding
does not depend on regime permission. Protection, actions and actual lifecycle
timing belong to the original-event daily owner, not this pure policy consumer.

All source/cost/execution/economic/promotion flags remain false. Tests use
fabricated inputs only. The complete daily runner, fold carryover, dependent
selection-adjusted evaluator, workload validation, executable freeze and real
economic study remain unfinished. No live trading or provider call is added.
