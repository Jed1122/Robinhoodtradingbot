# Current architecture

Operational composition keeps monitoring read-only, daemon startup paused, operator signing
outside the service host, and placement factories behind authorization and promotion.

## Implemented boundary

The repository is a paper-safe, fail-closed foundation, not a running trading system.
Implemented code is limited to canonical domain primitives and immutable cross-layer
safety attestations, strict configuration and hashing, capability evidence and sanitized
schema capture, least-privilege broker protocols, code identity, clocks, and structured
logging with pre-serialization redaction. It also contains an equity-only Robinhood Trading MCP
read adapter and one-shot connected-shadow probe. The connection owns a private encrypted OAuth
store. Its OAuth client requests and pins the sole official `internal` scope; that bearer credential
is trading-capable and is not a broker-enforced read-only grant. Local write incapability comes from
an SDK-session read allowlist, a second transport read allowlist, and the absence of provider review,
placement, and cancellation adapters. A stolen token or compromised host could trade in the
Agentic account through another client. The implemented execution boundary contains a
pure state machine backed by an immutable explicit transition table, an exact review-only
wrapper, a deterministic internal SHA-256 deduplication-key function, and non-waiting
account-scoped exclusion for single-process fake and simulation brokers. A broker-neutral
execution service owns the only implemented placement call site. It accepts independently
injected review and place capabilities, persists each safety boundary, and rejects micro-live
and normal-live modes at construction. The in-process exclusion is not a live-host mutex.
Reviewed submissions are canonical domain records: non-live records must use fencing token
zero with no lease claim, while live records require a positive fencing token plus complete
lease identity and evidence. No current composition can construct a live submission. The
implemented portfolio/risk boundary
contains pure position sizing and seven projected new-exposure checks. It consumes the
canonical config models directly, fixes the risk-equity reference against gain-based
auto-scaling, binds sizing requests to validated instrument metadata, applies percentage and
absolute notional caps, and has no provider or broker dependency. Exposure percentage caps
use the lesser of current and authorized risk equity; the minimum cash reserve remains based
on current equity. The implemented persistence foundation is an Alembic-owned, normalized
SQLite ledger with an async engine policy, a single-use async unit of work, lossless
order-intent persistence, append-only risk and transition evidence, exact review and broker-order
evidence, a unique one-attempt submission journal, secret-screened audit appends, and focused
stores for market-data quality, authorization, reconciliation, research, and promotion evidence.
Promotion observations and aggregate evaluator decisions are append-only. Full strategy-cycle
composition and a provider write adapter remain absent.

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

Pretrade evaluation is pure, ordered, broker-neutral, and non-short-circuiting. The
preliminary pass runs 23 shared check functions; the final pass adds the exact broker-review
match and runs all 24. `PretradeEngine` receives the canonical `AppConfig`, its externally
loaded config hash, an account allowlist, the active code hash, and a trusted `Clock` as
explicit constructor dependencies. It captures the clock once for each pass, uses that value
for every freshness and expiry decision and result timestamp, and treats the context's
`observed_at` only as bound snapshot provenance. Exposure projections are bound to account,
intent, instrument, asset class, correlation group, equity, and snapshot time. Cost evidence
is factory-only and quote/intent/hash bound. Dependent checks deny absent or mismatched
evidence instead of inventing defaults. Paper and simulation waive only a live lease; exact
config, code, research, strategy, alert, health, data, limit, and reconciliation evidence is
still required. Entry-only symbol, liquidity, earnings, and asset-enable policies do not trap
a verified reduce-only exit, but provider tradability, market state, reconciliation, broker
bounds, and non-increasing exposure checks still apply. Prediction live execution remains
denied.

`ExecutionService.execute` first commits the intent and its `PROPOSED` transition, then loads
fresh preliminary context and persists all 23 initial checks. A denial stops before review or
placement. An allowed intent advances through a separately injected, review-only capability;
the normalized review must match the durable intent exactly before the review and `REVIEWED`
transition are committed. The service then acquires the non-waiting account exclusion, loads
fresh final context, evaluates and persists all 24 checks, and rechecks the intent and review
expiration windows. A final denial or expiration is durably terminal and never calls placement.

For an allowed, current non-live intent, one transaction stores the final risk evidence, reserves
the unique pending submission attempt, and records `SUBMISSION_PENDING` before the injected
`BrokerPlace` capability is called exactly once. The response outcome and lifecycle transition
are committed before the exclusion is released. An exception, a response that does not match the
persisted submission, or an otherwise nonterminal broker state is recorded as ambiguous for later
reconciliation; it is not interpreted as a safe retry. Exact submitted and rejected responses are
bound to a canonical broker-order row. This sequence is an implemented local orchestration
boundary, not a provider adapter, runner, live-authorization service, or proof of broker access.

