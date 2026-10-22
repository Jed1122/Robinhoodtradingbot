# Bounded native stock filing-facts probe

Root-owned continuation of the authorized official individual-stock research work.
Base f378b6fc0f71cfde32ccdcae41a65feb316dbfe7. No account, order, control, deployment,
new-provider, subscription or live operation belongs to this source probe.

## Purpose and evidence discipline

The actual stock dossiers retain financial periods and broker filing indexes but
do not yet bind reported facts to a particular filing, currency or duration. The
pure SEC companyfacts parser is a separate declared profile without native evidence.
No currently retained stock dataset qualifies a stock-strategy study; ordinary
Robinhood bars retain unknown interpolation state, and that gate stays unchanged.

Use the existing saved dedicated research grant and pinned 13-tool stock-only
session/transport. Preserve provider text as untrusted data. Use the existing
private archive, schema, request, timeout, spacing and sanitized-error boundaries.
The grant remains trading-capable; the local research facades restrict these calls.

## Frozen selection and acquisition procedure

1. Rehash the previously committed 25-call enrichment capture through
   `read_stock_observations()`. Never print its contents. From valid filing-index
   observations for the previously shortlisted companies, select the alphabetically
   first company having a reported 10-K and select its most recent filed 10-K at or
   before the index receipt. Tie-break by exact filing ID. This is a data-schema
   calibration choice, not an investment selection or historical-universe claim.
2. Freeze one private job plan before connection: `get_sec_filing_facts_catalog`
   with that exact observed `filing_id` and `offset=0`. No guessed filing ID, concept,
   pagination completion or expected numeric value. Capture one page only.
3. Rehash the catalog receipt. Retain original concept names, text-block flag,
   periods, axes, count and pagination. Select at most ten unique actually returned
   non-text concepts having explicit empty axes, if available; sort exact names
   for deterministic selection. If no such concepts exist, stop and record missing
   evidence. A null axis list is unknown, not an explicit empty list.
4. Freeze a second private plan before connection: `get_sec_filing_facts` with the
   same filing ID and the selected exact concept names. Capture once without retries.
   Stop on authentication, schema, request, response or retention failure. No browser
   callback, credential-store replacement, fallback client or paid route.

The total budget is two sequential data calls. If the retained index is unsuitable,
stop rather than silently adding index/pagination calls. Each capture remains under
the existing 45-second per-call and 300-second job budgets. This is a bounded manual
source investigation, not a scheduled collector cycle or research-control resume.
Keep plans and results in a new owned mode-0700 directory outside all checkouts;
files are mode0600 and reports contain only sanitized hashes/counts/verdicts.

## Review and result

Bind index/catalog/facts argument identities, observed hashes and receipt timestamps.
Inspect native entity, period, axes, units, numeric/character values and missingness
without publishing payloads. Join only the exact broker filing ID. Do not equate it
with SEC accession, infer entity=CIK, parse arbitrary character text into a reported
numeric fact, infer units, flatten dimensions or choose a preferred accounting vintage.
Any combined availability is the latest contributing receipt, never the financial
period end or date-only filing metadata. One catalog page is incomplete if pagination
continues or its terminal status is unknown.

Record actual successful/failed call counts and sanitized observation/manifest hashes.
Then freeze an adapter/dossier contract against observed fields, or report that native
evidence is insufficient. No source/strategy/investment qualification or real-data
backtest is authorized by a successful capture. Price integrity, corporate actions,
security identity, chronological holdout, costs/taxes and statistical comparison
remain separate unmet requirements.
