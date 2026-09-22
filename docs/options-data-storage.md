# Offline options data storage

The options Parquet layer is an optional, credential-free research facility. It stores
already-normalized `OptionsDataRecord` values; it does not acquire data, contact a broker,
write to the trading ledger, establish data rights, or make a record eligible for live use.

## Dependency and interface

The implementation is pinned to DuckDB 1.5.5 in the research environment. The core package
does not import DuckDB at module load time. Calling either storage operation without that exact
version produces the sanitized `options_dataset_dependency_missing` error.

```python
from pathlib import Path

from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.options_parquet import publish_dataset, read_dataset

limits = BundleLimits(
    max_envelope_bytes=262_144,
    max_blob_bytes=131_072,
    max_total_bytes=1_048_576,
    max_records=100,
    max_json_depth=16,
)

manifest = publish_dataset(
    Path("/private/owner-controlled/options-data"),
    records,
    repository_root=Path("/absolute/path/to/repository"),
    limits=limits,
)
verified_records = read_dataset(
    manifest,
    repository_root=Path("/absolute/path/to/repository"),
    limits=limits,
)
```

The storage root must already exist, be owned by the current user, have mode `0700`, be
outside the repository, and contain no symlink traversal. Published directories remain `0700`
and files remain `0600`. Existing content-addressed files may be reused only when their bytes
match; conflicting files are never overwritten.

## Layout and integrity

Every Parquet file contains one record kind, one UTC event date, and one provenance class:

```text
partitions/
  kind=option_quote/
    event_date=2026-09-18/
      source_kind=imported/<sha256>.parquet
      source_kind=synthetic/<sha256>.parquet
manifests/<dataset-hash>.json
```

Synthetic and imported records therefore never share a part. `imported` describes provenance
only. Manifests always declare `production_eligible: false` and
`evidence_promotable: false`; neither successful storage nor successful verification changes
those verdicts.

The manifest binds the ordered record hashes, provenance classes, declared column schema, and
each part's relative path, SHA-256 digest, byte count, record count, and record hashes. Its file
name is the SHA-256 digest of the canonical manifest preimage. Reads validate those bindings,
file types and permissions before decoding records, then restore the original publication order.

Parquet exposes `kind`, `source`, `source_kind`, `entity_id`, `event_at`, and `available_at` as
queryable columns. The authoritative record is also stored as canonical JSON in a `VARCHAR`.
That JSON representation retains exact decimal money text and is decoded by the strict bounded
options-record codec rather than through floating-point Parquet types.

## Resource and network controls

Publication and reading enforce the same `BundleLimits` for record count, individual
JSON/Parquet parts, manifest size, JSON depth, and aggregate artifact bytes. A separate
aggregate decoded-UTF-8-byte budget spans every partition, so compression cannot evade the
record budget. SQL checks row counts and maximum/total record sizes before Python fetches
the rows; each row is charged again before decoding. Publication validates records and the
generated manifest with the same strict decoder used by reads.

DuckDB runs in memory with one worker,
a 64 MB memory limit, extension autoload and autoinstall disabled, community extensions disabled,
and external access disabled after its private temporary directory is allowlisted. SQL statements
are static, and both row values and file paths are passed as parameters.

Errors are intentionally sanitized and do not include rejected records or private paths. The
implementation does not infer dataset completeness, authenticity, licensing, economic value, or
authorization from an intact manifest. Those remain separate operator and governance decisions.
