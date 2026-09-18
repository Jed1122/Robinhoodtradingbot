# Current architecture

Operational composition keeps monitoring read-only, daemon startup paused, operator signing
outside the service host, and placement factories behind authorization and promotion.

## Implemented boundary

### Offline replay integration seams

`IntentPlanner` accepts an optional intent-ID factory while retaining UUID generation for
existing callers. `DecisionCycleService` accepts an optional outcome encoder; the default
string encoding and existing cycle-result hashes remain unchanged. A separate
`PerInstrumentDecisionCycleRequest` carries explicit per-instrument exit policies, preserving
the original request's serialized shape and paper restart keys. The portfolio constructor
requires exactly one policy form and rejects duplicate or missing entry-policy mappings.
The synthetic equity runner below uses these seams. No production paper, shadow, live,
broker or promotion composition is enabled by them, and they add no new risk gate.

`simulation/equity_replay_models.py` now defines strict synthetic scenario inputs: a detached
canonical `LoadedConfig`, a configuration-grid candidate, verified synthetic bundle, instrument
metadata, explicit UTC decisions and finite session opportunity declarations. Account identity
is derived only from the reserved `synthetic:` namespace. Non-simulation/live-enabled settings,
lowered history requirements, conflicting deliveries and undeclared quote opportunities are
rejected with stable local reason codes. This validates the scenario contract; it does not
assert that a future snapshot has sufficient visible history or that an order passes risk.

`equity_replay_codec.py` separates the stable run key, deduplicated economic-input audit hash
and delivery-receipt hash. The run key excludes future deliveries and the full bundle digest;
the coordinator additionally binds each cycle/order to its visible as-of inputs.
The closed outcome encoder never serializes arbitrary objects. All request eligibility flags
are immutable false. Shared synthetic portfolio accounting, configured exits, the economic
adapter, whole-strategy coordinator and aggregate result derivation are implemented below.
The private `simulate --scenario` CLI and final whole-milestone adversarial verification
remain pending; the existing CLI still reports configuration-only execution.

### Offline equity decision/event replay

`await simulation.equity_replay.replay_equity_strategy(request)` accepts only a validated
synthetic value request. `equity_replay_cycle.py` composes the real `BundleSnapshotLoader`,
`FeaturePipeline`, momentum or relative-strength strategy, `DecisionCycleService`,
`PortfolioConstructor`, `IntentPlanner` and typed in-memory journal. The original minimum
history requirement remains enforced. Feature/target calculations use fixed rounded Decimal
contexts; inner fill, funding and lifecycle accounting retain exact arithmetic.

`equity_replay_state.py` merges finite explicit market/decision times with each order's next
configured action. Time, control priority, instrument and order identity determine ordering.
Every transition reaches the shared portfolio and risk observer before the next action;
strategy decisions follow already-scheduled actions at the same time. Exits precede entries,
then instrument order is stable. Each intent receives fresh economic, funding and final-size
checks after earlier admissions; a denied order is not silently resized or retried.

New orders cannot consume the triggering event or their submission bar. Exit triggers first
request cancellation of any entry remainder. That causal request is processed after the
already-observed timestamp, followed by its configured acknowledgement; no microsecond delay
or backdated control is invented. Permitted race fills update the actual position. Another
explicitly declared decision after terminal cancellation must recompute the current quote,
exit trigger, quantity and checks. Cancellation alone never creates an implicit SELL.
Canonical loss dispositions cancel unfilled entries when required and never force liquidation.
Cancellation time, order and reason are retained in the synthetic audit result.

`equity_replay_records.py` derives immutable results from the authoritative book and recorded
cycles/transitions. Order terminality, position flatness and completed strategy outcomes are
separate facts; a filled, canceled or expired entry can leave unresolved exposure. End of input
does not force liquidation. Missing history or a fresh final mark raises a sanitized denial,
not an invented valuation or completed result. UTC reset observations are not synthesized.
`assumptions_validated`, `evidence_promotable` and `production_pretrade_eligible` remain false.
The runner has no provider transport, broker, production ledger, credential or promotion writer.

As-of cycle/intent IDs exclude future scenario digests. Duplicate deliveries change only the
receipt identity, not economic outcomes; extending the future stream preserves existing cycles,
fills and cancellation transitions. This is a small deterministic fixture runner, not calibrated
market execution, accepted research, a production pretrade engine or live-readiness evidence.

