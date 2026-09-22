# Databento acquisition: decisions before spending credits

2026-09-18 local date. Before acquisition, the authenticated billing page confirmed
$125 unused credit and $0 balance due. Prior free authenticated
metadata estimates are recorded in [the preflight guide](databento-preflight.md).
The observation/expiry implementation made no authenticated requests. The subsequent
acquisition continuation refreshed one free definition-cost estimate as recorded below.
After scoped operator approval and browser sign-in, one $11.44 definitions request was
submitted and accepted as queued. On September22 the operator supplied the completed
download; local receipt and native staging are now verified as recorded below. Final
charge remains unverified.
The replacement key remains private and was not read during the browser submission.

During this continuation the operator confirmed that Databento permits the account's
private automated historical OPRA research/trading and local retention. This is recorded
as **operator-attested**, not a separately inspected license document or provider API
entitlement. It is not spending approval or permission for redistribution/Cloud access.

## Current decision

The operator subsequently instructed us to proceed without obtaining a separate
OPRA agreement document. Proceed on the existing operator attestation of permitted
private automated historical use and local retention; requesting another agreement
or support reply is **not a prerequisite**. This changes the documentary requirement,
not actual provider restrictions or the distinction between attestation and independently
verified entitlement. Do not mark `download_entitlement_verified` true, bypass provider
access denials, accept new terms, buy a subscription or share raw data with Cloud agents.
Spending authorization remains a separate decision.

Do not download broad SPY option quotes: the observed 2025 `cbbo-1m` estimate was
$141.845587790012, and the 2023-2026 estimate was $396.336761265993. Both exceed the
reported credits before underlying data or other inputs. The three-year definition
estimate was $11.435879766941. Estimates are neither confirmed credit balances nor
hard spending caps. [Databento cost-estimation documentation](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost).

