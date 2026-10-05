# Independent ETF economic owner

## Intent and boundary

Continue the fixed ETF work after PR20 without another approval prompt under the
operator's standing native-build instruction. This coordinator-written specification
is not represented as a newly operator-reviewed artifact. Build independently
reconstructible local cash, shares, cash allocations, signed settlement obligations
and non-replenishing trial history. A broker observation never creates ownership.
Implementation and fixture evidence do not authorize or perform a real trade.

The reviewed starting base is `004390f0380d6fdb167271d0a847a3c0c43817e5`.
Reuse its accepted zero-fill lifecycle anchor, canonical configuration, UnitOfWork,
checked lifecycle arithmetic and `TrialEpisode`/`TrialLossState`. No dependency,
risk limit, strategy, live flag, production state or provider behavior changes.

## Supported local facts

One account and one equity instrument per owner, starting explicitly flat. Opening
cash and its independent source hash are supplied facts, not AccountRow balances.
Versioned immutable events have ID, UTC receipt time, source hash and configuration
identity. Payloads are opening cash, exact intent reservation, accepted zero-fill
order binding, an owned lifecycle event, explicit final aggregate fees, exact signed
obligation settlement, cash-allocation release, episode completion and signed
external funding. Each payload has a closed shape and exact canonical encoding.

Entry reservations bind the complete canonical intent, a nonnegative fee bound and
positive fixed episode risk reservation. The owner does not choose size or approve
risk: the existing pretrade engine remains mandatory. One incomplete episode, no
averaging down and no entry into held shares. Exits bind that episode and cannot
reserve more shares than are locally held and not already allocated to exits.
Unsupported market/stop orders, externally owned positions, initial partial/full
acceptance and history adoption deny. The original execution journal remains usable
independently for legacy records; no legacy history is rewritten or auto-adopted.

## Exact accounting and finality

Use checked `apply_lifecycle_fill` for actual share, provisional-fee and book-cash
deltas; its weighted-average price alone may round. Signed obligations preserve
both debit/payable and credit/receivable amounts, including explicit zero. Book cash
is settled cash plus all outstanding signed obligations. Sell receivables are not
spendable. A settlement supplies the exact outstanding obligation ID and signed
amount; duplicate/conflicting events are idempotent/denied before arithmetic.

Pending cash holds are remaining buy limit notional plus remaining fee capacity;
sell cash holds are remaining fee capacity. Outstanding payables are held separately.
Actual fees above the bound or negative settled/book cash deny. Partial fills reduce
only actual remaining quantity and fee capacity. Cancellation, expiry, rejected
cancel and uncertain state never release an allocation. Explicit release requires
terminal owned execution state, explicit final aggregate fees and settlement of
every recorded fill/fee-adjustment obligation. Final aggregate fees cannot be below
already recorded charges or above the frozen bound; refunds need a future explicit
credit contract rather than being inferred.

Trial reservation is fixed for the entire episode, independent of cash allocation.
Completion additionally requires a flat position, all episode orders released and
an explicit income/finality source fact. Absence of dividend/fee markers is not that
fact. Convert complete episode histories through existing `TrialLossState`; profits
and external funding never offset or reset previous losses. New funding changes
cash only and withdrawals cannot consume held cash. These typed finality assertions
are not authenticated customer evidence; source/cost/execution/promotion eligibility
is permanently false in this milestone. No input hash can change those flags.

## Durable joint publication

Add an account-scoped economic hash-chain table using additive migration0010 and
the existing UnitOfWork session. No second transaction owner. Pure projection and
canonical payload decoding remain independent of persistence/service bootstrap.
The account sequence is bounded at10,000 events; payloads at16KiB; exceeding a bound
denies rather than truncating history. Registered-secret identifiers are screened
before encoding/staging and on recovery; errors use a stable sanitized reason.

For execution facts, validate the economic projection first, then stage the existing
owned execution event and its economic counterpart in the same transaction. Bind
the exact owned-event ID, canonical payload, intent and order. Recovery verifies
that every event of each bound order has exactly one counterpart and rejects
missing/orphan/cross-account links. Exact retries must verify both sides, not merely
skip after the existing writer returns False. A failed joint append rolls back the
session, so catching an exception cannot commit half of the economic/execution pair.
No automatic retry, leadership fence or concurrent live-writer claim is introduced.

Append-only UPDATE/DELETE/REPLACE and rowid-collision guards match existing patterns;
downgrade refuses nonempty economic history. Process crash tests demonstrate old or
complete new local prefixes, never half a joint publication. Complete database
rollback still needs an independently retained trust anchor; local hashes cannot
prove it absent. Existing production migration, encrypted restoration and deployed
recovery are not performed or certified here.

## Acceptance and remaining dependency chain

Hand-derived buy/partial/cancel/sell/fee/settlement expectations, conflicting retries,
double reservations, stale/corrupt links, unknown acceptance, finality/withdrawals,
non-replenishment, two-engine restart, caught-error rollback and real SIGKILL cases
must pass. Enroll all new critical modules in unchanged90% branch checks and retain
80% overall coverage. Run complete regression/native coverage, Ruff, Mypy, Bandit,
both frozen locks/advisory audits, temporary-output SBOM and deployment manifests.
Obtain one independent whole-branch review and actual exact-head CI before merging.

After this milestone: independently admitted source genesis and authenticated
nonempty provider mapping, fresh initial/final risk context, exact preview/one-use
confirmation and fencing, causal quote/order/final-fee capture, qualified historical
execution and accepted economics, eligible paper/shadow time and standalone recovery.
These remain separate; the owner's existence is not live readiness or profitability.