### Shared synthetic equity portfolio funding

`simulation/equity_replay_portfolio.py` owns one in-memory `ReplayPortfolio`, starting flat
with the request's explicit synthetic cash. A BUY transfers limit notional plus a conservative
commission allocation out of allocatable cash; it does not debit total account cash. The
commission capacity uses the immutable declared session slots after submission and before
expiry, including declared slots beyond a shorter replay horizon. Delivered quotes,
liquidity, outcomes and eventual cancellation do not reduce this reservation at admission.
The caller's opportunity count must equal the declaration. GFD expiry matches the declared
session end, not an inferred exchange calendar.

One active order per instrument prevents independent lifecycle results from overwriting a
position. BUY admission into an existing position and SELL quantities above held shares are
denied. SELL proceeds remain in the order allocation until terminal; tiny proceeds insufficient
to pay their commission fail in the lifecycle instead of borrowing cash. Funding acceptance is
explicitly **not** economic-risk or production-pretrade approval.

Only the existing lifecycle authority changes fill cash, fees and shares. The portfolio
recomputes that lifecycle against its own original allocation, verifies canonical settings,
costs, tick/lot alignment, declared fill slots, decision-to-event links and immutable prefixes,
then checks shared-cash conservation before atomically publishing. Configured sampling and
market-input provenance remain owned by the simulator and coordinator; portfolio result
hashes are not proof of execution assumptions. An invalid operation latches the book invalid
while leaving the last monetary state available for diagnosis. Identical intent/result
redelivery is idempotent; terminal release cannot run twice or overwrite a later order.

Shared results must arrive in chronological order, including acknowledgements before later
fills in other instruments. Held positions are marked at a supplied, recorded, fresh synthetic
bid visible at the requested UTC instant. Current portfolio identity excludes configured full
input/result digests, which contain future deliveries. Cash-flow results are recognized as
realized only when a traced position returns flat and its order is terminal; partial exits and
fees stay in the remaining open-flow mark. These fields are not tax-lot or broker-settlement
accounting. Terminal orders and flat positions are separate facts. The module performs no
provider, ledger, credential or deployment I/O, and does not implement the strategy runner.

### Configured synthetic exits and economic checks

`equity_replay_policy.py` freezes a candidate's entry limit and positive ATR-derived stop
distance from the canonical configuration. Its immutable policy version binds the instrument,
config, feature identity, timestamp and thresholds; fills and completed holding bars do not
reprice that basis. `observe_entry` validates the entry's identity against its recomputed
lifecycle and derives first-fill time and completed-bar count. `exit_reason` requires a fresh
synthetic bid and returns a reason only: stop, target, maximum holding, then configured regime
exit/deselection. It has no fill, cancellation or order-submission capability. Completed-bar
provenance and visible feature/quote selection remain the coordinator's responsibility.

Momentum predicates and relative-strength ranking call the existing strategy classes. The
relative-strength wrapper returns no new selection between canonical rebalance boundaries;
an intervening HOLD is not silently converted into an exit. The policy adapter supplies the
existing planner's `ExitPolicy`, with the same configured stop, reward/risk and holding limit.

`equity_replay_risk_state.py` binds observations to one initially flat synthetic portfolio and
the full validated scenario identity. Every intervening lifecycle event and exposed quote
must be observed; skipped history is rejected. Held positions must use the latest visible
recorded mark by observation time, so duplicate delivery of an older quote cannot replace it.
Synthetic daily/weekly baselines reset only at an explicitly observed UTC boundary. Missing
baselines invoke canonical reset denials. Maximum observed drawdown remains latched through
a recovery. Consecutive losses derive from terminal, flat lifecycle cash flows; no-fill,
rejected and break-even outcomes do not clear the streak. Distinct BUY intents consume
activity capacity, including pending and simulated-rejected submissions, but funding denials
that never create an order do not. These are synthetic observations, not broker evidence.

`equity_replay_risk.py` projects current bid-marked positions, remaining pending BUY notional,
candidate exposure, and cash after existing allocations and declared commission capacity.
It delegates limits, purpose-aware loss decisions, activity and final sizing to the existing
canonical functions. Authorized risk equity stays fixed at initial synthetic cash; gains
cannot enlarge it. Each evaluation rechecks that the observation still matches the book.
An entry cannot average down or overlap an active order; an exit cannot oversell. Entry-only
activity limits do not apply to exits, while the canonical loss/drawdown rules still do.
Drawdown requests a hard-stop disposition, never a liquidation or automatic recovery.

