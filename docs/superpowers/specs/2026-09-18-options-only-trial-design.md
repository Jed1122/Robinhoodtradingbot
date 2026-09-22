# Options-only trial: offline foundation design

Date: 2026-09-18 UTC. Status: written for operator review; not implemented.

Scope: the existing Robinhood trading system, not the separate Polymarket project.
Inspected base: `5d3de0df92b1a206bba47957637bfd539df919a1` on
`codex/continue-implementation-from-commit-7c4dcd1`, plus existing uncommitted work.
This document does not authorize code/configuration changes, authenticated calls,
production-ledger access, deployment, subscriptions, or live orders.

## 1. Approved direction and scope boundary

The operator requested options-only trading and reported Level 2 options approval.
That report has not been verified against the dedicated Agentic account. The
operator approved these design inputs:

| Input | Trial rule |
| --- | --- |
| Allocated capital | $100 total, not an instruction to spend the whole balance |
| Per-trade potential loss | At most $50, including entry and exit fees |
| Cumulative trial losses | At most $50 for the entire initial trial, not per day |
| Replenishment | None from profits, deposits, a new day, restart, or automatic reset |
| Exposure | One long-call or long-put position at a time |
| Actions | Buy to open and sell to close only |
| Exclusions | Short options, spreads, averaging down, pyramiding, same-day-expiry entries |
| Initial operating scope | Offline, synthetic, broker-incapable simulation only |

These are ceilings, not spending targets. Existing stricter controls still apply.
No eligible trade is a valid outcome. Contract selection must not relax liquidity,
expiry, or research standards merely to find a premium below $50. This design makes
no return claim and does not establish that options are suitable for this account.

The selected approach extends the current canonical domain, configuration, and
simulation boundaries. A signals-only tool would avoid order-lifecycle work but
would not test the requested execution controls. A separate options bot would
duplicate safety authorities. Neither alternative is selected.

The next implementation milestone is deliberately limited to contract validation,
trial-loss accounting, and scripted synthetic order/position lifecycles. A complete
options strategy, data acquisition, connected paper/shadow runtime, and live
execution are later, separately designed milestones. Existing equity work is
preserved but is not the next expansion priority.

## 2. Verified repository boundary and conflicts

Current foundations and gaps are described in the
[architecture](../../architecture.md), [capability matrix](../../capability-matrix.md),
[limitations](../../limitations.md), [risk policy](../../risk-policy.md),
[research requirements](../../strategy-research.md), and
[live activation contract](../../live-activation.md).

| Subsystem | Current state | Consequence |
| --- | --- | --- |
| Canonical options instruments | Absent: `AssetClass` has equity, crypto, prediction only | Do not disguise an option as an equity |
| Options configuration | Blocked: `EquitySettings.options_allowed` is `StrictFalse` | Flipping YAML cannot enable options |
| Order state machine, Decimal primitives, pure risk checks | Implemented locally | Reuse reviewed neutral primitives; do not reuse equity economics blindly |
| Offline equity replay | Synthetic implementation with uncommitted follow-on work | Preserve it; its outcomes do not validate options |
| Authenticated connected reads | Seven reviewed equity reads; position/order rows accept empty collections only | No verified options adapter or nonempty options reconciliation |
| Provider review/place/cancel | No working live write composition | Public tool names do not remove this blocker |
| Options strategy, real data, promotion | Unimplemented/unverified | No options research acceptance or live eligibility |

The following settings come from the
[base configuration](../../../configs/base.yaml) and the
[release envelope](../../../configs/safety-envelope.yaml); the additional micro-live
caps are defined in the envelope. Dollar illustrations assume the relevant equity
reference is $100; percentage limits can tighten as equity falls.

