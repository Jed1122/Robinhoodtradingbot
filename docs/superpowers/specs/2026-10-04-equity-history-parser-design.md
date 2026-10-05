# Declaration-bound equity order history

## Purpose and boundaries

Implement a credential-free parser for supplied Robinhood-2 equity-order pages. This is the next independent prerequisite for private cost reconciliation, not an authenticated adapter, economic acceptance, paper promotion, or permission to trade. Standing native implementation/integration authority applies; there are no broker calls, credentials, purchases, deployment changes, or risk changes.

Use the exact current `mcp__robinhood_2__get_equity_orders` declaration, preserved in `src/trading_bot/brokers/schema_snapshots/robinhood_2_equity_orders.declaration.txt`. Its SHA-256 is `ee8c4019da683b7bfd56ff62ad20f0cf1d3d4080f3baa5f6f785a50a218fd470`. Do not mix the older namespace's URL-cursor semantics or modify the authenticated empty-only shape pin. Positions need a separate future contract.

## Input and immutable output

`EquityHistoryRequest(account_fingerprint, filters=())` binds a lowercase 64-hex fingerprint and a sorted tuple of unchanged filters. Allowed keys are `created_at_gte`, `order_id`, `placed_agent`, `state`, `symbol`; account numbers and cursors do not appear in filters. Filters are exact, bounded strings; duplicate/unknown keys fail. Creation lower bounds are not execution coverage bounds.

`parse_equity_orders_page(body: bytes, *, request, requested_cursor: str | None, received_at_ns: int, declaration_sha256: str) -> EquityOrdersPage` parses a bounded duplicate-free JSON envelope. The output keeps original body hash, request hash, declaration identity, UTC receipt, provider event nanoseconds, source order, decimal spelling, optional presence, and opaque continuation. It never has network/file side effects. Repr must not expose record data.

Only exact declared fields are accepted. `data` and `guide` are required; `orders:null` and null rows are unsupported inputs, not empty history. `next` is omitted or a nonnullable string (empty is terminal). All 20 required order fields and five required execution fields must exist; optional `ref_id` and `reject_reason` are nonnullable strings. `executions:null` remains unknown, distinct from an empty tuple. Dollar amount remains separate from nullable requested shares; no division-based share inference.

Financial strings use unsigned fixed-point grammar: no floats, signs, exponents, whitespace, leading-zero ambiguity, NaN/Infinity or coercion. Maximum 20 integer digits and 18 fractional digits. Preserve trailing zeros in Decimal. Prices, requested/fill quantities and dollar amount must be positive; cumulative quantity and fees may explicitly be zero. RFC3339 timestamps require `Z` or `+00:00`, preserve up to nine fractional digits without truncation, and remain bounded to nonnegative signed-64-bit nanoseconds. Reject future provider event times relative to receipt and events before order creation. No submission, acknowledgement, settlement, local monotonic time or latency is inferred.

UUID order/instrument/execution IDs must be canonical lowercase UUID strings. Source and optional/free-text strings are bounded and never included in errors. Unknown states (including declaration-discrepant `confirmed`) are retained with a semantic issue, never mapped to a domain state. Known output states are precisely the output declaration list. Type/trigger/time-in-force/market-hours/side use declared allowlists. No buy=entry/sell=exit or `ref_id`=strategy-ownership inference.

## Internal consistency, not reconciliation qualification

Deduplicate exact execution redelivery by native execution UUID within an order and count deliveries. Conflicting reuse fails; distinct IDs with identical economics count separately. Use exact bounded Decimal sums independent of ambient context. Compare unique execution share and regulatory/clearing-fee sums with cumulative values; preserve mismatch issue codes. Nullable executions, requested-share excess, filled/requested mismatch, missing average after fills, and contradictory price/trigger facts deny internal consistency. Do not impose exact VWAP equality because upstream rounding is unspecified. Preserve explicit charges on a zero-fill order without making a fill sample.

`assemble_equity_order_history(pages: tuple[EquityOrdersPage, ...]) -> EquityOrderHistory` accepts 1–128 pages, max 2,000 orders/page, 2,000 executions/order, 1 MiB/page, 16 MiB total and 20,000 unique orders/executions per chain. Reparse retained bytes at the assembler boundary so mutated/hand-built page summaries cannot alter evidence. First cursor is absent; subsequent cursor must exactly equal the previous nonempty next; unchanged request/declaration identity, nondecreasing receipts, no cursor loops, and a terminal final page are mandatory. Exact duplicate order deliveries deduplicate/count; changed order UUID snapshots or cross-order execution UUID reuse fail. A terminal supplied chain establishes supplied-chain completeness only, not account or execution-history completeness.

Rows must also match each explicit request filter; single-order mode permits at most one row. These checks reject mismatched supplied evidence, not attest actual transport arguments or account identity. Original declaration metadata is hashed without the storage file's added terminal newline.

All outputs expose permanently false `authenticated`, `execution_eligible`, and `promotable` properties. `fees_final` and `history_complete` remain unknown (`None`). Even matching fees prove only consistency of cumulative/per-execution regulatory-plus-clearing observations—not commission/SEC/TAF/CAT breakout, final settled charges or completeness. Do not adapt to `BrokerOrder`, `Fill`, calibration samples, promotion evidence or production ledger records.

## Verification and handoff

Tests cover real strict parsing and arithmetic under hostile ambient Decimal precision; malformed schema/JSON and sanitized errors; unknown/null vs zero; partial, dollar-based, rejected and cancelled orders; UUID dedup/conflicts; opaque URL-shaped cursors with no transport; pagination drift/loops/truncation; original adapter lock preservation. No authenticated tests or private data enter CI.

Actual calibration remains `BLOCKED_INPUTS` until genuine fills, final supported charge records, matching dated quotes, intent ownership and same-session recorded order receipts exist. Historical data qualification, accepted after-cost study, trusted forward paper owner, and deployed runtime recovery are independent later prerequisites. Do not widen the frozen 2016–2025 study to impersonate a 2026 forward runtime.
