# SNAPSHOT-DATA-TESTS-004 review

## Scope and identity

- Worker contract: `SNAPSHOT-DATA-TESTS-004`.
- Verified base SHA before work: `5178406cdd65fc4f03f37fdafd8d857116d58075`.
- Checkout observed before work: branch `work`, clean worktree, with `HEAD` exactly equal to the
  required base SHA. Because the exact revision matched and the checkout was clean, no detach,
  rebase, branch alteration, push, external write, or integration-branch operation was performed.
- Subsystem classification at the verified base: implemented production snapshot loader with an
  independently unverified Cloud test contract. This review tests only the offline synthetic data
  selection boundary; it is not a release, promotion, source-trust, paper, or live-readiness review.
- Owned paths changed:
  - `tests/unit/market_data/test_snapshot_data_contract.py`
  - `docs/reviews/snapshot-data-tests-004.md`
- Read-only production dependencies remained unchanged. No shared fixture, configuration, lockfile,
  provider, broker, persistence, runtime, strategy-selection, pricing, sizing, exposure, risk, or
  promotion code was changed.

## Dependency chain and critical path

The exercised dependency chain is synthetic row dictionaries -> `SourceCapture` ->
`assemble_bundle` -> `verify_bundle` -> `BundleSnapshotLoader.load` -> existing validated snapshot
and historical-slice values. The critical path is verification of a fully bound synthetic bundle
before conservative as-of selection; the tests do not bypass verification or construct
`VerifiedBundle` directly.

## Test proposal and cases

The owned file collects **21 deterministic, default-marker test cases** and uses only inline,
synthetic fixtures. It covers:

- two-instrument requested ordering, exact selected closes, absent spread, and order-sensitive
  snapshot identity;
- baseline inclusion, visible removal and reinclusion events, both announcement and local
  availability clocks, explicit exclusion denial, and no silent universe shrinking;
- late selected bars, insufficient history without padding, missing/late baseline, late coverage,
  and declared gap/unknown coverage denials;
- successful complete no-action coverage with unadjusted, non-interpolated bars;
- interpolation, adjusted basis, unknown basis, split, and dividend denials, including an action
  whose publication is later than the requested snapshot;
- a disjoint future synthetic source that changes bundle identity but leaves the earlier snapshot
  and feature value/hash unchanged; and
- a selected-source limitation identity change that changes snapshot identity while preserving
  prices.

The tests inspect selected instrument order, bar values, timestamps, absence of spread,
interpolation flags, snapshot equality/inequality, and feature equality rather than treating the
mere presence of a hash as sufficient evidence.

## Commands and observed results

Initial identity inspection:

```text
$ git rev-parse HEAD
5178406cdd65fc4f03f37fdafd8d857116d58075
$ git branch --show-current
work
$ git status --short --branch
## work
```

Final required verification:

```text
$ uv run pytest tests/unit/market_data/test_snapshot_data_contract.py -q
.....................                                                    [100%]
21 passed in 1.17s

$ uv run ruff check tests/unit/market_data/test_snapshot_data_contract.py
All checks passed!

$ uv run pytest tests/unit/market_data/test_snapshot_loader.py -q
.................................                                        [100%]
33 passed in 1.29s
```

During test construction, the first owned-file run reported `3 failed, 18 passed`: the new inline
helper used source identifiers that differed from its synthetic bars' `source` values. This was an
owned-fixture defect, correctly rejected as `bundle_scope_mismatch`, not a production defect. The
helper was corrected to copy input rows and bind each synthetic bar to its descriptor's source ID.
No production behavior or expectation was weakened.

## Assumptions and findings

- The frozen async loader signature, properties, error codes, snapshot/history shapes, and hash
  behavior are treated as authoritative; no private production helper is asserted as an interface.
- A complete corporate-action coverage declaration containing no action is the valid no-action
  control. It is not evidence that a source is authentic or that its history is complete outside
  the declared synthetic interval.
- A missing bar within complete declared slots cannot form a verified bundle under the upstream
  verifier. Loader-level unavailable-record behavior is therefore challenged with a retained bar
  whose availability is later than `as_of`; insufficient-history behavior is challenged separately.
- Feature comparison is an identity-invariance control using the existing deterministic pipeline,
  not strategy selection or a performance claim.
- Identified production defects: **none** in this scoped run.
- Unresolved scoped blockers: **none**.
- Broader verification, integration, and any release decision remain primary-owned. This review
  does not establish source authenticity, research acceptance, promotion eligibility, or live
  readiness.

## Disposition

**READY_FOR_INTEGRATION** as a scoped synthetic test proposal only. The primary must inspect the
complete diff and rerun central checks before integration. This disposition is not release or live
readiness.
