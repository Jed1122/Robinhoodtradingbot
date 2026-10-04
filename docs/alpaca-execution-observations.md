# Alpaca execution observations and customer cost measurements

The standalone workflow is implemented for local SPY/SIP quote, status and LULD
observations and private, offline execution-cost measurements. Two actual Alpaca
captures completed on the operator's Mac on October 2, 2026, and both passed their
retained-byte audits. Customer cost calibration remains **blocked** by missing
execution and operating-cost evidence. No credentials, raw private market data
or customer records were moved into Cloud. No orders, deployment or runtime
activation occurred.

## Actual observation result

Both captures used clean implementation revision
`e104f4f1be204db71e9e830303c12d3a0fd13878`, the existing explicitly selected
local key, fixed SIP endpoint and SPY subscriptions. Authentication and exact
subscription acknowledgement succeeded. The reviewed collection scopes were
60 seconds for the initial plan and 10 seconds for the deliberate restart.
Both retained `alpaca-observation-result-v1` records declared `duration_limit`
but contain no collection start/end monotonic pair. Both `audit-v2` re-audits
retained the observation counts and report `declared_termination="duration_limit"`,
`termination="duration_limit_unverified"` and
`duration_limit_elapsed_verified=false`. Actual elapsed collection time remains
unverified for these two captures.

| Segment | Quote observations | Uncrossed | Locked | Crossed/inactive | Status/LULD |
|---|---:|---:|---:|---:|---:|
| Initial | 5,432 | 5,385 | 47 | 0/0 | 0/0 |
| Deliberate restart | 527 | 525 | 2 | 0/0 | 0/0 |
| Total | 5,959 | 5,910 | 49 | 0/0 | 0/0 |

Each audit rehashed raw frames and plans, reparsed all observations and verified
receipt links. The restart reverified its direct predecessor result and plan bytes; the
first segment's frames were audited separately. Initial control state remains
unknown and the restart interval remains a discontinuity. No status/LULD messages
were observed; that does not establish market eligibility. Locked quotes are
retained and are excluded from the descriptive uncrossed-spread inventory.
Both CLI audits were repeated from clean auditor revision
`172a2d9289ffe8f729a127088743909591464556`, which is recorded in the reports.
The empty customer assessment was repeated from clean calibrator revision
`172a2d9289ffe8f729a127088743909591464556`. Its report identity includes that
revision, and the linked retained history/result source bytes were rehashed.

An additional private diagnostic reverified 1,917 raw frames (804,214 bytes).
Across the 5,910 uncrossed quote-update events, mean full quoted spread was
0.194864 basis points, nearest-rank p95 was 0.389836 and maximum was 0.519805.
These are event-weighted observations from this short capture, not a
time-weighted or order-weighted broker cost estimate. Spread is already in
execution prices; these values are not installed as another charge. They do not
measure fills, slippage, acknowledgement delay or broker execution latency.

Private result and audit identities, with no raw prices or customer identifiers:

| Artifact | SHA256 |
|---|---|
| Initial terminal result | `d2c573239b49884774a82356d2fbbd39a3c12448a651c047477026ee8ec77ac8` |
| Initial revision-bound audit artifact | `5989ba29a927a88582ad0e65cbcbc0a8f76d1ad0e15aeb43ee6b208752ddb802` |
| Restart terminal result | `0801135ba4740422576a2e723cffeafa8585e91d71578a0d45cab6b2236bd6de` |
| Restart revision-bound audit artifact | `27ba4cf8b65bda0de1ded4fe9f4b66105dadd3065e79d829f7b09e1b303d4e26` |
| Descriptive spread diagnostic | `a0618058894b81ca4794cdbb50a0e4e2916772b02eaaaacdc510bc06d259d72a` |
| Unfiltered bounded broker-history result | `eede4ecd91901ceec95d44d09d51a6013b4a544e9db6b3136e1364f6dd3cdc26` |
| Revision-bound empty customer-input calibration report identity | `6b12d28ea2661e30921e487cfa49a1cbad6d11cefb798b88b124369c54eb8fed` |
| Complete calibration file artifact | `1e44a959684b93ef3152d52695c94bc6589de3c3036116504c3554a58d742060` |
| Private revision-bound history/calibration file link | `7e3848ae4a08a8db7637ffb25b65d97318aa4bd689ff136f6727568dd983e4c9` |

