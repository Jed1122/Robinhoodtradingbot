# Bounded options numerical research

This is a tested offline foundation, not a trading strategy selection, executable quote,
account-risk certification or authorization. Use the separately locked
[research environment](../research/README.md); production dependencies are unchanged.

## Models and units

`research/options_pricing.py` accepts immutable `PricingInput` and `PricingSettings`.
QuantLib **1.43** is mandatory for numerical evaluation; missing or different versions
fail closed. European contracts use `AnalyticEuropeanEngine`. American contracts use
`FdBlackScholesVanillaEngine`, including an explicit discrete cash-dividend schedule.
European analytical inputs with discrete dividends are rejected. Continuous yield and
discrete cash dividends cannot be combined. No fallback changes exercise style.

The support domain is deliberately bounded: USD standard deliverables, PM settlement,
date-granular pre-expiration valuations, flat rates, constant volatility, Actual/365,
and bounded maturity/grid/input values. Same-day expiry and AM settlement are rejected.
Contract and dividend provenance must be established before constructing model inputs;
these records alone cannot verify when market data or dividend announcements were known.

Rates, volatility, yield and their numerical bumps use **fractions**; canonical trading
risk configuration continues to use whole percentages. Returned premium is per underlying
share. Multiply by the contract multiplier and complete structure quantity separately.
Greeks explicitly report delta per share, gamma per share per dollar, vega per volatility
point, theta per calendar day and rho per rate point. Theta crossing an ex-dividend date
is unsupported. Full-repricing stress recalculates the entire option value.

Each American valuation compares the requested grid with a twice-refined grid and
rejects failure to meet the explicit bounded absolute/relative tolerances. Exercise and
upper bounds are checked. A non-dividend American call with nonnegative rates must also
agree with its European analytical equivalent within tolerance. These checks are not a
general proof of accuracy for all financial models. Unresolvable numerical bumps are
rejected rather than returning spurious zero Greeks. A module lock serializes QuantLib's
global evaluation date and restores it even on failure; other code must not mutate
QuantLib globals concurrently outside this module.

## Exact terminal payoff calculations

`research/options_payoffs.py` uses Decimal arithmetic, the existing immutable options
intent/structure types, multiplier, opening side, leg ratio and whole package quantity.
It evaluates every piecewise-linear strike vertex and the right-tail slope for long
calls/puts, debit and credit verticals, and iron condors, including unequal wing widths.

Package premium already includes its execution price. Complete episode fees are deducted
once; subtracting spread/slippage again would double-count execution costs. Terminal
loss bounds assume all legs survive to common expiration and settlement. They do **not**
bound early assignment, exercise cash requirements, unexpected shares, pin risk, broken
packages or margin. Multi-leg payoff support does not establish package execution support.
Verticals and condors remain research-only; separate-leg substitution remains prohibited.

## Validation and missing work

Synthetic tests independently calculate European prices and Greek units, test American
early exercise and refinement, discrete dividends, full repricing, exact package cash
flows, and extreme inputs that previously produced incorrect finite-difference values.
They do not establish a volatility surface, historical fill quality or a trading edge.

Still required: licensed point-in-time datasets and verified announcements; empirical
model/fill validation; conservative liquidation-mark integration; hypothesis registration,
bounded search grids, leakage-safe splits and untouched tests; dependent-outcome uncertainty
and cost stress; complete strategy scorecards and common risk/runtime integration.
The current economic verdict remains `ECONOMIC_NO_GO` at every capital tier.
