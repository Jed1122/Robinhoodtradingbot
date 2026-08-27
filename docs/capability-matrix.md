# Robinhood capability baseline

Checked again on 2026-07-21. In addition to official public documentation, this repository now
contains a sanitized, value-free artifact from authenticated calls to the seven reviewed equity
read tools. It contains response structure and type information only—no account identifiers,
balances, symbols, order values, tokens, or other provider values. Runtime OAuth state remains
operator-controlled outside Git. A public endpoint URL alone is still neither authentication nor
capability evidence.

Robinhood exposes the sole official OAuth scope `internal`. The client pins that scope, but it is
not a broker-enforced read-only grant; its bearer credential must be treated as trading-capable. A
stolen token or compromised host could trade in the Agentic account. The implemented client is
write-incapable only because an SDK-session allowlist and an independent transport allowlist admit
the seven reads below and because no equity review, placement, or cancellation adapter exists.

Operational readiness, promotion, and authorization are independent gates and do not upgrade any
provider evidence level shown below.

## What is and is not implemented

- Implemented: immutable evidence records; strict official Crypto v2 DTOs and mappings; exact-byte
  Ed25519 signing; read-only Crypto account/position/order adapters against mock HTTP; schema-only
  `tools/list` capture; recursive artifact rejection; deterministic matrix rendering; and a strict
  equity-only `BrokerRead` adapter for seven authenticated MCP read operations.
- Documented: the exact equity MCP names and Crypto Trading API v2 paths below.
- Authenticated read verified: `get_accounts`, `get_portfolio`, `get_equity_positions`,
  `get_equity_orders`, `get_equity_quotes`, `get_equity_tradability`, and
  `get_equity_historicals`. Positions and orders accept only authenticated empty collections;
  any nonempty collection or pagination cursor fails closed until row shapes are reviewed.
- Locked externally: Crypto authenticated operations and every equity review, submission, and
  cancellation operation. Local schema fixtures, authenticated reads, and mock HTTP do not unlock
  a write path.
- Unsupported: prediction-order placement. The official public evidence records no
  programmatic placement interface, so positive placement evidence is prohibited.
- Implemented locally: a broker-neutral, non-live execution service that persists preliminary
  and final risk evidence, an exact review, one pending submission reservation, and the resulting
  accepted, rejected, or ambiguous outcome around an injected fake or simulation placement
  capability.
