# Capital-constrained ETF research

This versioned **offline foundation** implements capital budgets and fee-aware
assumed-instrument sizing. It is not a strategy evaluator or brokerage service.
It cannot enable paper, shadow, production execution or promotion.

Run from the repository root:

```sh
PYTHONPATH=src uv run python -m trading_bot.cli.etf_capital_research capital-plan
```

The existing canonical loader accepts an opt-in `research_policy_path`. The
resolved configuration and release envelope bind `capital-constrained-etf-research-v1`.
Legacy configuration hashes and production thresholds remain unchanged.
Environment overrides cannot enable this offline profile.

## Research budgets

| Current equity | Position ceiling | Planned risk incl. bounded fees | Cash floor | Daily breaker |
| ---: | ---: | ---: | ---: | ---: |
| $100 | $20 | $0.50 | $40 | $1 |
| $250 | $50 | $1.25 | $100 | $2.50 |
| $500 | $100 | $2.50 | $200 | $5 |
| $1,000 | $200 | $5 | $400 | $10 |
| $5,000 | $1,000 | $25 | $2,000 | $50 |
| $10,000 | $2,000 | $50 | $4,000 | $100 |

These are **research limits**, not permissions to increase production order size.
The $15 base and $5 micro order caps, $100 risk reference, $50 trial ceiling and
$1,000 live account ceiling remain production restrictions. Growing research
equity recalculates research budgets; it does not change the live ceiling.

Sizing reuses `SizingRequest` and `size_position`, then reserves a whole-episode
fee bound inside planned risk and cash. Missing fees deny admission. Quantities
round down to declared increments and must satisfy quantity/notional minimums,
maximum quantity, settled cash and the one-position/daily-breaker restrictions.
Any tighter correlated-group ceiling also reduces the single-position budget.
Stop risk is planned risk only: gaps can produce larger realized losses.
Cash-floor sizing assumes unallocated equity remains cash; the forthcoming replay
must account for unsettled proceeds and other obligations separately.

## Unknowns and operating costs

No historical price inputs are consumed by `capital-plan`, so it establishes no
executable quantity, fractional brokerage route or trading return. Instrument
metadata supplied to the sizing function is a research assumption, not account
permission. Free historical SIP and fresh consolidated quote access remain
unverified by this command.

Actual customer fees, data subscriptions, infrastructure bills and taxes remain
unknown. The report separates hypothetical zero-data/zero-compute operation from
zero-data/$12-monthly compute. The latter is $144 yearly:144% of $100 equity and
1.44% of $10,000 equity before any trading costs. These scenarios neither assert
an actual current provider price nor authorize billing changes. Prior research
expense is not silently treated as a recurring expense or a trading loss.

## Remaining implementation

1. Add versioned multi-symbol Alpaca daily intake and fixture-tested quality,
   corporate-action, distribution and availability contracts.
2. Implement momentum, mean reversion and rotation independently using the
   frozen six-capital/four-friction grid and purged rolling walk-forward tests.
3. Freeze executable/source/cost identities before evaluating development data.
   Used or uncertain historical holdouts are not called untouched.
4. Only if a candidate survives, evaluate the preregistered regime combination,
   compose trusted paper/shadow operation and verify actual runtime recovery.
5. Collect the frozen prospective final test. Produce separate economic, source,
   cost, broker, runtime and authorization verdicts. Live remains separately
   authorized; no credible edge means no unnecessary trading expansion.
