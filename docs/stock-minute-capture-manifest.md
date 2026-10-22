# Individual-stock minute capture manifest

`market_data.stock_capture_manifest` is a pure local codec and original-byte
reconstruction seam. It performs no file, credential, network, broker, database,
scheduling, risk, strategy, technical-admission or promotion operation. It does
not change the SPY/ETF adapters or Robinhood's unknown interpolation metadata.

## Public interface

`StockMinuteCaptureManifest` is a frozen, slotted value with suppressed field
representation. It binds a 32-character lowercase-hex capture identity, SHA-256
code/config declarations, one stock and one or two chronological existing
`StockMinuteRequest` values, original calendar bodies, a canonical lowercase UUID
boot declaration, a positive signed-64-bit monotonic start and a UTC capture start.

Every calendar body must be nonempty bytes of at most 1 MiB. One or two bodies
are hash-sorted, unique, all referenced and matched exactly against the requests'
calendar hashes. Their content is not parsed or authenticated. Capture starts at
least 15 minutes after every declared close and at or after calendar receipt.
These boundaries preserve the unchanged stock-minute parser's inclusive rules.

`dump_stock_capture_manifest(manifest)` returns strict version-1 canonical JSON
bytes with sorted keys, compact separators, ASCII escaping and exactly one final
newline. The closed top-level fields are:

```text
schema_version, capture_id, code_sha256, config_sha256, requests,
calendar_bodies, capture_boot_id, capture_started_monotonic_ns,
capture_started_at
```

Each request contains exactly `symbol`, `request_sha256`, `session_date`,
`opens_at`, `closes_at`, `calendar_source_url`, `calendar_sha256` and
`calendar_received_at`. Each calendar contains exactly `sha256` and `body_base64`.
Date/time strings use their existing values' canonical `isoformat()` output;
UTC datetimes therefore use `+00:00`. No source bytes are normalized.

`parse_stock_capture_manifest(raw)` accepts at most 3 MiB of exact immutable
bytes, reconstructs the existing session/request types, checks every hash and
requires byte-for-byte canonical round trip. Duplicate keys, extra/missing
fields, nonfinite JSON, noncanonical base64, altered padding bits, unsupported
versions and noncanonical date/time spellings reject.

`StockMinuteCapturedResponse` binds `request_sha256`, `body_sha256`, original
`body` bytes, `page_index`, `requested_page_token`, UTC `received_at`, positive
signed-64-bit `received_monotonic_ns`, canonical UUID `boot_id` and exact integer
`http_status=200`. Each body is nonempty and at most 1 MiB. Status and clocks are
caller declarations; this type is not an authenticated transport receipt.

```python
assessment = reconstruct_stock_capture(
    manifest_raw,
    responses,  # exact tuple of StockMinuteCapturedResponse values
    as_of=utc_cutoff,
)
```

Reconstruction reparses the manifest and every original response body using
`parse_stock_minute_page`, then calls the unchanged
`assess_stock_minute_proof`. Inputs cannot substitute derived aggregates. It
allows at most four responses and 4 MiB total, preserving the existing two-page
per-session bound. Request/page identities are unique; responses must follow
the existing cursor/session order with strictly increasing UTC and monotonic
receipts in the manifest's exact boot domain. Both clocks independently fall
inside the inclusive 60-second capture window, and no receipt may exceed
`as_of`. Equal elapsed durations across the two clocks are not inferred.

Missing responses, a valid empty response, incomplete pagination and absent
minutes remain explicit assessment outcomes. No row is repaired, dropped,
carried forward or zero-filled to make a complete grid. Invalid native rows,
unknown requests, hash/clock/boot drift or mutated records reject the whole
reconstruction through `StockCaptureManifestError`, whose only message is
`stock_capture_manifest_invalid`. Original values and lower-level diagnostics
do not enter that message. The module prints and logs nothing.

Both new objects expose permanent init-disabled `False` values for `qualified`,
`source_qualified`, `strategy_qualified`, `investment_eligible`,
`trading_enabled` and `live_authorized`. Flags are absent from the wire schema;
consumers revalidate them and nested immutable request declarations. The existing
assessment's qualification flags remain false as well.

## Evidence limits and next steps

A complete reconstruction establishes local byte integrity and declared clock
consistency. It does not establish authentic calendar/HTTP/elapsed-time evidence,
permitted SIP access, retention or cloud rights, provider finality/publication,
stable security identity, corporate actions, historical membership or total
returns. Native interpolation remains unknown. `no_fill_applied=True` describes
only the existing local aggregation recipe. The exclusive-close core window is
not complete auction-inclusive daily trading volume; two sessions do not supply
a 200-observation history or validate a trading strategy.

The next root-owned steps are the private immutable archive and attempt marker,
verified credential/entitlement/retention scope, bounded transport and actual
calendar/data acquisition. A separately reviewed source-neutral technical input
contract and broader stock point-in-time/out-of-sample cost/tax evidence remain
required before investment eligibility. This increment grants no live authority.
