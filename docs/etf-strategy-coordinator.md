# ETF signal, order and protective-exit checkpoint

The fixed SPY/cash study now has a runnable, bounded synthetic path from common
20/100-day momentum features through canonical sizing, pending reservations,
explicit order acknowledgements, later quote fills, protective exits and exact
cash/trial-loss accounting. This is an engineering simulation. It remains paused,
nonpromotable and unable to call a broker.

## Operator commands

Run from the repository with the existing locked environment:

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research strategy-fixture-run
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research strategy-fixture-run --capital 1000
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research strategy-fixture-run --scenario partial_cancel --restart-after 751
```

The default example fabricates 750 daily bars, an open session, quotes, two order
acknowledgements and final settlement. Starting at $500, it buys 0.15 shares at
$100, then observes a gap through the frozen $98 stop and sells at a later $97.99
bid. Fees total $0.06296985; cash finishes at $499.63553015. The completed loss of
$0.36446985 consumes trial capacity. It is an independent accounting expectation,
not a performance forecast or evidence of an economic edge.

`--scenario open` retains shares and unsettled obligations. `partial_cancel`
retains 0.04 shares, a pending cancellation, $11.0696 cash reservation and $15.10
trial reservation. Neither fabricates a closing fill or settlement at end of
input. Incomplete scenarios exit with status 2. Invalid inputs exit with status 1.
Every report returns `ECONOMIC_NO_GO` and false execution/promotion/live flags.

## Ownership and controls

- Common features and momentum supply the fixed five-session entry/deselection
  cadence. Common portfolio construction and sizing create candidate intents;
  the existing account owner decides admission and retains all cash/risk history.
- Hypothetical $500/$1,000 balances preserve the $100 authorized risk reference,
  canonical percentages/absolute limits and $50 non-replenishing trial loss.
  Fees can make an otherwise sized candidate inadmissible; denial does not retry
  with a different size or relax a limit.
- ATR stop, reward target, maximum holding period and regime-exit setting are
  frozen at entry. Eligible price events monitor protection between rebalance
  dates. An initial regime trigger requires a current-session, fully known
  cadence frame; a control-only new day cannot revalidate yesterday's features.
  Once a valid trigger is latched, price recovery does not erase it.
- A partial entry must receive explicit cancellation/reconciliation before a
  protective sell is proposed. An unacknowledged or ambiguous entry retains its
  reservation and cannot invent a cancellation transition or acceptance.
- The quote driver reconstructs consumed market context independently of the
  last accounting mutation. Rejected quotes do not strand later valid liquidity.
  Existing native timestamp, conflict, control, latency, size, fee, limit and
  accounting gates still decide every fill. A stop is a trigger, not a fill price.
- `resume_etf_fixture_strategy` reconstructs and compares the complete consumed
  prefix, policy, orders, cash, fees, reservations and decisions. Its scope is
  in-process replay. It does not establish durable process/service restart.

The coordinator accepts synthetic bars, session/control events, quotes and
explicit fixture account notices. Native archives cannot be relabeled to enter
this path. Corporate-action source events remain unsupported here; it does not
infer dividend payment, split adjustment, settlement or historical broker terms.

## Current real-data and runtime evidence

The new native quote reader validated the retained two-page archive containing
1,074 observations from the existing one-second probe. It preserves exact native
timestamps, original ordering, conditions, sizes and receipt/body hashes. It
rejects corruption, incomplete pagination and more than 10,000 rows. It does not
convert size eras, interpret unverified conditions or establish session coverage.
All native quote qualification, promotion and execution flags remain false.

The available-data reference screen was rerun on October 1. It evaluated 1,262
development observations and preserved all 502 holdout observations without
evaluating them. Result: `ECONOMIC_NO_GO`. This supports exploratory benchmark
analysis only. Candidate entry, monitoring and exit quote coverage, historical
controls, action continuity, fractional terms and calibrated costs remain absent
or unqualified. The publication/correction waiver does not supply those facts.

The older Robinhood app connection returned a reauthentication error. The
separate, user-configured `robinhood-2` connection succeeded: scoped reads found
the active cash Agentic account, empty equity position/order pages with no
continuations, and SPY active, tradable and fractional-eligible for that account
type. No regular-hours halt was reported. These are current session read
observations; order behavior and standalone runtime authentication remain
unverified. No account identifiers or financial values were stored in Git.

The read-only DigitalOcean SSH attempt returned `Permission denied (publickey)`;
the local SSH agent has no loaded identities. Service/image/authentication state
could not be inspected.

Local broker and promotion contracts remain testable. Qualifying paper/shadow
operation still needs trusted data, strategy outcomes, runtime identity and
reconciliation inputs. Synthetic cycles do not advance the existing 100 eligible
paper-cycle or seven-distinct-date shadow requirements.

## Remaining work

Complete the native source adapter and quote/control/action/terms qualification;
then run candidate after-cost development, uncertainty and holdout evaluation.
Finish durable coordinator persistence/restart and trusted paper/shadow runtime
composition. Restore DigitalOcean inspection access and verify broker behavior
from that runtime. Keep write integration and live
activation gated by their separate evidence and authorization requirements.

## Verification

At source commit `1a6b51c`, the local Python 3.12 regression passed **7,198 tests**
with 33 optional-dependency/tooling skips and one existing Starlette/httpx warning.
The separate locked research environment passed 20 native historical-episode
tests. Combined coverage was **90.15%**; every critical module passed the existing
90% branch gate. Coordinator branches were 61/64, quote execution 84/88, account
ownership 83/88. The new coordinator has no coverage exclusions.

An isolated archive of that committed source passed 925 focused tests, with 19
optional-dependency skips, excluding unrelated working-tree changes. Both locked
third-party dependency audits found no known vulnerabilities. Ruff, Mypy (305
source files), Bandit, lock consistency, SBOM reproducibility, Compose validation
and DigitalOcean shell syntax checks passed. The four encrypted-backup tests
requiring unavailable local `age` tooling remain skipped.

Independent review findings concerning source/account cursors and duplicate fill
delivery were reproduced and repaired with regressions. Adversarial tests also
cover unacknowledged cancellation, stale regime frames, partial fills, frozen
exits, holding limits, hostile input and restart tampering. These tests establish
the bounded fixture behavior, not source/economic/broker/promotion readiness.

Hosted Python matrix jobs are not awaited; no missing hosted check is represented
as passing. Existing merge protections remain in place.
