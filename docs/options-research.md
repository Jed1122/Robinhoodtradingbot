# Offline options research: first engineering slice

This is working synthetic engineering software, not historical performance evidence,
an accepted options strategy, a live adapter, or the completed six-milestone migration.
It reuses existing 20/100-window features and momentum decisions, strict config loading,
canonical hashes, Decimal arithmetic and the common order-transition function.

## Commands

From the repository root in the locked development environment:

```sh
PYTHONPATH=src uv run python -m trading_bot.cli.options_research capital-feasibility
PYTHONPATH=src uv run python -m trading_bot.cli.options_research capital-feasibility --premium 0.10
PYTHONPATH=src uv run python -m trading_bot.cli.options_research options-replay
PYTHONPATH=src uv run python -m trading_bot.cli.options_research options-replay --research-capital 2500
PYTHONPATH=src uv run python -m trading_bot.cli.options_research options-replay --research-capital 2500 --scenario unknown
```

The $100 default denies the fixture's $11 premium-plus-fee risk because its 0.50% budget
is $0.50. At hypothetical $2,500 research capital the fixture pays $10 premium and $0.50
entry fee, receives $15 on closing and pays $0.50 exit fee: final cash $2,504 after an
explicit settlement event. These prices, depth, sessions, fees and holding period are
fabricated inputs, not estimates of achievable returns or a recommendation to add funds.
The $100/$150 live assumptions remain unchanged.

Scenarios: `completed`, `loss`, `open`, `unfilled`, `unknown`, `unsettled`, `cancel_race`,
`canceled`, `rejected`. Incomplete scenarios return exit code 2; malformed input returns
1 with a value-free error; completed/no-trade outcomes return 0. No end-of-input exit
is invented. Reports include exact cash/receivables, fees, transition history, hashes,
trial reservation, and permanently false promotion/production eligibility.

Fill eligibility is tied to a new quote observation after acceptance and configured
latency, not merely a later replay envelope carrying an old quote. Closing orders get
their own session-bounded deadline. Settlement is an explicit event, including when
closing proceeds and fees net to zero; numeric zero alone cannot release a reservation.

`capital-feasibility` uses the requested eight hypothetical capital tiers. Its default
$0.25 premium, multiplier 100 and $1 round-trip fee reserve are unvalidated assumptions.
The existing $15 absolute order-notional cap is retained: therefore this particular
$25 premium example remains denied even at higher tiers. `--premium 0.10` demonstrates
whole-unit feasibility at some tiers without raising any ceiling. The report is only a
necessary capital filter; Greek/scenario/liquidity/account/research/operational gates
remain unsatisfied. Annual operating cost defaults to an explicit hypothetical zero,
not a statement that operation is free; supply `--annual-operating-cost` to show drag.

## Configuration and compatibility

`configs/options/simulation.yaml` is an overlay for the existing canonical loader.
Base settings retain legacy modes for compatibility; this options overlay disables
standalone asset entries and cannot enable broker-connected or live options modes.
All new thresholds are in the required `options` subtree of base/release config.
Environment override names follow existing paths, for example
`TRADING_BOT__OPTIONS__MAX_PER_TRADE_LOSS_USD`; only tightening is accepted. The isolated
research CLI intentionally ignores ambient environment overrides and credentials.
No changed configuration reuses the old hash. Historical intent serialization is unchanged.

The new module entry point is temporary deliberate isolation from the pre-existing
unfinished `trader` CLI changes. It is not a second configuration loader or live service.
The main CLI integration is still pending.

## Known limits

This slice handles one synthetic long-call unit per episode. Spreads/condors have validated
identity records only, not validated payoff engines or execution. It does not yet support
recorded external file imports, bearish/put selection, partial complete-package quantities,
continuous/restarted episodes, real calendars, real fee schedules, dividends, exercise,
assignment, settlement calendars or broker intervention. Fixture bars deliberately are
fabricated daily observations, including non-market dates; they are not exchange history.

An episode is complete only when flat, orders terminal, and settlement/fees final. The
in-memory trial state retains all supplied prior episodes and sums their losses without
offsetting profits. Durable append-only persistence, event deduplication across restarts,
deposit/rolling tests and live reconciliation are separate unfinished milestones.

The simulator's risk/review transitions are explicitly simulated stages: they are not
full 24-check production pretrade passes, broker reviews, executable pricing or evidence
that any account is connected. Every result remains `ECONOMIC_NO_GO`.
