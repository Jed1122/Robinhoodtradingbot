# Independent local ETF economic owner

This credential-free slice records explicit local economic facts beside the owned
execution journal. It does not wire a broker, admit customer evidence, qualify a
strategy or enable execution. Alpaca remains the selected data channel and
Robinhood the execution target; neither is called by this owner.

## API and accounting

`uow.economics.append(EconomicEvent) -> bool` stages a closed, versioned fact in
the existing UnitOfWork. `get(AccountId) -> EconomicState | None` reconstructs the
complete local history; missing history remains `None`, not a zero-cash account.
The caller commits once. Exact repeated facts return `False` only after recovery
verifies both economic and execution counterparts. Conflicts deny and latch the
transaction failed, including when an exception or cancellation is caught.

`Opening`, `Reserve`, `Bind`, `Execution`, `FinalFees`, `Settlement`, `Release`,
`Complete` and `Funding` are immutable payloads. Opening is explicitly flat, with
one equity instrument and one account. Reservations contain the entire canonical
limit intent, a bounded fee allowance and caller-supplied fixed episode risk.
This records risk allocation; it does not approve size or replace pretrade risk.
One incomplete episode is allowed. No averaging down or more reserved exit shares
than independently held shares. Market/stop orders, initial partial/full responses,
preexisting positions, history adoption and fee refunds are unsupported.

The existing checked lifecycle arithmetic accounts for shares and provisional
charges. Book cash equals settled cash plus signed outstanding obligations. Buy
payables and remaining notional/fee capacity are unavailable; sell receivables are
not spendable until exact signed settlement. Explicit zero differs from missing.
Only weighted-average execution price may round; other money calculations use
checked 28-digit Decimal arithmetic. Position market value uses the last execution
price, not a current executable liquidation quote.

Terminal execution alone never releases an allocation. Release additionally
requires explicit final aggregate fees and settlement of every recorded obligation.
Additional fees cannot exceed the frozen bound; their stable bounded identity is
derived from the fee event and order. Episode completion requires flat shares,
all episode allocations released and an explicit finality assertion. Profits and
funding never replenish prior completed losses or the non-replenishing trial budget.
Funding changes cash only; withdrawal cannot consume held cash.

## Durable publication and boundaries

Migration `0010_owned_economics` adds an append-only account hash chain and links
to canonical intent, accepted order and exact owned execution facts. Original
accepted response hashes and legacy records remain unchanged. Recovery verifies
all facts of every bound order against their economic counterparts. Missing,
orphaned, corrupt, advanced-before-bind or mismatched links deny; nothing is adopted
or automatically retried. Other accepted but unbound legacy orders are outside
this projection, so it is not account-wide completeness evidence.

The offline fixture anchors are accepted before economic reservation. They test
historical local reconstruction, not pre-send reservation chronology. A future
protected writer must reserve before transmission and establish authenticated
genesis, finality, fresh risk context and exclusive authority independently.

Both journals publish in one existing session/transaction. Four staged-error and
three real SIGKILL controls exercise failure after owned/economic flush and after
commit; recovery returns old or fully paired new state. Independent-engine tests
preserve final fees, pending settlements, shares and completed losses through later
profitable episodes and deposits. These are fictional local tests, not deployed
recovery, final customer charges or qualifying paper/shadow observations.

The history bound is 10,000 events per account, 16 KiB per canonical payload.
Exact-bound history is fully reconstructed; new events beyond the bound deny,
never truncate. Appends replay prior history and are not amortized ingestion.
UPDATE/DELETE/REPLACE/rowid-collision protections and nonempty-downgrade refusal
are additive. Registered secret material is screened before encoding/staging and
on recovery; failures use `owned_economics_invalid`. No production migration ran.

There is no live lease, multi-host fencing or account-wide writer integration.
SQLite serializes conflicting appenders without automatic retry. Removing guards
and restoring a complete database prefix requires a separately retained trust
anchor to detect; local hashes cannot prove rollback absent. Backup/deployed
restoration must be separately validated against an actually migrated ledger.

Source qualification, cost qualification, execution enabled and evidence promotion
are permanently false. Typed source hashes/finality assertions are integrity facts,
not authenticated evidence; valid settlement cannot change those flags.

## Remaining prerequisites

1. Independently admitted source genesis and authenticated nonempty broker mapping,
   including actual fee finality and settlement semantics.
2. Protected pre-send reservation, exact intent/preview and one-use confirmation,
   fresh final risk checks, fencing and ambiguous-acceptance reconciliation.
3. Genuine execution, matching Alpaca quote/order clocks and reconciled final fees.
   This feature cannot manufacture or certify a sample, and places no test trade.
4. Complete historical execution coverage and accepted after-cost/uncertainty results;
   engineering fixtures and an execution sample do not establish profitability.
5. Trusted paper/shadow composition, genuinely eligible elapsed observations and
   independently verified standalone runtime recovery. Diagnostics do not count.

All existing risk, kill, reconciliation, economic and live gates remain intact.
