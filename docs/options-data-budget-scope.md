# Lower-cost options data: scope and estimate record

Status: estimate-only; no acquisition authorization. Recorded 2026-09-22.
Implementation baseline: `c623ab2e63845b955a0a9c51ffb6f80a8192dcbe`.

## Decision and scope

Continue with Databento before considering another subscription. Existing SPY
definitions can be reused; do not buy them again. First prepare exact requests and
their estimates, not a broad $396.34 quote download. ThetaData remains a fallback
requiring a separate coverage, usage-rights and total-cost decision; no subscription
is approved. A lower data bill does not establish an economic edge.

At the planning baseline, the estimator supported parent option chains, not exact
option symbols or underlying prices. This document separates two deliverables:

1. **Completed now:** free metadata estimates for two fixed-calendar engineering
   pilots using the existing, tested diagnostic.
2. **Implemented and offline-verified:** bounded exact-symbol cost estimation using the same
   fixed free endpoint. This does not select a strategy, acquire data, or implement
   an underlying-data client. Its plan and verification record are
   [exact-symbol cost preflight](superpowers/plans/2026-09-22-exact-options-cost-preflight.md).

The operator approved this implementation plan after reviewing the estimates.
Approval covers the estimate-only software extension, not any quote purchase,
subscription, contract-selection strategy or live activation. See the
[preflight guide](databento-preflight.md) for the implemented command syntax;
the plan's completion record distinguishes verification from external evidence.

## Fresh estimates, not charges

Both requests used `OPRA.PILLAR`, `SPY.OPT`, `stype_in=parent`, `schema=cbbo-1m`.
All dates are UTC midnight, start inclusive and end exclusive. The earliest complete
calendar quarter covered by the supplied definitions was selected for engineering
scope, without examining strategy returns. No contract was selected using future
prices or observed profitability.

| Request | Quote coverage | Exact estimated USD | Quoted at UTC |
| --- | --- | ---: | --- |
| A | 2023-01-01 to 2023-04-01 | 29.655481874943 | 2026-09-22 19:05:58.048067 |
| B | 2023-01-01 to 2023-06-01 | 48.775968253613 | 2026-09-22 19:05:57.679052 |

These are **alternative, overlapping requests**, not two purchases to combine.
The displayed prices round to $29.66 and $48.78. The earlier full 2023–2025 estimate
was $396.336761265993; it was not refreshed in this continuation.

Request A could support January engineering entries with February–March available
for follow-through; B could support Q1 engineering entries with April–May available
for follow-through. That interpretation is conditional on a preregistered maximum
expiry/holding horizon of no more than 60 calendar days and verified sessions.
The scope does not change the configured strategy or create such a holding rule.
Longer or unresolved obligations require additional data, or an explicitly incomplete
episode. Never force a close at the last quote, drop an incomplete loss, or treat a
quote-coverage end as proof of settlement.

The last billing observation from the preceding continuation was $113.57 credits
and $0 due. **Billing was not refreshed here.** Both option-only estimates are below
that historical balance, but neither establishes current available credit or an
all-in budget. Underlying prices, warmup, actions/dividends, calendar information,
coverage repairs and any provider fees still need their own verified scope and cost.
Do not infer a $0 cash charge or guaranteed maximum from these estimates.

The diagnostic made two free GET requests to the fixed `metadata.get_cost` endpoint.
It did not call time-series or batch APIs. Its 68 credential/HTTP/CLI tests passed
immediately before those calls. No key, account identifier or market-data payload is
retained in this document. The portal draft created during scope inspection was
cleared; no request was submitted.

Databento documents free metadata access and estimates for specified symbols,
schemas and date ranges. Estimates are not spending controls or entitlement checks.
[Official metadata and cost documentation](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost).

## Exact-symbol estimator specification

Extend the existing `CostRequest`, never a parallel credential loader or client:

- Add `stype_in: Literal["parent", "raw_symbol"] = "parent"` as the final field.
- Existing parent mode stays one to four unique uppercase alphabetic roots of one
  to six characters, with `.OPT` appended only when constructing parent queries.
