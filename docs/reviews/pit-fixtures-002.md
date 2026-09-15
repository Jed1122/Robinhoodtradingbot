# PIT-FIXTURES-002: point-in-time membership fixture review

## Scope and disposition

This review is limited to deterministic synthetic tests of the existing
`UniverseMembership` and `PointInTimeUniverse` public behavior at base commit
`93b28f484f1968f415d2d765a2d50143831ad3e4`. It does not change production code, select or
validate a provider, establish dataset completeness, generate eligible trading evidence, or make a
promotion decision.

**Subsystem classification:** partial and promotion-blocked. The lookup primitive implements useful
announcement-time and effective-time filtering, event replay, and an explicit global
`history_complete` eligibility reason. Those behaviors are not a provenance or coverage system.

**Dependency chain and critical path:** source identity and licensed immutable event records ->
explicit temporal and instrument coverage -> validated event timestamps and conflict rules ->
point-in-time lookup -> research manifest binding and independent review. The missing source and
coverage evidence is the critical path; additional primitive tests cannot supply it.

## Observed behavior covered by the synthetic contract tests

The tests independently specify literal UTC inputs and expected member tuples. They demonstrate:

- an event is invisible until both its announcement and effective timestamps are at or before the
  query timestamp, including an inclusion whose announcement arrives after its effective time;
- inclusion is visible at the exact qualifying boundary, removal changes only its own instrument at
  the removal boundary, and a later inclusion can re-enter that instrument;
- separate instruments evolve independently and returned identifiers are sorted deterministically;
- reordering events that have distinct ordering keys does not change the answer;
- repeated calls over the same immutable inputs agree; and
- empty complete history returns no members and no reason, while `history_complete=False` returns
  `point_in_time_universe_unavailable`.

Setting `history_complete=True` in a synthetic test exercises only the primitive's declared branch.
It is not evidence that any real dataset has complete constituent, removal, delisting, or temporal
coverage.

## Remaining evidence boundaries

The interface has no source identifier, raw-record hash, license identity, collection timestamp,
coverage start/end, covered instrument or venue scope, gap representation, or per-interval
completeness status. Consequently it cannot demonstrate that absence means non-membership rather
than missing history, and its single caller-supplied boolean cannot establish source provenance or
complete interval coverage. No external data or production payload was inspected for this task.

The public values also do not validate timestamps. A naive query against UTC fixture events raises a
standard-library `TypeError`; non-UTC aware timestamps can compare by absolute instant; and no
domain-specific invalid-time contract is exposed here. These observations should not be interpreted
as an accepted validation policy.

Equal-key conflicting events are ambiguous. If two events for the same instrument have identical
`effective_at` and `announced_at` values but opposite `included` values, Python's stable sort leaves
their input order as the deciding factor. This makes logically equivalent input collections capable
of producing different answers. A minimal local reproduction is:

```python
from datetime import UTC, datetime

from trading_bot.domain import InstrumentId
from trading_bot.market_data import PointInTimeUniverse, UniverseMembership

at = datetime(2024, 1, 1, tzinfo=UTC)
add = UniverseMembership(InstrumentId("SYNTH-ALPHA"), at, at, True)
remove = UniverseMembership(InstrumentId("SYNTH-ALPHA"), at, at, False)
PointInTimeUniverse((add, remove), history_complete=True).members_at(at)  # ()
PointInTimeUniverse((remove, add), history_complete=True).members_at(at)  # (InstrumentId("SYNTH-ALPHA"),)
```

The contract needs an explicit rejection or deterministic conflict-resolution rule before this case
can be regression-tested as valid behavior. The test suite therefore covers reorder invariance only
for events with distinct ordering keys and does not encode the current ambiguous result as correct.

## Assumptions and unperformed verification

- Synthetic identifiers and timestamps test lookup mechanics only; they say nothing about an
  authoritative universe, source selection, licensing, survivorship bias, or external validity.
- The fixture assumes unique event ordering keys. Duplicate/conflicting event validation remains
  unspecified.
- Authenticated calls, broker/provider access, credentials, accounts, production ledgers, external
  datasets, deployment, live controls, and promotion evaluation were not used or performed.
- A future evidence contract must bind source provenance and explicit coverage intervals and fail
  closed on gaps before any dataset can truthfully set completeness or research eligibility.

## Central integration verification

The primary reviewed the complete two-file Cloud diff and ran the existing and new universe tests:
18 passed. Ruff passed for the new test file. Only imports were added to the documented conflict
reproduction during integration. Verification used the existing clean locked Python 3.12.13
environment with `PYTHONPATH=src` from the implementation worktree; no authenticated checks ran.
The Cloud CLI supplied a ready diff but did not expose its local commit or full command transcript,
so these results are central verification, not a claim about an unobserved Cloud test run.
