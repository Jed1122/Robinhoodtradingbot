# Offline native ETF replay and economics

The standalone command is `python -m trading_bot.cli.etf_native`. It does not
change the main CLI, contact a provider, read credentials, connect to a broker,
deploy a service, or enable paper/live trading. The software path and actual
market-data qualification are separate deliverables. Every result remains
`ECONOMIC_NO_GO`, `execution_enabled: false`, and `evidence_promotable: false`.

## Complete software demonstration

Create an absolute, private directory outside the repository (mode `0700`), then:

```sh
PYTHONPATH=src uv run --offline python -m trading_bot.cli.etf_native fixture-study \
  --report-dir /absolute/private/reports \
  --config-dir configs
```

This preregisters exact inputs before evaluating the real offline engine and
economic evaluator for hypothetical $500 and $1,000 cash, each under conservative,
base, and optimistic scenarios. Input generation is pure: no strategy, account
replay, or outcome evaluation runs while creating fictional observations.
All six combinations share identical source, cost, and instrument identities.
The $100 risk reference and canonical limits remain unchanged.

Fictional acknowledgements, cancellation timing, settlement, quoted capacity and
costs demonstrate mechanics only. They do not establish historical execution,
empirical calibration, profitability, paper cycles, or shadow dates.

## Saved native observations

`history-run` requires saved, receipt-bound Alpaca bars and quote pages, plus the
hash-bound calendar and issuer workbook. It accepts no network endpoint or secret.
Use matching repeated `--quote-capture-dir` and `--quote-manifest-hash` options
for multiple archives. There are at most 128 archive inputs and 128,000 total quote
observations. Duplicate archive identities are rejected; equal-time native quote
records remain present for the execution owner's conflict/capacity checks.

```sh
PYTHONPATH=src uv run --offline python -m trading_bot.cli.etf_native history-run \
  --capture-dir /absolute/private/bars --manifest-hash BAR_MANIFEST_SHA256 \
  --quote-capture-dir /absolute/private/quotes --quote-manifest-hash QUOTE_MANIFEST_SHA256 \
  --reference-dir /absolute/private/references \
  --calendar-hash CALENDAR_SHA256 --issuer-hash ISSUER_XLSX_SHA256 \
  --cost-manifest /absolute/private/costs/COST_MANIFEST_SHA256.json \
  --instrument-file /absolute/private/instruments/INSTRUMENT_SHA256.json \
  --report-dir /absolute/private/reports --capital 500 --scenario base
```

The reference directory contains `calendar.json` and `ssga-distributions.xlsx`.
Each directory must be `0700`; input files must be `0600`. Paths must be absolute,
outside the repository, and have no symlink/traversal components. Filename hashes
bind the exact cost/instrument bytes; changing formatting also changes identity.

Native record hashes and provider provenance survive adaptation. Daily completion
is explicitly projected to the following New York midnight. Native quote replay
availability uses its market timestamp as an **unverified research assumption**;
retrieval timestamps do not certify original publication. Calendar openings do
not prove absence of halts. All unknown quote conditions, controls, fractional
terms and size conversions remain blocking reasons. A raw round-lot value is not
silently multiplied into shares. No native observation is relabeled synthetic.

Issuer ex/pay events use exact calendar session openings as a disclosed,
hash-bound date-to-time assumption. Missing dates within the calendar deny input.
A payment beyond the final calendar date leaves its entitlement outstanding and
adds `payable_after_input_horizon`; no payment or settlement is fabricated.
Split history is not inferred. The adapter retains 2024–2025 records, including
the final daily bar's true projected completion beyond the UTC year boundary;
the runner keeps the holdout excluded from development evaluation.

### Explicit instrument metadata

The instrument file is strict bounded JSON, at most 16 KiB. The top-level fields
are exactly `schema` and `instrument`; the schema is `etf-native-instrument-v1`.
The instrument mapping contains all common `Instrument` fields except `data_hash`,
which is derived from the exact file bytes. For example:

```json
{
  "schema": "etf-native-instrument-v1",
  "instrument": {
    "id": "SPY",
    "symbol": "SPY",
    "asset_class": "equity",
    "provider_status": "unverified-research-input",
    "tradable": true,
    "fractional_eligible": false,
    "price_increment": "0.01",
    "quantity_increment": "1",
    "minimum_quantity": "1",
    "minimum_notional": "1",
    "maximum_quantity": null,
    "correlation_group": "US-equity",
    "observed_at": "2015-12-01T00:00:00.000000Z"
  }
}
```

These example values are **not verified broker terms**. Native CLI metadata is
intentionally integer-only: `fractional_eligible` must be false, quantity increment
and minimum quantity must be at least one, and the status must remain explicitly
unverified. User-supplied metadata cannot clear the independent quote/source gates.
Do not add credentials or free-form provider responses to this file.

### Cost and study identity

The existing `etf-cost-manifest-v1` loader remains authoritative. Every required
role must cover the full fixed study window, with exact Decimal text, valid units,
known-before-effective dates and retained SHA256-named source/calibration bytes.
Missing roles are never treated as zero cost, and calibration stays unverified.

Before replay, the CLI reads only bounded manifest syntax to derive `cost_hash`,
freezes the study with `source_plan_hash = dataset.dataset_hash` and
`cost_plan_hash = cost_hash`, then invokes the unchanged cost loader. That loader
must validate the manifest against this exact study hash, current code/config,
and retained evidence. The syntax preview alone never admits costs. Preparing a
cost manifest therefore requires the current study preimage; an older code or
source identity is not silently migrated. No outcomes are used to choose inputs.

