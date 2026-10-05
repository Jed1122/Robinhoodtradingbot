# Durable owned equity lifecycle

This slice adds credential-free order/fill persistence behind the existing
UnitOfWork. It does not enable a provider transport or live execution.

`orders.record_event(OwnedOrderEvent)` accepts an explicit post-submission fact
only after checking a durable local intent/review/accepted-submission chain. The
initial supported anchor is an equity order acknowledged as submitted with zero
fills. Initial partial/full responses, unknown acceptance and unowned/external
orders deny; a later verified intake must handle those cases without inventing
ownership or retrying the submission.

The pure `domain/owned_order_lifecycle.py` contract uses the canonical state
machine and exact Decimal quantities. Actual fill identities, chronology, limit
price and cumulative partial/full quantities are checked before staging. Every
fill requires an explicit fee; unknown charges cannot be represented as zero.
This API's typed inputs are local facts, not attestations of customer provenance,
fee finality, broker timestamp meaning or execution eligibility.

The same transaction publishes an append-only journal fact, transition and
optional provider-scoped FillRow. Exact repeated delivery is idempotent before
terminal-state evaluation; conflicting IDs, native keys or ordinals deny. The
original OrderRow and submission-response hash are unchanged. Current order
state is returned by `orders.get_broker_order`; complete fact/transition/fill
links and hashes are replayed before returning it. Pending cancellation remains
pending through a partial race fill, and terminal states cannot reopen.

Recovery reconstructs the full canonical intent and review, verifies all three
review binding hashes, and validates the submission/review time window. If an
original acceptance transition is present, only one exact execution-owner record
is allowed, bound to the intent, config, correlation, original completion time,
actor and reason. Unrelated, duplicate or future-dated acceptance records deny.
A zero-fill anchor must have no average fill price. An order with any recorded
fill cannot reconcile to submitted or rejected; a failed reconciliation preserves
the prior unknown state and actual fill history instead of masking execution.
`RECONCILE_PARTIAL` and `RECONCILE_FILLED` may carry an explicit newly discovered
fill with its native key and contiguous ordinal. The full cumulative quantity
must match the target state. Existing control-only reconciliation records remain
readable, but cannot invent missing execution. Registered secret material in
event/fill/native identifiers is denied before encoding or staging, and screened
again on owned recovery; the pure codec has no credential-registry dependency.

`fills.get` and `fills.list_for_account(account_id, since)` read exact persisted
domain records. They do not attest ownership, authenticity or completeness of
legacy fills. The explicit time filter must eventually align with the broker
reconciliation window; no concrete account/position reconstruction is supplied.
Each account/time read returns the complete filtered result up to an independent
10,000-fill bound, or raises a sanitized error; it never returns a truncated
history. A busy interval requires future trusted window/pagination composition,
not treating the bounded prefix as complete. No production reconciler is wired
to this reader in this slice.

Migration `0009_owned_order_lifecycle` adds the journal and immutable-fill guards,
without rewriting historical records. UPDATE, DELETE, REPLACE and negative-rowid
replacement are denied. Downgrade refuses a nonempty owned journal. No production
migration or deployment occurred. Existing ledger backup includes the new table
only when a separately authorized migrated ledger is backed up.

## Bounds and recovery

At most 10,000 events per order and 16 KiB per canonical payload are supported.
Reads and appends replay at most that bounded prefix. Repeated appends are not
amortized streaming ingestion; heavy research stays separate. A conflicting
concurrent writer fails through SQLite isolation/unique ordinals, without retry.
This is not a live execution lease or multi-host writer fence.

Corrupt/missing individual journal, fill and transition links deny reconstruction.
Ordinary application/database mutations are guarded; a database owner who removes
all complete suffix effects or restores the entire database is outside this
boundary. Detecting full rollback requires an independently retained trust anchor.
Local independent-engine/process tests are not deployed-host recovery evidence.

## Remaining protected-execution dependencies

1. Joint economic ownership: independently reconstruct cash, positions, reservations,
   settlement and trial history atomically with execution effects; never release
   an allocation merely because an order became terminal.
2. Authenticated nonempty history/position and provider write semantics, exact intent
   and preview matching, and final-fee source semantics. Declaration fixtures remain
   unqualified and the existing empty-only adapter remains locked.
3. Concrete fresh initial/final risk context, live leadership/fencing, protected
   one-intent diagnostic authority, unknown-acceptance reconciliation and recovery.
4. An admissible diagnostic lifecycle with genuine Alpaca quote/order clocks and
   final fees. The conditional one-trade grant is recorded, but there is no trade
   or calibrated sample here. Order policy/limits and mandatory preview confirmation
   must not be bypassed to create one.
5. Complete execution inputs, honest after-cost results, trusted qualifying
   paper/shadow composition and independently verified standalone runtime recovery.

All live, research acceptance and promotion blocks remain unchanged. No profitability
claim is made.