Authenticated, value-free equity read shapes have been captured and are enforced by strict DTOs.
Nonempty position and order collections remain unsupported until their authenticated shapes are
observed and reviewed. Prediction live execution is unsupported. No live order has been placed.
The CLI provides offline commands, a health-only paused service, explicit OAuth bootstrap for the
locally write-incapable client, and a one-shot connected shadow probe, not a live trading application. The repository
makes no profitability claim.

## Dependency direction

`trading_bot.domain` and `trading_bot.clock` are dependency roots. Configuration owns
validated thresholds but does not import provider code. Capability models record the
kind and source of evidence without turning documentation or a schema into behavioral
proof. The broker package contains independent read, review, place, and cancel-only protocols;
strict equity read DTOs/mapping; a dual-allowlisted MCP transport and SDK composition; and safe
broker-neutral errors. Provider imports remain outside strategy, risk, and broker-neutral
execution logic. The execution review wrapper receives only the review protocol, validates
exact canonical intent equality, and cannot place an order. Its internal deduplication key
hashes the account, persisted intent identity, configuration hash, and purpose; it does not
replace a provider client-order identifier. The in-process exclusion fails immediately on a
same-account overlap, permits independent accounts, and always releases its slot on exit.

Domain safety attestations carry only validated status, identity, UTC time, and evidence
hashes. Reconciliation attestations are account-bound, and live leases are account-, config-,
mode-, and expiry-bound. They do not import or implement reconciliation, authorization, monitoring,
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

The initial migration and ORM metadata establish the normalized ledger, and each migration
revision runs inside an explicit rollback-capable SQLite transaction. The current revision adds
identity-bound promotion observations and database mutation guards for both raw observations and
aggregate promotion decisions. Composite constraints
bind eligible stage-specific promotion evidence to authorizations; authorizations to leases
and used nonces; live submissions to the exact lease, account, stage, and evidence; and local
intents, reviews, submissions, orders, transitions, and fills across duplicated identity and
economic payload fields. Provider routing is bound to account and instrument identities,
instrument references are bound to their asset class, fill-attributed realized P&L is bound
to the same account and instrument, and position rows can be bound to the account-matching
portfolio snapshot they comprise. Live authorization rows are limited to micro-live and
normal-live stages.

Paper promotion recording adds a non-waiting filesystem claim around one deterministic cycle ID.
Inside that claim it checks the append-only observation ledger before any simulated economic
effect, runs only the broker-incapable paper composition, derives the result-dependent eligibility
facts, and appends the observation. A restart that finds the exact durable observation returns it
without re-running the cycle. This recorder is infrastructure only until a concrete CLI or worker
supplies an accepted strategy and validated non-fixture data.

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

The submission-attempt migration adds database triggers that admit only canonical pending
inserts and one pending-to-terminal update. Non-live reservations require fencing token zero
and no lease claim; live-shaped reservations require a positive fencing token and complete lease
provenance. Attempt identity and provenance are immutable, accepted and rejected outcomes require
canonical response evidence, and completed timestamps cannot precede their attempt. Application
repositories additionally bind intent, review, attempt, broker order, account, instrument,
configuration, and economic fields before staging the transaction.

Relational provenance does not itself prove that an authorization or lease is currently valid.
The live runtime boundary checks expiry, revocation, exact config/code/strategy/promotion identity,
authorization, and lease evidence before a placement factory could be constructed, but no current
application composition supplies that factory. Provider write payloads, signing material, and
lease acquisition policy remain deliberately absent. The current repository surface does not invent lossy
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

Provider-connected equity market reads are implemented for the reviewed MCP surface. Complete
strategy scheduling, authenticated nonempty position/order mappings, remaining action and
authorization gates, connected review/placement/cancellation, and a live application runtime
remain planned.
The implemented durable execution service composes only explicitly injected broker-neutral
capabilities and refuses live modes. The default deployable runtime is limited to loopback-published
health for a write-incapable paused process with no host volumes or credential access. An explicit
Compose profile runs one authenticated, locally write-incapable equity probe and appends durable
evidence before exiting; it has no live mutex,
lease leadership, or complete strategy cycle. Its deliberately ineligible observation cannot start
the seven-date shadow promotion clock. Later slices must preserve the independent broker
capabilities and add their tests and documentation with each architectural change.
