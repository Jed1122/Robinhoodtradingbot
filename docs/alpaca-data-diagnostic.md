# Alpaca first-response diagnostic

This standalone operator diagnostic is separate from the trading runtime. Its default is
offline preparation, not authentication. It cannot place orders, move funds, enable live
trading, or accept a research dataset. Robinhood remains the intended broker.

The operator has confirmed a paper-only Basic/free Alpaca account. Account creation does not
resolve contractual feed entitlement, private-retention rights, or technical data access.
The project budget for data subscriptions remains $0. No paid plan, trial, funded-account
workaround, or automatic provider/feed change is supported.

## What is implemented

- A canonical SHA-256-bound manifest using the existing loaded backtest configuration.
- Exactly two proposed GETs to `https://data.alpaca.markets`: `/v2/stocks/bars`, then
  `/v1/corporate-actions`, each requesting only its first page with `limit=1`.
- The full configured symbol tuple and history window are preserved. At implementation they
  are SPY/QQQ/IWM/DIA and 3,650 calendar days. The 750-bar minimum remains an unmet research
  requirement; it is not replaced by the sample limit.
- Fixed raw SIP daily bars, USD, ascending ordering, and `asof=-` (no symbol remapping).
  Actions use all documented types, `region=us`, `data_quality=all`, and process-date filters.
- One MiB per raw response, at most two MiB total, 10-second HTTP I/O timeouts, and a
  60-second asynchronous run deadline. The manifest expires after 30 minutes.
- No redirects, environment proxies, retries, pagination, streaming subscriptions or fallbacks.
- Private exact-byte blobs and safe receipts, with no-overwrite publication and no symlink
  traversal. An exclusive manifest-digest attempt marker blocks repeated use of the scope.

This is a first-response collector, not an Alpaca bar/action parser. Successful HTTP 200 JSON
objects establish only sample transport access and retained-byte integrity. Their fields have
not been mapped or accepted as historical research evidence. Unknown source semantics require
primary review. No genuine provider response is included in tests or Git.

## Offline use

Run from the repository with the locked environment and `PYTHONPATH=src`:

```bash
PYTHONPATH=src uv run python scripts/probe_alpaca_data.py --help
```

Preparation is the default. It loads `configs/base.yaml`, `configs/backtest.yaml`, and
`configs/safety-envelope.yaml` with no environment overrides. It reads the local Git revision
and writes only the explicitly selected private manifest file. It never opens the credential
file, creates the quarantine directory, or contacts Alpaca.

The manifest parent must already be an owner-owned 0700 directory outside the repository,
without symlink components. The manifest filename must not exist. Choose the private paths
yourself; paths below illustrate argument syntax and are not installed locations:

```bash
PYTHONPATH=src uv run python scripts/probe_alpaca_data.py --prepare \
  --manifest-file /absolute/operator-chosen/private/probe-manifest.json \
  --credential-file /absolute/operator-chosen/credentials/alpaca-paper.json \
  --quarantine-root /absolute/operator-chosen/quarantine \
  --requested-end 2026-09-15T00:00:00+00:00
```

Supply a canonical UTC end at least 24 hours before preparation. This buffer does not prove
session finality. The canonical configured history length determines the start; no CLI option
can shorten it or alter strategy thresholds. A prepared manifest is 0600 and may include
private local paths, so keep it out of Git, Cloud, screenshots and shared messages. Stdout
contains only a sanitized JSON assessment and digest, never the paths or credentials.

Exit 0 for preparation means only `prepared_offline`; disposition is `BLOCKED_PREREQUISITES`.
Missing or invalid flags fail with exit 2 and a fixed reason code, without echoing arguments.
Supplying an approval digest without `--capture` does not trigger capture.

## External gate: not executed by implementation approval

Before any credential operation or capture, the primary and operator must complete the
separate acquisition review described in the [approved specification](superpowers/specs/2026-09-17-alpaca-free-data-validation-design.md):

1. Resolve paper-only SIP entitlement and intended private research/retention use. Public
   documentation contains an unresolved paper-only/IEX versus historical-SIP distinction.
   HTTP success is not legal clearance; do not bypass this with a live credential or paid plan.
