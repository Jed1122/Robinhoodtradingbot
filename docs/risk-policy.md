# Risk policy

All entries require the canonical 24-check final pretrade evaluation. Limits only become more
restrictive at runtime. Missing data, stale evidence, reconciliation drift, an invalid lease,
or the kill switch denies placement. This software makes no profit claim.

## Account-equity ceiling amendment — 2026-09-30

The operator explicitly raised `portfolio.live_account_equity_ceiling_usd` from
$150 to $1,000. The canonical base configuration and release safety envelope now
share that ceiling; tighter resolved overrides remain permitted, while overrides
above $1,000 are rejected. The pretrade account gate and locked live composition
both consume the canonical value. Exactly $1,000 satisfies this one balance
condition; $1,000.01 does not. This is not a statement of actual account equity.

The $100 expected starting-capital assumption, separately signed risk-equity
reference, 0.5% per-trade risk, all order/exposure/cash caps, daily/weekly/drawdown
limits and non-replenishing $50 options trial-loss ceiling are unchanged. A higher
account balance does not automatically authorize larger positions or $1,000 of
trading capital. Micro-live and normal-live notional caps remain distinct.

The change is local development configuration, not deployment or live activation.
Live mode remains disabled and startup remains paused. Configuration identity
includes the release envelope, so old preflight/authorization evidence cannot be
reused as if it approved the new configuration. The locked live constructor now
requires the canonical loaded configuration and matching preflight identity.
Historical $150 documents remain historical records; this dated amendment and
the canonical files govern the current configured ceiling.
