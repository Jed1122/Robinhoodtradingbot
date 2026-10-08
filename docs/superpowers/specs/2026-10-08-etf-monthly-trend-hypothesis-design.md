# New SPY/cash hypothesis: fixed monthly SMA10 with canonical protection

Date: October 8, 2026.
Status: **written research design approved by the operator on October 8, 2026;
implementation plan subsequently approved**.
Scope: fixed research design. The operator subsequently authorized fixture-first
implementation, integrated verification, executable freeze and one development
study under the linked plan. This is not implementation or outcome evidence and
does not authorize source upgrades, broker calls, purchases, deployment, risk
changes or live operation. Preserve native execution.

## 1. Intent, motivation and alternative approaches

The operator requested a new frozen research hypothesis after the corrected
20/100-momentum study produced 9 REJECT, 15 INSUFFICIENT_EVIDENCE and zero
PROCEED_TO_FURTHER_RESEARCH scenarios. Preserve that study and its rejection.
The purpose is to test a distinct, simple candidate with existing access—not
manufacture a passing answer or promise profitability.

Selected proposal: one unleveraged SPY position or cash, with a fixed ten-month
moving-average signal evaluated at month-end. A slower calendar schedules fewer
entry opportunities than five-session decisions; it does not guarantee fewer
actual trades, lower total fees, a positive return or a statistical advantage.
Protective exits and the unchanged risk policy can dominate the resulting path.

Falsifiable development claim: under the fixed 25bps-per-side/$0.01-per-order
stress assumption and an independently supportable operating budget, this
candidate can pass every completeness, operating-profit, drawdown, episode-count
and paired-uncertainty condition in section 6. Failure or insufficient evidence
stops expansion; merely beating the old candidate or producing a positive gross
return does not pass. This is a descriptive development claim, not an assertion
of a live edge or a new statistically independent test.

Alternatives considered without testing outcomes:

- Short-term mean reversion: a separate hypothesis with more timing/fill
  sensitivity; not selected or implemented.
- Passive constrained buy-and-hold/cash: keep as the descriptive benchmarks,
  not call it a newly established automated trading edge.
- Further momentum grids: not selected; avoid searching the previously examined
  history for the best-looking windows.

