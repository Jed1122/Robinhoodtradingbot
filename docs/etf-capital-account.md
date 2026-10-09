# Capital research account boundary

Status: funding, strict account and v2 synthetic checkpoint/marked-risk/prefix
composition released through PR29/PR30. Separate opt-in v3 corporate-action
accounting is locally certified; its hosted release remains pending. See
[Action-account boundary](etf-capital-actions.md). Action-aware risk/admission,
joint risk/account/action recovery and the economic evaluator are **not
implemented**. No operational readiness is asserted.

`simulation.etf_capital_funding.capital_order_reservation` validates original
broker-neutral LIMIT order records and explicit bounded whole-episode fee facts.
It reserves remaining BUY limit notional for pending, partial, cancel-pending and
unknown/reconciling orders. A terminal order releases only unfilled notional.
Unused episode fees remain reserved until explicit finality and flat holdings.
An active SELL cannot request more remaining shares than the supplied holdings;
it does not consume BUY notional. Input identity includes the complete order,
fee bound/charged fees/finality and held quantity even for equal reservations.

`capital_available_cash` subtracts explicit unsettled sale proceeds and one
current reservation from total economic cash. Insufficient or invalid balances
deny rather than clamp to zero. These are fixed-context Decimal calculations;
they are not a second risk engine, configuration loader or trading authority.

Literal fabricated example:100 initial cash,0.2-share limit100 and0.10 episode
fee bound reserve20.10. A0.1-share fill at99 with0.04 fee leaves90.06 cash and
10.06 reservation,80.00 available. Confirmed cancellation releases10 unfilled
notional but retains0.06 episode fees, leaving90.00 available. A0.1-share sale
at101 with0.05 fee yields100.11 economic cash,10.05 unsettled proceeds and0.01
unused fee capacity:90.05 available. After explicit settlement and final fees,
100.11 is available. Fees total0.09 and synthetic ending-cash delta0.11.
No real fill, fee or settlement has been observed or asserted here.

The output is informational, with permanently false execution/promotion flags.
Its hash is not authenticated account evidence. A future authoritative owner
must recompute it from validated current events, never adopt a caller's declared
reservation. This function does not validate account-wide completeness,
instrument increments, live capability, strategy selection, market sessions,
freshness, cash floors, loss limits, cancellation ownership or settlement source.
Those independent checks remain necessary; no order factory is introduced.

## Next steps

The new `replay_capital_account` recomputes one cash account from at most4096
original typed events, never from caller-declared balances or reservations.
Orders use a research-only instrument namespace and the existing lifecycle
transition/fill accounting. It denies additions, overlapping active orders,
oversells, account/basis changes, conflicting duplicates, stale events and
unsupported symbols. Explicit sale-fill settlement and matching whole-episode
fee finality are necessary to release obligations. Pending, partial and terminal
incomplete histories remain incomplete; input end never forces a fill.

Thirty-eight synthetic controls include independent cash expectations and a
separate-process reconstruction of partial, sold-unsettled and completed prefixes.
This is not durable checkpoint restoration or deployed recovery: those controls
reconstruct supplied fixtures, not a production store or broker observations.
The reducer has no canonical entry-approval or cost/source-qualified verdict.
It is not directly consumable by an execution service. Hashes are structural,
not authentication. All execution/promotion flags remain permanently false.
Accepted identifiers are bounded consistently to256characters, including sale
fill references, so every admitted sale can be explicitly settled. The reducer
replays each current-order prefix; this deliberate reuse has superlinear cost.
A representative performance gate and incremental shared seam remain deferred
before economic-evaluator integration, not a deployed-runtime performance claim.

Finish exact-source integrated verification/review. Then compose canonical sizing,
current-equity loss latches, explicit marks, split basis/distribution entitlements
and versioned bounded checkpoints with this account reconstruction.
Only then compose the approved three strategy families and purged walk-forward
economic evaluator. Source acceptance, actual costs, prospective final testing,
trusted paper/shadow and deployed recovery remain separate unfinished stages.
Production limits/defaults are unchanged; live remains disabled.

## Versioned episode finality

Current account replay uses the explicit `capital-account-event-v2` and
`capital-account-replay-v2` namespaces. `CapitalEpisodeFeesFinal` binds final
fees to the account and its unique opening order; equal amounts from another
account or earlier episode cannot release this episode's reserve. Both optional
submission identifiers (`intent_id`, `client_order_id`) use the same256-character
bound before serialization/hashing in current replay; absent identifiers remain
absent. The submission record retains the historical construction shape. The
explicit v1-only reader preserves previously valid longer optional identifiers
and their original hashes; no current owner accepts that compatibility path.
Standalone funding validates all six order identifiers before hashing. Its
private legacy arithmetic seam is used only by explicit historical replay, not
exposed as a permissive option on the public funding API.

