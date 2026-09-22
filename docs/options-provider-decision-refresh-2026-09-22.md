# Options data-provider decision: refreshed priority and evidence

Recorded 2026-09-22 UTC against `01e2a8423668fef4bafcf7805eeb259a400ec988`.
Scope: provider selection, public documentation, existing-session billing observation
and free portal estimates. No acquisition, subscription or trading authorization.

## Decision

**Prioritize targeted Databento acquisition planning; retain ThetaData as fallback.**
This is the coordinator's recommendation from the evidence below, not proof that
Databento is the cheapest complete study or that either source qualifies an economic
result. No complete targeted request manifest or all-in targeted price exists yet.

The operator explicitly prioritized this decision over durable-ledger implementation.
Data preparation, exact request scoping and purchase comparison now come first.
The ledger remains necessary project work, but is not a prerequisite to comparing
providers. Its written plan remains unimplemented and pending review.

Do not buy the broad chain, repurchase existing definitions, start a ThetaData
subscription, or increase the trading balance on the strength of this comparison.

## Fresh Databento observations

The existing signed-in Billing page displayed **$113.57 remaining credits**, **$0.00
due**, zero subscription plans/licenses, and usage-based access enabled with no
limit. No billing setting, payment detail or credential was changed. The credit
observation is current for this check, not a reservation or an exact spending cap.

The SPY OPRA portal produced these displayed, rounded estimates. Dates are UTC,
start inclusive and end exclusive; the UI end date at 24:00 means the next midnight.

| Scope | Schema | Estimate | Displayed size | Interpretation |
| --- | --- | ---: | ---: | --- |
| Entire SPY chain, 2023-01-01 through 2026-01-01 | CBBO-1m | $396.34 | 212.78 GB | Refreshed earlier broad request; not recommended for purchase |
| Entire SPY chain, 2023-04-01 through 2023-07-01 | CBBO-1m | $28.54 | 15.32 GB | Fixed-calendar, post-feed-change cost comparison only |
| Same Q2 chain and period | CMBP-1 | $486.70 | 3.27 TB | Event-level comparison; not the targeted-contract price |

