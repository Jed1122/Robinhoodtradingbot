# Standing operator authority

Recorded 2026-09-28 UTC from the operator's direct instructions in this project.
The original grants update workflow authority, not software risk policy,
economic acceptance criteria, credentials, account permissions, or live controls.
The separately dated account-ceiling amendment below records a later narrow exception.
Later explicit operator instructions supersede this record.

## Automatic integration and merging

The operator requested: "Proceed with economic validation and update your
authority to auto merge everything without my approval."

For this Robinhood project, the coordinator may commit, push, create or update
pull requests, and merge completed in-scope work without another per-merge
approval. This includes the options-research/data-validation work already approved.
It does not authorize arbitrary changes in other projects or incorporation of
unrelated staged, unstaged, or untracked work.

The established integration target is `codex/robinhood-system-implementation` in
`Jed1122/Robinhoodtradingbot`, as used by merged PR #1. At this recording, `main`
contains the initial commit, not the integration history. Recheck remote ancestry
before each integration; do not silently retarget or replace branches. Preserve
active worktrees and other tasks' changes.

Required conditions:

- Review the exact diff, its ownership, base/head revisions, and affected contracts.
- Run relevant local verification and inspect all required current CI results on
  the exact PR revision. A prior green revision is not a substitute.
- Resolve substantive review findings; never use admin bypass, disable checks,
  weaken assertions, force-push, or remove protections to obtain a merge.
- Inspect merge-triggered workflows. Deployment, broker calls, data publication,
  credential access, or other separately gated effects need their own authority.
- Retain accurate limitations and separate technical, economic, capability, and
  operator-authorization verdicts. A successful merge is not a release approval.

## Execution calibration diagnostics — explicit 2026-10-02 grants

The operator answered "Allow read-only history check" to a bounded diagnostic
of existing Robinhood equity order history for fill and fee records. Customer
payloads remain on the trusted Mac. This authorizes account binding and the
bounded history read, not order review, placement or cancellation.

When the existing selected connection required browser authentication before any
history response, the operator answered "Allow sign-in and history check" to
opening the existing OAuth workflow and saving a new connection in a separate
private directory. The operator completes the browser sign-in. Robinhood's sole
`internal` OAuth credential remains trading-capable; the diagnostic's local
read-only allowlist provides the write boundary. Existing credentials, service
configuration, production mounts and deployment are not replaced by this grant.
The saved account fingerprint must match the existing intended account before
history is read. No new market-data provider or paid agreement is authorized.

## Databento credit-only data acquisition

The operator previously authorized all existing credits for data necessary to
complete economic validation and explicitly reconfirmed: "I also gave you
approval to purchase all remaining data with the remaining credits that I have."

Do not ask again for individual necessary purchases that meet the existing
[acquisition controls](options-data-validation-handoff-2026-09-25.md). The grant
is permission to use the remaining authorized credits, not a requirement to
exhaust them or a guarantee that they fund a complete qualifying study.

Before any submission:

1. Verify authenticated, current applicable credits and outstanding accepted or
   uncertain jobs. The earlier recorded balance is historical, not current proof.
2. Check existing receipts and local archives to avoid unnecessary duplicates.
3. Freeze the exact necessary dataset/schema/symbols, UTC windows, encoding,
   reference data, and complete entry/monitoring/exit/settlement coverage before
   examining outcomes. Bind the complete package to customized-request pricing.
4. Confirm that the complete cost fits unconsumed authorized credits after pending
   costs, with no potential cash charge. Reserve the cost privately, submit once,
   and reconcile uncertain acceptance before considering any retry.
5. Preserve receipts and raw inputs privately; validate integrity, semantics,
   point-in-time availability, and actual usable coverage separately.

The existing private-personal-use/local-retention attestation remains accepted;
do not invent a repeat OPRA-agreement approval requirement. If the provider
presents a new binding agreement, stop for the operator instead of accepting it.
No cash top-ups, subscriptions, upgrades, live-data services, or unrelated data
purchases are authorized. Additional unrelated future credit grants do not
automatically enlarge this scope. Missing access or an undefined/unusable data
package pauses only dependent acquisition, not credential-free development.

## Databento support outreach — 2026-09-29 update

The operator instructed that the proposed technical questions must not be sent to
Databento support and reports that the answers are affirmative. Do not send those
questions or treat outreach approval as pending. Retain the report as operator-provided
information, not as a provider document or independently verified protocol.

Continue the approved credential-free implementation and examine available public
documentation and preserved data. Exact timestamp, correction, initialization,
mapping and coverage rules still require reproducible evidence before actual-source
qualification. This update does not install source rules, change risk limits or
authorize live operation. The existing credit-only acquisition grant is unchanged.

## Unchanged boundaries

No broker order review, placement, cancellation, real-money test trade, transfer,
credential change, deployment, live activation, or risk-limit increase follows
from the integration or data-acquisition grants above. Existing separately
approved read-only checks retain their original scope. Research data and secrets must not enter Git or Cloud
agents. Genuine economic validation still requires actual option bid/ask and
underlying data, defensible costs and uncertainty, and all canonical acceptance
criteria; a synthetic run or an engineering pilot cannot stand in for it.

## Account-equity ceiling — explicit 2026-09-30 amendment

The operator requested: "also change the $150 live account ceiling to $1,000."

