# Pure native capture request coverage

`market_data.etf_capture_coverage` plans missing half-open quote request spans.
It performs no acquisition, reads no files or credentials, selects no strategy
sessions, evaluates no holdout and provides no retry or trading authorization.
The caller owns scope selection, receipt verification and authenticated actions.

## API

- `CaptureInterval(start_ns, end_ns)` is an immutable exact-integer nanosecond
  range. It must fit wholly within one UTC day. An end exactly at midnight is
  valid for the preceding day. Booleans, floats, negative or reversed bounds,
  cross-day spans and values above signed 64-bit nanoseconds are denied.
- `CaptureAttempt(request, manifest_sha256, status, record_count, page_count)`
  is an immutable declaration. Status is `complete_nonempty`, `complete_empty`,
  `page_limit`, `failed` or `uncertain`. Counts are exact integers or `None`;
  absence is not replaced with zero. Terminal complete/page-limit outcomes
  require known counts. Counts cannot exceed the existing 128-page/128,000-row
  capture ceilings or 1,000 rows per reported page. A page-limit declaration can
  have fewer than 128 pages because the original manifest may have a lower cap.
- `plan_quote_coverage(required, attempts, maximum_window_ns, minimum_window_ns)`
  accepts tuples of these exact types, not arbitrary mappings. It returns an
  immutable `QuoteCoveragePlan`. Input ordering is canonicalized and each input
  is revalidated. Empty required scope creates no implicit request.

The plan exposes `missing_requests`, `covered_intervals`, `empty_intervals` and
`blocked_intervals`, all sorted, disjoint and contained in the required union.
Together those outputs partition that union exactly. Integer duration/count
properties expose requested coverage, proposed requests, empty and page-limit
attempts, known recorded/page totals, and the number of absent count declarations.
Known totals include all declared attempts, including incomplete ancestors and
out-of-scope attempts: they are **not deduplicated observation counts**.

`plan_hash` binds the complete normalized inputs, window policy and outputs in
the `etf-native-capture-coverage-v1` schema. Changing a manifest identity, absent
count, measured count or policy changes the hash. It is an inventory identity,
not receipt verification, a permission grant or a runtime attestation.

## Completion and adaptation

Only declared complete, nonempty requests satisfy **request-span coverage**.
An empty completed interval stops reacquisition but remains separately empty;
it does not enter the existing nonempty native quote catalog. Failed or uncertain
intervals block automatic retry wherever they intersect required scope.

Page-limited requests contribute no observed prefix. They may be replaced only
by exact deterministic bisection descendants: split `[a,b)` at integer
`m = (a+b)//2` into `[a,m)` and `[m,b)`. A selected child can itself be split.
No timestamp-based continuation cursor is inferred from observed records, because
equal-timestamp quotes can cross pagination boundaries. Previously retained
attempts remain in the input and hash; no original marker is removed or replayed.

Overlapping declarations are denied unless an enclosing attempt is page-limited
and the descendant is an exact node in its bisection tree. Identical requests,
reused manifest digests, overlapping completed attempts, arbitrary clipped
children and descendants of failed/uncertain requests deny. Deeper exact tree
nodes do not require fictional intermediate attempted requests. Completed
historical children can be shorter than a newly supplied minimum policy; the
minimum governs newly proposed acquisition, not retained facts.

Unattempted spans are also bisected until they meet the maximum window. Children
below the minimum are never proposed. Unsplittable portions become blocked,
including boundary slivers when required scope clips a page-limited ancestor.
Every proposed descendant remains inside required scope. A one-nanosecond
page-limited interval cannot be retried or split.

## Bounds and safety

The input and output contracts allow at most 4,000 distinct UTC days and 1,024
intervals per day. Attempt bounds count ancestors as well as children. Required
intervals and attempts are each bounded; their combined day union is bounded.
The combined output partition is also bounded, with a guard during expansion
so an enormous nanosecond partition is denied before it is materialized.
Maximum/minimum windows must be positive exact integers, with minimum no larger
than maximum and maximum no larger than one day.

All source/cost qualification, execution, promotion and market-completeness
flags are permanently false and cannot be supplied to the planning function.
The October 5 historical halt/LULD/gap waiver does not turn requested intervals
into market completeness, observed controls or executable coverage. This module
does not change the frozen 2016–2025 study, 2024–2025 holdout, canonical risk,
existing capture/attempt/hash schemas or sealed qualified-source admission.

## Next integration steps

The acquisition owner must provide the root-approved required intervals and
independently verify actual immutable outcomes before converting them to these
declarations. Next work is private durable intent/outcome persistence, explicit
uncertainty recovery, catalog-reference inventory, bounded standalone acquisition
composition and integrated review. This planner alone neither supplies remaining
history nor establishes executable data, economic acceptance, paper/shadow
eligibility, deployed recovery or live authorization.
