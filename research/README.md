# Options research environment

This directory is a separately locked environment for optional, heavy options-research
dependencies. QuantLib and DuckDB are intentionally absent from the production dependency lock:
production and ordinary paper-safe operation do not need a numerical pricing engine or a Parquet
query engine.

The environment is for credential-free numerical and storage validation only. It does not fetch
market data, run authenticated tests, place orders, modify the trading ledger, deploy services, or
authorize imported data for production use.

## Reproduce the environment

From the repository root, install exactly the locked research dependencies:

```console
uv sync --project research --locked --all-groups
```

The backend preflight is mandatory. Run it before the tests so an unavailable optional dependency
cannot turn numerical or Parquet coverage into a silent skip:

```console
uv run --project research --no-sync python - <<'PY'
import QuantLib
import duckdb

actual = (QuantLib.__version__, duckdb.__version__)
expected = ("1.43", "1.5.5")
if actual != expected:
    raise SystemExit(f"research backend version mismatch: {actual!r}")
PY
```

Then run the same credential-free selection used by CI:

```console
PYTHONPATH=src uv run --project research --no-sync pytest \
  tests/unit/research/test_options_pricing.py \
  tests/unit/research/test_options_payoffs.py \
  tests/unit/market_data/test_options_records.py \
  tests/unit/market_data/test_options_data_codec.py \
  tests/integration/market_data/test_options_parquet.py
```

Dependency installation is a separate setup phase and may access package indexes. The selected
tests themselves use synthetic/local inputs and require no network, credentials, broker session,
or cloud service.

## Date and unit conventions

- Pricing is date-granular. The valuation date and expiration are calendar dates, time is measured
  with Actual/365, and intraday expiry is unsupported. Valuation on expiration day and AM-settled
  contracts fail closed.
- Rates, continuous dividend yield, volatility, and their bumps are fractions: `0.25` means 25%,
  not 0.25%. A volatility shift of `0.10` is ten volatility points.
- Model premiums and delta are per underlying share. Gamma is per share per dollar; vega is per
  one volatility point; theta is per calendar day; rho is per one rate point. Apply the contract's
  exact premium multiplier separately.
- Terminal payoff results include the exact contract multiplier, leg ratio, order quantity,
  package premium, and the supplied complete fee bound. They are cash results for the modeled
  package, not per-share prices.
- Options data records use UTC timestamps. Parquet partitions use the record event's UTC date and
  keep synthetic and imported provenance in separate parts.

## Limitations

QuantLib checks cover a bounded flat-curve, constant-volatility research model. European pricing
uses an analytical engine; supported American pricing uses a bounded finite-difference grid.
Discrete dividends, numerical convergence, exercise style, settlement timing, and maturity are
validated only within the documented support domain. The model does not represent volatility
surfaces, stochastic rates, liquidity, assignment behavior, pin risk, margin, or execution quality.

Payoff bounds describe terminal package cash flows under common-expiry/common-settlement
assumptions. They are not account-risk, margin, or early-assignment bounds. Fabricated tests and
successful Parquet integrity checks are not empirical economic evidence, source authenticity,
licensing evidence, profitability evidence, or authorization for promotion or live trading.

The ordinary production environment may skip tests whose optional backend is absent. The
`options-research` CI job must not: its explicit version preflight makes both QuantLib 1.43 and
DuckDB 1.5.5 mandatory before any selected test runs.
