# Capital research action accounting — partial implementation

Current follow-on: shared v3 prefixes and action-aware risk/joint reconstruction
are released through PR32/PR33; corrected signal/admission PR34 is merged atf1326c9.
Fixed-original-input joint checkpoint reconstruction passed independent review,
9,804 full/20 native tests and92.10% combined coverage at0a4ff8d, including the
unchanged80overall/90critical gates. This follow-on is merged, not deployed.
Representative replay and local SIGKILL checks are synthetic;
economic execution/evaluation and genuine source/cost evidence remain unfinished.
Older remaining-work paragraphs below describe prior source increments only.

PR31 is released at678f3d2f51a752a8d08c36e20c97379fed84e324 after9,763 full
tests,20 native tests,92.07% combined coverage, unchanged80overall/90critical
gates and all14 current hosted jobs. Both implemented findings were resolved.
Earlier release-pending paragraphs below are retained historical checkpoints.

The separate `replay_capital_action_account_prefixes` API reconstructs genesis
plus one immutable v3 result per original delivery, including duplicate-aligned
snapshots, through the same reducer once. Whole-tape validation finishes before
the tuple returns; an invalid late event denies the entire call. It accepts no
saved account state. Existing v1/v2 APIs and hash preimages remain unchanged.
This increment is under verification, not yet released or consumable by a trusted
risk/checkpoint owner. Prefix hashing/order-local replay still has superlinear
cost; no linear-performance or operational recovery claim is made.

The opt-in `replay_capital_action_account` API uses the same original-event
account reducer as strict v2 replay, with distinct v3 event/replay identities.
Existing v1/v2 readers, outputs and hash preimages remain unchanged. They reject
the new action types. This is declared synthetic accounting, not source
qualification, broker observations, an economic study or execution authority.

`CapitalSplitApplied` binds account, opening order, symbol, action identity,
source-record hash, ratio and post-action mark. Held quantity changes by the
ratio; average basis changes reciprocally. Cash and total basis are conserved.
Only exactly representable, bounded Decimal results are supported. Repeating
basis, residual-share rounding and cash-in-lieu are unsupported and deny.

`CapitalDistributionEntitled` binds a declared per-share amount, ex-date mark
and payment date to that same episode. Entitlement and mark apply atomically:
cash90.06 plus0.1shares at98 plus0.10receivable gives99.96 marked equity.
The receivable is not spendable cash. A lower ex-mark retains the real price
loss rather than clamping it away. Flat observations invent no entitlement.

`CapitalDistributionPaid` references the original entitlement and exact amount.
Payment before its declared date, unknown or repeated payment, wrong account,
episode or symbol denies. Payment transfers receivable to cash without changing
shares or reinvesting. Exact duplicate delivery is idempotent. Distinct events
reusing an action identity or conflicting event identity deny.

Date comparison currently uses the declared UTC cursor date. This is a synthetic
ordering assumption, not broker settlement/calendar verification. A future
session-aware owner must bind qualified calendar facts before use.

Unpaid entitlements survive a sale. Completion and fee-reserve release wait for
payment, sale settlement and the existing episode-bound final-fee event. There
is no automatic payment-tail extension or forced final event. Split-adjusted
holdings/basis can feed a new explicitly supplied sell request; original order
records are never rewritten. Actions and payment during active orders are
unsupported and deny. Old fills cannot resume after an applied split.

The v3 output adds average basis, distribution receivable and an optional mark
and marked equity. Held shares without an explicit valid mark remain unknown;
a fill invalidates an older held mark. Flat valuation includes outstanding
receivables but never makes them available for an entry. Marks, dates, source
hashes and completeness are declarations, not authenticated facts. All source,
execution and promotion flags remain permanently false.

## Remaining work

A later PR31 finding identified invalid intermediate marked equity being hidden
by subsequent actions. Two synthetic regressions were watched RED; valuation is
now bounded after every unique v3 event as well as at snapshot.356 focused tests
pass, but fresh full/native/hosted certification is still required. The preceding
mark-preservation source completed9,761full/20native/92.07% and critical gates;
that certification is historical after this new correction. No economic or
operational qualification follows from either correction.

PR31's subsequent review reproduced six failures: accepted/cancel controls
incorrectly discarded explicit action marks while holdings were unchanged. The
correction retains those declared marks across non-fill controls, but every
fill still invalidates them; this is not fresh-quote evidence. Source changed,
so current full/native/hosted certification must be completed anew. The following
counts belong to the earlier source, not the corrected candidate.

Corrected source `01c51ad3c57dca29206ebc95c79d03f01c69966d` passed9,754 full
tests (33 optional skips and one existing warning),20 native tests and92.07%
combined coverage; unchanged80%overall/90%critical gates passed. Independent
review's aggregate-receivable bound finding was fixed with watched RED/GREEN
controls before the corrected full run. Static, lock, SBOM, advisory and manifest
checks passed. Hosted release remains pending; these are synthetic software
checks, not data qualification or deployed recovery.

V3 original-prefix and shared marked-risk
composition, durable joint account/action/risk checkpoint restoration and
representative performance are not implemented here. Existing v2 risk and
checkpoint owners reject action events. Existing persisted directories remain
untouched and are not adopted or migrated; a historical persisted-checkpoint
reader remains separately unfinished. The approved strategy/fold/economic
evaluator and executable study freeze follow those prerequisites. Production
configuration, live activation and risk limits are unchanged.
