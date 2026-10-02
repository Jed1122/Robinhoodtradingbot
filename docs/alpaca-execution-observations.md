# Alpaca execution observations and customer cost measurements

The standalone workflow is implemented for local SPY/SIP quote, status and LULD
observations and private, offline execution-cost measurements. Actual capture and
customer calibration are **blocked**, not qualified. The Cloud task cannot reach
the local private-data host; both installed Alpaca connector access checks timed
out on October 2, 2026. No credentials, private market data or customer records
were moved into Cloud. No orders, deployment or runtime activation occurred.

## Forward observations

Use a clean committed checkout and the existing explicitly selected local Alpaca
paper-key file. The file contains exactly `key_id` and `secret_key`, is owned by
the current user with mode 0600, and has a mode 0700 parent. Capture and report
directories must already exist, be owner-only mode 0700, and be outside the
checkout. Key values must never appear in command arguments or shell history.
The existing market-data-only grant applies; the key itself is not assumed
intrinsically unable to trade.

Run `python -m trading_bot.cli.etf_observations --help` for the commands. The
existing offline `etf_research` CLI remains separate.

1. `prepare --credential-file KEY_FILE --output-root CAPTURE_DIR
   --manifest-file MANIFEST_FILE` writes an offline plan and prints its SHA256.
   It opens no key and makes no network request. Paths must be absolute.
2. Review the saved plan's fixed source, config, paths and limits. `capture
   --manifest-file MANIFEST_FILE --approved-plan-hash SHA256` consumes that exact
   scope once. The digest binds the reviewed scope, not new operator authority.
3. `audit --input-root CAPTURE_DIR --result-hash SHA256 --report-dir REPORT_DIR`
   revalidates retained bytes and receipt links and writes a private aggregate
   report. Exit 2 explicitly means unqualified observations.

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

For a deliberate restart, prepare a new plan with
`--predecessor-result-hash SHA256`. The preceding terminal result must be retained
and its exact bytes revalidated. Its frames are not recursively reverified by the
new segment's audit; audit each segment separately. The interval between segments
remains a discontinuity. A failed or uncertain attempt cannot replay its consumed
`.observation.attempt` marker. Never remove markers to force a retry.

The current public stream docs were inaccessible from Cloud (HTTP 403). Field
syntax was checked against the official [Alpaca Python mappings](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/mappings.py)
and [legacy stream entities](https://github.com/alpacahq/alpaca-trade-api-python/blob/master/alpaca_trade_api/entity_v2.py).
This establishes parser syntax only. Authenticated stream behavior, entitlements,
condition eligibility and source qualification remain unverified.

## Private cost input

`calibrate-costs --input-file INPUT_FILE --input-root INPUT_DIR
--report-dir REPORT_DIR` opens no key, broker or network. It writes a private
content-addressed report, prints only its hash/status, and exits 2 because
canonical calibration and promotion remain unverified. Invalid input exits 1
with a fixed sanitized reason. Missing observations do not become zero costs.

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
notation. Digests are lowercase SHA256. The input is bounded to 1 MiB, 1,000
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
