# Native ETF quote catalog

The v1 catalog indexes existing private Alpaca SPY/SIP quote captures. It does not
acquire data, read credentials, connect to a broker, generate controls, execute
orders or establish customer costs. Source/cost qualification, execution and
promotion flags are permanently false. Historical control/gap waivers apply to
exploratory research only.

## Library usage

Run with the project environment and `PYTHONPATH=src`. `private_root` must already
exist outside every Git checkout, owned by the current user with mode 0700.
Each selected capture is beneath it, with original owner-private 0600 files.

```python
from pathlib import Path
from trading_bot.config import load_config
from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.etf_quote_catalog_models import QuoteCaptureLocation
from trading_bot.market_data.etf_quote_catalog import (
    publish_quote_day, publish_quote_catalog, iter_catalog_quotes,
)

repository_root = Path.cwd().resolve()
private_root = Path("/absolute/private/source-root")
loaded = load_config(repository_root / "configs/base.yaml",
                     repository_root / "configs/backtest.yaml",
                     repository_root / "configs/safety-envelope.yaml", environ={})
# Replace declarations locally; do not paste customer data or credentials.
location = QuoteCaptureLocation("existing-capture", "a" * 64)
day = publish_quote_day(private_root, (location,), repository_root=repository_root)
identity = publish_quote_catalog(private_root, (day.index_hash,), loaded=loaded,
                                code_revision="b" * 40, repository_root=repository_root)
count = 0
for occurrence in iter_catalog_quotes(
    private_root, identity,
    start_ns=parse_timestamp_ns("2018-12-26T14:30:00Z"),
    end_ns=parse_timestamp_ns("2018-12-26T14:35:00Z"),
    repository_root=repository_root,
):
    count += 1  # Consume incrementally; never log native customer/source records.
# Count is a traversal result only after normal exhaustion, not a study verdict.
```

The supplied code identity is a caller declaration, not verified release/runtime
attestation. Publication verifies canonical backtest/live-disabled configuration;
original native manifests retain their distinct source code/config identities.

## Integrity and limits

- Day index: at most 1,024 distinct, sorted, nonoverlapping capture requests wholly
  within one UTC day. Study: at most 4,000 sorted unique days. JSON: at most 1 MiB
  per artifact, separate `etf-native-quote-day-v1` / `etf-native-quote-catalog-v1`
  hash domains, duplicate-free exact fields, immutable publication with fsync.
- Original captures are referenced, not copied, rounded, converted to synthetic
  records or loaded into the transactional ledger. Decimal prices, integer ns,
  raw sizes/conditions, native page/row/body identities remain exact.
- All selected captures are verified before the first occurrence. Each is reread
  before traversal. A later external mutation can still raise after a yielded
  prefix: discard incomplete traversal results. This API issues no economic or
  completed-study receipt. Nonselected future raw captures are never opened;
  bound metadata indexes are still checked.
- Memory is capture-bounded, **not page-streaming**: the existing native reader
  materializes at most 128,000 observations for one capture. Day metadata is read
  independently. Collecting the iterator into a list/tuple forfeits this bound.
- Missing quote intervals, historical publication/control state, size/condition
  interpretation and coverage stay unknown; adjacent request bounds do not prove
  continuous market coverage. No fabricated OPEN or availability timestamp.
- Reject symlinks/hardlinks/devices, unsafe modes/ownership, Git ancestors,
  duplicate/overlapping captures, corrupted/missing files and mismatched counts.
  Errors expose only `etf_quote_catalog_invalid`, not private paths or contents.

Existing 10,000-row legacy readers, 128,000-row native capture limits, historical
dataset/account/statistics/checkpoint limits, sealed qualified-source factories
and canonical risk configuration are unchanged. Existing Parquet/DuckDB bulk
research storage is still the projection target; this index is not a database.

## Remaining integration

This intake slice is not the complete historical execution/replay/economic study.
The current replay/account/statistics kernels still materialize bounded histories;
they need a separately versioned, integrated incremental consumer under the waiver.
Remaining study intervals and costs must be acquired/validated without evaluating
the untouched holdout prematurely. Genuine customer fills, final fees and causal
order/quote timings remain independent missing evidence.

The operator's diagnostic-trade authorization is recorded separately. Fresh local
preflight denies with `ready=false/external_capability_missing`; no constructible
equity write adapter or trusted live composition exists. Do not bypass it through
an app tool. Paper/shadow eligibility, deployed recovery and live authorization
remain independent; no diagnostic catalog traversal counts as a qualifying cycle.
