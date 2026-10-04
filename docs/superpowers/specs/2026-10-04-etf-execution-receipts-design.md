# ETF execution receipts and quote linkage

## Intent and authority

Extend the existing offline observation workflow so future execution-owner events
can be recorded contemporaneously and linked to retained Alpaca SPY quotes.
The operator requested completion without repeated setup questions; native
execution and existing build authority are retained. This is software work,
not permission to submit orders, open credentials, deploy or change risk.

Current account evidence has zero equity orders/fills. Past missing local timing
cannot be reconstructed. Customer calibration remains BLOCKED_INPUTS until actual
attributable executions, charges and contemporaneous observations exist.

## Selected approach

Use a transport-free local receipt sink and a separate offline verifier/linker.
Retain the existing cost-observations-v1 schema and immutable old evidence.
Do not retrofit historical broker UTC dates into monotonic measurements or add
an authenticated order adapter. An in-memory-only sink was rejected because
it cannot preserve failure prefixes; caller-declared quote values alone were
rejected because byte hashes do not establish semantic linkage.

## Receipt sink

`EtfExecutionReceiptRecorder` owns one fresh clock session. Its default provenance
is paper; customer is only a declaration, never authentication or live authority.
The recorder samples injected UTC/monotonic clocks itself, validates nonnegative
bounded monotonic values, rejects clock regression, and latches failed recording.
A fresh random nonce distinguishes each process session; tests inject a nonce.
No restart appends to a prior session or claims clock continuity across processes.

Store exact source bytes as SHA256.source, session metadata as a source, ordered
hash-chained event receipts, and immutable checkpoint manifests using the existing
owner-private, no-symlink, no-overwrite, fsync storage. Source/receipt bodies are
bounded to 1 MiB, retained source totals to 8 MiB and events to 10,000. Existing
canonical configuration is unchanged; maximum quote age is explicitly supplied
from the canonical executable-quote-age policy, never an independent safe default.

Event kinds: alpaca_frame, decision, submitted, acknowledged, fill, terminal.
Payloads use hashes rather than account/order identifiers. Decision names an
already-received observation. Submission/acknowledgement/terminal reference retained
source bytes; fill contains source-backed declared quantity/price and a fill hash.
Terminal charged fees are absent or explicit complete components whose sum matches
total. The sink makes no provider call and cannot grant an execution capability.

## Offline verifier/linker

Rehash session, receipts and every referenced source. Validate exact schemas,
sequence/previous links, session identity and UTC/monotonic ordering. Reparse
Alpaca raw frames with the existing parser and derive quote values/timestamps from
the exact identified observation; never accept independently supplied prices.

Decision quotes must precede submission in event order and both clock domains.
Select the first subsequently received uncrossed, positive quote with provider
time no earlier than submission; it must precede the first fill receipt and satisfy
the explicit quote-age bound. Future, stale, crossed, locked and inactive quotes
cannot supply cost linkage. This does not establish market-control eligibility.

Validate order lifecycle: decision -> submission -> optional acknowledgement ->
one or more fills -> terminal. Deduplicate identical fill-hash deliveries, reject
conflicts, and reject new fills after terminal. Partial/pending episodes remain
incomplete and are not forced into completed samples. Fee components must reconcile
exactly; missing fees remain null. Validate the resulting existing cost input with
`measure_etf_cost_observations` before publishing anything.

Clock and source declarations are internally consistent provenance, not hardware,
provider or customer attestation. Output always preserves unverified calibration,
non-promotability and live-disabled flags. Raw broker record semantic qualification,
representativeness, applicable terms, cash yield, historical execution coverage,
paper/shadow elapsed evidence and runtime verification remain separate gates.

## Operator integration

Add a separate offline `link-costs` command to the existing observations CLI.
It reads only an explicitly selected private checkpoint and publishes a private
normalized input and descriptive report, including incomplete-order counts.
It opens no credentials/network and never selects a trade or changes an order.
No recording path is wired to authenticated broker transport under this scope.

## Frozen wire and boundary details

Session fields are exactly: schema (`etf-execution-clock-session-v1`), nonce
(64 lowercase hex characters), provenance, code_revision (40 lowercase hex),
started_at (six-digit UTC), started_monotonic_ns, maximum_quote_age_ns,
evidence_promotable (false). Its byte SHA256 is the clock session identity.
Receipt fields are exactly: schema (`etf-execution-receipt-v1`), session_hash,
sequence, previous_hash (null only for first), kind, received_at (six-digit UTC),
received_monotonic_ns, payload. Checkpoint fields are exactly: schema
(`etf-execution-receipt-checkpoint-v1`), session_hash, receipt_hashes,
source_hashes, evidence_promotable (false). All referenced files are SHA256.source.

Payload field sets:

- alpaca_frame: frame_index, body_sha256.
- decision: order_hash, side, terms_hash, observation_hash.
- submitted / acknowledged: order_hash, source_hash.
- fill: order_hash, fill_hash, quantity, price, source_hash.
- terminal: order_hash, source_hash, state, charged_fees.

Terminal state is filled, cancelled, rejected or failed. Filled without fills and
rejected/failed with fills are denied. Partial fills followed by cancellation
form a terminal order sample, not a claim that its economic position is closed.
Unfilled charges remain explicitly recorded outside filled samples.

Decision quote age is checked at selection and submission. Arrival quote age
is checked at its receipt and the first fill receipt, not subsequent partial
deliveries. Check both provider-UTC age and local receipt-monotonic age against
the supplied bound, inclusive; exclude provider times later than frame receipt.
All comparisons use full nanoseconds before legacy microsecond formatting.
Arrival selection uses receipt ordinal then frame row index, never favorable
prices or reordered provider timestamps. This is observational linkage, not a
replacement market-control or executable-quote risk policy.

Duplicate fills compare the complete immutable fill payload excluding the new
delivery clocks. Exact repeats keep the earliest receipt, including repeats
after terminal; conflicts across fields/orders and new fills after terminal are
denied. Acknowledgement after first fill is denied, not silently removed.

The linker returns a separate envelope with `cost_input` containing only the
legacy five fields; counts and false readiness flags stay outside it. Receipt
bodies have an aggregate 8 MiB limit in addition to source totals. Neither
session identity nor local hash verification establishes customer attestation.

## Acceptance

Tests prove exact quote derivation, independent partial-fill/fee expectations,
duplicate/conflicting events, pending outcomes, terminal races, stale/future/locked
quotes, both clock regressions, cross-session/tampered sources, private permissions,
storage failure latching and durable prefix reconstruction. Synthetic fixtures only.
Run focused tests, full regression/coverage, Ruff, Mypy, Bandit and lock check.
Review the integrated diff independently. No code outcome may be labeled actual
customer calibration or permission for live trading.
