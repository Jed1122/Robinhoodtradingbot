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

Sensitive schema names are classified from percent-decoded separator and camel-case tokens
plus an anchored, reviewed compound grammar. The grammar covers singular/plural API, private,
signing, access, client, consumer, and secret key forms; API/access/client/consumer secret
forms; auth/OAuth/bearer/authorization token forms; session and account identifiers; and auth
headers. It recognizes exact compact components and separators or punctuation such as array
brackets, without raw substring matching. Thus `api_keys`, `clientsecret[]`, `oauthtoken`, and
`accesskeyid` are sensitive, while author, signal, designation, assignment,
accounting-period, session-duration, client-order, public-key, accessibility, and secretary
names remain ordinary metadata. Candidate names containing non-ASCII, control, or format
characters fail closed. Assignment inspection uses bounded overlapping boundaries, so a safe
outer field cannot hide an inner assignment such as `safe=clientsecret=tiny`. Under sensitive
scope, schema
declarations are accepted only when their values have validated built-in shapes: known types
and formats, safe local JSON pointers, exact booleans, matching required-property names, and
recursive schema maps or combinators. Local pointer fragments are inspected as decoded path
pairs after bounded percent decoding and RFC 6901 `~1` then `~0` unescaping. Every decoded
segment must be ASCII and free of control, format, and bidirectional override characters. A
terminal schema name such as `#/$defs/AuthToken` is declaration-only, while a sensitive
segment followed by another segment, including `access_token~1tiny`, is rejected as
value-bearing. Unvalidated
numeric/list carriers, defaults, examples, descriptions, custom metadata, encoded
assignments, userinfo, and identifier-bearing paths are rejected. Standalone bearer material
is rejected regardless of length.

The documented fixture loader requires duplicate-free finite JSON, exact root/record/
evidence fields, format version integer `1`, and an aware UTC `checked_at`. Invalid
fixtures and external MCP parser/session failures cross the boundary only as generic
errors without including provider payload text. The same text predicate scans fixture and
matrix free-form provider, operation, limitation, lock-reason, and evidence-note values.
Fixture source URIs pass through that predicate before the official-scheme/host/path URI
validator; digests and enums retain their dedicated validators. Snapshot timestamps must be
exact built-in datetimes and are stored as the canonical UTC value returned by validation,
so subclass methods cannot cross the serialization boundary. Capability evidence timestamps
have the same exact-type and canonical-UTC rule, and model string fields require exact
built-in strings before any string operation. NUL, escape, invisible format, and bidirectional
override characters are rejected from model and matrix free-form text; ordinary documented
prose remains supported. Capability records reconstruct every exact nested evidence value,
and manifests reconstruct every exact nested record and evidence value, before safety
decisions or storage. Exported snapshots likewise rebuild every nested sanitized tool schema
and the full manifest before deriving names, comparing schema evidence, or storing copies.
Unsafe descriptions, malformed canonical JSON, stale or false schema digests, subclass
equality, forged model fields, and missing fields therefore cannot satisfy consistency or
capability gates. Provider identity and deterministic tool ordering are also revalidated at
construction. Only exact MCP SDK result and tool model types cross the external-result
boundary.

When no proven configured session is injected, the CLI exits with status 2, writes
nothing, and prints:

```text
codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading
```