Neither adapter calls `PretradeEngine`, mutates an order, or mints production attestations;
`evidence_promotable` and `production_pretrade_eligible` stay false. The coordinator consumes
denials and cancellation/hard-stop dispositions, sequences same-time causal events, refreshes
checks before admission, and owns partial-entry cancellation before any exit.

### Configuration-driven synthetic order simulation

`simulation/configured.py` is the backward-compatible one-shot wrapper over
`ConfiguredOrderSession` in `configured_session.py`. That module owns the single virtual-time
scheduler and existing lifecycle integration. Its input models and whole-stream validation live in
`configured_models.py` and `configured_validation.py`; `configured_fills.py` adapts canonical
simulation/cost settings, `configured_codec.py` derives event-keyed random streams and hashes,
and `configured_results.py` owns immutable audit/results. There is no provider, broker,
runtime, persistence, or promotion composition dependency.

An incremental session publishes immutable `result` snapshots, advances through an explicit UTC
time with `advance_to`, accepts append-only future inputs with `deliver`, and exposes the next
in-horizon queued time through `next_event_at`. Queue/decision mutations are staged before an
advance is published. A failed fill cannot leak an acknowledgement or consume a queued event.
Inputs must arrive before their timestamp is published, including exact duplicate deliveries;
pending duplicates are audit-only. Delivery replays the existing prefix in fresh private state
to preserve the same validated input/decision identities as the one-shot wrapper. This favors
small deterministic fixtures, not production throughput. The API is synchronous and single-owner.

`next_event_key` exposes the next time and control priority; `advance_next` atomically publishes
one action, allowing a cross-order coordinator to apply all same-time acknowledgements before
market opportunities. The equity-only `cancel_after_observation` queues one versioned causal
request after a fully observed timestamp. Its priority is after ordinary market input; all
same-time causal requests precede zero-latency acknowledgements. Later acknowledgements use
ordinary control priority. Forward delivery rebuilds the exact processed action count, not an
entire timestamp, so it cannot accidentally drain a pending same-time action. The opt-in phase
does not change unused legacy input preimages or pinned one-shot hashes.

`InstrumentConfiguredOrderRequest` explicitly opts into `synthetic-equity-increments-v1`.
This equity LIMIT/GFD-only subtype validates identity, tick/lot alignment, size bounds and metadata
time, and binds the instrument and version into settings/RNG identity. Quantities round down through
canonical quantization; sub-lot outcomes do not fill or charge a commission. Cost-adjusted BUY prices
round up and SELL prices round down to the supplied tick, then face the existing limit guard.
Fees are recalculated from the rounded quantity/price through the existing cost function. The
legacy request schema, fixture semantics and pinned full/partial/cancel/expiry hashes are unchanged.

Submission rejection is sampled once at the configured acknowledgement time. Accepted
orders receive conditional no-fill/full/partial opportunities only after latency, next-bar,
quote/session, cancellation-race, liquidity, and cost-adjusted limit checks. Partial sizes
use the configured range against remaining quantity. The configured cancel-race percentage
allows at most one eligible pending-cancel opportunity; it is not a measured fill rate.
Virtual-time ties prioritize expiry, submission acknowledgement, cancel request, cancel
acknowledgement, then market input. Synthetic GFD expiry is explicit, not inferred from a
real session calendar. A finite horizon may leave orders pending or partially filled.

Each generated event prefix is replayed through the unchanged lifecycle authority before
publication. Exact duplicate input delivery is audit-only; conflicting duplicates fail
before scheduling. Random streams and generated IDs are independent of future market inputs;
cancel acknowledgements also bind their triggering request. Full input/result hashes retain
all inputs, no-fill decisions, duplicates, settings, horizon, and accounting outcomes.

