# DATA-BUNDLE-TESTS-004 review

## Scope and identity

- Worker contract: `DATA-BUNDLE-TESTS-004`.
- Verified base SHA: `5178406cdd65fc4f03f37fdafd8d857116d58075`.
- Initial checkout branch reported `work`; `HEAD` exactly matched the required base and
  `git status --short --branch` reported only `## work`, so no detach, rebase, branch change,
  push, or external write was performed.
- Subsystem status at the verified base: production bundle models, codec, normalizer, verifier,
  and loader were present; this independently owned integrity test surface was unverified.
- Dependency chain and critical path: synthetic capture bytes -> public bundle assembly ->
  canonical envelope plus exact-byte blobs -> public verification -> immutable verified values.
  The tests mutate one binding layer at a time while leaving production implementation and the
  shared fixture unchanged.

## Scoped diff

The proposal adds only:

1. `tests/unit/market_data/test_bundle_contract.py`, containing 21 deterministic,
   non-authenticated synthetic-only test cases (including parametrized cases) that exercise
   public assembly, codec, and verification APIs.
2. `docs/reviews/data-bundle-tests-004.md`, this review record.

No production module, shared fixture, configuration, runtime, persistence, provider, broker,
risk, pricing, sizing, strategy, exposure, deployment, or live-operation path was changed.

## Coverage and observed values

- Repeated assembly produces byte-identical packages; verification selects the two expected
  synthetic bars with exact `(open, close, volume)` values of `("10", "10", "100")`.
- Semantically identical JSON with different whitespace retains those values but changes the
  SHA-256 blob identity and bundle identity, demonstrating that exact retained bytes—not a
  canonicalized JSON value hash—bind the source.
- Recomputing only the outer bundle hash does not conceal normalized value, locator,
  source-descriptor reference, or manifest mutations. Recomputing a changed raw blob digest,
  descriptor hash, and outer hash still fails normalizer replay.
- Tests exercise source instrument/kind/source-label scope, malformed JSON, duplicate keys,
  floats, non-finite numbers, wrong schema types, nesting depth, envelope/blob/total byte limits,
  and combined raw-plus-normalized record limits, asserting registered public error codes.
- An imported-origin relabel is rejected as `bundle_source_unsupported`.
- Both `gap` and `unknown` coverage states retain their actual decoded states and derive
  `declared_coverage_gap` in the verified limitation codes and manifest known gaps. These
  assertions do not infer source authenticity, acceptance, promotion eligibility, or readiness.

## Verification results

Final verification from the scoped worktree:

```text
$ uv run pytest tests/unit/market_data/test_bundle_contract.py -q
.....................                                                    [100%]
21 passed in 0.46s

$ uv run ruff check tests/unit/market_data/test_bundle_contract.py
All checks passed!

$ uv run pytest tests/unit/market_data/test_bundle_models.py tests/unit/market_data/test_bundle_codec.py tests/unit/market_data/test_bundle_normalize.py tests/unit/market_data/test_bundle_verify.py -q
........................................................................ [ 35%]
........................................................................ [ 71%]
..........................................................               [100%]
202 passed in 0.89s
```

During development, the first combined run found one unused test import while the new tests
were already green (`21 passed in 0.42s`) and the primary comparison set was green
(`202 passed in 0.98s`). The unused import was removed within the owned test file; no check was
weakened, skipped, or marked xfail. Earlier targeted runs also corrected test inputs that were
invalid at domain construction before they could reach the intended verifier layer; those were
test-authoring errors, not production findings.

## Assumptions, findings, and blockers

- Assumption: the frozen public dataclasses and functions, registered error codes, exact hash
  preimages, and synthetic fixture semantics in the approved plan are authoritative for this
  proposal. Private implementation helpers are not asserted as contracts.
- Assumption: the primary-owned `_bundle_fixtures.py` remains a synthetic input factory only;
  this proposal imports it read-only and keeps all mutation helpers in the owned test file.
- Identified production defects: none in the exercised contract.
- Unresolved blockers for this scoped proposal: none.
- This result is test-review evidence only. It is not release, source-trust, promotion, paper,
  or live-readiness evidence; central integration and complete baseline verification remain
  primary-owned.

## Disposition

**READY_FOR_INTEGRATION** — scoped synthetic test proposal only, subject to primary inspection
of the complete diff and central checks.
