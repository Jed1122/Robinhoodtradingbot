# Current architecture

## Implemented boundary

The repository is a paper-safe, fail-closed foundation, not a running trading system.
Implemented code is limited to canonical domain primitives, strict configuration and
hashing, capability evidence and sanitized schema capture, least-privilege broker protocols,
code identity, clocks, and structured logging with pre-serialization
redaction.

Trading MCP is not configured. Prediction live execution is unsupported.
No live order has been placed. Trader CLI is not implemented. Broker adapters are not implemented.
Account access is not implemented. The repository makes no profitability claim.

## Dependency direction

`trading_bot.domain` and `trading_bot.clock` are dependency roots. Configuration owns
validated thresholds but does not import provider code. Capability models record the
kind and source of evidence without turning documentation or a schema into behavioral
proof. The broker package currently contains only independent read, review, place, and
cancel-only protocols plus safe broker-neutral errors; it contains no transport or
implementation.

Shared capability sanitization owns the reviewed sensitive-name and sensitive-text
taxonomy. Structured logging reuses that taxonomy, adds only the process-local exact
secret registry, recursively detaches trusted built-in data, renders exceptions, redacts,
and only then emits JSON. Unknown objects and internal redaction failures produce generic
markers rather than invoking application-defined string or representation methods.

## Capability state

The [capability matrix](capability-matrix.md) separates implemented local foundations,
officially documented operation names, locked operations, external evidence still
pending, and unsupported operations. Public documentation does not unlock an adapter.
An unauthenticated schema declaration would remain distinct from an authenticated read
or a non-submitting order review.

## Absent runtime layers

Market data, strategies, portfolio construction, risk gates, persistence, authorization,
simulation, paper and shadow runners, provider adapters, review and execution,
reconciliation, recovery, operations, and deployment remain planned. No current module
composes a place capability or provides an order call site. Later slices must preserve
the independent broker capabilities and add their tests and documentation with each
architectural change.