These are alternatives, not items to add together. The Q2 interval was chosen as
the first complete quarter after the documented feed change, without evaluating
returns; it is not an approved study split or sufficient exit/settlement coverage.
Sources: authenticated [Billing](https://databento.com/portal/billing) and
[SPY catalog estimate panel](https://databento.com/portal/catalog/opra/OPRA.PILLAR/options/SPY).
The temporary request selection was cleared; the portal showed no products selected.
No request was submitted and no licensed dataset was downloaded.

Databento supports free cost metadata before data requests. Estimates do not enforce
credit-only execution. Its documented usage limit blocks subsequent historical
requests after the limit is exceeded, so even configuring it would not establish an
exact transaction cap. [Cost metadata](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost),
[billing behavior](https://databento.com/docs/portal/billing).

## Compare equivalent data, not just headline prices

CBBO-1m is an interval sample. Its receive field labels the interval end; its event
field describes the last trade, and components can be carried forward. It does not
by itself establish original quote age or the intervening path. Do not relabel these
samples as fresh executable quotes. [BBO/CBBO schema](https://databento.com/docs/schemas-and-data-formats/bbo).

CMBP-1 contains consolidated top-of-book events with event and capture timestamps.
It is the event-level candidate to price when validating quote chronology under the
existing strict rules; it still does not prove a hypothetical order would fill.
[CMBP-1 schema](https://databento.com/docs/schemas-and-data-formats/mbp-1).

Databento documents that OPRA history before **2023-03-28** is subsampled, with no
CMBP-1, CBBO-1s or TCBBO for that earlier period. The old Q1 pilot therefore cannot
be treated as event-level validation. This is a source constraint, not authorization
to silently change the study dates or weaken evidence gates.
[OPRA feed specifications](https://databento.com/docs/venues-and-datasets/opra-pillar).

## ThetaData alternative

Official public pricing was rechecked, including the Stocks tab:

| Monthly retail product | Advertised price | Decision limitation |
| --- | ---: | --- |
| Options Value | $40 | Minute history; matching underlying entitlement not established as included |
| Options Standard | $80 | Tick-level option alternative; not within the earlier $40 subscription preference |
| Stocks Value add-on | $30 | Pricing says 15-minute intervals; subscription documentation says one minute |
| Stocks Standard add-on | $80 | Advertises minute stock history |

Options Value plus Stocks Value is $70/month; plus Stocks Standard is $120/month,
before applicable charges. These are advertised-price combinations, not verified
checkout totals or unavoidable minimum costs. A **hybrid** using Databento underlying
history and ThetaData options is possible to investigate; it must be priced and
validated, not ignored to make either vendor look cheaper. [Pricing](https://www.thetadata.net/pricing),
[subscription documentation](https://thetadata.net/docs/Articles/Getting-Started/Subscriptions.html).

Published subscription documentation lists Options Value history from 2020, while
marketing uses a four-year headline. Historical contract listing and quote endpoints
support dated contracts and interval bid/ask observations; this does not certify
every required SPY session or original quote-age semantics.
[Historical contracts](https://www.thetadata.net/docs/operations/option_list_contracts.html),
[historical quotes](https://www.thetadata.net/docs/operations/option_history_quote.html).

The subscriber agreement's sections 8(c) and 8(e) contain termination/deletion
requirements, including data and derived works. Accordingly, a one-month payment
must not be presented as permission to retain a permanent validation archive.
Applicable account terms and permitted continued retention need provider clarification
before relying on that approach. This records published provisions, not legal advice
or a determination about a specific account. [Subscriber agreement](https://www.thetadata.net/subscriber-agreement).

## Why Databento is the next path to scope

Existing credits, already-acquired definitions and implemented native staging/cost
diagnostics give it a practical starting advantage. We can investigate exact
contract/time requests without a recurring subscription or a second vendor's
retention uncertainty. That is not a claim that the final bundle fits the credits.
The prior operator attestation for Databento private use/local retention remains
accepted; no repeat request for a separate OPRA agreement is introduced.

The $1.09 Nasdaq-only underlying subtotal in the
[earlier preflight](options-underlying-data-preflight-2026-09-22.md) was **not refreshed
in this check** and is not a complete data budget. XNAS.ITCH SPY history is
venue-specific and starts in 2018, not national consolidated history or proof of the
longer applicable research window. Corporate actions/dividends, session enrichment,
normalization and source suitability remain separate inputs.
[SPY source catalog](https://databento.com/catalog/us-equities/XNAS.ITCH/etf/SPY).

## Next deliverable: purchase-ready request, not the full ledger

The subsequent [bars-only prerequisite proposal](options-underlying-bootstrap-proposal-2026-09-22.md)
freezes the first request at a refreshed $0.89 displayed estimate and seeks a $1
credit-only cap. It does not complete the targeted option manifest: native source
integration and calendar/action evidence are still missing. Nothing was acquired.

1. Resolve the minimum underlying input and its source semantics, warmup, sessions,
   corporate-event coverage and cost. Acquire nothing without exact separate approval.
2. Normalize the already-acquired native definitions and permitted underlying inputs
   into independently verified point-in-time records. The current shortlist's imported
   lane is deliberately denied; do not bypass it or relabel real data as synthetic.
3. Apply the approved fixed shortlist: one call and one put per eligible session,
   prior completed-session close, nearest strike, target 30-day expiry within 21–45
   days, deterministic ties and missing-input denial. Select before inspecting returns.
4. Produce a private, deduplicated symbol/time manifest including required exit and
   expiry follow-through. Quote minute screening and event-level validation separately;
   the current exact-symbol CLI only supports CBBO-1m, so CMBP-1 requires a reviewed
   estimate-only extension or verified portal requests. Never equate an example
   contract estimate with the full shortlisted study.
5. Present the full price and known coverage limitations, freshly checked credits,
   residual cash exposure, and a specific acquisition approval request. Reconsider
   ThetaData/hybrid only on equivalent coverage and confirmed retention semantics.

Keep the 3,650-calendar-day request, 750-bar minimum, five folds, 50 test bars/fold and
30 independent opportunities wherever applicable. A small engineering pilot cannot
replace them. No holdout outcome was examined or chosen in this comparison.

The remaining live gates are independent: genuine qualified economic evidence,
capital feasibility under unchanged limits, complete pretrade/lifecycle/reconciliation,
verified broker/account/runtime capabilities and explicit activation. At the retained
$100 assumption, 0.5% per-trade risk is $0.50; obtaining data does not enlarge it.

## Verification and disposition

Provider audit used official public sources; billing and estimates were read through
the existing browser session. A local read-only agent independently checked ThetaData;
it received no private account data or licensed files, and no Cloud job ran.
Only decision/priority documentation changed. Product code, risk configuration,
dependencies, deployment, broker state and live locks were unchanged. Documentation
checks are not product tests or economic validation.

Disposition: **Databento targeted path recommended; targeted acquisition not yet
purchase-ready; ThetaData fallback; economic/live eligibility unchanged.**