| Existing limit | Current value | Relationship to the proposed trial |
| --- | --- | --- |
| Per-trade risk | 0.50%, illustrated as $0.50 | Much stricter than $50 |
| Position notional | 15%, illustrated as $15 | Does not admit a $50 premium position |
| Order notional | $15 | Does not admit a $50 entry |
| Gross exposure | 60% and $60 | Remains an independent cap |
| Cash reserve | 40% | Remains independently required |
| Daily / weekly loss | 2% / 5%, illustrated as $2 / $5 | Can stop entries before trial exhaustion |
| Peak drawdown | 10%, illustrated as $10 | Existing hard-stop semantics remain |
| Micro-live limits | $5 order, $20 gross, two new orders/day | No bypass by jumping directly to normal live |
| Other controls | Activity, correlation, reward/risk, freshness, health, reconciliation | Still required; no implicit exemption |

**No existing limit is raised or reinterpreted by this approval.** Trial admission
is necessary but not sufficient. In an eventual composition, an entry must satisfy
the intersection of trial limits and every applicable canonical check. Under the
current configuration, options are denied outright.

A future options policy must explicitly define premium risk, premium notional,
underlying exposure and correlation, and any applicability changes to equity-only
checks. Stop distance must never replace full premium-at-risk for a long option.
Unsupported applicability denies; it is not a reason to omit a check. Any proposed
release-envelope change requires a separate exact old/new policy review and operator
approval. The $50 answers are not that approval.

## 3. Offline architecture and canonical ownership

All names below describe proposed responsibilities, not existing APIs. The
implementation plan must freeze exact interfaces after this specification is
approved. No provider transport enters domain, strategy, or risk modules.

1. **Contract values in `domain/`:** immutable option identity and validated
   contract economics. Reuse bounded Decimal and UTC primitives. Add a distinct
   option asset identity only with exhaustive dispatch tests proving existing
   production paths continue to reject it.
2. **Trial parameters in `config/`:** one strictly validated extension of the
   existing canonical configuration graph, with corresponding envelope validation.
   There is no second YAML loader, options-only risk configuration, or per-scenario
   override of release limits. The production options prohibition remains intact.
3. **Pure budget accounting in `risk/`:** derive consumed loss, active reservation,
   remaining allowance, and denial reasons from validated trial state. This is an
   additional restriction, not a replacement pretrade engine or an authorization.
4. **Scripted coordinator in `simulation/`:** in-memory, one-owner sequencing of
   explicit synthetic events, contract quantities, cash, fees, and the trial book.
   Reuse the generic order state machine where its invariants match; do not pass
   options through an equity request to evade existing type checks.
5. **Results in `simulation/`:** deterministic audit records distinguish terminal
   orders, flat positions, final fee accounting, and completed episodes. Synthetic
   outputs cannot create provider, research, authorization, or promotion evidence.

The first slice has no broker object, credentials, production persistence import,
network client, live CLI composition, scheduler, or deployment change. It takes
explicit scripted candidates, not a trading signal generator. Small fixtures supply
fees and event timing as visibly unvalidated assumptions. No equity commission or
fill calibration is silently presented as options evidence.

Synthetic policy examples can exercise the pure $50 trial calculation without
claiming full admission. A scripted lifecycle fixture is not an allowed production
intent: the current options prohibition and stricter canonical limits remain
independently tested. The runner must report that distinction explicitly, never
label a trial-budget-only result as passing the complete pretrade checks.

Existing canonical entry points and serialized identities must remain compatible.
If the canonical configuration needs a versioned extension that changes its hash,
that change must be explicit and must invalidate incompatible evidence; never
preserve an old hash over different content. The implementation plan must select
and test the compatibility mechanism before editing shared models.

## 4. Contract, quote, and intent requirements

An option identity includes the source contract reference, underlying reference,
call/put type, exact strike, expiration, currency, multiplier, deliverable, exercise
style, settlement type, and metadata provenance/observation time. Display symbols
alone are insufficient. Synthetic references stay in a reserved synthetic namespace.
Real account identifiers or provider payloads never enter fixtures or this document.