- Raw mode initially accepts one to 100 unique, exact, standard-format SPY option
  symbols: `SPY` plus three ASCII spaces, six ASCII expiry digits `YYMMDD`, uppercase
  `C` or `P`, and eight ASCII strike digits. The encoded date must be valid under
  the explicit 2000–2099 interpretation and the encoded strike must be positive.
- Raw mode supports only `cbbo-1m`. It must reject other roots, adjusted-root strings,
  wildcards, comma-separated input, duplicate symbols, invalid calendar dates,
  Unicode digits/spacing, newlines and mixed parent/raw representations.
- Preserve supplied raw symbols exactly: no stripping, padding, case conversion,
  expiry guessing or appending `.OPT`. Syntax is not proof of contract identity,
  deliverables, historical availability, entitlement or tradability.
- Dataset and endpoint stay fixed. No retries, redirects, environment proxies,
  downloading, batch submission, subscription or broker interfaces are added.
- Default CLI behavior remains a credential-free, network-free preview. Add
  `--stype-in {parent,raw_symbol}`; explicit network opt-in still permits only the
  free cost request. Estimate flags remain false for download authorization,
  verified entitlement and economic evidence, and credits remain unknown.
- Validation errors stay sanitized and do not echo arbitrary command arguments.
- No dependencies, runtime configuration, risk limits or production capabilities change.

## Research scope still needed before a quote purchase

Exact-symbol price support does not finish the research dataset. Before requesting
purchase approval, the coordinator must freeze these dependencies without inspecting
holdout outcomes:

1. Underlying SPY history with justified adjustment/availability semantics, enough
   warmup for the actual research gate, and matching timestamps for selection and
   exposure marking. No underlying provider or $0 price is assumed here.
2. Point-in-time symbol mappings and contract/session enrichment. Native definition
   `ts_recv` is not automatically a research availability timestamp; native expiration
   is not automatically a last-trading deadline. The existing archive's partial-symbol
   and missing/degraded-day disclosures remain unresolved.
3. An explicit candidate-selection rule, including direction, expiry, strike, ties,
   missing inputs and rejection reasons. The 20/100-day momentum signal alone does
   not choose an option. Near-the-money selection needs contemporaneously available
   underlying prices. Current prices, future survivors and profitable contracts are
   not valid selection substitutes.
4. Date partitions retaining every required observation through exit and economic
   settlement. De-duplicate overlapping symbol/time coverage before cost aggregation.
   Record immutable input identities, request hashes, exact Decimal estimates and UTC
   quote times in a private manifest. Keep raw licensed data out of Git and Cloud tasks.
5. One complete acquisition proposal with separate costs for every required input,
   a freshly checked credit balance and an explicit credit-only maximum for approval.
   Re-estimate changed or stale scopes. Any cash spending, subscription, access grant
   or new terms require separate direction.

The existing operator attestation covers private automated historical use and local
retention. Do not request a separate OPRA agreement again. It remains an attestation,
not independent entitlement verification; access denials must not be bypassed.

## Evidence and live-trading boundaries

A pilot is pipeline and replay evidence, not a shortened final study. Preserve
`history_calendar_days=3650`, `minimum_history_bars=750`, five walk-forward folds,
50 minimum test bars per fold, and 30 minimum independent opportunities wherever
applicable. The definition archive's 752 receive dates do not satisfy any of these
underlying-history or effective-sample requirements. Neither pilot nor a three-year
quote subset is automatically sufficient for final validation.

Keep holdouts untouched and report incomplete/unqualified research honestly. Account
capability, standalone runtime authentication, production lifecycle readiness and
operator authorization remain separate from economics. The $100 capital assumption,
$150 live ceiling, 0.5% per-trade limit ($0.50 at $100) and non-replenishing $50 trial
loss ceiling are unchanged. No contract may be admitted solely because data is cheap.

No data purchase, subscription, broker operation, deployment change or live activation
occurred. `ECONOMIC_NO_GO` and live locks remain in force. This document recommends
pricing the narrower complete study before deciding whether a pilot is worth buying.