Raw frames and reports remain under the operator's private
`~/.local/share/robinhood-trading-bot/alpaca-observations-20261002` directory,
outside every checkout. None is committed.

## Forward observations

Use a clean committed checkout and the existing explicitly selected local Alpaca
paper-key file. The file contains exactly `key_id` and `secret_key`, is owned by
the current user with mode 0600, and has a mode 0700 parent. Capture and report
directories must already exist, be owner-only mode 0700, and be outside the
checkout. Key values must never appear in command arguments or shell history.
The existing market-data-only grant applies; the key itself is not assumed
intrinsically unable to trade.

After `uv sync --frozen --all-groups`, run
`PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_observations --help`
from the clean checkout for the commands. Explicit `PYTHONPATH=src` also works
on the operator's Mac, where the editable environment's import path was not
available. The existing offline `etf_research` CLI remains separate.

1. `prepare --credential-file KEY_FILE --output-root CAPTURE_DIR
   --manifest-file MANIFEST_FILE` writes an offline plan and prints its SHA256.
   It opens no key and makes no network request. Paths must be absolute.
2. Review the saved plan's fixed source, config, paths and limits. `capture
   --manifest-file MANIFEST_FILE --approved-plan-hash SHA256` consumes that exact
   scope once. The digest binds the reviewed scope, not new operator authority.
3. `audit --input-root CAPTURE_DIR --result-hash SHA256 --report-dir REPORT_DIR`
   revalidates retained bytes and receipt links and writes a private aggregate
   report. It requires a clean committed checkout and records
   `auditor_code_revision` separately from the capture plan's revision. Exit 2
   explicitly means unqualified observations.

Transport is fixed to `wss://stream.data.alpaca.markets/v2/sip` and subscriptions
are fixed to SPY quotes/statuses/LULD. It has TLS verification, no environment
proxy, no redirects, no compression, no broker endpoint and no reconnect/retry.
The locked WebSocket dependency is shared by the main and research locks. A
dedicated disabled logger prevents library authentication-frame logging.

Limits are 1–900 seconds of collection after handshake (default 60), at most
10,000 frames, 1 MiB per frame, 32 MiB retained raw bytes, and 1,000 observations
per frame. Plan validity is 30 minutes. Authentication/subscription have a shared
10-second deadline. Invalid responses, credential echoes, transport/storage
failure or clock regression stop collection; expiry jumps leave incomplete
evidence rather than publishing an invalid terminal result.

New captures write `alpaca-observation-result-v2`, recording
`collection_started_monotonic_ns` after the subscription handshake and
`collection_finished_monotonic_ns` before connection close. These are bounded
local integer nanoseconds. `alpaca-observation-audit-v2` checks that each retained
receipt lies within that collection window. A declared `duration_limit` requires
the exact integer difference to be at least `duration_seconds * 1_000_000_000`;
handshake and connection-close time fall outside this window. A failure before
collection leaves both fields null and retains no frames.

Legacy `alpaca-observation-result-v1` records remain readable and their retained
bytes and observations remain auditable. They have no collection window, so a
declared `duration_limit` is reported as `duration_limit_unverified` with
`duration_limit_elapsed_verified=false`. UTC run timestamps and interframe gaps
do not establish the missing collection interval.

Each accepted frame is retained privately with its raw SHA256. Its receipt binds
the plan, ordinal, UTC receipt time, local monotonic time, preceding receipt and
all parsed observation identities. Duplicate JSON keys and unsupported rows are
denied; same-provider-timestamp rows remain distinct. Quote prices use Decimal;
timestamps retain nanoseconds. Status/reason codes and LULD indicators are
preserved without inventing eligibility. Embedded quote `page_index=0` is a
compatibility sentinel; **use the full `observation_hash` for stream identity**.

