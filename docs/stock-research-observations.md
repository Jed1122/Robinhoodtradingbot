# Individual-stock observation and screening workflow

Individual stocks are the primary discovery universe. Broad equity ETFs remain
benchmarks and optional diversification instruments. This workflow collects current
company evidence through the official Robinhood MCP; it does not propose orders or
qualify stock-selection strategies.

## Boundaries

The dedicated research facade validates 13 exact input/output schemas against the
reviewed selected-server profile. A second transport allowlist independently denies
all other tools. Account, portfolio, position, order review/submission/cancellation,
saved scans, watchlist changes and alerts are excluded. The OAuth credential itself
remains trading-capable; these controls are local software boundaries.

Schema drift, authentication failure, provider failure or incompatible results stop
collection. No browser callback is installed during acquisition. There is no order
submission adapter, live activation path, blind retry or AI override in this workflow.
A successful saved-token restart does not prove natural-expiry refresh or revoked-grant
handling. Those operational proofs remain outstanding.

## Bounded acquisition

Create an existing owned mode-0700 output directory outside source checkouts. An
explicit JSON job plan contains 1–32 `{tool, arguments}` objects. Job plans are inputs
to a bounded research experiment, not a second investment configuration system.

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_capture \
  --oauth-store /absolute/private/oauth-stock-research \
  --requests-file /absolute/private/requests.json \
  --output-dir /absolute/private/capture
```

The complete request graph and output directory are validated before connecting.
The directory handle remains open throughout acquisition. Input files must be regular,
not symbolic links, and at most 128 KiB. Calls are sequential, separated by at least one
second, with a 45-second per-call and 300-second acquisition budget. Numeric provider
quotas have not been established; these local bounds do not assert a vendor quota.
Provider failures stop the run without retry. Cancellation records a partial manifest
where persistence remains available, then propagates cancellation.

Each private observation preserves tool arguments, schema digests, request start and
receipt time, native structured payload and payload hash. Availability is receipt time;
financial period dates do not become publication timestamps. Results are SDK-level
observations, not original HTTP wire frames. Provider text is untrusted data and never
becomes an instruction. Public command output contains only status, counts and hashes.

Publication writes/fsyncs a temporary private file, links complete bytes without
replacement, then fsyncs the directory. A final content-addressed run manifest commits
its observation set. Ordinary publication failure removes only a newly created target.
A crash may leave orphan files; readers ignore observations without a committing
manifest. Previously committed files are never replaced.

`read_stock_observations` checks private regular-file metadata, bounded sizes, manifest
and observation identities, payload hashes, reviewed schema identities, request bounds
and receipt ordering. This establishes retained-byte integrity, not independent vendor
attestation, point-in-time historical completeness or economic qualification.

## Canonical stock policy

`configs/hybrid/stock-research.yaml` explicitly opts into `StockResearchAppConfig`
through the existing `load_config(..., hybrid_policy_path=...,
stock_research_policy_path=...)` loader. The resolved stock policy and its envelope
must match exactly. Existing hybrid settings and canonical hashes remain unchanged
when this extension is absent. An existing journal cannot adopt the new configuration
hash implicitly.

Defaults screen stocks at $10 or more, $2 billion market capitalization and a broker
30-session turnover feature of $20 million or more. These are research hypotheses.
Scanner turnover is not independently verified completed raw close-times-volume ADV.
Stock identity, tradability, spreads, balance sheets, corporate actions, execution
eligibility and full investment risk assessment require additional evidence.

`discovery_requests` partitions market capitalization into non-overlapping intervals.
Every partition must return its entire reported result, echo the requested filters and
contain only compatible rows before a global research-priority list is emitted.
Truncation, missing partitions, stale receipts or overlapping membership suppress the
ranking. Sequential results are explicitly non-atomic; completeness applies to each
observed query at its own receipt, not a simultaneous exchange-wide universe.

## Research priority

`screen_stocks` ranks six available current factors: return on equity, net margin,
annual EPS growth, quarterly revenue growth, positive earnings yield and free-cash-flow
yield. Sector percentiles are used when enough peers exist, otherwise the broader peer
basis is disclosed. Fixed experimental category weights are 40% quality, 35% growth
and 25% valuation. Missing/unusable facts exclude a company rather than becoming zero.
Legitimate negative accounting and growth values remain negative.

The score prioritizes deeper research. It is neither a confidence percentage nor a
calibrated return estimate. No historical predictive advantage has been established.
A high score does not establish a sound investment thesis, reliable balance sheet,
sustainable growth, executable liquidity or favorable after-tax returns. Every
candidate remains investment-ineligible and strategy-unqualified.

Next work is completed-history validation, financial/filing/earnings dossiers, cached
scheduled acquisition, authentic OAuth expiry/revocation recovery, stock strategy
validation, portfolio risk/reconciliation and operating evidence. No mandatory paper
waiting period is imposed, and live activation still requires separate authorization.