2. Review the exact committed implementation and tests, requested scope and expiry, explicit
   private paths, retention permission, and private manifest digest.
3. Separately authorize installation/read of the paper credential. Do not paste it into chat.
   The 0600 file must contain exactly the JSON keys `key_id` and `secret_key`, with nonempty
   printable ASCII values of 16-256 characters and no whitespace. Its parent must be private
   0700. This is the helper's local file contract, not a provider key-format guarantee.
4. Pre-create the separately approved 0700 quarantine, outside Git, Cloud and production
   evidence locations, and approve one specific manifest digest for one capture attempt.

The helper constrains its own HTTP requests; it does not make the credential itself read-only.
It has no account, portfolio, order, funding or subscription endpoints. It does not inspect
account pages or discover credentials from environment variables or home directories.

After the separate gate, the command surface is `--capture --manifest-file` plus
`--approved-manifest-sha256`. The latter must be the exact reviewed 64-character digest; no
credentials or other prepare-time flags belong in the capture invocation. The helper verifies
the canonical config identity, repository root, matching full commit, tracked helper files,
clean tracked checkout and unexpired scope before accessing credentials. No source acceptance
or legal permission can be inferred from merely supplying the digest: operator approval is
an out-of-band prerequisite, not an unforgeable software capability.

The attempt marker is claimed before credentials/network. Existing or durability-uncertain
markers deny replay even if the earlier attempt failed before any request. Do not delete a
marker to retry. Diagnose the outcome and obtain a freshly prepared, separately approved
scope when another attempt is appropriate; the helper never does that automatically.

## Private outputs and failure meaning

- `<body-sha256>.raw`: exact successful, bounded, UTF-8 JSON-object response bytes. Duplicate
  JSON keys, nonfinite/unrepresentable numbers, excessive nesting, credential/header echoes,
  and inconsistent or unsupported response encodings are rejected. No price mapping occurs.
- `<receipt-sha256>.receipt.json`: request index, manifest/body hashes, bounded counts, HTTP
  status if observed, actual UTC instants, and an enumerated safe reason. No header or error
  response body is retained. A byte hash is not a canonical market-value hash.
- `<manifest-sha256>.attempt`: an empty owner-only exclusive attempt marker, not evidence of
  successful acquisition, research eligibility or promotion.

The first failure stops the run. An earlier successful sample may remain if the second
request fails; an unreceipted blob may remain if its receipt cannot be durably published.
Those are incomplete evidence, not a successful full capture. Clock regressions do not get
fabricated timestamps. An overall asynchronous timeout or unavailable storage can prevent a
failure receipt; the command still denies success and the attempt marker blocks replay.
Failed command summaries use `null` for sample count and body hashes instead of claiming no
sample was retained. Review the private receipts to establish any partial result.

Successful two-sample capture exits 0 with `capture_completed` and
`INSUFFICIENT_SOURCE_EVIDENCE`. Failures exit 2. The assessment preserves all fourteen spec
checks. Only two-sample HTTP/JSON access and retained-byte integrity can become `observed_pass`;
account status is linked to operator handoff, not authenticated. Rights, historical availability,
identity, numerical meaning, coverage, interpolation, session timing, actions and historical
universe are not certified by this helper. It never emits `READY_FOR_IMPORTER_DESIGN_REVIEW`.

The existing synthetic-only bundle assembler, loader, store allowlist, paper/shadow evidence
and paused deployment are unchanged. A full-history acquisition plan and importer require
subsequent authenticated-shape review and separate approval. This diagnostic starts no
paper-cycle or elapsed shadow clock.

## Verification

Default tests use synthetic JSON, invented credentials in temporary directories, and mocked
HTTP only. They never contact Alpaca. Narrow selection:

```bash
uv run pytest tests/unit/diagnostics tests/integration/diagnostics \
  tests/smoke/test_alpaca_probe_command.py -q
```

The implementation also requires the repository-wide Ruff, strict mypy, full Pytest with
branch coverage and unchanged 80% floor, Bandit, dependency audit, and lock validation.
See the [handoff](../PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md) for observed outcomes; local
test success is not CI or authenticated provider verification.