Every segment starts with unknown control state. Absence of a halt or LULD
message does not establish an eligible market. Alpaca provides no demonstrated
gap-free exchange sequence here. Interframe receipt gaps and provider-clock skew
are reported, not interpreted as broker latency or missing-exchange-record proof.
A limit-ended capture does not establish complete market coverage.
Retained empty frames carry no observations: an all-empty segment remains
`BLOCKED_INPUTS`. With fewer than two retained frames, the maximum interframe gap
is null because no interval was measured; a measured zero is reserved for an
actual pair of frames with equal local monotonic receipt times.
An audited `frame_limit` termination requires the full planned receipt count.
A duration or byte-limit stop requires remaining planned frame capacity. A
32 MiB byte-limit stop requires more than 31 MiB retained, since any unretained
frame is at most 1 MiB. Declared observation counts must be integers, not booleans.
A transport failure while closing can still produce `capture_failed` after the
last planned frame; retained frames do not turn that failure into success.
An operational receive or storage timeout remains `capture_failed`; only expiry
of the actual collection timeout context with a recorded collection window at
least as long as the requested duration can yield a new `duration_limit` result.
An earlier measured end fails closed as `capture_failed`.

For a deliberate restart, prepare a new plan with
`--predecessor-result-hash SHA256`. The preceding terminal result and its referenced
plan must be retained. Their exact bytes are rehashed, and the direct predecessor's
counts, termination and any recorded collection window are checked against its
own plan limits. A legacy duration declaration remains elapsed-time unverified.
Its frames are not recursively reverified by the new segment's audit; audit each
segment separately. The interval between segments remains a discontinuity.
A failed or uncertain attempt cannot replay its consumed
`.observation.attempt` marker. Never remove markers to force a retry.
Predecessor bytes must have the exact terminal-result schema with bounded hashes,
times, counts, sizes and unqualified flags; a partial result-shaped object is denied.