Historical `CapitalFeesFinal` records and their dataclass shape remain intact.
Only the explicitly historical `replay_capital_account_v1` reader accepts them
and preserves valid original v1 hash preimages. Current replay rejects unbound
legacy completion, and the historical reader rejects v2 completion. Neither
reader grants execution, promotion, authenticated account evidence or a broker
final-fee completeness claim. Checkpoint/risk descendants must be re-composed
against this new strict contract before their old certification can apply.

## Synthetic account checkpoints

The separate `advance_capital_account_checkpoint` API binds canonical research
configuration, declared code identity, initial capital and the complete original
typed event tape. It reconstructs every committed prefix before comparing the
stored envelope byte-for-byte; saved balances never become authority. Exact
retries are idempotent. Earlier cursors, stale expected heads, altered owners,
corruption and unknown filesystem entries deny.

Storage uses the existing private descriptor-bound no-overwrite publisher,
current-user ownership, 0700 directories and 0600 files outside the repository.
A non-waiting local writer lock covers reconstruction and publication. Input
and envelope admission is jointly bounded to 8 MiB; directory occupancy is
bounded to 64 MiB and 8196 names, including retained internal staging aliases.
Projected initial owner and checkpoint publication must fit before either write.
Recognized staging files are verified and retained, never deleted or adopted.
External hardlinks and unresolved aliases deny. Two real local SIGKILL controls
cover immediately before and after checkpoint linking; they do not establish
deployed recovery, multi-host fencing, alerts or backups.

This increment is synthetic and offline. Caller-declared code hashes are not
executable authentication. Original inputs must be resupplied on restart; the
store is not a market-data archive, authenticated observation reader or forward
paper owner. Source, costs, execution and promotion remain unqualified. Complete
critical review and release verification before composing risk/actions and
strategy economics with these checkpoints.

## Synthetic marked loss composition (partial)

`replay_capital_risk` reconstructs original account prefixes and explicit assumed
marks before applying the existing canonical purpose-aware loss evaluator.
Held shares without a positive mark deny; flat valuation is reconstructed cash.
Daily and weekly reset declarations are synthetic inputs, not reconciliation
attestations. New UTC windows use the preceding observed NAV so overnight gaps
are not absorbed by resets. Weekly breaches require a reviewed new-week reset;
drawdown remains latched. Loss percentages round upward to 18 decimal places
in whole-percent units, using a fixed Decimal context.

Completed flat, settled, final-fee episodes update the consecutive-loss streak.
Observation jumps consume every intervening original prefix, and the final
completion event sets the loss clock. Repeated observations neither recount
episodes nor extend the pause. Positive completed episodes clear the streak;
this does not replenish the separate non-replenishing trial budget.

`evaluate_capital_entry` first reconstructs loss state and denies incomplete
episodes, including pending unfilled orders or unresolved settlement/final fees.
It then reuses current-equity research sizing and declared instrument/fee terms.
It does not accept saved balances or caller risk decisions as authority.

This is not complete Task 5: split basis, distribution entitlement/payment,
durable joint risk/account recovery, representative replay performance and
economic evaluator integration are unfinished. Marks, resets and source coverage
remain unqualified assumptions. No production consumer or broker capability is
added; execution and promotion remain permanently false.

## Shared original-prefix reconstruction

`replay_capital_account_prefixes` uses the same account transition reducer once
for the complete original tape. It returns genesis and one immutable result per
supplied event, including identical results for exact duplicate delivery. Invalid
late inputs fail the entire call; no valid partial tuple escapes. The current
replay API is strict v2; the explicit historical v1 reader preserves the original
v1 hash preimages. Historical unbound fee completion cannot feed current risk or
checkpoint reconstruction.

Marked risk and checkpoint reconstruction consume this internally reconstructed
tuple instead of replaying every complete account prefix. Stored envelopes,
source clocks, exact retry rules, alias admission and private-publication bounds
remain unchanged. This is not incremental adoption of caller or persisted state.
Current-order lifecycle prefixes and prefix hashing still have superlinear cost;
the change removes an additional nested replay layer, not all performance work.
Representative synthetic timing is not runtime or economic qualification.

Risk observation boundaries use effective unique-event clocks reconstructed from
the validated account prefixes, not raw delivery adjacency. Repeated old events
cannot backdate future state or falsely deny a current observation. Distinct
events at the same timestamp still form a real chronology boundary.

## V2 descendant storage separation

Current checkpoint inputs, owner and envelope schemas use v2 namespaces and the
`capital-account-checkpoints-v2` directory. Current risk results use the
`capital-risk-replay-v2` namespace. Existing v1 directories are not adopted,
migrated or modified. This increment does not add a legacy persisted-checkpoint
reader; the explicit v1 account-event reader remains available for historical
event evidence. It is not a joint risk/actions restart implementation.
