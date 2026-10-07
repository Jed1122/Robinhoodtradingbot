# Lean ETF delivery task list

This is the current priority list for the operator's fixed SPY/cash bot. It
implements the October 7 instruction to remove unnecessary work and focus on
economic viability. It supersedes the earlier requirement to finish a bulk
historical quote archive before obtaining an initial economic result.

The goal is to establish whether the fixed strategy has a repeatable advantage
after execution and operating costs, and then run it reliably within an admissible
capital/risk policy. No result establishing that advantage exists yet. Existing
software, historical evidence and enforced runtime limits retain their identities.

## Requirements removed from the initial critical path

| Previous work | Revised disposition |
|---|---|
| Download every quote through all 1,262 development sessions | Deferred. Use retained daily bars for the first economic screen. Acquire additional quotes only for a justified follow-up after that screen. |
| Build whole-history compression, bulk acquisition and archive scaling first | Deferred with the bulk archive. Preserve all existing original files. |
| Obtain a real-money calibration fill before starting research | Waived as a research prerequisite. Start with explicit conservative cost scenarios and published charges. Observed fills/fees remain evidence needed to calibrate actual execution. |
| Restore original historical publication/correction timelines or halt/LULD/gap proof | Existing exploratory waivers remain effective. Missing observations remain unknown. |
| Add data providers, options, crypto or prediction strategies | Outside this ETF milestone. Alpaca supplies market data; Robinhood remains the execution target. |
| Optimize strategy parameters or implement neighbor-parameter searches before evaluating the fixed candidate | Outside the initial screen. Register and retain any later variants before evaluation; account for selection if variants are introduced. |
| Use the generic 750-bar warmup as a computational prerequisite for the initial screen | A new exploratory screen needs the fixed features' 100 completed prior bars. The old registered profile's 750-bar requirement remains unchanged. |
| Build dashboards, LLM reporting, multi-host availability, new cloud provisioning or hardware upgrades first | Deferred. Use a private report, one execution owner and one chosen runtime. |
| Require arbitrary 100-cycle/seven-date quotas for the lean bounded pilot | Waived prospectively for a new, reviewed operational policy. Replace counts with genuine session, decision, lifecycle and recovery coverage. Existing runtime gates remain unchanged until that replacement is implemented and verified. |
| Complete normal-live expansion requirements before a small pilot | Deferred to a later normal-live release. Its existing enforced limits are preserved. |

This reprioritization does not certify an input, sample or strategy. It changes
what must be completed first. Current qualification flags and checks are not
changed by editing this document.

## Updated task list

### 1. Establish affordable operation and admissible sizing — next

October 7 result: the [cost/sizing diagnostic](etf-lean-feasibility-2026-10-07.md)
is complete for the current path. Receipt-verified development prices prove zero
native whole-share size under both capital tiers. Hypothetical fractional math
fits the numerical caps, but actual broker/runtime support and an affordable
fresh-quote operating path remain unverified. Do not expand the failed integer
route. Task 2 can proceed only as separately identified assumption-based research,
not a claim that executable sizing has been established.

- Produce the $500 and $1,000 capital-feasibility report using actual canonical
  limits and supported account/instrument/order terms.
- Current reference equity is $100; base caps include $15/order and $60 gross,
  with $5/order and $20 gross in micro-live. The $1,000 account ceiling does not
  enlarge those values. The native historical path is integer-only. Resolve
  the feasible fractional/order route or record zero admissible size; never
  silently increase limits or treat hypothetical buying power as authority.
- Establish the minimal ongoing cost budget. Separate already incurred research
  expenses from recurring operating costs. Compare both capital tiers under
  the paid data plan and a supported low-cost alternative within Alpaca.
- Alpaca lists Algo Trader Plus at $99/month: $1,188/year, or 237.6% of $500 and
  118.8% of $1,000 before other costs. Its Basic plan is free, and its FAQ permits
  historical SIP queries whose end time is at least 15 minutes old. Verify
  account access before depending on that path. Live prices require their own
  fresh, supported source; delayed data cannot become an order-time quote.
- Do not change subscriptions or funding as part of this documentation amendment.

