# Stock economic replay kernel

`research.stock_economic_replay` is a pure session/accounting kernel for developer
fixtures. It composes the existing experimental account, fill/settlement functions,
exit proposals and dividend book. It performs no network or brokerage operation.
It does not yet admit actual provider observations or establish a strategy edge.

Inputs support individual-stock candidates, preselected long-term stock allocations
and an optional labeled passive comparison. Supplied signals are fixture inputs;
the optional seven-family policy seam is described in
[the policy guide](stock-economic-policies.md). Long-term quality-stock selection
remains separate.
The `make_fictional_replay_inputs` factory and validation retain the fictional
profile. All investment, source and live-authorization flags remain false.

## Mechanics

The initial simulated account contains $1,000 with 75% long-term, 15% tactical and
10% liquidity targets. Unused capital stays cash. New orders respect the 10%
company, 4% tactical-position, 15% tactical-sleeve and 25% sector limits. Tactical
initial-stop risk uses at most 0.5% of gross equity immediately before entry,
including both modeled fees and adverse stop-sale slippage. A future price gap
can exceed that modeled loss.

Close decisions execute at the next supplied open, starting at session 200.
Pending budgets consume available capital once; fills, lots, tax reserves and
settlements have one account owner. Re-entry requires a fresh signal and the
configured five-session cooldown. Daily loss, weekly decline and drawdown state
latch; the emergency halt blocks new orders while accounting can advance.
The final close's pending instructions remain unexecuted.

Tactical exit methods are principal-value retention at +15%, partial reductions
at +12.5%/+20%, and a 5% trailing rule. Full +20% and 20-session exits are controls.
Common risk, family-failure and maximum-holding rules retain priority. Long-term
holdings do not receive tactical profit rungs.

An activated, partially filled profit rung retains its original target and fill
history. Principal resumption additionally uses the current known-close surplus
over the episode's original allocation; zero surplus pauses the reduction.
Requested quantity remains bounded by the owned rung remainder and share precision.
The percentage partial-rung remainders keep their fixed share targets. Minimum
order and fee constraints can prevent a small sale. Subsequent opening-price gaps
mean principal-value retention does not guarantee a retained dollar value.

Sale proceeds remain unsettled until the supplied ordinary-equity settlement
calendar permits the modeled funding instant. This calendar differs from market
sessions. Dividend funding uses a separate explicit date/status/source table:
ordinary CNS settlement support does not prove dividend-payment availability.
Missing or conflicting payment support leaves an earned receivable. The existing
book's first-market-open-after-pay-date convention remains an explicit limitation.

The result retains marked positions, receivables, reservations, tax estimates,
modeled fills/disposals, denials and pending final instructions. It does not force
a horizon liquidation or manufacture a later market price. Taxes use labeled flat
scenarios; an unknown rate retains the existing full-positive-gain/paid-dividend
reserve convention. These are not final tax-reporting figures.

## API and verification

The narrow APIs are `begin_stock_economic_replay`,
`advance_stock_economic_session`, `finish_stock_economic_replay` and
`halt_stock_economic_replay`. State continuation carries the same account and
history across a chronological cutoff. There is no broker authorization object.

```sh
PYTHONPATH=src uv run pytest tests/unit/research/test_stock_economic_replay.py -q
```

These tests use fictional observations. Provider records require a separate
purpose-specific admission path; changing a fixture label cannot qualify them.

## Remaining integration

The optional [operating-cost phase](stock-operating-costs.md) uses the same paused
book and a separate gross/net liability report. The original absent-plan path
keeps its prior evidence and result shapes. Preparation of actual observations
is a separate [conditional input boundary](stock-monetary-preparation.md); it
cannot relabel actual data as a fictional replay or admit a constrained strategy.

Actual-source replay, complete stock-quality selection, corporate-action
conversion, volatility and scheduled-rebalance controls, statistical comparisons
and the actual economic study remain incomplete. The original late period was
already used for price research and cannot become a fresh confirmatory holdout. Broker deployment and
live activation are separate; no mandatory paper-trading waiting period is added.