Only fresh in-memory synthetic equity/crypto LIMIT scenarios are accepted. Assumption and
promotion flags must be false and are fixed false on output. Money must be exact in the
lifecycle's fixed Decimal context. Spread comes from supplied quotes, while slippage and
per-fill fees use the canonical costs. Exchange increments require the explicit equity subtype;
legacy fixtures are still unconstrained. Stressed costs, shared liquidity and real calendars
remain unsupported. This is not a strategy runner or a qualifying paper
cycle. The legacy `FillModel` API and production execution/risk gates remain unchanged.
See the [configured simulator design](superpowers/specs/2026-09-17-configured-order-simulator-design.md).

### Offline scripted single-order lifecycle

`simulation/lifecycle.py` replays one synthetic equity or crypto LIMIT order from a
submission-pending fixture through explicitly scripted acknowledgements, partial/full fills,
cancel requests/confirmations, and expiration. Frozen records and boundary validation live in
`lifecycle_models.py`; checked arithmetic and domain-separated hashing are isolated in
`lifecycle_accounting.py` and `lifecycle_codec.py`. The component reuses the unchanged domain
state machine and partial-fill helper. It does not implement a broker capability or call the
production execution service.

Each replay starts from fresh in-memory state. Exact duplicate events add a receipt but do not
change balances, cursor, or snapshot hash; conflicting identities or reused fill IDs fail
closed. New events cannot reopen terminal orders. Money and quantity calculations must be
exact within the fixed 28-significant-digit Decimal context; the existing weighted-average
formula may round. Position market value is marked at the last scripted fill, not a fresh
market quote. No realized/unrealized P&L or buying-power attestation is manufactured.

Results and receipts are deterministic and permanently labeled synthetic/non-promotable.
An order being terminal does not establish a flat position or complete strategy outcomes.
There is no file/ledger I/O, CLI, concurrent-order reservation, random fill-model integration,
provider access, or production runtime wiring. See the
[approved lifecycle design](superpowers/specs/2026-09-17-offline-order-lifecycle-design.md)
for exact supported inputs and failure behavior.

### Offline synthetic research bundles

The separate `market_data/bundle_models.py`, `bundle_codec.py`, `bundle_normalize.py`,
`bundle_verify.py`, `snapshot_loader.py`, and `bundle_store.py` implement the approved
`research-bundle-v1` offline format. Exact raw bytes, source descriptors, normalized records,
legacy manifest preimages, and the envelope are content-addressed and replay-verified.
Explicit coverage slots and membership baselines are source assertions, not authenticated
coverage or accepted research. Imported sources and unknown normalizer versions are rejected.

`BundleSnapshotLoader` implements the existing async snapshot interface without changing
application or runtime composition. Queries require visible complete bar/membership/action
coverage, visible baseline/event membership, and sufficient available completed bars. Only
unadjusted, non-interpolated histories without effective retained actions are supported;
spread remains unavailable. Hashes bind selected provenance and settings, so unrelated future
captures cannot rewrite earlier snapshot or feature identities. The loader is deliberately
not re-exported by `market_data/__init__.py`, preserving the application dependency direction.

Artifact storage requires an existing current-owner `0700` root outside the explicit repository.
Descriptor-relative no-follow reads and private `0600` regular files are bounded by explicit
limits. No-overwrite publication writes/syncs blobs before the envelope; retries verify existing
bytes and re-establish directory durability. A post-publication sync failure reports uncertainty
without deleting the complete artifact. There is no garbage collector or evidence-ledger write.
An in-memory synthetic integration test connects the real loader and feature pipeline to the
existing decision cycle with no strategies, no planned intents, and an execution stage that
raises if called. This is not production wiring or a complete paper, shadow, or live cycle.

### Existing foundation and operational composition

The repository is a paper-safe, fail-closed foundation, not a running trading system.
Implemented code is limited to canonical domain primitives and immutable cross-layer
safety attestations, strict configuration and hashing, capability evidence and sanitized
schema capture, least-privilege broker protocols, code identity, clocks, and structured
logging with pre-serialization redaction. It also contains an equity-only Robinhood Trading MCP
read adapter and one-shot connected-shadow probe. The connection owns a private encrypted OAuth
store. A connected run first verifies a canonical root-owned, non-writable release artifact binding
its immutable image ID, resolved configuration hash, Compose hash, and release key. The deployment
helper creates that artifact only after the paused candidate passes exact-image, configuration,
health, readiness-denial, and live-disabled checks; the default service never mounts it. The OAuth
client requests and pins the sole official `internal` scope; that bearer credential
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
