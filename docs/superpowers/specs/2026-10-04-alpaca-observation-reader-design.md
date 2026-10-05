# Verified Alpaca observation reader

The operator requests completion of data/cost, economic and paper/shadow prerequisites
without further setup questions. Native execution and automatic reviewed integration
remain the standing workflow. This first dependent increment supplies usable retained
market-data records, not source qualification, accepted research or runtime activation.

## Scope and dependency chain

Retained frame bytes/receipt chains -> typed receipt-ordered observations -> source and
execution qualification -> accepted economics -> trusted paper/shadow composition ->
independently verified runtime -> genuine qualifying observations. Only the first two
links are implemented by this increment. Missing authentic fills, fees, causal order
clocks, historical controls and accepted research remain denied.

The existing audit reparses observations but discards them and each frame's monotonic
clock. A second reader would risk different validation. Refactor the current verifier
to serve both aggregate audit and a typed reader; retain existing audit-v2 JSON and
its semantics. No new provider, credentials, network capture, broker operation,
deployment, risk/config changes or promotion acceptance is included.

## Immutable values and shared verification

Add `AlpacaObservationFrame` and `AlpacaObservationCapture` in a focused pure
`market_data/alpaca_observation_capture.py`. Frames retain frame index, receipt/body
SHA-256, exact UTC and monotonic receipt nanoseconds and parsed observation tuples.
Captures retain result/plan hashes, recorded code/config identities, UTC bounds,
optional collection window, predecessor hash, audited termination and frame tuple.
Representations must not print records. Validation reconstructs nested observations,
rejects identity/clock regressions and keeps every qualification/execution/promotion
flag false. Direct construction is not authentication or a qualified-source factory.

`read_observation_capture(root, result_hash, repository_root)` uses the existing
descriptor-bound private storage verifier and rehashes all plan/result/receipt/raw
bytes before returning any records. Credential files are not opened. The existing
audit delegates to the same verifier without retaining frames; its current bounds
and wire/hash semantics remain unchanged. Typed retention has an explicit 10,000
observation limit in addition to existing 10,000-frame/32-MiB raw bounds. Overflow
fails atomically, never truncates. Empty frames remain transport receipts, not cycles.

Provider timestamp order is not receipt order. Never sort or deduplicate provider
timestamps. Preserve raw status/reason/LULD/quote-condition fields without interpreting
them as OPEN, executable liquidity or verified gap continuity. October 2026 forward
captures cannot become the frozen 2016-2025 historical dataset.

## Causal receipt prefixes

`capture.visible_frames(received_at_ns=..., received_monotonic_ns=...)` returns only
frames already received under both clocks, preserving original frame/row identity.
Require exact bounded nonnegative integers, reject booleans and invalid/forged models.
The method samples no clock and attests none; both cutoffs belong to this one capture.
It does not chain predecessor segments, infer missing frames, or establish market-time
eligibility. Clock-skew observations remain explicitly unqualified observations.

Add `stream-prefix` to the existing standalone offline observations CLI. Bind the clean
auditor revision before private reads, read the capture, select the dual-clock prefix
and publish a private content-addressed report with query/capture identities, ordered
receipt and observation hashes and counts. Print only report hash, counts and permanently
false qualification/promotion/execution/live flags. Empty prefixes remain BLOCKED_INPUTS;
nonempty prefixes are OBSERVED_UNQUALIFIED. No API, credential or write-capable transport
is available. Exit 2 for valid unqualified output and 1 for sanitized denial.

## Verification and limitations

Use failing tests first: mixed q/s/l and out-of-order provider timestamps; dual-clock
visibility; empty/failed/v1 captures; missing/tampered/readdressed bytes; record/clock
forgery; retention limits; private-root violations; unchanged aggregate audit values;
CLI revision-before-I/O, safe stdout and deterministic private reports. Run current
observation/receipt/CLI regression, Ruff, Mypy, full pytest, Bandit, locked checks and
an independent whole-diff review. No synthetic test creates customer or elapsed evidence.

Actual customer cost calibration remains BLOCKED_INPUTS without attributable executions,
final fee evidence and contemporaneous causal quote/order timings. Qualified historical
execution controls, accepted economic evidence, stage identity/composition, installed
runtime authentication/renewal/recovery and 100 paper cycles/seven shadow dates remain
separate unfinished prerequisites; do not flip existing false gates to finish this task.