The proposed initial supported contract class is a standard USD stock/ETF option
with a verified 100-share deliverable. Adjusted contracts, unknown multipliers,
nonstandard deliverables, index options, and unknown settlement conventions are
denied. The arithmetic uses the validated multiplier, not an assumed universal 100.
Robinhood describes standard contracts as typically 100 shares with premiums quoted
per share; it also lists long calls and puts among Level 2 strategies.
[Official options reference](https://robinhood.com/us/en/support/articles/options-knowledge-center/).

Quantities are positive whole contracts. Side and purpose must explicitly mean
buy-to-open or sell-to-close. The first version supports only limit orders with an
explicit validated session end/time-in-force. Price increments, multiplier, contract
identity, quote timestamps and executable side must agree. No fractional contracts,
market orders, synthetic quote from an underlying price, or guessed Greeks.

One active entry reservation or position occupies the account's trial slot. The
original entry may fill in multiple whole-contract parts, but no additional entry
may add to the position. Before an exit, any unfilled entry remainder must become
terminal and the actual held quantity must be reconciled. Exit quantity cannot
exceed verified holdings minus quantities committed to another active close order.
No overlapping close orders or silent cancel-and-replace exposure increase.

Live-facing liquidity, quote freshness, underlying universe, expiry window, session
calendar, entry signals and closing thresholds are not selected by this document.
They require explicit canonical policy and evidence in a later design. No 0DTE
entries means no entry on the contract's exchange-local expiration date; storing
timestamps in UTC does not justify comparing only UTC dates. Missing session or
expiry interpretation denies admission.

## 5. Non-replenishing trial budget

### Accounting definition

The proposed trial has one fixed identity, $100 authorized capital, $50 per-episode
risk ceiling, and $50 cumulative loss ceiling. A trade episode begins with the first
entry reservation and ends only when its position is flat, all related orders are
terminal, and all cash flows and fees are final and reconciled.

The cumulative measure is **the sum of net losses of completed episodes**, including
their entry and exit fees; it is not net portfolio P&L. Netting proceeds and costs
within one episode determines that episode's result. A profitable episode cannot
offset a loss from any other episode. Partial exits do not end an episode or free
trial capacity prematurely.

Define:

- `L`: sum of `max(0, entry debit + all episode fees - closing proceeds)` over
  completed episodes. Expired contracts contribute zero proceeds only after a
  verified no-exercise terminal outcome. `L` never decreases.
- `R`: full worst-case loss reserved for the active episode, including unfilled
  entry quantity and conservative total fee capacity. There is at most one episode.
- `available`: `max(0, 50 - L - R)`. An unknown amount is a denial, not zero.

For a candidate with `q` whole contracts, multiplier `m`, per-share limit `p`, and
bounded total fee capacity `F`, reserve `q * m * p + F` before any economic effect.
The candidate must satisfy the $50 per-episode ceiling and `L + R + candidate <= 50`,
as well as all applicable canonical constraints and verified funding requirements.
For an already reserved episode, subsequent fills consume its reservation; they do
not create a second reservation or a second charge to `L`.

Fee capacity must cover the supported maximum fill/close pattern, not merely an
optimistic one-fill commission. If fees or the supported event count cannot be
bounded, admission fails. Price slippage cannot violate a limit. Closure slippage
can consume the entire premium; a stop instruction does not lower this reservation.

Keep the original full reservation through partial fills, partial closes, pending
cancels and uncertain outcomes. A terminal no-fill order may release it only after
all related fees are known; any incurred fees count as episode loss. At completed
episode settlement, atomically replace `R` with that episode's nonnegative loss in
`L`. Release only unused reserved capacity. Closing proceeds remain subject to
independent cash-settlement and funding checks before reuse.

### Examples and lifecycle invariants

- Start: `L=0`, `R=0`, allowance $50. Reserving $50 leaves no additional allowance.
- Close that episode with a $20 loss: `L=20`, `R=0`, allowance $30.
- Later complete a profitable episode: `L` remains $20, allowance returns to $30,
  not $50 and not $30 plus the gain.
- Accumulate $50 of losing-episode losses: new entries remain blocked indefinitely
  under that trial identity. A smaller remaining allowance shrinks the ceiling;
  it never authorizes averaging down or automatic retries.
- Synthetic arithmetic case: `0.49 * 100 * 1 + 1.00 = 50.00`. The $1 fee is a
  fixture assumption, not Robinhood pricing. This passes only the proposed trial
  arithmetic test; current production options and stricter risk gates still deny it.

Daily/weekly counters keep their existing semantics; the trial counter never resets
with those counters. Deposits and profits cannot increase authorized risk equity.
A new trial would require separate explicit approval, audited closure of the old
trial, and a reviewed state transition; automatic creation of a fresh trial on
startup is prohibited.

The offline milestone verifies deterministic reconstruction from the same complete
synthetic event history, including duplicate-event idempotency. It does not provide
durability across real process/host failures. Before any connected runtime, a
separately reviewed persistence/reconciliation design must bind the trial to account,
config/code identities, durable reservations and append-only settlement evidence.
Missing state, mismatched identities or replay gaps must block startup/entries, not
reinitialize an allowance. A code/config upgrade must never erase spent loss budget.

The $50 ceiling is an admission/accounting control, **not a guarantee that a real
brokerage account cannot lose more than $50**. Unexpected fees, exercise-created
stock exposure, manual activity or execution/reconciliation faults can invalidate
the model. Any overrun is recorded as an incident, not clipped out of accounting.

## 6. Failure and expiry behavior

Trial exhaustion is entry-blocking, not process termination. Continue monitoring,
alerts, reconciliation and eligible close handling. Request cancellation of unfilled
entries only through a separately authorized cancel capability. Cancellation requests
and transport timeouts do not prove an order is terminal; retain reservations until
confirmed. An ambiguous submission is never retried as a new order.

This does not bypass existing hard stops. The canonical drawdown rule can deny both
entries and new exits and request the kill switch; it cannot request liquidation.
If those controls conflict with closing an expiring position, remain fail-closed,
alert the operator, and use the separately approved incident procedure. Do not turn
trial exhaustion into permission to override health, ownership, reconciliation,
authorization, or kill controls. A live design must resolve that operational conflict
before activation; the offline tests must expose it rather than hide it.

The long-only plan must not intentionally exercise contracts. Robinhood describes
automatic exercise conditions and best-effort sale or do-not-exercise handling near
expiration. Its actions do not guarantee that an option will be closed safely.
[Official expiration and exercise rules](https://robinhood.com/us/en/support/articles/expiration-exercise-and-assignment/).

Therefore live readiness requires a verified closing schedule, exercise-prevention
procedure, confirmation semantics, and an outage/illiquidity/holiday escalation
procedure. Do not infer an exercise or do-not-exercise API from public order-tool
names. If the necessary control cannot be verified for this account and workflow,
the options-only live path remains unavailable. A canceled closing order, the end
of a replay file, or the expiration timestamp alone never establishes a flat account.

## 7. Capability and evidence boundaries

Robinhood's public documentation currently names option chain, instrument, quote,
historical, position and order reads, plus `review_option_order`,
`place_option_order` and `cancel_option_order`.
[Official agent tools](https://robinhood.com/us/en/support/articles/trading-with-your-agent/).
This is public documentation only, not authenticated schema/behavior evidence or
account authorization. No such operation is invoked for this specification.

Later work requires separately authorized schema capture and sanitized read-shape
review, including nonempty/paginated positions and orders, followed by distinct
review/place/cancel implementations and behavioral evidence. Do not assume an
order review is an offline test. Read, review, place and cancel remain independently
injectable and independently gated. The current two read allowlists remain unchanged;
the OAuth bearer credential is trading-capable despite those local restrictions.

Options research must account for point-in-time chains, contract availability,
quotes, costs, expiry, corporate actions and execution outcomes. Equity-only history
and accepted equity results cannot substitute for options validation. Existing history,
source-quality, research and promotion constraints remain unchanged; any proposed
options-specific interpretation needs a separate documented review, not a waiver.
No data subscription or provider switch is authorized; current authorized data spend
remains $0.

All first-milestone outputs have `assumptions_validated=false`,
`evidence_promotable=false`, and `production_pretrade_eligible=false`. A successful
synthetic replay cannot start paper/shadow clocks, validate account permissions or
unlock a production order. Later qualifying promotion retains the existing exact
identity and elapsed-time requirements, including 100 eligible paper cycles and
seven distinct UTC shadow dates before micro-live. No accelerated synthetic clock
or existing equity observation can fill an options evidence gap.

## 8. First-milestone acceptance criteria

The later implementation plan should cover this one offline slice, not the entire
live system. Acceptance requires deterministic, local tests proving:

1. Exact, bounded contract/money/UTC validation; invalid deliverables, fractional
   quantity, missing metadata, crossed/stale quotes, unsupported settlement and
   same-expiration-day entries fail closed.
2. Premium times verified multiplier and quantity, plus bounded fees, drives risk.
   Values just below, at and above the trial ceiling use exact Decimal arithmetic.
3. The $50 -> $20 loss -> $30 remaining sequence is correct; gains, date changes,
   event replay and deposits cannot restore consumed capacity.
4. The active slot blocks a second position or entry, including after partial fill.
   Full reservation remains through partial close, cancel race and ambiguous state.
5. Duplicate events are economically idempotent; conflicting duplicates and out-of-order
   state that cannot be safely reconstructed deny without partially publishing money.
6. Canceled/rejected no-fill orders release only verified unused capacity; fees are
   retained. Terminal entry/close orders do not by themselves imply position flatness.
7. Close quantity cannot exceed available held contracts; pending closes cannot be
   duplicated. Exhaustion blocks entries but does not itself block a valid close.
   A separate canonical hard stop is still honored and visibly reported.
8. Missing final fee/cash/position evidence yields an incomplete result with its
   reservation intact. No forced fill, forced liquidation or assumed worthless expiry.
9. Cash, positions, active commitments and trial losses reconcile through each
   atomic synthetic transition; no borrowing or double counting occurs.
10. Existing production options rejection, legacy equity/crypto behavior, identity
    checks, read allowlists and non-promotable defaults remain intact. Tests cannot
    construct a live broker or produce promotion evidence.

End-of-input reports explicitly separate completed episodes, remaining positions,
pending orders, reserved risk, consumed trial loss and remaining allowance. Missing
outcomes are not reported as a completed successful strategy trial.

## 9. Dependency chain, decisions and review gate

Critical path:

Written-spec approval -> bounded offline implementation plan -> offline contracts,
budget and lifecycle verification -> options strategy/data and exact risk-policy
design -> separately authorized capability/behavior verification -> durable connected
runtime and expiry-control validation -> qualifying research/paper/shadow evidence
-> separate signed live authorization and manual activation.

Offline work does not depend on buying data or inspecting the account. Later live
gates remain blocked until the operator and primary owner explicitly resolve:

- Exact options universe, entry/exit strategy, DTE window, session/expiry calendar,
  liquidity thresholds, fee bounds and exercise-prevention workflow.
- The canonical treatment of options within every existing risk check; explicit
  approval for any proposed old/new safety-envelope change, without bypassing it.
- Dedicated-account permission and usable funding evidence, licensed/suitable
  options data and any separately approved acquisition cost.
- Authenticated schemas and behavior, complete nonempty order/position mapping,
  restart-safe trial persistence, reconciliation, and cancel/close failure handling.
- Full options-specific research, promotion, security, operating and release evidence.

Protected design and implementation remain primary-owned: pricing, strategy,
exposure, risk, broker writes, reconciliation, authorization and production
persistence are not delegated. Documentation/fixture assistance, if separately
requested, cannot decide those policies or receive secrets/provider payloads.

This design is complete only as a review artifact. The next action is operator
review of this file, then a separate implementation plan. No options code, risk
setting, account state or live capability is changed by writing or accepting the
document alone.
