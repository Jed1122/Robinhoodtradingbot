# ETF synthetic quote execution increment

This is an offline execution seam around the existing account owner. It accepts
an already admitted, reserved `pending_intent`, explicit synthetic lifecycle
observations and synthetic bid/ask quotes. It is not the complete strategy
coordinator, qualified historical execution, broker paper trading or live trading.
`execution_enabled` and `evidence_promotable` remain permanently false.

## Runnable example

From the repository root, using the locked local environment:

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research quote-fixture-run \
  --capital 500 --scenario partial --restart-after 1
```

The command returns exit `2` because the account outcome is incomplete. With
fabricated prices and fees, exactly 0.04 shares fill at the $100 ask; cash is
$495.9696 and cumulative execution fees are $0.0304. Remaining reserved cash is
$6.0756, including remaining quantity at the $100.10 limit and unused fee
allowance. The $10.11 trial reservation remains in place through the open episode.
There is no closing order, automatic settlement or final P&L.

The fixed scenarios are `full`, `partial` and `pending_ack`. `full` fills 0.1
shares and still leaves an open, unsettled episode. `pending_ack` has no acceptance
fact and therefore cannot fill at all: cash remains unchanged and the entire
reservation remains. Both $500 and $1,000 are hypothetical cash tiers; sizing
authority remains the canonical $100 risk-equity reference. These examples do
not select a strategy opportunity or calibrate actual costs.

`--restart-after N` reconstructs and verifies a consumed source prefix, then
resumes within the same process. Output matches uninterrupted replay without
duplicating liquidity, fees or cash flows. This option does not persist a crash
checkpoint or prove durable database or broker recovery. Existing
`account-checkpoint-run` remains the separate private, descriptor-bound accounting
checkpoint example.

## Ownership and event ordering

- `etf_fixture_decision_frames` exposes the existing causal 20/100 momentum
  decision and ATR without changing legacy decision records or hashes. Its
  `can_propose_fixture_entry` field is not risk approval or execution permission.
- `EtfFixtureExecutionRequest` reconstructs the admitted account prefix; unknown
  orders, unsupported source records, invalid chronology and changed facts deny.
- `EtfFixtureAccountObservation` can carry explicit acknowledgement, settlement
  or dividend facts, never a new intent, fill or mark. Time passing or receiving
  a quote does not manufacture these facts.
- `replay_etf_account` remains the sole owner of cash, positions, reserves,
  settlement and non-replenishing trial-loss history. Proposed execution facts
  are committed to the returned history only after this owner accepts them.
- A newer native halt cannot be overridden by a delayed older OPEN observation.
  Conflicting controls at the same native timestamp block until a strictly newer
  explicit control. Delayed older quotes and conflicting same-time prices cannot
  supply a favorable fill; a strictly newer quote must re-establish the frontier.
- Displayed capacity is consumed by native quote timestamp and side. Re-receiving
  or rehashing the same quote does not replenish it. Restart reconstruction
  preserves the consumed capacity.

Execution requires consistent session boundaries, fresh quotes after the control
epoch, submission and acknowledgement, positive configured latency, an unexpired
order, acceptable spread, instrument quantity increments and the frozen limit.
Prices use ask for buys and bid for sells, adverse tick rounding and extra
slippage once. The bid/ask spread is already in that price and is not charged a
second time. Unknown, pending, cancel-pending or ambiguous order states cannot
obtain fill permission from a quote. Protective sells still require explicit
owned intent and acknowledgement facts.

## Incremental fees and reservations

`etf_execution_charges` uses the existing cost-evidence contract. Commission is
the increment in `max(order minimum, cumulative quantity × per-share rate)`;
partial fills do not repeatedly pay the order minimum. Regulatory charges apply
only to the current fill's notional. Their both-sides treatment is an explicitly
unverified conservative assumption, not a claim about broker billing. Operating
costs and cash interest are not execution fees.

The active cost schedule is bound at submission. Missing, expired, future-known
or changed schedules deny execution rather than repricing a reserved order.
Decimal arithmetic is isolated from ambient precision/traps; an ordinary narrow
spread does not need a terminating percentage quotient to pass validation.
Fees beyond the recorded episode allowance deny without poisoning account
history. Profitable episodes do not replenish consumed trial capacity.

Unsettled fills preserve the existing entry halt. A second partial entry may only
continue after explicit account facts re-establish the common gate; this seam
does not relax it to manufacture a completed order. End-of-input never forces a
closing fill, cancellation, settlement or a positive economic verdict.

## Remaining integration

The next primary-owned slice must compose reconstructed causal decisions,
canonical portfolio/intents and account admission, then carry consumed control,
quote-frontier and capacity context into execution. The current seam starts from
an explicit order and later observations; it cannot safely reuse a pre-proposal
OPEN control by fabricating a replacement observation.

That coordinator must also freeze canonical stop/target/holding/regime policies,
manage partial-entry cancellation before a protective sell, retain unresolved
outcomes and integrate durable cursor/account transactions. Real-data execution
and after-cost acceptance require complete executable quotes, controls, action
continuity, fractional terms and qualified/calibrated cost evidence. The current
native bars/calendar/dividends are not a substitute. Broker/runtime verification,
qualifying paper/shadow clocks and explicit live authorization remain separate.

Development does not wait for the hosted Python matrix. Required checks and
branch protections remain intact; a missing or failing check is not represented
as a pass and is not bypassed for merge or promotion.

## Verification of this increment

The final local Python 3.12 working-tree regression ran 7,069 passing tests, 33
skips and one existing Starlette/httpx deprecation warning. It reached 84.39%
overall coverage before the separate native-history append. The skips concern
optional native/pricing dependencies and unavailable local backup tooling, not
approved broker tests; authenticated tests remain excluded by default. Ruff,
Mypy (303 source files), Bandit, both offline lock checks, Compose configuration
and DigitalOcean shell syntax checks passed. No dependency or CI workflow changed.

Independent checks covered exact incremental fees, 1,000 Fraction-oracle cases
under hostile Decimal settings, and the new CLI's accounting/restart behavior.
The initial execution review identified three ordering/arithmetic defects; five
regressions were observed failing before repairs and then passed. The full local
regression is working-tree evidence, not a claim about every supported Python
version or an automatic merge/promotion grant.