## Resume and six-run economics

For a durable prefix, add an absolute private `--checkpoint-dir` and
`--through-ordinal N` to `history-run`. Its summary includes `checkpoint_head`.
To advance, repeat the same input arguments with the same directory, remove or
increase the prefix boundary, and pass `--expected-head` from the previous result.
Changed inputs, stale heads and cursor regression deny. Reconstruction remains
paused; local checkpoints do not certify production recovery or distributed leases.
An expected head without a checkpoint directory is rejected.

Replace `history-run` with `economic-report` and omit capital/scenario/checkpoint
options to run all six fixed combinations. The evaluator receives the exact
candidate and constrained benchmark outcomes, cost identity, daily observations,
and residual account obligations. It preserves canonical validation thresholds,
purged folds, independent-opportunity counts, matched cash/benchmark comparisons,
and dependent uncertainty calculations. Missing samples, unresolved execution,
unmeasured robustness and unqualified sources remain explicit no-go conditions.

## Artifacts and status

Before evaluation, a descriptor-bound content-addressed preregistration freezes
study, source/cost/instrument identities, simulation schedule and request hashes.
Each history result is published separately, followed by the economic report.
Publication uses existing no-symlink, no-overwrite, private-file machinery and a
32 MiB ceiling per artifact. Identical retries are idempotent; conflicting bytes
are never overwritten. A later failure can leave a valid preregistration or
partial set of history artifacts; their presence alone is not a completed report.

Standard output contains only sanitized hashes, counts and readiness flags.
Raw quote arrays, native archive payloads and credential paths are not printed.
Full simulated outcomes are retained in private report files. The report does not
grant any authority. Exit code `1` means invalid/unsafe input or publication failure;
exit code `2` means an offline non-promotable result was produced. No command has a
live-enable, assumptions-validated, promotion or risk-limit override option.

## Next steps toward project completion

The source-neutral runner, persistence, evaluator and operator commands implement
the bounded offline software path. Separately establish continuous usable
development quote/control/action coverage, valid instrument/size semantics,
cost calibration and sufficient independent economic evidence. Only accepted
research can lead to the unchanged qualifying paper/shadow observations and
broker/runtime checks. Explicit live authorization remains a final separate gate.

## Execution and evaluation details

The account owner remains `replay_etf_account`; no alternative sizing or loss
calculator is introduced. Native execution reuses the common feature, momentum,
portfolio, intent, cost and fill-accounting components. The source-neutral records
also admit explicitly synthetic inputs for tests, without weakening old fixture
validators. Acknowledgements and settlement are simulated protocol events, not
claims about a broker. Cancellation-race fills require the frozen explicit
`allow_inflight_cancel_fill` assumption and cannot exceed the original reservation.

Conservative/base/optimistic participation fractions are 25%/50%/100% of observed
capacity, with extra-slippage multipliers 2/1/0.5. All still execute at adverse
bid/ask prices, respect the original limit and require a later eligible event.
Prices must be two-sided and unlocked. Duplicate native timestamps cannot refill
capacity. Missing, crossed, stale or unsupported observations remain denials.
The original 10,000 account-fact bound is retained; this bounded evaluator is not
a claim of unrestricted tick-history throughput. Large-history reconstruction
performance must be benchmarked before choosing a production/research data scale.

Daily account observations include an explicit account-event cursor so equal-time
later facts do not leak into an earlier snapshot. Later terminal facts without a
corresponding mark preserve actual cash/fees and make the final marked comparisons
unavailable. Paid dividends, receivables, unsettled fills and trial reservations
are distinct. No terminal or fold boundary fabricates a sale or settlement.

Liquidation marks use the same market-control, split, quote-quality and epoch
checks as fills. A closing snapshot is taken immediately before applying the
closing control, using only a still-fresh, previously admissible quote. Equal-time
control disagreements include unknown execution semantics and remain latched
until a strictly newer native control. Older session deliveries cannot advance
settlement or rebalance cadence. Positive entry-stop geometry does not suppress
an independently authorized simulated protective sell after a severe price gap.

The v1 account contract cannot reconstruct historical ex-date entitlement from a
delayed ex-date observation. Such input explicitly blocks further execution and
economic completeness; neither entitlement nor a subsequent payment is invented.
Recorded cash and fees remain visible, but profit, marked return, opportunity
counts and the fully invested comparison are unavailable. On-time distributions
belong only to shares actually held at ex-date. Episode labels extend through
their own settlement and first entitled payment, never shrink on payment, and
never include distributions on shares already sold. Fold opportunity intervals
match the corresponding return intervals, including first-day intraday activity.

Operating costs are charged over inclusive calendar dates. The current canonical
cost contract supplies aggregate USD/day, not verified data/model/server line
items; the report explicitly marks itemization unverified. Episode operating
allocation is equal with the rounding residual assigned to the last episode.
Cash yield is separately labeled unverified simple ACT/365 on initial principal.
Spread/slippage are embedded in fills, never subtracted twice; separate attribution
is unavailable unless the inputs support it. Draws are not independent trades.
The final holdout remains sealed; unmeasured parameter stability and unresolved
multiple testing remain reasons for `ECONOMIC_NO_GO` even when returns are positive.