The current public stream docs were inaccessible from Cloud (HTTP 403). Field
syntax was checked against the official [Alpaca Python mappings](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/mappings.py)
and [legacy stream entities](https://github.com/alpacahq/alpaca-trade-api-python/blob/master/alpaca_trade_api/entity_v2.py).
Those references establish parser syntax. The actual captures additionally
demonstrate authentication, subscription acknowledgement and quote delivery in
these segments. Account-plan identity, complete entitlements, status/LULD event
behavior, condition eligibility and source qualification remain unverified.

## Private cost input

### Verified retained reader and causal prefixes (offline)

`read_observation_capture` revalidates the same bytes, receipt chain, terminal
shape and clocks as the aggregate audit, then returns immutable typed frames.
It never opens the credential path stored in the plan. Frame boundaries, empty
frames, raw status/LULD fields and receipt ordinals are preserved. Typed retention
has a 10,000-observation cap in addition to the existing frame/raw-byte limits;
overflow denies the whole read. The aggregate audit retains its previous bounds
and `audit-v2` wire format.

`capture.visible_frames(received_at_ns=UTC_NS, received_monotonic_ns=MONO_NS)`
requires both receipt clocks to be at or before the supplied cutoffs. It never
sorts, deduplicates or selects by provider event time. Both cutoffs belong to this
single capture; monotonic clocks must not be combined across predecessor segments.

From a clean committed checkout, the equivalent private report command is:

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_observations stream-prefix \
  --input-root PRIVATE_CAPTURE_DIR --result-hash RESULT_SHA256 \
  --received-at-ns UTC_NS --received-monotonic-ns MONO_NS \
  --report-dir PRIVATE_REPORT_DIR
```

The report contains capture/query identities and ordered receipt/observation
hashes, not raw records. It is content-addressed, current-user-owned and mode
0600 in an existing 0700 directory outside the checkout. Exit 2 means a valid
but unqualified result; empty observations remain `BLOCKED_INPUTS`. Public output
contains only report hashes, counts and false capability flags.

This completes retained-record consumption, not execution-data qualification.
Initial controls, gap continuity, historical coverage, actual customer fills,
final fees, causal order clocks, accepted economics and qualifying paper/shadow
runtime operation remain separate prerequisites. No new provider, broker calls,
credential operations, deployment, activation or risk changes are involved.

### Durable receipt linkage (offline)

The transport-free `EtfExecutionReceiptRecorder` records execution-owner
observations using its own injected UTC and monotonic clocks. It retains immutable
hash-chained receipts and checkpoint manifests in an owner-only directory outside
the checkout. Storage failure or clock regression latches recording failure;
restart requires a fresh session, not an appended or reconstructed clock history.
It cannot authenticate, submit an order or manufacture a broker observation.
No authenticated runtime is wired to this recorder.

From a clean committed checkout, run:

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_observations link-costs \
  --input-root PRIVATE_RECEIPT_DIR --manifest-hash CHECKPOINT_SHA256 \
  --report-dir PRIVATE_REPORT_DIR
```

Use absolute paths to existing current-user-owned mode-0700 directories. The
command opens no credentials or network. It rehashes the checkpoint, session,
receipts and retained source bytes, reparses exact Alpaca frames, derives the
decision quote from an already-received observation, and chooses the first
eligible subsequently received arrival quote. Both clock domains must satisfy
the explicitly supplied age bound. This is descriptive linkage, not trading
eligibility or an executable-quote risk-policy substitute.

Identical fill redelivery keeps the original receipt; conflicting duplicates,
future/stale quote references and invalid lifecycle transitions are denied.
Pending and partially filled orders without a terminal event remain incomplete.
Terminal unfilled outcomes retain any explicit charges outside filled samples;
partial fills followed by cancellation are terminal order samples, not proof
that the economic position is closed. Missing fees remain null.

Referenced originals are copied without modification as `SHA256.source`, with
hashes rechecked immediately before private publication. Normalized input is
saved as `SHA256.cost-input.json`; the existing cost loader revalidates it and
its references before a revision-bound descriptive report is published.
Incomplete/unfilled counters and checkpoint identity remain separate from the
unchanged five-field cost-input schema. Reports are deterministic, mode 0600
and content-addressed. Public output contains hashes, aggregate counts and
unqualified verdicts only. Invalid input exits 1 with a sanitized reason;
successful descriptive publication intentionally exits 2.

`quote_receipt_bytes_linked=true` establishes internal linkage only.
`customer_authenticated=false`, `clock_session_attested=false` and
`calibration_verified=false` remain explicit. Caller-declared customer provenance
does not authenticate broker quantities, prices, charges or applicable terms.
Customer calibration, economic qualification, paper/shadow progression and
live authorization remain unchanged. All new validation uses synthetic fixtures;
it supplies no genuine customer fills or missing historical timings.

`calibrate-costs --input-file INPUT_FILE --input-root INPUT_DIR
--report-dir REPORT_DIR` opens no key, broker or network. It writes a private
content-addressed report, prints only its hash/status, and exits 2 because
canonical calibration and promotion remain unverified. Invalid input exits 1
with a fixed sanitized reason. Missing observations do not become zero costs.
The cost report's `report_hash` identifies its canonical contents excluding that
self field. The CLI requires clean committed source before opening input, binds
`calibrator_code_revision`, and hashes this extended report. The pure loader's
unbound draft hash is not the bound CLI report identity. `artifact_digest` hashes
the complete saved file and names `ARTIFACT_DIGEST.observation-report.json`.
Audit reports have no self-hash field, so their two CLI digests are equal.

The JSON object has exactly `schema="etf-cost-observations-v1"`,
`provenance` (`synthetic`, `paper` or declared `customer`),
`execution_broker="robinhood"`, `market_data_source="alpaca-sip"`, and `orders`.
Alpaca-only concerns market data; it does not change the execution broker.
An empty order list produces `BLOCKED_INPUTS` with empty measurements.

Each terminal order contains exactly:

| Field | Meaning |
|---|---|
| `order_hash`, `source_hash`, `terms_hash` | SHA256 order identity, retained execution record and applicable customer/channel terms. No account or order identifier appears in the normalized input. |
| `side` | `buy` or `sell`. |
| `submitted_at` | UTC text with six fractional digits and `Z`. |
| `clock_session_hash` | Identity of the single local monotonic clock session used by all the order's timings. A declaration is not clock attestation. |
| `submitted_monotonic_ns`, `acknowledged_monotonic_ns`, `terminal_monotonic_ns` | Nonnegative local clock integers; acknowledgement may explicitly be null. |
| `decision_quote`, `arrival_quote` | Each has `bid`, `ask`, `source_hash`, `observed_at`, `received_monotonic_ns`. Use recorded two-sided uncrossed Alpaca observations. Decision precedes submission; arrival follows submission and precedes the first fill receipt. |
| `fills` | Positive `quantity`/`price`, distinct `fill_hash`, and ordered `received_monotonic_ns`. |
| `fee_grouping` | Exactly `terminal-order-total`. Supply each charged fee component once for the terminal order, after reconciling the broker's actual grouping. |
| `charged_fees` | Either null or exactly `commission`, `sec`, `taf`, `cat`, `other`, `total`, `source_hash`. Every amount must be explicit and nonnegative; components must sum exactly to total. |

All decimal values are canonical finite decimal **strings**, without exponent
notation, within the shared 512-character canonical Decimal bound. Digests are
lowercase SHA256. The input is bounded to 1 MiB, 1,000
orders and 10,000 total fills. Each source/terms/quote/fee reference must exist
as `SHA256.source` in the private input directory. The loader checks exact bytes,
owner-only permissions, symlink exclusion, 1 MiB per source and 8 MiB aggregate.
Retain permitted originals privately; raw bytes and account information never go
into Git, logs, task prompts or Cloud. Hash equality establishes integrity only.

Reports use the terminal order as the sampling unit, including partial-fill
VWAP. Signed adverse slippage uses the decision ask for buys and bid for sells.
It separates market movement to the arrival quote from the remaining fill-price
residual, using the same denominator. Decision half-spread is descriptive and
already present in the price; it is never charged again. Exact notional/fee
reconciliation is independent of the caller's Decimal context; descriptive
ratios/means use an explicit 40-digit context and nearest-rank p95.
Before the pure measurement function returns, it validates the entire report
with the canonical JSON encoder used for storage. If a derived product, sum or
ratio exceeds the same 512-character Decimal bound, measurement rejects the input
with the fixed reason `etf_cost_calibration_invalid`. Finite bounded inputs alone
do not guarantee that every derived report value can be encoded within the bound.

Local acknowledgement, first-fill receipt and terminal receipt durations describe
the same local clock session. They are not exchange execution latency. Paper and
synthetic observations are explicitly distinct from customer execution. Declaring
`customer` does not authenticate a record or establish representative calibration.

Cash yield, operating bills, dated customer fee rules, fractional/channel terms,
sampling uncertainty and source authenticity remain separate missing evidence.
The canonical seven-role `EtfCostEvidence` and its historical hashes/fee behavior
are unchanged. This report does not install a fee rate, create a qualified dataset,
touch the holdout, grant promotion or enable execution.

## Qualification result

The last real retained package still has zero quoted development sessions out of
1,262 required sessions. Forward collection cannot backfill historical halt,
LULD or continuity controls. No customer execution/charged-fee sample is available
to this task. Genuine after-cost acceptance remains `ECONOMIC_NO_GO`.
The 100 eligible paper cycles, seven shadow dates and all broker/runtime/live
authorization gates remain separate requirements. See the
[existing qualification result](etf-execution-cost-qualification-2026-10-02.md).

The bounded saved-record search examined Documents and Downloads outside the
project checkout. No execution-shaped CSV header was found among 27 CSV files.
Eight filename-selected PDFs were inspected privately: seven were readable and
none provided recognized execution or applicable provider billing evidence;
one was unreadable. This search does not prove that no saved records exist.
The existing selected OAuth connection initially requested sign-in before any
account/order response. The operator then separately authorized browser sign-in
and the history check. The reviewed existing bootstrap saved a new connection in
a separate private directory, verified its read declarations, and matched the
existing intended account fingerprint. The existing store was not replaced.

The read-only diagnostic then requested existing equity orders from the selected
individual cash Agentic account: first since January 1, 2026, then without a date
filter. Each response contained zero orders and no next page. The scope was at
most four pages, 256 orders, 1 MiB per retained structured response and 120 seconds
per diagnostic. Only account binding and order-history reads were made; no broker
quotes, review, placement or cancellation occurred. These results concern this
endpoint and selected account, not other accounts or exports that were not found.
No candidate returns or holdout strategy outcomes were evaluated.

The unfiltered history response and private result were rehashed before producing
an empty customer-observation input. Both assessments remained `BLOCKED_INPUTS`.
The standalone CLI bound the clean calibrator revision, published the distinct
report and artifact identities above, and exited with the intentional unqualified
code 2. Its identity differs from the pure loader's unbound draft.
There are zero order/fill samples, no measured charged fees, and no slippage or
order-latency estimate. Empty fee distributions remain missing, not a zero fee
rate. A separate private link binds the input, history result and calibration
report. Applicable fee terms, cash yield and subscription/hosting bills remain
unverified; successful SIP delivery does not establish a free subscription.
Slippage and same-clock order latency cannot be reconstructed from historical
fill prices alone. Customer cost qualification therefore remains incomplete.
