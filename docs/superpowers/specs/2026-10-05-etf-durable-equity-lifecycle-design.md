# Durable owned equity lifecycle

## Scope and authority

Continue the operator's native, uninterrupted ETF build. This coordinator-written
specification is not a newly operator-reviewed artifact. It implements the next
dependency of protected execution, not the whole live runtime. No broker/provider
calls, credentials, customer records, deployment, orders or risk changes are part
of this slice. All existing promotion and live blocks remain unchanged.

The existing accepted submission record is the ownership anchor. Independently
supplied broker history must never be adopted as local intent, and missing fees
must never be converted into the domain Fill's mandatory nonnegative fee.

## Design

Use the existing SQLite/Alembic ledger, UnitOfWork, OrderRow, FillRow and immutable
OrderTransitionRow. Preserve the original OrderRow and submission-response hash.
Add an append-only versioned owned-order event journal linking each fact to its
original order, its exact local transition, and optional provider-scoped fill.
Current order state is reconstructed, not independently overwritten.

An OwnedOrderEvent carries a bounded event identity, local order identity, exact
OrderEvent, UTC observation time, source hash, and optional complete Fill plus
native execution key and occurrence ordinal. Fill events require all fill fields;
control events require none. Only post-submission lifecycle events are admitted.
No nanosecond provider time is silently narrowed to domain microseconds.

The initial supported ownership anchor is an exact, locally submitted equity order
with zero fills and a complete durable intent/review/submission chain. Partial or
filled initial responses need a separately verified historical-intake path and are
denied here. Unknown acceptance is not adopted or retried.

Pure advancement uses the canonical state machine, checks all fill identities,
chronology and remaining quantity, and uses exact bounded Decimal arithmetic.
Partial/full events must agree with actual cumulative quantity. Cancel-pending
partial fills preserve pending cancellation. Terminal states cannot reopen;
duplicate facts remain idempotent even after terminality. Reconciliation events
cannot invent missing fills or quantities.

One unit-of-work transaction appends the journal, transition and optional FillRow.
The journal hash binds version, ordinal, previous head, canonical fact, and resulting
order hash. Recovery reparses canonical payloads, reconstructs every event, verifies
all transition/fill links, and denies omissions/conflicts. At most 10,000 events
per order and 16 KiB per payload are supported; exhaustion denies before mutation.
Provider execution keys and fill identifiers cannot be reused across orders.
Concurrent writers are denied by SQLite isolation and unique order ordinals;
there is no automatic retry or live-leadership claim.

Database guards prevent update/delete/REPLACE of the new journal and fill facts,
including ordinary raw-SQL insert conflicts and negative-rowid replacement routes.
The additive migration does not rewrite historical data. Production migrations
are not run under this development task.

## Read/reconciliation boundary

The order repository returns reconstructed owned orders; the fill repository
returns exact recorded fills with explicit account/time filters. Historical data
remain readable, but unowned or incomplete chains deny the owned-order API.
Local execution reads do not copy broker account/position snapshots, infer cash,
settlement, buying power or ownership, nor declare reconciliation clean. A later
trusted economic owner must supply independently reconstructed account/positions
and align the broker/local reconciliation window.

## Acceptance and limitations

Tests prove atomic rollback, exact repeated delivery, conflict denial, partial and
full fills, pending-cancel races, terminal closure, restart reconstruction,
provider/account/intent binding, altered journal/fill/transition denial, bounded
arithmetic, and database append-only behavior. Preserve overall 80% coverage and
add both new critical modules to the existing 90% branch gate.

Public parsers remain unqualified. No fixture establishes authenticated nonempty
broker mapping, final customer fees, causal quote/order clocks, accepted economics,
qualifying paper/shadow cycles or deployed recovery. The next dependency is a
verified provider mapping and fenced context/one-intent authorization composition,
not a direct app-tool trade around the execution owner.
