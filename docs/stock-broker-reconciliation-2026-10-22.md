# Dedicated equity account: read-only reconciliation checkpoint

Observed at **2026-10-22 04:50:35 UTC**, using the existing official interactive
Robinhood connection. This is independent of the restricted background research
client and does not establish its deployed authentication lifecycle.

Root performed three authenticated reads: account discovery, open equity positions,
and equity orders created at or after `2026-09-22T00:00:00Z`. Account discovery
identified exactly one caller-accessible, active, nondeactivated cash account.
Only that intended dedicated account was used for the position/order reads.
No account identifiers, credentials, balances or unrelated account records are
included in this checkpoint.

| Observation | Actual result | Scope of evidence |
| --- | --- | --- |
| Open equity positions | Empty array, no next cursor | Empty-state read only |
| Equity orders since the stated UTC boundary | Empty array, no next cursor | Bounded recent history, not all historical activity |
| Nonempty positions, fills and order reconciliation | Not observed | Remains unverified |
| Open tax lots | Not requested: no held symbol was returned | Remains unverified |
| Specific-lot execution selection | Not exercised | Readable lots or selectable flags do not establish allocation at execution |
| Background authentication after natural expiry/revocation | Not exercised | Interactive access does not establish unattended operation |

The selected connection currently declares position quantity/average-cost/hold
breakdowns, order lifecycle and execution details, and open-lot basis/acquisition/
availability fields. These are declarations, not authenticated nonempty-row proof.
Unknown or omitted basis and nullable executions must remain unknown. Sellable
quantity must use the broker's available-for-sale field rather than total shares.

The next native reconciliation check must use an existing position or known order
in this same account, privately retain its receipt and identity bindings, and verify
quantities, execution IDs/totals, fees and lifecycle state. Empty reads do not justify
creating a real trade merely to obtain a fixture. No order review, submission,
cancellation, transfer, account change or live activation occurred.
