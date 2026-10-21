# Descriptive raw stock technical features

`research.stock_technicals.compute_stock_technicals` computes reproducible
descriptions of accepted raw daily histories. It performs no I/O, broker calls,
source acquisition, configuration changes, forecast, ranking, score, portfolio
decision or order generation. All source/strategy qualification, investment
eligibility, trading and live flags stay false.

```python
compute_stock_technicals(
    *, as_of: datetime,
    history: tuple[StockHistoryProjectionBatch, ...],
) -> tuple[StockTechnicalFeatures, ...]
```

## Input and provenance

`as_of` must be aware UTC. Only original receipts at or before it contribute
features or company membership. Duplicate visible companies reject rather than
silently selecting a receipt. Inputs must be an exact immutable tuple; bounds
are 256 batches, 1,000 visible companies and 100,000 visible source bar slots.
Identity, source hash, original request, projected hash and normalized receipt
must remain consistent. Invalid global provenance raises only
`ValueError("stock_technicals_invalid")`.

Each frozen feature record retains the original receipt, original projection
batch hash, entire immutable company outcome/projection context, and normalized
observation hash when available. `feature_hash` binds this provenance, method,
values, missingness, limits and false flags under `stock-technicals-v1`.

The input must already have passed the unchanged history normalizer. Every
retained actual bar must additionally have explicit raw basis, regular session,
`interpolated=False`, positive consistent OHLC, nonnegative volume and an
injected completion declaration valid by receipt time. Unknown markers/basis/
completion, unresolved null bar rows or invalid chronology leave every metric
null. The module neither selects a completed prefix nor removes a bad actual
row to make a feature available. Caller declarations remain unqualified; the
calculator authenticates neither source adjustments nor an exchange calendar.

`calculation_status` distinguishes calculated, unavailable, quarantined and
input-ineligible histories. This describes calculation prerequisites only.
Quarantined companies keep no metrics and unknown counts (`None`). Validated
empty histories can have actual zero counts. `total_bar_count` counts retained
actual bars; `source_bar_slot_count` also counts interpolated omissions and null
slots; `supported_bar_count` counts bars meeting the calculation prerequisites.
Omitted interpolated-bar symbol/left-edge provenance stays in the outcome.

## Windows and formulas

Windows count **retained completed daily observations**. They do not certify
all exchange sessions: source gaps, holidays and calendar coverage remain
unverified, and no gap is filled. The conventional 20/60/120-session labels
therefore mean observation lags in these unqualified outputs. The method is
explicitly recorded as `window_basis="retained_completed_daily_observations"`.

For positive raw closes `C` and share volumes `V`, the following fields use the
latest retained observations:

| Field | Formula and minimum history |
| --- | --- |
| `price_return_20/60/120` | `C[-1] / C[-N-1] - 1`; needs `N+1` bars |
| `sma_50/200` | Arithmetic mean of the latest `N` closes; needs `N` bars |
| `realized_volatility_20` | Sample standard deviation of 20 consecutive simple close returns, multiplied by `sqrt(252)`; needs 21 bars |
| `average_volume_20/30` | Arithmetic mean of the latest `N` share volumes; needs `N` bars |
| `average_dollar_volume_20/30` | Arithmetic mean of each bar's `C * V`; needs `N` bars |
| `series_max_drawdown` | Maximum `1 - C / running_peak` over the entire retained close series; needs two bars |

Returns, volatility and drawdown are fractions, not percentage display values.
Drawdown is a nonnegative loss magnitude. Zero is retained when the observations
actually imply zero, such as constant-price volatility or zero share volume.
Insufficient windows stay `None`; there is no zero fill or short-window fallback.

Volatility uses centered sample variance with denominator 19 for 20 returns.
The fixed factor 252 is a documented nominal annualization convention, not a
claim that the retained observations cover 252 exchange sessions per year.
Calculations use an isolated Decimal context: precision 50, half-even rounding,
explicit exponent/trap settings. The caller's Decimal precision or rounding
does not change the output. Unsafe/nonfinite derived magnitudes stay null for
the affected metric with reason `arithmetic_invalid`.

`missing_metrics` contains fixed metric names and reasons:
`insufficient_observations`, `ineligible_history` or `arithmetic_invalid`.
No exception message or source text becomes an interpretation or recommendation.

## Economic and research limits

These are raw **price** returns and close drawdowns. Splits, distributions,
dividends, symbol history and other corporate actions are unqualified. No total
return, economic P&L, adjustment or forecast is inferred.

The dollar-volume field is a close-valued share-volume proxy. It uses each
individual bar's close and volume; it never substitutes current price times
average share volume. It is not actual trade-by-trade dollar turnover, and
quote currency remains unknown. It does not qualify liquidity or dollar-volume
eligibility. Moving-average price units similarly inherit the unverified quote
currency. No benchmark-relative strength is supplied without benchmark input.

## Next steps

The integration owner can bind verified retained history receipts and reviewed
completion evidence, then show these descriptions with their source limitations
beside the stock dossier. Unknown inputs need source/calendar evidence before
calculation; source-quality quarantines need separate investigation. Corporate
action reconciliation, benchmark comparisons, model validation, strategy and
portfolio evaluation, continuous scheduling and any paper/live progression
remain separate work. No feature enables an investment or an order.
