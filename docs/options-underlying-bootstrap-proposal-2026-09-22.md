# Targeted Databento prerequisite: SPY underlying bars

Recorded 2026-09-22 UTC against `f5dc9351b3e31164be5b236f6444809650155621`.
Status: exact bars-only acquisition proposal, awaiting operator approval and final
cost/credit checks. **Not a complete options dataset or economic validation.**

## Recommendation and exact request

Acquire the following small underlying-data prerequisite before paying for option
quotes. Reuse the existing SPY definitions; do not buy them again. This proposal
advances the [targeted Databento decision](options-provider-decision-refresh-2026-09-22.md),
not the deferred durable-ledger implementation.

| Request field | Proposed value |
| --- | --- |
| Dataset | `XNAS.ITCH` |
| Symbol / input symbology | `SPY` / `raw_symbol` |
| Schema | `ohlcv-1m` |
| Start, inclusive | `2018-05-01T00:00:00Z` |
| End, exclusive | `2026-01-01T00:00:00Z` |
| Intended local encoding | Native DBN with its request metadata and symbol mappings; compressed storage |
| Portal estimate, refreshed around 23:46 UTC | **$0.89**, displayed rounded |
| Portal displayed size | **79.62 MB**; not a measured downloaded/compressed size |
| Proposed authorization ceiling | **$1 total from existing credits only**, no cash charge |
| Subscription, option quotes, live data | None |

The portal was set to OHLCV-1m, May 1, 2018 at 00:00 through December 31, 2025 at
24:00 UTC. The request above expresses the latter as the following midnight. The
estimate is not a locked checkout total or proof of entitlement. The encoding is a
proposed retrieval setting, not a setting verified by submitting a download.
[Authenticated SPY estimate page](https://databento.com/portal/catalog/us-equities/XNAS.ITCH/etf/SPY).

Do not also acquire the overlapping 2023–2025 bar request. Defer the earlier
$0.20 underlying BBO proposal: bid/ask is not an input to the shortlist, and sampled
BBO alone cannot establish original quote age. This deferral does not remove the
matching underlying-price/quote requirements of later economic testing.
[BBO timestamp and forward-fill semantics](https://databento.com/docs/schemas-and-data-formats/bbo).

## What this input can and cannot support

The intended reference is an **unadjusted Nasdaq-source regular-session last
trade**, explicitly labeled `source_last_trade`, not an official consolidated
close or national volume. XNAS.ITCH covers Nasdaq's exchange feed; the catalog
starts SPY history on 2018-05-01. This is a venue-specific research choice whose
limitations must remain in subsequent reports.
[Feed specifications](https://databento.com/docs/venues-and-datasets/xnas-itch),
[SPY catalog](https://databento.com/catalog/us-equities/XNAS.ITCH/etf/SPY).

Minute bars require a separately reviewed normalizer and verified regular-session
calendar before use as daily inputs. Their timestamps label interval starts;
no-trade intervals may be absent, and the vendor's daily schema uses UTC dates.
Do not expose completed bars at their start, invent availability or missing rows,
or treat a historical revision as what was necessarily visible in real time.
[OHLCV specification](https://databento.com/docs/schemas-and-data-formats/ohlcv).

The longer range preserves available warmup for the later 20/100-day research
hypothesis; it does not select a holdout or inspect option outcomes. It contains
only 2,802 calendar days and cannot establish the configured 3,650-calendar-day
history request. Actual usable regular-session bars have not been counted. The
750-bar minimum, five folds, 50 test bars per fold and 30 independent opportunities
remain unchanged wherever applicable. This input is not a qualifying study.

## Dependency inventory: bars alone do not unlock selection

Read-only source inspection confirmed:

| Dependency | Current status | Required before a genuine targeted option manifest |
| --- | --- | --- |
| Native option definitions | Raw decoding/staging exists | Resolve historical identity, update/delete state, availability, chain coverage and contract enrichment; raw hashes do not prove these |
| Underlying bars | This request is priced; no acquisition in this task | Native decoding, exact values, regular-session aggregation, coverage and defensible availability |
| Sessions | Synthetic fixtures exist | Verified historical holidays, early closes, DST and immediately preceding session |
| Corporate events | Canonical evidence types exist | As-of coverage, including evidence for an empty event list; no assumed absence of actions |
| Genuine shortlist | Imported inputs deliberately denied | Reviewed source-verification integration, without relabeling real data as synthetic |
| Option quote purchase | No exact selected-symbol request exists | Freeze candidates without outcomes, deduplicate symbol/time coverage through exits/expiry, then estimate suitable quote detail |

The existing selector rejects imported evidence in
[`options_shortlist.py`](../src/trading_bot/research/options_shortlist.py). Its
[`input models`](../src/trading_bot/research/options_shortlist_models.py) require
the close, calendar, action coverage, complete chain and canonical contracts.
The [native definition scanner](../src/trading_bot/market_data/databento_definitions.py)
explicitly leaves complete chains, historical availability and enrichment false.
No genuine prior-session SPY closes were identified in committed public fixtures.

Therefore the full targeted option price remains **unknown**, not $0.89 or the old
$1.09 underlying subtotal. Calendar/action sources, contract enrichment, applicable
reference-data costs and exit/settlement coverage remain unresolved. Native source
integration is a separate architectural milestone, not implemented by this proposal.

## Approval boundary and purchase stop conditions

Billing was rechecked around 23:47 UTC: **$113.57 remaining credits**, **$0.00 due**,
zero subscription plans/licenses, and usage-based access enabled with **no limit**.
No account, payment, credential or limit setting changed.
[Authenticated billing page](https://databento.com/portal/billing).

The requested approval is for this bars-only scope, up to $1 of existing applicable
credits, with no cash spending. Before submission, recheck the exact scope, final
price and usable credits. Stop if the total exceeds $1, credits do not apply, a
cash charge cannot be ruled out, access is denied, or new terms/license/subscription
acceptance is required. Approval must not be stretched into permission for those
changes. Check for an existing identical download before creating a duplicate.

The displayed credit balance is not a reservation or a hard spending cap. Databento
documents credit application and a usage limit that blocks requests after the limit
has been exceeded; neither an estimate nor such a limit guarantees this transaction's
maximum. If the credit-only conditions cannot be established, do not submit.
[Billing documentation](https://databento.com/docs/portal/billing).

Existing private-use/local-retention attestation is retained; this task does not
ask for a separate OPRA agreement. Acquired raw files, mappings and normalized
outputs must stay in owner-private storage outside Git/Cloud. No data is to be
shared with parallel agents.

## Verification and handoff

The temporary estimate selection was cleared and the portal confirmed **No products
added yet**. No Customize download submission, acquisition, credit spend, subscription,
broker operation, deployment or live activation occurred. Public documentation and
sanitized portal amounts supported the proposal; no credential contents were read.

A local read-only agent independently audited committed importer/shortlist interfaces;
the coordinator checked the decisive denial and unverified-definition flags. This was
not Cloud execution. Documentation checks cover local links, Markdown fences and
whitespace; product tests were not rerun because no product code changed.

Disposition: **bars-only proposal ready for operator decision; complete targeted
option package still blocked on the dependencies above; economic/live eligibility
unchanged.** All capital assumptions, risk limits and write-incapable defaults remain.
