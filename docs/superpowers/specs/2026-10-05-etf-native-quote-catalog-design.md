# Bounded native ETF quote catalog

Date: 2026-10-05. Scope: an independently testable intake slice of the requested
Alpaca-only historical intake/replay. Native execution is the retained operator
preference. Standing uninterrupted-build instructions govern execution; no claim
is made that the operator reviewed this newly written artifact individually.

## Intent and boundary

Preserve original Alpaca SPY/SIP captures and make a many-capture study traversable
without materializing all historical quotes. The October 5 historical halt/LULD/gap
waiver applies only to exploratory research. Missing control state is unobserved;
the catalog emits quotes, never fabricated OPEN/control events or executable orders.

The operator has now explicitly authorized a trade for cost diagnosis. That is
authorization, not capability/readiness evidence or permission to bypass existing
pretrade/promotion/reconciliation controls. The fresh local preflight returns
`ready=false`, `external_capability_missing`. No broker write is part of this slice.

This deliverable is NOT whole-study replay/economics. Existing replay datasets,
account facts, statistics and checkpoints have independent materialization/count
bounds. They remain unchanged; a catalog must not be wrapped in `tuple(...)` and
misrepresented as a streaming economic owner.

## Approach

Use a two-level content-addressed catalog over existing private native captures.
One UTC-day index binds at most 1,024 nonoverlapping captures; one study catalog
binds at most 4,000 distinct sorted day indexes. Each JSON artifact is bounded to
1 MiB with duplicate-free exact-field decoding. These are new format bounds, not
new risk settings or a competing configuration loader. Existing capture/page,
legacy small-reader and replay limits remain unchanged.

Reusing the native reader once per capture retains its maximum 128,000-row
working set; this is capture-bounded iteration, not page-streaming. Raw captures
are retained outside Git, not copied into SQLite. Existing Parquet/DuckDB research
storage remains the future bulk projection target; this catalog is an immutable
source index, not a replacement database or compressed archive.

Alternatives rejected: lifting the old CLI/tuple ceilings does not fix downstream
memory; converting native records to synthetic records loses provenance; storing
rounded prices or microsecond timestamps loses admitted financial/time precision.

## Frozen interfaces

New modules: `market_data/etf_quote_catalog_models.py` owns exact immutable models,
strict versioned codecs and file-format bounds; `market_data/etf_quote_catalog.py`
owns private publication/read/iteration, reusing existing descriptor-relative
storage and receipt-bound archive readers.

- `QuoteCaptureLocation(relative_path: str, manifest_hash: str)` selects an explicit
  capture beneath a private root. No absolute, parent, empty or alias paths.
- `QuoteCaptureReference(location, archive_hash, start_ns, end_ns, record_count)`
  binds the verified native request and archive identity without retaining keys,
  credential paths or continuation tokens.
- `QuoteDayIndex(day, captures)` and `QuoteCatalog(code_revision, config_hash, days)`
  have separate v1 hash domains and immutable false source/cost/execution/promotion
  flags. Day references bind date, index hash, capture count and observation count.
- `publish_quote_day(root, locations, *, repository_root) -> QuoteDayReference`
  verifies complete native receipts before publishing an immutable day index.
- `publish_quote_catalog(root, day_hashes, *, loaded, code_revision,
  repository_root) -> str` checks canonical backtest/live-disabled configuration
  and returns its content-addressed catalog hash. Code identity is a caller
  declaration, not release/authentication attestation.
- `read_quote_catalog(root, catalog_hash, *, repository_root) -> QuoteCatalog`
  rehashes strict private metadata and reconstructs its exact bound day indexes.
- `iter_catalog_quotes(root, catalog_hash, *, start_ns, end_ns,
  repository_root) -> Iterator[CatalogQuoteOccurrence]` prevalidates all selected
  captures before its first occurrence, then rereads one capture at a time.
  Each occurrence preserves capture/record identity, Decimal prices, integer
  nanoseconds, raw sizes and conditions, and unknown historical availability.

## Integrity, privacy and incomplete outcomes

Day request intervals must belong wholly to that UTC day; crossing-day requests
are unsupported by this new catalog, not silently split. Sorted disjoint intervals
may have gaps; adjacency/request coverage is never tick completeness. Duplicate
capture identities, overlap, mismatched metadata, missing/corrupt receipts or raw
bytes deny. Identical quote rows at one timestamp remain distinct occurrences.

Require explicit owner-private roots/files, no symlink traversal, hardlinked files,
FIFO/device inputs, any Git ancestor or outward references. Reuse stricter native
private-file helpers, sanitized errors, immutable publication and fsync. Never scan
unrelated directories, open credentials or call a provider/broker.

All selected captures are validated before initial yield. An external mutation
after that pass can still fail a later reread: any yielded prefix is incomplete,
not a completed study. Only normal iterator exhaustion supports a traversal count;
no economic completion report is published by this API. Future/holdout raw captures
outside the explicit half-open selection are not read, and adding unrelated future
partitions cannot change selected native occurrences. Metadata identity does change
when the catalog changes. No unrecorded availability timestamps are invented.

## Acceptance

Tests first: more than one day/capture without aggregate quote materialization;
exact Decimal/ns/conditions and same-time occurrence ordering; gaps stay unknown;
overlap, duplicates, dirty flags/schema/counts and late corruption deny; selected
prefix unchanged after future inputs; nonselected raw files are not opened;
unsafe roots/links/modes deny; idempotent publication does not overwrite; network
and credential access forbidden; legacy limits and identities unchanged.

Run focused catalog/native tests, Ruff/Mypy, whole default pytest with unchanged
80% overall coverage, security/lock/config checks and independent whole-branch
review. Report any unavailable check; fixture tests are not genuine data/cost or
promotion evidence. Reverify the retained development capture privately only after
committing a clean candidate. No deployment, live-mode change or trade occurs.
