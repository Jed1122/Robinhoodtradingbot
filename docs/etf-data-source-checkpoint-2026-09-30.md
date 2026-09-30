# ETF data-source checkpoint — 2026-09-30

Status: **no qualified complete-history source selected; economic results unavailable**.
The operator prioritized a focused SPY-plus-cash research pilot while preserving
the options implementation, and approved the design brief, not live activation.

## Newly inspected provider reply

A read-only, narrowly scoped search found Alpaca's September 21 response to the
earlier paper-only Basic/free historical SIP, corporate-actions and private-retention
inquiry. The coordinator read that message on September 30. The response identifies
itself as automatically generated using AI. It is provider correspondence, not an
executed contract, human-reviewed legal opinion or independently verified API behavior.

Its stated position is:

- Paper-only accounts may use IEX data; the general older-than-15-minutes historical
  SIP access statement does not grant SIP entitlement to paper-only accounts.
- Corporate Actions Announcements history starts in April 2020. The reply reports
  no separately stated paper-only restriction, rather than confirming a complete
  account-specific entitlement and history.
- Personal, non-commercial historical retention is described as permitted within
  account entitlements and API limits. Redistribution or sharing with third parties
  is excluded. No exact applicable agreement version or retention expiry is supplied.

Consequently, the earlier question is no longer merely awaiting an uninspected
reply: the inspected reply expressly denies the proposed paper-only SIP route.
Do not use a technically successful SIP request to override that response. IEX is
not a silent substitute for consolidated-market coverage. No human follow-up,
subscription, funded-account change, agreement acceptance or data request was made.

The original email remains in the operator's mailbox. No mailbox identifiers,
headers, signatures, addresses, authentication material or full message bodies
are stored in this document or research fixtures.

Public context, not account entitlement:
[Alpaca market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq),
[paper-only documentation](https://docs.alpaca.markets/us/docs/paper-trading), and
[plan description](https://docs.alpaca.markets/us/docs/about-market-data-api).

## Remaining data decisions

The existing acquired XNAS SPY archive is a potential engineering input, not a
qualified 2016–2025 source. It begins in May 2018; documented bad/degraded rows,
availability/revision semantics, sessions and distributions remain unresolved.
Neither it nor an April-2020-starting corporate-actions feed satisfies the full
history by itself. No archive was re-imported or represented as newly verified here.

Freeze the ETF study specification first. Then select a permitted source or
compatible source package that supplies the unchanged history/observation span,
point-in-time actions, publication/correction evidence and execution inputs.
Source coverage and technical suitability must precede data spending. Existing
credit-only Databento authority does not authorize cash charges, subscriptions,
new agreements or blind acquisition before an exact useful package is defined.

Daily bars may support a clearly labeled exploratory screen. Genuine risk-aware
after-cost execution needs suitable bid/ask, liquidity/control information and
complete event coverage through exits and settlement. Missing data means NO-GO,
not zero costs, assumed fills or a shorter unreported evaluation period.

## Fresh broker and host checkpoint

Read-only `robinhood-2` calls succeeded for the Agentic account, account status,
options/equity order collections and options/equity position collections. Each
collection was empty and had no next page. The account was active, cash-type and
Level 2 options-approved. SPY was active and account-type/fractional tradability
was reported; no regular-session halt was reported by that lookup.

These are interactive, momentary observations. They do not establish nonempty
fill/fee/settlement parsers, minimum increments, fractional order-type support,
review/place/cancel behavior, idempotency or unattended runtime authentication.
No order review or write was called, and no account identifiers or balances are
stored here. Existing live blocks remain unchanged.

Read-only SSH inspection of the existing DigitalOcean service returned healthy
paused status (HTTP 200), readiness denial (HTTP 503: `paused`,
`external_capability_missing`), shadow mode and `trading_bot_live_enabled 0.0`.
The container was non-root UID/GID 10001, read-only, with zero mounts; its executing
image remained `sha256:1a259e1a559c2ecb2ae0277e8f7fa2733e7e9f0c2b90ff418f5baa1c527e9d25`.
This is the existing health-only image, not the current research/ceiling changes.
No credentials/environment values or ledger were read and no process was changed.
Renewal/revocation, restoration, fencing and real strategy-heartbeat proofs remain
unverified. A healthy paused process is not a paper/shadow promotion observation.

Next: review the [ETF specification](superpowers/specs/2026-09-30-focused-etf-research-design.md),
write its implementation plan, qualify an actual source, then obtain after-cost
results before qualifying paper and shadow operation. No profitability or launch
date is established by this checkpoint.
