# Databento acquisition: decisions before spending credits

2026-09-18 local date. The operator reports $125 unused credit. Prior free authenticated
metadata estimates are recorded in [the preflight guide](databento-preflight.md).
The observation/expiry implementation made no authenticated requests. The subsequent
acquisition continuation refreshed one free definition-cost estimate as recorded below;
no history was downloaded and no credits were spent. The replacement key remains private.

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

The free diagnostic does not expose current billing credits. The official billing
page redirected to sign-in in the in-app browser; two native Safari access attempts
timed out without reading the existing session. A Databento sign-in tab was opened
for operator handoff. No login credentials were requested in chat, no account settings
were changed, and no acquisition was submitted. Next: operator signs in, inspect
remaining eligible credits and the exact definitions request, then acquire only if
the approved credit-only/cost conditions hold. No separate OPRA agreement is pending.

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