A narrower candidate procedure is definitions first, then frozen exact-contract and
date partitions, then a fresh estimate for each quote request. Databento documents
option identities and definition retrieval; this is not evidence that the selected
scope will fit $125 or meet research requirements. [Official options example](https://databento.com/docs/examples/options/equity-options-introduction).

Before acquisition:

1. Record the operator's existing private-use/local-retention attestation and instruction
   to proceed without a separate agreement. Do not infer additional sharing, perpetual
   post-termination use or fee exemptions from it. If acquisition requires a new agreement,
   fee or access grant, stop for the operator; do not circumvent the provider's controls.
   No raw data is to be sent to Cloud agents or redistributed.
2. Freeze the contract-selection rule and development/validation/final-test split before
   examining outcomes. Use definitions and information available at the decision time.
   Do not shorten evidence requirements or select favorable contracts to force a GO.
3. Estimate the complete package: definitions, selected bid/ask quotes, underlying
   history, calendar and corporate-action/dividend coverage. Preserve exact request
   parameters, valid symbology intervals, timestamps and hashes. A record limit truncates
   evidence; it is not an independent dollar-denominated spending guarantee.
4. Present an explicit acquisition amount and credit-only/cash-spend policy for approval.
   Recheck balance and request estimates immediately before any authorized download.
   Scope changes need new estimates and approval. Preserve a margin for uncertainty.
5. After an authorized acquisition, validate completeness/provenance and retain raw
   hashes and usage-rights records. Only then run the frozen research procedure.

Only the definitions-only acquisition described below is now authorized, up to $12
of existing credit and no cash spending. The private-use/local-retention attestation
is not independent verification of the account's OPRA terms or additional charges.

## Definitions-only proposal — refreshed 2026-09-19 00:45:38 UTC

One successful free `metadata.get_cost` call returned **$11.435879766941** for
`OPRA.PILLAR`, parent `SPY.OPT`, schema `definition`, from `2023-01-01T00:00:00Z`
inclusive to `2026-01-01T00:00:00Z` exclusive. This is the same estimate as the prior
check, not a bill or a verified credit balance. The existing diagnostic's 68 tests
passed before the request; its credential is read only internally and never printed.

The operator explicitly approved **at most $12 of existing credit**, definitions
only, no cash charges, subscriptions, quotes or live data. This approval is confined to
the exact scope above; do not ask for the same approval again unless its conditions
change. Stop if credit coverage or the cost conditions cannot be established. Definitions
support point-in-time contract identity/selection; they contain no bid/ask execution
history and cannot alone establish economic evidence. No historical downloader is
implemented in the existing cost-only diagnostic; an acquisition path still needs
implementation and verification before use, or the official portal can be used under
the same authorization after verifying its request and credit conditions.

The initial browser sign-in blocker was resolved by the operator. The authenticated
billing page showed $125 remaining credits and $0 due before submission. No login
credentials were requested in chat, and no account settings were changed. No separate
OPRA agreement is pending.

## Accepted portal request — 2026-09-19 00:53 UTC

The official portal accepted one request showing **$11.44**, below the approved $12
credit-only cap. Request details confirm `SPY.OPT`, Definition, DBN/zstd, direct
download and `[2023-01-01 00:00 UTC, 2026-01-01 00:00 UTC)`. Optional file splitting
is off; the portal showed four output files. At that time the verified portal state was
**Queued**. The later local download validation below supersedes the pending-file status,
not the last portal observation. Do not create a duplicate request or purchase another
format. Final billed cost and post-acquisition credits remain unverified.
While the job remained queued, a subsequent billing-page check still showed $125 in
credits and $0 due. That is not evidence that the accepted request is free; final
accounting is pending.

The request identifier and exact acquisition details are stored in a private receipt
outside Git under the existing private research directory, not in a Cloud task or
tracked artifact. No payment-method details, API keys or provider payloads are stored
in this guide. No subscription, quote data, live data or broker action was requested.

## Supplied local download — 2026-09-22

The four supplied files match the exact approved request and provider-listed sizes/hashes.
The source download is unchanged; a verified no-overwrite private copy is retained outside
Git. Complete Zstd/DBN validation found **6,821,768 native definition records**, spanning
**752 receive dates**, with **224,696 distinct raw symbols**. Distinct symbols are not
asserted to be permanent unique contracts or executed trades. Native staging contains
**1,433 content-addressed Parquet parts**, **355,875,960 bytes**, plus its private manifest.
An independent decompressed-byte calculation agrees exactly with the record count:
`(2,657,756,012 - 201,919,532) / 360 = 6,821,768`.

The provider metadata contains 217,732 partial-symbol declarations; its conditions list
779 available,2 degraded,3 missing dates. These are retained limitations, not proof of
which eligible trading sessions are missing. Mapping conflict resolution, historical
availability, complete chains and canonical contract enrichment remain unverified.
No quotes, underlying prices or strategy returns are in this definitions archive.

The reviewed [offline importer](databento-offline-import.md) is now implemented with pinned
decoders, synthetic no-network tests and private hashed Parquet snapshots. It does not
change risk limits, grant economic evidence, unlock a broker or permit live trading.
No credential, provider request, account inspection or additional spending occurred during
local import. The final charge remains unknown; do not infer it from the estimate or from
successful downloading.

Next data work: resolve definitions point-in-time with verified contract/session enrichment,
freeze admissible selection and existing research splits, then estimate the required quote,
underlying and event-data scope. Quotes or additional inputs need separate approval before
acquisition. Existing evidence-duration/sample requirements remain unchanged. Definitions
alone cannot establish trading performance or promotion eligibility.

## Supplied terms review — 2026-09-18

The attached document is **Website Terms of Use**, effective January 31, 2024, not
an OPRA entitlement or account-specific support reply. It directs data users to the
User Agreement and applicable third-party terms. No private portal or credential was
accessed for this review.

The public [User Agreement](https://databento.com/legal/databento-user-agreement)
grants conditional internal use in section 1.1; section 1.5 also requires compliance
with provider-specific terms. Section 9.3 ends rights to access or use third-party
data on termination. Sections 3.3–3.5 describe historical-service credits, possible
expiry and exclusion of live data. These provisions do not establish this account's
OPRA permissions or indefinite retention/use rights.

The public [Exchange Data Policy](https://databento.com/legal/exchange-data-policy)
currently addresses CME non-professional data, not OPRA. CME conditions must not be
applied to OPRA by analogy. These are historical review findings, not an outstanding
request for another document after the operator's later instruction above. No extra
subscription or exchange fee is presumed either necessary or waived.

## Optional support question (not sent; no longer an acquisition prerequisite)

“I plan to use historical OPRA.PILLAR instrument definitions and bid/ask observations
for my own private automated options research and eventual personal trading. There
will be no client service, redistribution, public dashboard or raw-data access by
Cloud agents. Please confirm which historical/non-display permissions and fees apply,
whether my introductory credits cover the approved requests, and the rules for local
retention, encrypted private backups and derived research results after account closure.”

Buying data, authenticating successfully, or obtaining a positive replay result does
not establish an economic edge. The project remains `ECONOMIC_NO_GO` pending adequate
real-data out-of-sample evidence and cost/uncertainty analysis.
