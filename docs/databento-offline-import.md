# Offline Databento definition archive

This research-only importer validates a supplied OPRA.PILLAR parent-symbol Definition
batch, then streams provider-native records into private, content-addressed Parquet.
It never acquires data, loads a key, calls a broker, constructs an executable contract,
or grants economic/promotion/live eligibility. Existing option contracts, replay inputs,
configuration and trading risk limits are unchanged.

## Use

Install the separately locked research environment with `uv sync --project research
--locked --all-groups`. Create a private output directory outside the repository (mode
0700); keep original downloads private and outside Git, CI and Cloud tasks.

```sh
PYTHONPATH=src uv run --project research --no-sync python -m trading_bot.cli.databento_import stage \
  --source /absolute/private/download \
  --output-root /absolute/private/native-definitions \
  --parent SPY.OPT --start 2023-01-01 --end 2026-01-01

PYTHONPATH=src uv run --project research --no-sync python -m trading_bot.cli.databento_import verify \
  --manifest /absolute/private/native-definitions/manifests/HASH.json
```

The end date is exclusive. These commands accept local data only; they are not purchase
commands. No API key argument or environment variable is needed. Command errors are
sanitized and do not echo arguments. Exit0 means the stated archive operation completed,
not that the strategy is ready to trade.

## Validation and representation

- Provider manifest names, sizes and SHA-256 values must match all expected files; extra
  files, symlinks, writable-by-others sources, duplicate keys and request mismatches deny
  import. `preserve_batch` supports a verified, private, no-overwrite raw copy.
- The exact request is bound to OPRA.PILLAR, Definition, one explicitly supplied parent,
  nanosecond range, DBN/zstd, unlimited record count and unsplit direct delivery. Embedded
  DBN metadata must agree. Hash agreement is byte integrity, not source authentication.
- Versions1/2/3 are decoded without record upgrades using `databento-dbn==0.69.0`.
  Metadata mappings are structurally scanned with constant memory rather than loaded
  into Python objects. Mapping uniqueness, conflict-free joins and resolution remain
  **unverified**. The deprecated V1 record-count field is not trusted.
- `zstandard==0.25.0` checks complete concatenated frames, checksums when present and
  final EOF. Partial metadata/records, unsupported record types and trailing garbage
  deny completion. Compressed/decompressed bytes, metadata, record counts and unique
  symbols are bounded. No complete-file decompression or transactional-ledger bulk load.
- Partial-symbol and provider per-day quality declarations remain explicit limitations.
  A valid archive does not prove complete chains or complete eligible trading sessions.
  Out-of-request receive timestamps and receive-order regressions are reported, not
  silently clipped, sorted or relabelled.
- Preserve native nanosecond timestamps, integer 1e-9 price fields, exact raw-symbol
  padding, update actions, provider IDs, file identity and record ordinals/hashes.
  Undefined numeric sentinels become SQL NULL, never zero or huge fabricated values.
  All original bytes remain in the separate raw archive.
- A raw provider multiplier is not asserted to be the verified premium multiplier.
  OPRA date-only expiration is not a last-trading timestamp or a settlement deadline.
  `ts_recv` is not silently turned into research `available_at`. Sessions, deliverables,
  adjustment status, settlement/exercise rules and broker IDs require explicit enrichment.

The native format deliberately does **not** implement `OptionContract`, `ChainSnapshot`
or an executable `OptionsDataRecord`. This preserves those stricter existing contracts.

## Publication and verification

Records are retained in original order, including repeated updates. Bounded chunks are
partitioned by UTC receive date. JSON is only temporary, with explicitly typed DuckDB
columns preserving integers; permanent bulk storage is Parquet with Zstd compression.
DuckDB1.5.5 runs with extension auto-install/autoload disabled and restricted local access.

All provisional parts remain temporary until input EOF/hash validation succeeds. Final
part paths and manifests are content-addressed, private and no-overwrite. A publication
failure can leave unreferenced immutable parts; without a verified complete manifest they
are not a dataset. Verification checks manifest identity, private paths, part hashes,
columns and counts, including closed nested profile/provenance shapes and false eligibility
flags. JSON parsing and fingerprints use the same bounded snapshot; DuckDB queries a private
copy of the exact hashed Parquet bytes, never a second read of the mutable source path.
The result verifies that snapshot, not perpetual filesystem immutability. It does not
authenticate the source or establish financial validity.

## Economic evidence still required

Definitions contain no executable bid/ask history, underlying prices or realized strategy
returns. Genuine economic validation additionally requires authorized historical quotes,
underlying and event/calendar data, point-in-time contract enrichment/coverage, preregistered
selection/splits, a complete historical replay, after-cost accounting and uncertainty tests.
Do not buy additional data or consume credits under definitions-only approval.

Full risk composition, broker response/adaptor integration, complete lifecycle persistence
and continuous runtime composition remain separate unfinished migration work. Neither this
importer nor the existing paused monitor is a live options trading service.

## Primary format references (checked 2026-09-22)

- [DBN format and version layout](https://databento.com/docs/standards-and-conventions/databento-binary-encoding)
- [Pinned official metadata decoder](https://github.com/databento/dbn/blob/v0.69.0/rust/dbn/src/decode/dbn/fsm.rs)
- [Pinned official metadata encoder](https://github.com/databento/dbn/blob/v0.69.0/rust/dbn/src/encode/dbn/sync.rs)
- [Pinned official Python decoder interface](https://github.com/databento/dbn/blob/v0.69.0/python/python/databento_dbn/_lib.pyi)
- [OPRA definitions, expiration and ID caveats](https://databento.com/docs/venues-and-datasets/opra-pillar)
- [Definition schema and chronology](https://databento.com/docs/schemas-and-data-formats/instrument-definitions)
- [Pinned Zstd backend window-size implementation](https://github.com/indygreg/python-zstandard/blob/0.25.0/c-ext/decompressor.c)
