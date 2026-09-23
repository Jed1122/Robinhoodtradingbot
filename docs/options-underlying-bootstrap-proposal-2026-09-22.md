# Targeted Databento prerequisite: SPY underlying bars

Recorded 2026-09-22 UTC against `f5dc9351b3e31164be5b236f6444809650155621`.
Status: operator-approved package acquired; completed job shows $0.89, credits
decreased by $0.89 and amount due remains $0.00. Local receipt/integrity checks
passed; native semantic normalization remains unimplemented as recorded below.
**Not a complete options dataset or economic validation.**

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

## Approved acquisition — 2026-09-22 23:53 UTC

The operator explicitly approved the exact bars-only package above, with a $1
existing-credit ceiling, no cash charge and no subscription. This approval does
not cover option quotes, BBO, repeat requests, different symbols/dates or live data.

Before submission, the complete Download center listing showed no matching SPY
bars job. Fresh billing showed $113.57 credits, $0.00 due and zero subscription
plans/licenses. The customized Data request page quoted **$0.89** for the exact
OHLCV-1m scope, DBN/zstd, direct download, no optional splitting and four output
files. No new license, terms, payment or subscription step appeared.

Databento distinguishes the customized request-page quote from the catalog
estimate and states that applicable historical-data credits apply before charges.
The fresh credit balance exceeded the quote and the approved ceiling. This is
the pre-submission basis for credit-only acquisition, not a claim that the account
has an enforced spending cap. [Official pricing/credits FAQ](https://databento.com/docs/faqs/usage-pricing-and-data-credits).

Exactly one Submit request action produced an accepted confirmation. The existing
job's detail panel confirmed `OHLCV-1m`, DBN/zstd, direct download and
`[2018-05-01 00:00 UTC, 2026-01-01 00:00 UTC)`, with status **Queued**. Its private
request identifier and receipt are retained outside Git/Cloud in the owner-private
research directory. Do not resubmit or use Start duplicate request.

The first post-submission billing check still showed $113.57 credits and $0.00
due. That does not establish a free request or a final charge; billing remains
pending. Files have not yet been retrieved or validated. Retrieve the existing
job's files when ready, preserve metadata/conditions/provider hashes privately,
and verify final billing without starting a new request.

The earlier estimate-only observations above remain historical. This section
supersedes their no-acquisition status, not the source/economic limitations.
No broker call, code/config change, deployment or live activation occurred.

## Completed delivery and credit accounting — 2026-09-22/23 UTC

Around 23:56 UTC the same job became **Ready**, showing a completed cost of **$0.89**,
79.6 MB billing size and four downloadable files totaling 25.6 MB. The portal's
job-specific expiry display was recorded privately; do not infer a UTC deadline
from its unlabeled local display. Download all was invoked once for this existing
job. No duplicate batch or streaming request was made.

The downloaded ZIP is 25,560,016 bytes. A no-overwrite private copy and its four
extracted files are retained outside Git/Cloud. Checks confirmed:

- ZIP integrity and the complete Zstandard stream, decompressing to 79,656,090 bytes.
- Exactly the three provider-manifest-listed files plus the manifest itself;
  all three listed sizes and SHA-256 values match.
- Metadata matches SPY, `XNAS.ITCH`, `ohlcv-1m`, `raw_symbol`, the approved UTC
  bounds, unlimited record count, DBN/zstd and unsplit direct delivery.
- Source ZIP and private copy have identical SHA-256 values. Storage directories
  are 0700; archive, receipt and extracted files are 0600. The initial per-file
  permission check caught extractor-default 0644 modes inside the private directory;
  those new files were restricted to 0600 and the full check then passed.

The provider condition file declares **1,999 available dates and 3 degraded dates**.
These are provider status entries, not verified regular-session counts or a clean
data-quality verdict. Native OHLCV record validation, gap analysis, session
aggregation, availability/revision semantics and strategy evaluation have not run.
No market returns or holdout outcomes were evaluated.

After completion, billing displayed **$112.68 remaining credits**, **$0.00 due** and
zero subscription plans/licenses. The displayed credit deduction is exactly **$0.89**,
matching the completed job's displayed cost and remaining below the $1 authority.
This verifies current portal accounting to cents, not an exact API cost or a
month-end invoice. No cash payment, subscription or billing-setting change occurred.

The request ID, provider hashes and detailed receipt stay private; only sanitized
scope, aggregate verification and accounting findings are recorded here. Product
tests were not rerun: no product code, configuration or dependencies changed.

Current disposition: **approved underlying-bars acquisition complete and byte
integrity verified; native source integration and the exact option-quote package
remain unfinished; economic/live eligibility unchanged.**
Final receipt verification was recorded at 2026-09-23 00:00:06 UTC.
