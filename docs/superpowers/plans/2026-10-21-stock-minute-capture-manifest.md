# Individual-stock minute capture manifest and reconstruction

This is one pure data-adapter increment within stock-data qualification. It does
not qualify a source or strategy and performs no filesystem, credential, network,
broker, scheduling, technical-feature admission or promotion operation.

## Intent and dependencies

Individual companies remain the research priority. Existing scanner rankings are
research triage; Robinhood's unknown native interpolation still blocks technical
metrics. Reuse `market_data.alpaca_stock_minutes` without changing its public
interfaces, flags, grid recipe or native parser. Leave SPY/ETF adapters untouched.

The output binds original calendar evidence and exact response bytes to one stock
and one or two declared sessions so a later owner can reconstruct the existing
proof independently. Successful reconstruction means local integrity and clock
consistency only. Actual entitlement, retention/cloud rights, authentic calendar,
HTTP/elapsed-time provenance and source/strategy qualification remain separate.

## Frozen public contract

Add `trading_bot.market_data.stock_capture_manifest`:

- `StockMinuteCaptureManifest`, frozen/slotted and `repr=False`: `capture_id` (32
  lowercase hex), `code_sha256`, `config_sha256` (64 lowercase hex), `requests`
  (tuple of one or two existing `StockMinuteRequest` objects), `calendar_bodies`
  (tuple of original bytes), `capture_boot_id` (canonical lowercase UUID string),
  `capture_started_monotonic_ns` (exact positive bounded integer),
  `capture_started_at` (aware UTC datetime). Requests must have one exact symbol
  and distinct chronological sessions. Every declared calendar hash must match an
  original body; bodies must be unique, all referenced and sorted by SHA-256.
  At most two bodies, each at most 1 MiB, with no repair or normalization.
- `dump_stock_capture_manifest(manifest) -> bytes` and
  `parse_stock_capture_manifest(raw: bytes) -> StockMinuteCaptureManifest`:
  strict version-1, closed-schema canonical JSON with one trailing newline,
  sorted keys, compact separators and no duplicate keys/nonfinite values. The
  exact field set is `schema_version`, `capture_id`, `code_sha256`,
  `config_sha256`, `requests`, `calendar_bodies`, `capture_boot_id`,
  `capture_started_monotonic_ns`, `capture_started_at`. The version is integer 1.
  Each request record contains exactly `symbol`, `request_sha256`, `session_date`,
  `opens_at`, `closes_at`, `calendar_source_url`, `calendar_sha256`,
  `calendar_received_at`; reconstruct the existing declaration/request and verify
  its request hash. Each calendar record contains exactly `sha256` and
  `body_base64`; require canonical validated base64 and verify exact original-byte
  hash. Enforce a 3-MiB total manifest limit. Date/times use canonical ISO strings
  emitted by these existing Python values; reject noncanonical round trips.
- `StockMinuteCapturedResponse`, frozen/slotted and `repr=False`:
  `request_sha256`, `body_sha256`, `body` (bytes), `page_index`,
  `requested_page_token`, `received_at`, `received_monotonic_ns`, `boot_id`,
  `http_status`. Exact status must be integer 200; other fields retain the
  existing page/parser limits. These are caller declarations, not authenticated
  HTTP or clock evidence. A body is nonempty and at most 1 MiB; reject bad hashes
  and malformed field types with the fixed error below.
- `reconstruct_stock_capture(manifest_raw, responses, *, as_of)` returns the existing
  `StockMinuteProofAssessment`. Reparse the manifest, reconstruct every page from
  its original bytes with `parse_stock_minute_page`, then call the unchanged
  `assess_stock_minute_proof`. Never accept already-derived aggregates as inputs.
  Responses must be an exact tuple with at most four entries/4 MiB overall,
  ordered by strictly increasing UTC and monotonic receipts in the manifest's
  exact boot domain. Both clocks must fall within the declared 60-second capture
  window. Preserve missing/partial captures for assessment; unknown requests,
  mismatched hashes, duplicate identities, future receipts, token/sequence errors
  or mutated records reject the whole reconstruction. No rows may be dropped.
- Fixed `StockCaptureManifestError(ValueError)` message:
  `stock_capture_manifest_invalid`; no input values, bodies, symbols, URLs or
  diagnostics in errors. All public functions sanitize lower-level validation
  errors. Objects expose permanent init-disabled false values for `qualified`,
  `source_qualified`, `strategy_qualified`, `investment_eligible`,
  `trading_enabled`, `live_authorized`; these flags are not serialized or accepted
  as caller input. Original bytes are never printed or logged.

All datetimes must be UTC. Capture starts at least 15 minutes after every declared
close and after calendar receipt. The manifest's clocks/code/config/URL/HTTP fields
remain declarations. Do not infer actual elapsed time, permitted SIP access,
publication/finality, stable security identity, corporate actions, historical
membership or total returns. Native interpolation stays unknown; local no-fill
recipe metadata is unchanged. Two sessions do not provide a 200-observation history.

## Implementation and verification

1. Write fictional RED tests for missing codec/reconstruction, deterministic exact
   round trips, corrupt or missing calendar bodies, changed context/hashes, invalid
   booleans/numbers/flags, unsupported schemas, noncanonical encodings and limits.
2. Implement only pure value validation/codec/reconstruction. Avoid a second config
   system, duplicate native parsing or a new acceptance/qualification policy.
3. Test complete two-session input, valid empty/partial input, pagination/gaps,
   clock/boot/cursor/hash drift, altered raw bytes and future data. Assert unchanged
   native interpolation and all false qualification flags.
4. Run new tests, existing stock-minute/technical/screen tests, Ruff and strict mypy.
   Root independently reviews exact diff and centrally verifies integration.

The agent may modify only the new source module, its new unit test and
`docs/stock-minute-capture-manifest.md`. This plan and all existing source/contracts
are read-only. The agent cannot alter the frozen schema, acquisition authority,
policy, risk, strategy, persistence, runtime or deployment. Return questions to root
if the contract cannot be implemented coherently; do not invent an unsafe fallback.

The actual immutable private archive, attempt marker, credential/entitlement checks,
bounded transport and native acquisition remain root-owned future work.
