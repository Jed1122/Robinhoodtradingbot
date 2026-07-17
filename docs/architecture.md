# Current architecture

## Implemented boundary

The repository is a paper-safe, fail-closed foundation, not a running trading system.
Implemented code is limited to canonical domain primitives and immutable cross-layer
safety attestations, strict configuration and hashing, capability evidence and sanitized
schema capture, least-privilege broker protocols, code identity, clocks, and structured
logging with pre-serialization redaction. The implemented execution boundary contains only
a pure state machine backed by an immutable explicit transition table; it has no broker
call site. The implemented portfolio/risk boundary contains pure position sizing and seven
projected new-exposure checks. It consumes the canonical config models directly, fixes the
risk-equity reference against gain-based auto-scaling, binds sizing requests to validated
instrument metadata, applies percentage and absolute notional caps, and has no provider or
broker dependency. Exposure percentage caps use the lesser of current and authorized risk
equity; the minimum cash reserve remains based on current equity. The implemented persistence
foundation is an Alembic-owned, normalized SQLite ledger with an async engine policy, a
single-use async unit of work, lossless order-intent persistence, and secret-screened audit
appends. It does not yet include the remaining workflow repositories or runtime composition.

Loss and activity evaluation is also pure and config-bound. `LossSnapshot` never resets its
own counters: the future context loader must derive the daily boundary from the canonical
trading-session calendar, derive the UTC weekly boundary, and attest daily reconciliation
and weekly review. Each loss snapshot and decision is bound to one account. Missing reset
evidence is a hard stop. Daily, weekly, and active
consecutive-loss limits block entries and request cancellation of unfilled entries while
leaving eligible exit intents to later reduce-exposure checks. A drawdown breach blocks new
entry and exit intents, requests kill-switch activation, and never requests liquidation;
existing broker-held protective orders remain governed by the runtime action matrix.
`ActivitySnapshot` is bound to one account and instrument and counts distinct durable entry
intents that reached submission. Transport retries do not add capacity usage, while an
ambiguous submission continues to count until reconciliation. Its day boundary is UTC and
spacing evidence is exact to the microsecond.

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

Domain safety attestations carry only validated status, identity, UTC time, and evidence
hashes. They do not import or implement reconciliation, authorization, monitoring,
promotion, or research services. Audit events have one canonical domain class while the
prior decision-module import remains a compatibility alias.

`trading_bot.persistence` maps canonical domain records to SQLAlchemy rows; domain, strategy,
risk, and broker modules do not import persistence. Every new or reused SQLite connection
must prove WAL mode, foreign-key enforcement, recursive-trigger enforcement, and
`synchronous=FULL` or fail closed. Trading
Decimal values, UTC timestamps, SHA-256 digests, booleans, and safety counters use exact
bind/read types plus database checks, preventing raw SQL from storing noncanonical evidence.
Pure arithmetic and persistence share one bounded, fixed-form Decimal renderer; unsafe
finite exponents or digit counts fail before sizing or evidence serialization.
Decimal, Boolean, and safety-counter columns declare no-coercion `BLOB` affinity while
their validated values retain SQLite `TEXT` or `INTEGER` storage classes. Stored generated
identity columns provide tagged, null-safe equality for optional prices and client order
identifiers; SQLite 3.31 or newer is therefore required.

The initial migration and ORM metadata define the same 32-table ledger, and each migration
revision runs inside an explicit rollback-capable SQLite transaction. Composite constraints
bind eligible stage-specific promotion evidence to authorizations; authorizations to leases
and used nonces; live submissions to the exact lease, account, stage, and evidence; and local
intents, reviews, submissions, orders, transitions, and fills across duplicated identity and
economic payload fields. Provider routing is bound to account and instrument identities,
instrument references are bound to their asset class, fill-attributed realized P&L is bound
to the same account and instrument, and position rows can be bound to the account-matching
portfolio snapshot they comprise. Live authorization rows are limited to micro-live and
normal-live stages.

The next migration makes audit events, order transitions, risk evaluations, configuration
versions, live authorizations, kill-switch events, and reconciliation events insert-only at
the database boundary. Each table rejects updates and deletes and validates inserts so
SQLite `REPLACE`, `INSERT OR REPLACE`, and conflict-update paths cannot erase history through
validated application connections. Insert guards also block ordinary replace conflicts on
raw connections, while database-owner changes remain outside the trigger threat boundary. A
correction is a new row whose `corrects_id` names a distinct existing row. Trigger rejection
rolls back the whole transaction. The application unit of work also
requires an explicit commit, rolls back normal uncommitted exits and failures, closes its
session, and prevents repository use outside its one transaction. Construction binds the active
code and configuration hashes; intent or audit writes with another identity are rejected while
historical reads remain available. Audit identifiers are checked against the process
exact-secret registry, while detail values pass both the shared sensitive-material classifier
and that registry before canonical JSON encoding. Raw UUID, account, and provider identifiers
are not accepted in free-form details; callers use the event correlation ID and content hashes until a later
migration adds an explicit typed foreign-key field for a required durable identity.

Relational provenance does not itself prove that an authorization or lease is currently
valid. Expiry, revocation, nonce consumption, exact config/code identity, and execution
fencing are fail-closed runtime decisions owned by later pretrade, authorization, and
execution-leadership services. Provider payloads, signing material, workflow-specific
submission/fill/authorization/reconciliation repository commands, and lease acquisition
policy remain deliberately absent. The current repository surface does not invent lossy
commands for domain records that cannot yet populate their required provenance columns.

Shared capability sanitization owns the reviewed sensitive-name and sensitive-text
taxonomy. Structured logging reuses that taxonomy, adds only the process-local exact
secret registry, recursively detaches trusted built-in data, renders exceptions, redacts,
applies the canonical `logging.max_event_bytes` bound, and only then emits JSON. The
setting is required in `AppConfig`, capped by `SafetyEnvelope`, and must be privately
installed by future application bootstrap; logging configuration fails if it is absent.
Stdlib formatting inputs and exception arguments are sanitized before interpolation;
existing handlers and filters, the record factory, and last-resort output are normalized
behind one fail-closed JSON sink. Its formatting-error path never prints the raw record.
Unknown objects and internal redaction failures produce generic markers rather than
invoking application-defined string or representation methods.
Detached logging extensions are retained for the active process so reconfiguration does
not trigger their lifecycle hooks. Arbitrary third-party destructors run outside the
logging pipeline during interpreter teardown, so production bootstrap treats preinstalled
logging extensions as trusted process code and must never put secrets in destructor behavior.
Logging configuration must complete in the single-threaded entry point before importing
application modules that materialize or bind Structlog loggers and before starting workers.
Structlog exposes no registry for revoking already-bound objects, so pre-bound loggers and
custom processors are unsupported trusted pre-bootstrap code. An already-running
third-party callback likewise cannot be revoked by a completed reconfiguration.

## Capability state

The [capability matrix](capability-matrix.md) separates implemented local foundations,
officially documented operation names, locked operations, external evidence still
pending, and unsupported operations. Public documentation does not unlock an adapter.
An unauthenticated schema declaration would remain distinct from an authenticated read
or a non-submitting order review.

## Absent runtime layers

Market data services, strategies, portfolio target construction, remaining risk and action
gates, persistence commands beyond order intents and audit events, authorization services,
simulation, paper and shadow runners, provider adapters, review and order-submission
services, reconciliation services, recovery, operations, and deployment remain planned. No
current module composes a place capability or provides an order call site. Later slices must
preserve the independent broker capabilities and add their tests and documentation with each
architectural change.