Sources reviewed October 7: [Alpaca plan details](https://docs.alpaca.markets/us/docs/about-market-data-api)
and [historical access FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

**Done when:** the report identifies an executable sizing path and a supportable
cost budget, or gives a concrete infeasibility result. A hypothetical risk-policy
alternative must be labeled and separately implemented/authorized before use.

### 2. Run the conservative daily-data development screen — next

- Reuse retained Alpaca daily OHLCV, session references and issuer distributions.
  Verify the selected dates, price basis, split treatment and dividend accounting;
  do not double-count distributions through adjusted prices and cash flows.
- Freeze a new exploratory screen identity before reading outcomes. Preserve the
  full approved 20/100 predicate, five-session cadence, ATR stop, target,
  holding-duration and regime exits. Freeze the first-rebalance anchor explicitly;
  shortening computational warmup must not silently shift the schedule. Reuse
  feature, sizing and accounting code.
- Decisions use completed prior bars. Model scheduled execution no earlier than
  the next eligible session, with explicit adverse price/cost assumptions.
  A gap through a stop uses the worse opening price and cost allowance, not a
  guaranteed stop price. If a bar can hit stop and target, use the adverse ordering.
  Intraday ordering, liquidity, fill probability and latency remain assumptions.
- Report trading P&L, operating profit, turnover, drawdown and sizing for both
  capital tiers against cash and an exposure-matched buy-and-hold benchmark.
  Show conservative execution-cost stress and uncertainty. Use an explicit
  zero-cash-yield case where an attainable rate is unavailable.
- Keep 2024–2025 outcomes sealed during development. A data inventory is not an
  evaluation of those outcomes. Do not force final liquidation or fabricate fills.
- Produce a clear reject/proceed/insufficient-evidence screening result. Preserve
  unqualified inputs and assumptions in the result; never relabel it as the old
  qualified native study or use it as a live-promotion artifact.

**Done when:** reproducible private development reports reveal whether further
execution research is justified. If the candidate fails conservative economics
or cannot trade under the applicable policy, stop its implementation expansion.

### 3. Validate the surviving candidate out of sample — conditional on task 2

- Freeze rules, evaluator, cost scenarios and acceptance criteria before opening
  the final test, including the reviewed admission/report semantics for the
  supported model. Preserve all prior attempts and uncertainty about dependent
  observations; a single trade does not establish an advantage.
- Evaluate the final test once. A strategy changed in response to its result
  needs new untouched evidence; do not reuse that test as fresh validation.
- Obtain only the additional execution-window, corporate-action or cost evidence
  that resolves a material remaining uncertainty. Because protective exits can
  occur between rebalances, narrow quote windows alone may be insufficient;
  document what they establish before choosing broader coverage.
- Build a reviewed admission/report contract for the supported evidence rather
  than unlocking permanently unqualified diagnostic schemas. Cost assumptions
  remain disclosed during screening. Assumption-based final-test sensitivity
  results can justify further research, but cannot pass economic admission.
  Accepted out-of-sample economics require calibrated execution-cost evidence
  under that reviewed contract; the initial-screen waiver does not waive this.

**Done when:** the candidate passes stated after-cost and risk criteria on
supported out-of-sample evidence, or is rejected. Positive gross returns alone
do not satisfy this task.

### 4. Finish the protected Robinhood worker — conditional on viability

- Reuse the implemented execution/accounting journals, receipt recorder and fee
  attachments; complete their runtime wiring rather than rebuilding them.
- Verify standalone authentication, supported fractional/order terms, nonempty
  order/position mapping, pagination and ownership, and incremental fills on
  previously created orders. Support or explicitly deny immediate-fill responses.
- Complete review/place/cancel semantics through one execution owner. Reserve
  cash/fees/risk before transmission, perform fresh final risk checks, and
  reconcile ambiguous acceptance before considering another action.
- Wire the fixed signal and monitored protective exits to the worker. Entry
  pauses must preserve permitted risk-reducing protection. All actions retain
  account, order, source, configuration and code identity.
- Record attributable quote/order/fill receipts and final charges when actual
  executions become available through the authorized path. Calibration is a
  measurement task, not an instruction to submit an extra trade.

**Done when:** relevant fake-transport/lifecycle tests and operation-specific
broker evidence support the chosen runtime; unknown facts reliably deny action.

### 5. Qualify paper/shadow operation and recovery — conditional on admission

- Use one qualification campaign with the same reviewed strategy and identities.
  Paper and shadow observations can be collected alongside each other when
  eligible; they are not duplicate economics studies or required real trades.
- Verify entry/exit behavior, partial fills, rejects, cancellation races, duplicate
  delivery, disconnections, ambiguous responses, settlement, restart, backup
  restoration, stale inputs, loss limits and alert delivery. Rare failure cases
  can be established with controlled tests rather than waiting for live accidents.
- Demonstrate a durable single owner on one selected runtime. Check actual
  executing code/configuration, paused recovery, retained obligations and receipts.
- Implement a separate, reviewed `spy-cash-lean-pilot-v1` operational policy
  without the arbitrary 100-cycle/seven-date quotas. Require genuine eligible
  normal-session, session-close and closed-to-next-session observations and two
  scheduled decisions spanning the fixed five-session interval, with complete outcomes,
  consistent worker/source/account/code/configuration identities and no unresolved
  reconciliation drift. Establish controlled entry/exit/failure/restart behavior
  and alert/backup restoration evidence as labeled tests, not genuine market cycles.
  A no-order decision can be valid evidence; never force a trade to satisfy coverage.
- Preserve source/account admission, freshness, latest-state, risk and authority
  checks. Implement and test the new versioned envelope before it can admit a
  bounded pilot. Current 100-cycle/seven-date gates remain enforced until then;
  old diagnostics remain permanently ineligible. Normal-live expansion policy is
  outside this amendment. Neither counts nor this coverage proves profitability.
- Use canonical configuration and promotion machinery, not a bypass flag. Test
  that old configurations still reject reduced quotas and that the new scope
  rejects missing coverage, expired/conflicting evidence, dirty state, identity
  mismatches and diagnostic-only records.

**Done when:** the qualification report shows correct behavior, clean account
reconciliation, complete recovery and the implemented coverage-based pilot policy.

### 6. Authorize and supervise the bounded live pilot — final

- Bind the admitted strategy, cost evidence, broker/runtime identity and risk
  limits to explicit stage-specific authorization. Preserve the prior conditional
  diagnostic-trade grant without expanding it into general live operation.
- Start at the authorized admissible size with working exits, monitoring,
  reconciliation and kill controls. Compare observed fills and charges with the
  tested cost bounds; halt new entries when required evidence or limits fail.
- Expand only through a separately supported release. Actual performance may
  invalidate the hypothesis even after all engineering tasks pass.

**Done when:** the authorized pilot operates correctly and its observed economic
results support continuing within the stated limits. Engineering completion does
not guarantee a profitable trading strategy.

## Current implementation inventory

Retained inputs include 2,514 daily bars, calendar/date matching and issuer
distribution work. Accounting, lifecycle, offline replay, economic-evaluator and
local recorder primitives already exist. PR22 has current implementation evidence;
it was verified merged October 7 at 73ccd6c19ad0138e522d8cbf64541415fafec317,
with the exact reviewed tree and fourteen hosted checks passing. This did not
deploy a worker or establish any source/cost/promotion capability.

No accepted after-cost edge, trusted recurring execution worker, qualifying
paper/shadow campaign or live pilot is established. One complete quote session
of 1,262 is retained. Completing the other 1,261 is now conditional follow-up,
not the next delivery prerequisite.

Risk limits, clean reconciliation, fresh order data, ownership/idempotency,
kill controls, secret handling, relevant tests, explicit authority and honest
economic reporting remain required throughout. Retain the repository baseline
and exact-candidate release checks, including authoritative documentation changes;
record unavailable checks explicitly. Critical code changes additionally require
focused tests and integrated review.

## Scope reconciliation with earlier contracts

The October 7 operator amendment is prospective. The separate development screen
uses 100 prior bars only to compute the fixed features; it cannot satisfy the
750-observation evidence boundary of the September 30 registered study. Neither
that study nor its evaluation/promotion factory is altered. A positive new-screen
result means only further research is justified, never acceptance of the old study.

Likewise, the proposed coverage-based bounded-pilot policy intentionally requires
a separately reviewed authority/envelope amendment before use. It does not meet
or alter the existing non-reducible elapsed-time gates in `docs/live-activation.md`.
Those gates remain enforced for all current profiles and normal-live expansion.
The new policy cannot be enabled merely by assigning a new ID or reading this
task list; canonical validation, integrated tests and operational evidence remain
necessary. No current runtime safety requirement is weakened by these documents.