This authorizes changing only the configured account-equity ceiling and its
canonical release bound from $150 to $1,000, with consistent enforcement and
regression tests. It does not authorize a transfer, balance inspection, deployment,
live activation, real-money order, changed strategy, larger risk-equity reference,
larger order/exposure limits, or weaker loss/reconciliation/kill controls.
All other capital assumptions and limits remain unchanged. See the current
[risk-policy amendment](risk-policy.md#account-equity-ceiling-amendment--2026-09-30).

## ETF research priority and paid-data consideration — 2026-09-30

The operator prioritized the focused SPY/cash ETF research pilot, approved its
written specification and implementation plan, and retained native execution.
This supersedes options-only research priority, not options evidence, risk limits,
source qualification, broker/runtime gates or live authorization. The separate
[approved plan](superpowers/plans/2026-09-30-focused-etf-research.md) governs this
research identity; do not repurpose the historical four-ETF comparison.

The operator reports installing Massive and is willing to pay for a suitable data
account. Paid-provider evaluation is therefore no longer constrained to free-only
recommendations. No exact subscription, recurring total or applicable new agreement
has yet been selected or accepted. Verify useful coverage, account entitlement,
permitted automated use/retention and full cost before a purchase commitment;
the existing Databento credit-only acquisition grant continues independently.
The [provider comparison](etf-provider-comparison-2026-09-30.md) records public
coverage/prices and remaining issues. No subscription was purchased in this turn.

The operator then requested the most cost-effective qualification route, signed
in for read-only Alpaca plan inspection, and explicitly approved one support
inquiry about the displayed $99/month paper-only offer, historical SIP use,
private automated research, retention and original/corrected history. That inquiry
was sent in the existing support conversation. This does not authorize a paid
subscription, agreement acceptance, live-account opening/funding or brokerage
operation. No raw data, credentials or private account identifiers were sent.

## Continue implementation without waiting for support — 2026-10-01

The operator instructed the coordinator to continue building the bot regardless
of further Alpaca support responses and states that they intend to subscribe.
Support correspondence is not a prerequisite for credential-free implementation,
synthetic fixtures, offline replay, restart tests or report development. Continue
those approved tasks now; do not repeatedly pause them for provider clarification.

A subscription is not assumed active until observed. Once access exists, evaluate
the actual supported data against the approved source contract and retain explicit
limitations. Do not turn correspondence, subscription status or a successful API
request into verified coverage, point-in-time history, accepted economics or live
authority. Missing evidence limits the dependent claim or operation, not unrelated
development. This instruction does not authorize a purchase by the coordinator,
agreement acceptance, account funding, changed risk limits, deployment or orders.

The operator subsequently reported purchasing Algo Trader Plus. Record this as
user-reported subscription status, not account-bound access verification. Continue
read-only market-data access checks and the existing approved offline build; no
additional purchase, upgrade, broker write or live authorization is implied.

## Latest-vintage ETF research and uninterrupted build — 2026-10-01

The operator explicitly authorized the ETF study without the original publication
and correction timeline, and instructed the coordinator to finish the ETF bot with
the existing access without further setup questions. Continue the approved native
implementation, simulation, restart, reporting and read-only verification work.
Do not request the same authority again between tasks or merges.

For this research identity only, use immutable history as retrieved, explicitly
labeled latest-vintage. Retain retrieval timestamps and raw-response hashes;
never invent original publication or correction timestamps. This supersedes that
specific research prerequisite in the approved ETF specification, not other data
coverage requirements, executable quote semantics, cost calibration, objective
economic criteria, risk controls, paper/shadow elapsed-time gates or live authority.
Later corrections can affect historical signals; disclose that limitation in every
actual-data report. Exploratory results remain non-promotable and must not be
presented as point-in-time validation or expected live performance.

General build permission does not authorize real-money orders, live activation,
production credential use, deployment changes, a new paid service or higher risk.
Previously approved scoped read-only market-data/broker checks retain their scope.

## Continue building without hosted-matrix waits — 2026-10-01

The operator instructed the coordinator to proceed without waiting for GitHub
Python 3.12–3.14 quality checks because of their duration. Continue implementation
with focused local tests and review plus one local regression pass. Do not make
hosted-matrix polling a dependency of the next development task. This changes
development scheduling, not risk controls, truthfulness, required merge checks or
branch protections. It does not authorize bypassing a failed/missing check,
automatic research promotion, deployment or live trading.

## Alpaca-only ETF market data — 2026-10-02

The operator explicitly selected Alpaca as the sole market-data channel for the
ETF bot and said no additional data channels are needed. Continue the approved
native Alpaca build and read-only data work without pursuing another ETF provider,
subscription or Databento purchase. Earlier provider investigations remain a
historical record, not the active acquisition path. This instruction concerns
market-data sources; it does not silently change the execution broker.

Use documented Alpaca historical bars/quotes and, where separately implemented
and verified, its forward status/LULD/quote observations. Do not invent missing
historical controls, condition eligibility, customer costs or calibration. Keep
latest-vintage exploratory research separate from qualified execution/economic
evidence. A single-source choice does not waive safety, risk, reconciliation,
paper/shadow observation or live-authorization gates. No further provider purchase,
broker order, account change, deployment or live activation is authorized here.