The ten-month/month-end choice has a pre-existing public research rationale:
[Meb Faber's timing-model description](https://mebfaber.com/timing-model/)
describes monthly evaluation and the ten-month moving average. This is motivation,
not evidence for our candidate. Our SPY-only raw-price inputs, small caps,
ATR/target/maximum-hold exits, zero-yield cash and modeled costs differ from that
work. Do not import its performance claims or label this a replication.

## 2. Separate identities and attempt history

- Design ID: `spy-cash-monthly-sma10-protected-design-v1`.
- Proposed research policy ID: `spy-cash-monthly-sma10-protected-development-v1`.
- Parent documentation/source checkout: `20b7141ae6026d279a4606da0c28a3a1bd1a89fe`.
- Existing executable baseline remains the reviewed source at
  `bc49e1104a5c3c3d2498df6ea39ecc6f008e9bc1`; no behavior changes at design time.

`EtfStudy`, `EtfPilotSettings` and `EtfDailyProtocol` retain their old literal
policy IDs, 20/100 windows, five-session cadence, validators, hashes and reports.
Never mutate them to accept monthly rules or attach a new name to an old run.
The new policy needs separately typed, immutable, research-only contracts in the
same canonical configuration/release-envelope graph. No second risk/config loader.

Design registration locks the hypothesis choices. A later executable freeze must
bind the actual reviewed code/config, policy, calendar, distribution, source and
cost hashes before market outcomes. Do not invent future hashes or treat a design
commit as executable readiness. Any substantive pre-evaluation amendment creates
a retained version; an outcome-driven amendment is a new attempted hypothesis.

This is at least the second strategy family considered in this local study
sequence. The earlier pre-correction and corrected screens are retained versions
of the same momentum hypothesis, not independent confirmations. All attempts,
including rejected/insufficient ones, remain visible. No result-selection or
multiple-testing requirement is waived by choosing a single new candidate.

## 3. Data, development window and causal monthly observations

Use only retained Alpaca SPY daily OHLCV, the existing session reference and issuer
distributions; no new provider or acquisition. Main alone handles private inputs.
Preserve original bytes and use the bounded receipt/hash readers. Bind the exact
component identities again during the executable freeze; earlier verification
does not make an unqualified source eligible.

The eligible development price window is `[2016-01-01, 2024-01-01)`. These inputs
have already been examined through the earlier study: this is **adaptive
development research**, not fresh out-of-sample evidence. The 2024–2025 outcome
period remains excluded. Integrity/date inventory is not outcome evaluation;
historical human/external exposure remains unknown and must be disclosed before
claiming an untouched final test.

For each calendar month, take the raw close of its exact final eligible trading
session from the frozen session calendar. Do not substitute the last available
bar when the required final-session observation is missing. Require ten
consecutive complete monthly observations, including the decision month. No
interpolation, skipped months, shortened averages, optimized windows or inferred
no-trade/closure messages.

Fixed first decision anchor: **October 31, 2016**, selected from dates alone,
using January–October 2016 monthly closes. Require that anchor to be the calendar's
eligible October month-end. If the calendar/required inputs cannot establish it,
deny the candidate's initialization rather than silently shift the anchor.
Evaluation points begin on the first eligible session after that anchor; subsequent
entry decisions occur only after eligible month-end closes through December 2023.
The old May 26 anchor, 100-bar screen and legacy 750-observation profile stay unchanged.

Represent the final December 2023 decision even when its next eligible execution
session falls outside the development window. Such an intent remains pending
and its outcome incomplete; never consume 2024 prices, silently drop the intent
or force an end-of-input fill. Existing positions, reservations and settlement
obligations remain outstanding as applicable. An incomplete case cannot pass the
screen, even if this prevents a terminal-month candidate from qualifying.

Raw/unadjusted/no-splits price basis and calendar-close availability remain
explicit unqualified assumptions. Feature closes are not total-return prices;
cash distributions enter the ledger once under existing entitlement/payment
rules. Do not add dividend cash to already adjusted prices. Unknown corporate
actions/publication history remain limitations, not assertions of no actions.

The monthly signal uses only bars completed and assumed available before the
decision. Its decision phase is after month-end close; execution cannot occur
at that closing price. Missing monthly/daily inputs deny new entries, preserve
known obligations and independently defined protection, and mark affected
outcomes incomplete. Do not fabricate a strategy liquidation or fill from missing
data. Missing observations cannot be counted as successful market monitoring.

## 4. Fixed strategy and independent risk/protection

Let `C_m` be that month's raw closing price. With ten consecutive eligible months,
compute `SMA10_m = (C_m + C_(m-1) + ... + C_(m-9)) / 10` using Decimal.

- If `C_m > SMA10_m`, the regime is LONG_ELIGIBLE. When flat, propose one entry
  for the next eligible session, subject to every independent admission check.
- If `C_m <= SMA10_m`, the regime is CASH. When holding, schedule a complete
  closing intent for the next eligible session. Equality is cash, not an
  implementation-dependent tie or inherited old strategy action.
- A positive signal while already holding causes no addition, pyramiding,
  notional rebalance, stop reset or trial-budget replenishment.
- After any exit, no discretionary re-entry occurs before the next month-end
  decision. A rejected/unfilled entry does not authorize blind retries.

The monthly regime changes only at a validated monthly decision. Its negative
transition is the new policy's regime/deselection exit; it does not reuse daily
20/100 HOLD as a monthly signal. Existing monthly and momentum paths must remain
distinct. This observation schedule does not turn off daily protective monitoring.

Retain the canonical 2.0 ATR stop multiplier, 2.0 reward-to-initial-risk target,
100-session maximum hold and enabled regime/unselected exits. Compute entry ATR
with the existing FeaturePipeline true-range convention on the latest 100
complete daily bars ending at the monthly decision; require the exact daily
window. Lock the original entry stop/target; never widen or reset them to keep
the position alive. The entry session counts as holding session one. If still
open after holding session 100, schedule the closing intent for the next
eligible opening, without forcing a fill. Independent controlled fixtures must
verify compatibility with the common owner's current holding-age convention.

Daily protective stop/target conditions remain eligible between month-ends.
A stop gap uses the worse opening price with adverse costs. A favorable target
gap is marked at the target conservatively, not a chosen favorable opening.
When a daily range can reach stop and target, process stop first. A lifecycle
event cannot sell twice when scheduled and protective exits overlap.

Unchanged authority: $100 risk reference, $0.50 stop-plus-bounded-fee budget,
$15 base/$5 micro order caps, $60/$20 gross caps, 80% unencumbered cash,
$50 non-replenishing cumulative trial loss, $1,000 equity ceiling and all stricter
daily/weekly/drawdown/activity/account controls. Hypothetical $500/$1,000 cash is
not an increased risk allocation. One position, no additions, no leverage,
shorting, options or other assets. Profits/deposits do not replenish consumed loss.

Native whole-share feasibility remains separately reported as zero where the
unchanged caps require it. A development-only fractional scenario may reuse the
explicit hypothetical .001 quantity increment, .000001 price increment and
$1 minimum notional; it never proves a supported broker order route.

## 5. Execution, account continuity and reuse boundaries

No transport or credentials can reach the new strategy. Reuse common Decimal
sizing, reservations, cash/trial accounting, settlement, lifecycle, private
publication, benchmark and paired-statistics primitives. Extend only necessary
research seams rather than rebuild an execution owner or competing risk engine.
The existing simulator hardcodes its momentum strategy; any extraction needed
for the new research path requires compatibility tests preserving old behavior
and hash preimages, not an arbitrary caller callback that controls risk.

Scheduled entries/exits use the next eligible session's adverse opening assumption,
not the signal close. Fill probability, displayed liquidity, latency and intraday
ordering remain unobserved. Retain T+2 as the explicitly hypothetical settlement
convention of this model, not a statement of historical/current broker settlement.
Keep full cash and bounded-fee reservations, unresolved obligations, duplicate
guards and non-replenishing completed-episode accounting. No forced terminal
sale, zero-fill fabrication or completed-cash claim for open obligations.

Pure resumption tests must retain the ten-month observation window, last monthly
decision identity, pending intents, original entry risk/holding age, accounting
cursors and unresolved obligations. Split-input/resumed results must match the
uninterrupted synthetic run. This is not deployed recovery or qualifying paper.

All new source/cost/execution/economic/promotion/live fields remain false.
Existing diagnostic owners stay permanently ineligible. No monthly ID, successful
backtest or new constructor may unlock production, alter old promotion quotas or
implement the proposed lean-pilot policy by implication.

## 6. Frozen economics, uncertainty and stop conditions

Keep the existing 24 descriptive combinations: two cash tiers ($500/$1,000),
three per-side price/fee assumptions (0bps/zero fee; 5bps/$0.01; 25bps/$0.01),
and four monthly data/compute budgets ($0/$0, $0/$12, $99/$0, $99/$12). Nonzero-fee
cases reserve $0.10 for the complete episode. No cost case is a customer invoice,
quote, calibrated execution or verified free-plan entitlement.

Whole-month counterfactual budget renewals start at the first evaluated session;
record that derived anchor in preregistration, not after seeing outcomes.
Report trading P&L and recurring operating profit separately. Spread/slippage
embedded in prices and fees are charged once. Sunk research expense/measured
cash yield remain unknown; assumed cash yield is zero. Do not lower modeled costs
after outcomes or cancel a subscription under this design authorization.

Use identical evaluation dates for candidate, cash and the existing retrospective
mean-exposure-matched, capped buy-and-hold reference. It is a descriptive reference,
not a tradable allocation. Do not compare the new shorter evaluation window with
the old whole-window P&L as if periods/exposures were identical. No old market
study rerun is requested here merely to construct a comparison.

Retain prior-NAV performance returns with explicit undefined treatment for
nonpositive preceding NAV. Paired uncertainty uses fixed-initial-capital P&L
fractions, 20/100-session blocks, 1,000 draws, 95% bounds and seed 20260710.
Daily observations/draws/completed episodes are not independent opportunities.
Adaptive selection and multiple-testing limitations remain unresolved; existing
qualified-research/PBO/fold/stability requirements are not bypassed.

Per-scenario descriptive screen order remains:

1. Missing/no evaluated data or incomplete outcomes: INSUFFICIENT_EVIDENCE.
2. Otherwise nonpositive operating profit or risk-reference drawdown above 10%:
   REJECT.
3. Otherwise fewer than 30 completed-episode proxies, missing uncertainty or a
   nonpositive paired lower bound against either cash or constrained reference:
   INSUFFICIENT_EVIDENCE.
4. Only the remaining case: PROCEED_TO_FURTHER_RESEARCH, never economic admission.

Lower expected trade count is not permission to reduce the 30-proxy floor,
effective-sample requirements or uncertainty criteria. An insufficient sample
is a valid outcome. Retain every scenario; no selected winner. A zero-cost-only
positive case does not establish viability. Further execution research is
justified only if a **25bps-per-side/$0.01-per-order** case survives and its
operating path is independently supported. Which budget cases have support must
be recorded before evaluation from entitlement/runtime evidence, without using
strategy outcomes; an unsupported $0 budget cannot become the selected winner.
If no operating route can yet be supported, the screen may still be reported as
assumption-based research but cannot justify execution expansion. A 5bps or
zero-cost pass alone cannot replace the frozen stress condition. Acceptance on
the final test still needs eligible source and calibrated costs under a
separately reviewed admission contract.

If no such case survives, stop this candidate's data/execution expansion. No
parameter search, risk increase, forced trade or holdout optimization follows.
A follow-on idea needs a retained, separately frozen research hypothesis.

## 7. Verification and gates before any outcome run

This specification is not implementation evidence. Written-design and linked
implementation-plan review are complete. No outcome run occurs until the plan
is implemented, reviewed and the actual executable protocol is registered
before evaluation.

Fixture-first verification must cover independent exact monthly-average/equality
expectations, exact month-end selection including leap/holiday/early-close/DST,
missing terminal-session/required-month observations, prior-bar/decision/fill
timing, old/new policy rejection and hash compatibility, protective/maximum-hold
overlap, restart/no-double-action, cash/dividend/fee conservation, zero admissible
size, profit/deposit/trial history, incomplete terminals and holdout rejection.
Reuse baseline reports/paired statistics with exact return-convention and
zero-cost-only-expansion-denial controls. No authenticated tests or private input
delegation in CI. Keep 80% overall and 90% critical branch gates and normal
Ruff/Mypy/pytest/Bandit/locks/audit/manifest/exact-candidate review requirements.

No source/risk/execution code or config has changed. No new economic result,
broker readiness, paper/shadow observation or live authorization exists.

## 8. Conditional path to completing the project

Written design review -> reviewed implementation plan -> synthetic implementation
and compatibility checks -> executable preregistration -> one private adaptive
development evaluation. Only a surviving candidate warrants minimal source/cost
qualification and untouched final testing, followed by protected broker wiring,
genuine qualifying paper/shadow, selected-runtime recovery and separately
authorized bounded live operation. Each gate is independent; profitability is
not promised and the project remains incomplete.
