# Official Robinhood options capability boundary

Evidence reviewed on **2026-09-18 UTC** against repository baseline
`dde6e4610d951502b3fc5846f4fe518a897b2dcc`.

This document is an operator/developer boundary, not a readiness claim. The audit inspected
official public Robinhood and FINRA documentation and current-session tool declarations only.
No Robinhood tool or authenticated interface was invoked. No account number, permission,
position, order, quote, credential, or provider response was read.

`OPTIONS_LIVE_SUPPORTED=false` must remain the default.

## Four independent verification dimensions

These dimensions are independent and must never be promoted by inference:

| Dimension | Current state | What it establishes |
|---|---|---|
| `PUBLICLY_DOCUMENTED` | yes | Robinhood documents its official Trading MCP endpoint, ten named options tools, interactive client setup, Agentic-account boundary, settlement behavior, and expiration practices. FINRA documents the intraday-margin transition. |
| `SESSION_DISCOVERED` | partial | Current-session declarations expose nine of the ten named options tools and typed request/result contracts. Declaration presence is not tested behavior. |
| `ACCOUNT_VERIFIED` | **no** | No account was read. Agentic eligibility, options level, account type, buying power, product access, positions, and order permissions are unknown. |
| `RUNTIME_VERIFIED` | **no** | No unattended authentication, renewal, restart recovery, daemon connectivity, rate limit, request, response, order, or reconciliation behavior was tested. |

Public documentation does not prove session availability. Session declarations do not prove
account entitlement. Interactive connectivity does not prove unattended runtime support.

## Public and session-discovered tools

Robinhood documents the official Streamable HTTP endpoint as
`https://agent.robinhood.com/mcp/trading`.

| Options tool | Public docs | Session declaration | Boundary |
|---|---:|---:|---|
| `get_option_level_upgrade_info` | yes | **absent** | Do not invent a call. |
| `get_option_historicals` | yes | present | Schema metadata only. |
| `get_option_chains` | yes | present | Schema metadata only. |
| `get_option_instruments` | yes | present | Schema metadata only. |
| `get_option_quotes` | yes | present | Schema metadata only. |
| `get_option_positions` | yes | present | Requires account evidence. |
| `get_option_orders` | yes | present | Requires account evidence. |
| `review_option_order` | yes | present | Exactly one leg. |
| `cancel_option_order` | yes | present | Acceptance is declared asynchronous. |
| `place_option_order` | yes | present | Exactly one leg. |

The review/place declarations describe only single-leg Level 2 structures: long calls/puts,
covered calls, and cash-secured puts. They explicitly say multi-leg structures are not supported
by this MCP, including for Level 3 accounts. Never substitute independently submitted legs for a
spread, condor, butterfly, or other complex order.

The declaration guide refers to `replace_option_order`, but no such tool is present in the
session or Robinhood's public options-tool list. No native cancel-replace capability may be
assumed. No exercise, DNE, assignment-event, expiration-event, settlement-event, authenticated
streaming, or broker websocket tool was discovered.

## Declaration-only schema observations

Every item below is an untested assumption derived from current-session declaration metadata:

- `get_option_chains` declares chain identity, expirations, `min_ticks`, multiplier,
  AM/PM settlement indicator, late/extended-hours state, and
  `sellout_time_to_expiration`.
- `get_option_instruments` declares paginated contract identity, expiration, strike, type,
  state, tradability, `min_ticks`, underlying type, and per-contract `sellout_datetime`.
- `get_option_historicals` declares UTC OHLC bars, session labels, interpolation flags, interval,
  and unresolved IDs. It declares no volume field for bars.
- `get_option_quotes` declares results pairing a timestamped quote with an optional official
  close. Quotes include bid/ask, sizes, mark, Greeks, volume, and open interest; close lookup may
  fail separately.
- `get_option_positions` declares quantities and separate pending buy, sell, exercise,
  assignment, and expiration quantities.
- `get_option_orders` declares pagination, legs/executions, partial quantities, source,
  type/trigger, TIF, market-hours label, and states `queued`, `confirmed`, `partially_filled`,
  `filled`, `rejected`, `cancelled`, `failed`, `voided`, and `pending_cancelled`.
- `review_option_order` declares exactly one leg and returns echoed intent, quotes, arbitrary
  alert details, and optional fees/collateral. It declares no durable review ID, expiry, or token.
- `place_option_order` declares exactly one leg and an optional UUID `ref_id`, described as an
  idempotency key. It does not accept a review token. Provider idempotency and review-to-place
  binding are unverified.
- `cancel_option_order` declares `accepted: boolean`. Acceptance is not final cancellation;
  a later read must distinguish pending cancellation, cancellation, and a raced fill.

The declarations mention limit, market, stop-limit, and stop-market orders plus regular/CURB
session labels. Schema availability is not authorization to use them. Ordinary automated entry
must remain limit-only under project policy. Tick values, quote timestamps, sellout timestamps,
alerts, order states, and pending quantities are provider-controlled inputs and must be parsed
strictly and rejected when missing, stale, malformed, or inconsistent.

## Public operating facts that are not API guarantees

- Robinhood documents interactive setup and desktop authentication for Agentic accounts, but the
  reviewed pages do not document a supported unattended daemon OAuth flow, refresh-token
  lifetime, renewal contract, revocation behavior, or DigitalOcean support. Never copy an
  interactive credential into a daemon.
- Robinhood says an agent can place trades only in an Agentic account. Cash Agentic accounts must
  wait one business day for proceeds from closing stock/options positions to settle; limited
  margin permits trading with unsettled funds. Margin borrowing is not currently enabled for
  Agentic accounts.