- Equity read mapping and a one-shot connected-shadow composition are implemented. The SDK-session
  allowlist rejects write tools before the MCP SDK call, and the provider transport's separate
  allowlist contains only the seven reads above. These are local restrictions, not OAuth scope.
  Prediction live operations always raise `UnsupportedCapabilityError`.
  Equity review, placement, and cancellation therefore have no adapter classes: write argument
  and result fields are not guessed from public operation names.

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
| robinhood-trading | `get_accounts` | equity | read | authenticated-read-verified | implemented_read_only |
| robinhood-trading | `get_equity_fundamentals` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_historicals` | equity | read | authenticated-read-verified | implemented_read_only |
| robinhood-trading | `get_equity_orders` | equity | read | authenticated-read-verified | implemented_empty_only |
| robinhood-trading | `get_equity_positions` | equity | read | authenticated-read-verified | implemented_empty_only |
| robinhood-trading | `get_equity_quotes` | equity | read | authenticated-read-verified | implemented_read_only |
| robinhood-trading | `get_equity_technical_indicators` | equity | read | documented | documented_locked_external_pending |
| robinhood-trading | `get_equity_tradability` | equity | read | authenticated-read-verified | implemented_read_only |
| robinhood-trading | `get_portfolio` | equity | read | authenticated-read-verified | implemented_read_only |
| robinhood-trading | `place_equity_order` | equity | place | documented | documented_locked_external_pending |
| robinhood-trading | `review_equity_order` | equity | review | documented | documented_locked_external_pending |

The `implemented_read_only` and `implemented_empty_only` states describe this repository's local
adapter behavior. They do not describe or reduce the authority of the OAuth bearer credential.

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
headers. Session identifier/reference/number/UUID/`no` variants and account
identifier/reference/number/UUID/`no` variants use that same grammar. Reviewed compact account
abbreviations include `acctNum`, `accountNbr`, and `acctRef`, with plural and terminal carrier
variants. Authorization/OAuth/auth/verification/MFA/recovery/OTP code variants are also covered.
It recognizes exact compact components and separators or punctuation such as array
brackets, without raw substring matching. A compact strong credential base may have a bounded
alphanumeric namespace. Any exact sensitive single-name lexeme may also have a bounded leading
alphanumeric namespace when that lexeme is terminal; this detects compact carriers such as
`verificationtoken` without classifying words where `token` is not terminal, such as
`tokenization` or `tokenbucket`. One exact reviewed terminal carrier suffix from `value`,
`values`, `data`, `bytes`, `material`, or `pem` may follow any already-sensitive base,
including exact single-name lexemes. Thus `api_keys`, `clientsecret[]`, `oauthtoken`,
`awssecretaccesskey`, `walletprivatekey`, `sessioncookievalue`, `apikeymaterial`, `authvalue`,
`accountdata`, `headervalue`, `bearermaterial`, and `oauthvalue` are sensitive. Generic `key`
is never a credential base: author, signal, designation, assignment, accounting-period,
session-duration, client-order, public-key, key-value, monkey, tokenization, token-bucket,
author-value, accounting-data, headerless-value, accessibility, and secretary names remain
ordinary metadata. Candidate names containing non-ASCII, control, or format characters fail
closed. Explicit benign compounds include accounting reference, authorization status, OAuth
scope, postal/ZIP code, code point, reference price, and identifier format. Assignment
inspection walks each ASCII or fullwidth colon/equal delimiter and extracts up to four immediate
bounded name words across whitespace and unreserved name punctuation. Percent-encoded spaces
and delimiters receive the same inspection, while semicolons, slashes, quotes, and other carrier
boundaries expose inner values. A safe outer field or a long padded value cannot hide an inner
assignment such as `safe=clientsecret=tiny`; a continuous assignment-name span beyond 128
characters fails closed.
Under sensitive scope, schema
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
is rejected regardless of length. Valid padded or unpadded standard-Base64 opaque values with
the standard `+` or `/` alphabet, a decoded length of at least 24 bytes, and a bounded diversity
floor are rejected without classifying ordinary public API paths. Bare identifier-like runs of
eight or more digits are also rejected from free-form evidence, while ISO dates and seven-digit
public values remain valid.

The documented fixture loader requires duplicate-free finite JSON, exact root/record/
evidence fields, format version integer `1`, and an aware UTC `checked_at`. Invalid
fixtures and external MCP parser/session failures cross the boundary only as generic
errors without including provider payload text. One dependency-neutral text predicate scans
direct evidence models, captured schemas, fixtures, and matrix free-form provider, operation,
limitation, lock-reason, source-URI, and evidence-note values; no model imports the MCP capture
layer and no competing credential-name taxonomy is maintained.
Fixture source URIs pass through that predicate before the official-scheme/host/path URI
validator; digests and enums retain their dedicated validators. Snapshot timestamps must be
exact built-in datetimes and are stored as the canonical UTC value returned by validation,
so subclass methods cannot cross the serialization boundary. Capability evidence timestamps
have the same exact-type and canonical-UTC rule, and model string fields require exact
built-in strings before any string operation. NUL, escape, invisible format, and bidirectional
override characters are rejected after every bounded percent-decoding stage as well as from
raw model and matrix free-form text; ordinary percent-encoded public text and documented
prose remain supported. Capability records reconstruct every exact nested evidence value,
and manifests reconstruct every exact nested record and evidence value, before safety
decisions or storage. Exported snapshots likewise rebuild every nested sanitized tool schema
and the full manifest before deriving names, comparing schema evidence, or storing copies.
Unsafe descriptions, malformed canonical JSON, stale or false schema digests, subclass
equality, forged model fields, and missing fields therefore cannot satisfy consistency or
capability gates. Every standalone schema accessor and every tool/snapshot JSON serializer
reconstructs its complete object immediately before export, so post-construction mutation and
exact `object.__new__` forgery cannot emit stale state. Exact capability lookup validates its
query keys before comparison and never invokes subclass or non-string equality. Both exported
lookup-error constructors independently retain only exact safe strings, replace hostile or
sensitive provider/operation attributes with generic placeholders, and replace an invalid
minimum evidence attribute with `unsupported`. Provider identity and deterministic tool
ordering are also revalidated at construction. Only exact MCP SDK result and tool model types
cross the external-result boundary.

Schema discovery accepts at most 32 `tools/list` pages and applies a 10-second cooperative
async timeout to each individual page call. A continuation cursor on page 32 is rejected before
a page-33 request or artifact write. Empty and repeated cursors still fail closed,
timeout/session failures remain generic, and caller cancellation propagates without being
converted into a capture error. The async timeout can cancel a session implementation that
yields to the event loop; it cannot preempt an implementation that blocks the event loop or
never reaches a cancellation point. No background thread or process workaround is used.

The operator CLI can use the existing encrypted OAuth store to capture all `tools/list`
declarations through a session with no `call_tool` method. OAuth authenticates the transport, but
the resulting sanitized artifact remains schema-declaration evidence only and contains no account
data. A declared review, place, or cancel schema does not implement or authorize that operation.
The artifact destination must have a service-owned parent that is not writable by group or other
users, and the file is written atomically with mode `0600`.

The older injected-session schema-capture script remains unauthenticated declaration evidence
only. When no proven configured capture session is injected, it exits with status 2, writes
nothing, and prints:

```text
codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading
```
