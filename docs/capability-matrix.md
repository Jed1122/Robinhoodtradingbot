# Robinhood capability baseline

Checked on 2026-07-12 from official public documentation only. The local MCP state is
`blocked_unconfigured_mcp`: no `robinhood-trading` configuration was present in the
filtered local Codex MCP listing. The public endpoint URL in an environment variable is
not configuration or authentication evidence.

## What is and is not implemented

- Implemented: immutable evidence records, exact categorical gates, schema-only
  `tools/list` capture for an injected configured session, recursive artifact rejection,
  and deterministic matrix rendering.
- Documented: the exact equity MCP names and Crypto Trading API v2 paths below.
- Locked: every documented broker operation. Public documentation alone cannot unlock an
  adapter, authenticated read, review, submission, or cancellation path.
- External evidence pending: a real sanitized MCP schema capture and later separately
  authorized authenticated verification. No schema or authenticated result is claimed
  by this committed baseline.
- Unsupported: prediction-order placement. The official public evidence records no
  programmatic placement interface, so positive placement evidence is prohibited.
- Not implemented in this slice: broker adapters, account access, order review, order
  submission, cancellation, and live trading.

`documented_locked_external_pending` means the public operation is named, but required
schema/behavioral evidence and implementation are absent. `unsupported_locked` is a
terminal negative record, not a lower positive evidence rank.

## Evidence matrix

| Provider | Operation | Asset | Kind | Evidence | State |
|---|---|---|---|---|---|
| robinhood-crypto-v2 | `GET /api/v2/crypto/marketdata/best_bid_ask/` | crypto | read | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `GET /api/v2/crypto/trading/accounts/` | crypto | read | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `GET /api/v2/crypto/trading/estimated_price/` | crypto | read | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `GET /api/v2/crypto/trading/holdings/` | crypto | read | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `GET /api/v2/crypto/trading/orders/` | crypto | read | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `GET /api/v2/crypto/trading/trading_pairs/` | crypto | read | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `POST /api/v2/crypto/trading/orders/` | crypto | place | documented | documented_locked_external_pending |
| robinhood-crypto-v2 | `POST /api/v2/crypto/trading/orders/{id}/cancel/` | crypto | cancel | documented | documented_locked_external_pending |
| robinhood-prediction | `place_prediction_order` | prediction | place | unsupported | unsupported_locked |
| robinhood-trading | `cancel_equity_order` | equity | cancel | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_fundamentals` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_historicals` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_orders` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_positions` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_quotes` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_technical_indicators` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_tradability` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `place_equity_order` | equity | place | documented | documented_locked_external_pending |
| robinhood-trading | `review_equity_order` | equity | review | documented | documented_locked_external_pending |

The machine-readable public baseline is
`tests/fixtures/capabilities/documented_robinhood.json`. It records Crypto v2 signed
request labels, account scope, UUID `client_order_id`, eligible USD-pair constraints,
and jurisdiction/permission limits without credential or account values. It does not map
Robinhood Chain streaming documentation to the custodial Crypto Trading API; no streaming
transport is recorded for that API.

## Official sources

- [Agentic trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)
- [Trading with your agent](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
- [Crypto Trading API v2](https://docs.robinhood.com/crypto/trading/)
- [Crypto API help](https://robinhood.com/us/en/support/articles/crypto-api/)
- [Event contracts](https://robinhood.com/us/en/support/articles/trading-event-contracts/)

The forward-looking 2026-07-01 newsroom statement about future MCP crypto support is not
current capability evidence and is intentionally excluded from the matrix.

## Capture boundary

The capture core accepts only a session exposing MCP 1.28.1 `list_tools`. It retains
`name`, `description`, `inputSchema`, and explicit `outputSchema` (including `null`) plus
a canonical digest over the named input/output schema object. It does not inspect full
SDK objects, annotations, `_meta`, auth state, or account data, and it never invokes a
declared tool. Captured schema views are detached from immutable stored JSON so callers
cannot mutate a schema away from its digest. Snapshot writes use a private `0600` sibling
temporary file and atomic replacement; destination symlinks are rejected.

Sensitive schema names are classified by conservative components such as token, account,
auth, credential, key/signature, cookie/header, session, bearer, and secret/password.
Schema-only declarations remain recordable, while defaults, examples, descriptions,
custom metadata, encoded assignments, userinfo, and identifier-bearing paths are rejected
under sensitive scope. Standalone bearer material is rejected regardless of length.

The documented fixture loader requires duplicate-free finite JSON, exact root/record/
evidence fields, format version integer `1`, and an aware UTC `checked_at`. Invalid
fixtures and external MCP parser/session failures cross the boundary only as generic
errors without including provider payload text. The same text predicate scans fixture and
matrix free-form provider, operation, limitation, lock-reason, and evidence-note values;
timestamps, digests, enums, and validated official source paths retain their dedicated
validators. Exported snapshot records revalidate canonical JSON, schema digests, UTC,
provider identity, tool order/type, and manifest consistency at construction. Only exact
MCP SDK result and tool model types cross the external-result boundary.

When no proven configured session is injected, the CLI exits with status 2, writes
nothing, and prints:

```text
codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading
```
