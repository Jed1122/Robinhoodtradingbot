# Native Alpaca SPY capture boundary

This is a standalone, operator-authorized market-data acquisition owner, not a
broker adapter, continuously running collector, qualified historical dataset or
economic test. The existing two-response Alpaca diagnostic remains unchanged.

The operator requested native capture after reporting Algo Trader Plus and saving
an explicit local paper-key source. This covers market-data GETs for the approved
SPY study, not account inspection, order endpoints, subscription changes or live
activation. Key format checks cannot establish account identity or entitlement;
credentials are not assumed intrinsically read-only. Never put their values in
commands, reports, Git or agent prompts.

## Request and receipt contract

`market_data.alpaca_native.AlpacaStockRequest` freezes either daily bars or quotes
for SPY, SIP, USD, ascending order and `asof=-`. Daily bars explicitly request raw
adjustment. Start is inclusive; the half-open end is sent as end-minus-one
nanosecond because Alpaca's REST bounds are inclusive. Quote requests are bounded
to at most 24 hours; bars may span the approved 2016–2025 study. The capture owner
accepts at most 1,000 rows per page and 128 pages per manifest, at most 1 MiB of raw
bytes per response and 60 seconds overall. Bounds are ceilings, not guaranteed
coverage or an instruction to download all ticks for ten years.

`diagnostics.alpaca_capture.prepare_capture` is offline. Its separate
`alpaca-native-capture-v1` manifest binds code revision, canonical backtest config,
fixed request, private paths, page ceiling and a 30-minute scope lifetime.
`encode_capture_manifest` / `decode_capture_manifest` and
`capture_manifest_sha256` support exact review before `capture_native`.
A digest confirms the reviewed request; it is neither a permission grant nor
proof of licensing. Call only from the reviewed committed source and canonical
configuration (a verified exact-commit archive is acceptable), with a UTC clock.
Do not import this standalone owner into a daemon: its library logging suppression
is process-global and intended only for a dedicated capture process.

The credential file must be explicitly selected outside the repository, owned by
the current user, mode 0600, and contain exactly `key_id` and `secret_key` string
fields. Its parent and the separately selected existing output directory must be
owned mode 0700; symlink traversal is denied. No credential discovery or fallback.

Before opening keys or constructing transport, capture validates scope and claims
an exclusive `<manifest-sha256>.native.attempt`. A failed or uncertain attempt
cannot be replayed; do not remove its marker to retry. Investigate the failure and
prepare a new authorized scope if needed. A fresh manifest is not independent
authority to expand the operator's grant.

Transport is fixed HTTPS GET to `data.alpaca.markets`, TLS verified, environment
proxies disabled, redirects disabled, retries zero, and 10-second I/O timeouts.
It accepts JSON with identity encoding only. Opaque continuation tokens are used
only as escaped query parameters; all other request fields remain fixed. Short
nonterminal pages still continue. Repeated tokens, invalid schemas, HTTP failures,
clock regressions or storage failures stop capture.

Exact response bytes are retained privately under their SHA256. JSON syntax and
credential-echo screening occur before retention. Error HTTP bodies and malformed
or secret-containing JSON are not retained. Syntactically safe responses that fail
the native schema can be quarantined, but cannot continue or count as accepted
records. Per-page content-addressed receipts bind request/query identity, raw hash,
observed timestamps and preceding receipt hash. No raw page token is copied into
a receipt. Manifest and terminal result are also retained privately.

If an outer timeout, crash or disk failure prevents the terminal result, retained
pages and the attempt marker are incomplete evidence, never a completed capture.
There is no automatic retry or resume. This is separate from the future durable
ETF account restart mechanism.

## Native interpretation and qualification limitations

Native prices use exact Decimal values from JSON numeric lexemes and timestamps
retain integer nanoseconds. Same-timestamp quotes are preserved by page/row
ordinal, not deduplicated or presented as a proven exchange sequence. Missing,
extra or inconsistent native fields fail closed. Zero, locked and crossed quote
observations can be retained but are not executable entries.

Alpaca specifies quote size in round lots before November 3, 2025 and shares
afterward. Because the date-only notice does not establish the exact intraday
cutover, the union of that UTC and New York date is explicitly unverified.
No universal historical multiplier is assumed. Conditions retain their order and
whitespace. [Quote schema](https://docs.alpaca.markets/us/reference/stockquotesingle-1),
[size change](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change).

Daily timestamps identify a New York aggregation start, not session close or
original publication. Raw adjustment and `asof=-` do not prove an original
historical vintage. REST bars/quotes do not provide original publication/receipt
or a full correction timeline. Today's retrieval receipt cannot substitute for
those facts. [Bar schema](https://docs.alpaca.markets/us/reference/stockbarsingle-1),
[aggregation FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

`pagination_complete=True` means the bounded request reached its terminal cursor.
It does not prove expected session coverage, historical availability, corporate
action completeness/payable semantics, fractional execution terms, permissible
use/retention or calibrated fills. Native pages, archive assessments and capture
results always have `source_qualified=False` and `evidence_promotable=False`.
They never construct `QualifiedEtfDataset` or change risk/live configuration.

## Remaining work

1. Capture and inventory authorized real bytes; compare expected sessions, source
   eras, action and quote coverage with the frozen study's requirements.
2. Resolve unsupported publication/correction and execution assumptions explicitly.
   Do not manufacture availability times or silently lower acceptance criteria.
3. Complete ETF cash/order/reservation/settlement accounting and durable restart;
   the existing fixture prefix implements decisions only.
4. Run after-cost benchmarks and uncertainty tests only when the input/account
   contracts support them, keeping the final holdout untouched until frozen.
5. Independently complete broker/runtime evidence and actual eligible paper/shadow
   operation. Merging this acquisition increment does not satisfy those gates.