- Robinhood may attempt to close expiring at-risk stock/ETF options, generally beginning at
  3:30 PM ET or 3:45 PM ET for late-close products, and may act outside the last 30 minutes.
  This is possible intervention, not guaranteed protection. The standard process does not apply
  to index options.
- Robinhood documents automatic exercise rules, early assignment risk, after-hours moneyness
  changes, and app/web/support workflows for exercise and DNE. DNE requests have a documented
  5 PM ET cutoff, but no programmatic DNE or exercise route was discovered.
- Most equity/ETF options trade 9:30 AM-4 PM ET; some late-close products trade to 4:15 PM ET,
  and Robinhood currently lists selected index-option trading to 5 PM ET. Eligibility can change;
  never hard-code a static symbol list.
- FINRA states its new intraday-margin rules became effective 2026-06-04, with broker-dealer
  transition permitted through 2027-10-20. A firm may still use old PDT rules during transition
  or migrate earlier. Robinhood's current per-account regime is not publicly established and
  must remain `unknown` until verified.

## Prioritized credential-free contracts

These contracts can be implemented and tested using synthetic, value-free fixtures and injected
fake transports. They must retain `SESSION_DISCOVERED` provenance and must not be presented as
authenticated captures.

1. **Fail-closed response parsers.** Parse exact built-in types, decimal strings, UTC timestamps,
   nullable arrays/items, opaque IDs, declared order states, pending lifecycle quantities,
   `min_ticks`, `updated_at`, and `sellout_datetime`. Reject unknown enums and malformed values.
2. **Safe pagination and transport envelope.** Accept only the declared result envelope, extract
   cursors from expected Robinhood origins, reject redirects/origins outside the allowlist, and
   ensure parser errors never expose provider payloads or secrets.
3. **Single-leg request validator.** Require exactly one leg, positive integral quantity,
   supported side/position-effect combinations, valid tick-aligned limit prices, and explicit
   account binding. Reject a second leg and every attempt to leg into a complex position.
4. **Review/place equality contract.** Canonicalize the locally approved intent and require exact
   equality of account, contract, side, position effect, ratio, quantity, order type, TIF,
   session, price, and stop price before a fake placement. Treat the missing provider review
   token as an unresolved external gap.
5. **Idempotency and ambiguity contract.** Persist a synthetic logical intent and `ref_id` before
   fake submission; reuse it only for the same logical request. An ambiguous fake response must
   halt new exposure until reconciliation, never trigger blind resubmission.
6. **Order/cancel lifecycle contract.** Model partial fills and `pending_cancelled` separately.
   A cancel acceptance must not release exposure or reservations until a subsequent reconciled
   terminal state proves the outcome.
7. **Freshness and expiration contract.** Reject stale quotes and missing/stale/inconsistent
   intervention timestamps. Treat public closeout times and declared `sellout_datetime` as risk
   inputs, never as a promise that the broker will close a position.
8. **Margin-transition contract.** Test `old_pdt`, `new_intraday_margin`, and `unknown`; default to
   `unknown` and block affected live actions. Do not infer the regime from the calendar.

Fake transports must have no authentication path, no network fallback, and no order-changing
side effects.

## External prerequisites for any future live evaluation

Keep these outside credential-free parser work:

- Operator-approved Agentic account identity and proof of `agentic_allowed` status.
- Account-specific options level, cash/limited-margin type, settlement state, buying power,
  permissions, and current FINRA transition regime.
- Supported unattended authentication and renewal documented by Robinhood for the intended
  runtime, with least-privilege storage, revocation, and restart procedures.
- Sanitized authenticated response-shape evidence for every required read, plus verified quote
  entitlement, latency, pagination, product coverage, tick rules, fees, collateral, and rate
  limits.
- Separately authorized micro-live verification of review, placement, idempotent retry,
  ambiguous-response reconciliation, cancellation/fill races, and final-state reads.
- A supported path to observe or control exercise, DNE, assignment, expiration, settlement, and
  broker intervention. Missing critical lifecycle support blocks dependent live strategies.
- Current capability evidence with expiry/revalidation rules, successful reconciliation, risk
  self-tests, operator authorization, and all ordinary live gates.

Until every affected prerequisite is independently satisfied, live options execution remains
blocked. No official public evidence reviewed supports a hypothetical options REST adapter; do
not invent one or use unofficial endpoints, browser automation, scraping, captured cookies, or
password automation.

## Dated primary sources

Retrieved `2026-09-18` UTC:

- Robinhood, [Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)
- Robinhood, [Trading with your agent](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
- Robinhood, [Options Knowledge Center](https://robinhood.com/us/en/support/articles/options-knowledge-center/)
- Robinhood, [Options trading hours](https://robinhood.com/us/en/support/articles/options-trading-hours/)
- Robinhood, [Expiration, exercise, and assignment](https://robinhood.com/us/en/support/articles/expiration-exercise-and-assignment/)
- FINRA, [SR-FINRA-2025-017](https://www.finra.org/rules-guidance/rule-filings/sr-finra-2025-017)
- FINRA-hosted SEC [approval order, Release No. 34-105226, dated 2026-04-14](https://www.finra.org/sites/default/files/2026-04/SR-FINRA-2025-017-91-FR-20731.pdf)
- FINRA, [Understanding the New Intraday Margin Requirements](https://syndication.finra.org/content/understanding-new-intraday-margin-requirements)
- FINRA, [Rule 4210 interpretations](https://www.finra.org/rules-guidance/guidance/interps-4210)
