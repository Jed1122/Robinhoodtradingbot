"""Property tests for projected exposure limits."""

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from trading_bot.config import CryptoSettings, PortfolioSettings, PositionRiskSettings
from trading_bot.domain import AccountId, AssetClass, InstrumentId, OrderIntentId
from trading_bot.risk import ExposureProjection, evaluate_exposure_limits

OBSERVED_AT = datetime(2026, 7, 15, 4, 30, tzinfo=UTC)
PERCENT_DENOMINATOR = Decimal("100")
POSITIVE_MONEY = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000000"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)
PERCENT = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


def percentage(amount: Decimal, percent: Decimal) -> Decimal:
    return amount * percent / PERCENT_DENOMINATOR


@st.composite
def exposure_cases(
    draw: st.DrawFn,
) -> tuple[ExposureProjection, PortfolioSettings, PositionRiskSettings, CryptoSettings]:
    equity = draw(POSITIVE_MONEY)
    authorized_risk_equity = draw(POSITIVE_MONEY)
    cash = percentage(equity, draw(PERCENT))
    gross_exposure = percentage(equity, draw(PERCENT))
    position_notional = percentage(gross_exposure, draw(PERCENT))
    correlated_group_exposure = percentage(gross_exposure, draw(PERCENT))
    crypto_exposure = percentage(gross_exposure, draw(PERCENT))
    single_crypto_exposure = percentage(crypto_exposure, draw(PERCENT))

    gross_cap_pct = draw(PERCENT)
    cash_reserve_pct = draw(
        st.decimals(
            min_value=Decimal("0"),
            max_value=PERCENT_DENOMINATOR - gross_cap_pct,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    total_crypto_cap_pct = draw(PERCENT)
    single_crypto_cap_pct = draw(
        st.decimals(
            min_value=Decimal("0"),
            max_value=total_crypto_cap_pct,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    projection = ExposureProjection(
        account_id=AccountId("property-account"),
        intent_id=OrderIntentId("property-intent"),
        instrument_id=InstrumentId("property-instrument"),
        asset_class=AssetClass.CRYPTO,
        correlation_group="property-group",
        equity=equity,
        authorized_risk_equity=authorized_risk_equity,
        cash=cash,
        gross_exposure=gross_exposure,
        open_position_count=draw(st.integers(min_value=0, max_value=12)),
        position_notional=position_notional,
        correlated_group_exposure=correlated_group_exposure,
        crypto_exposure=crypto_exposure,
        single_crypto_exposure=single_crypto_exposure,
        observed_at=OBSERVED_AT,
    )
    portfolio = PortfolioSettings(
        expected_starting_equity_usd=Decimal("1"),
        live_account_equity_ceiling_usd=Decimal("1"),
        max_total_gross_exposure_pct=gross_cap_pct,
        min_cash_reserve_pct=cash_reserve_pct,
        max_open_positions=draw(st.integers(min_value=0, max_value=12)),
        max_gross_exposure_usd=draw(POSITIVE_MONEY),
    )
    position_risk = PositionRiskSettings(
        max_risk_per_trade_pct=draw(PERCENT),
        max_position_notional_pct=draw(PERCENT),
        max_correlated_group_exposure_pct=draw(PERCENT),
        minimum_reward_to_initial_risk=Decimal("1"),
        averaging_down_allowed=False,
        pyramiding_allowed=False,
    )
    crypto = CryptoSettings(
        enabled=True,
        max_total_crypto_exposure_pct=total_crypto_cap_pct,
        max_single_crypto_exposure_pct=single_crypto_cap_pct,
        initial_symbol_allowlist=("PROPERTY",),
        max_spread_pct=Decimal("100"),
        leverage_allowed=False,
        reconciliation_quantity_tolerance=Decimal("0"),
    )
    return projection, portfolio, position_risk, crypto


@given(case=exposure_cases())
@settings(deadline=None, max_examples=500)
def test_allowed_projection_never_exceeds_any_exposure_or_cash_cap(
    case: tuple[
        ExposureProjection,
        PortfolioSettings,
        PositionRiskSettings,
        CryptoSettings,
    ],
) -> None:
    projection, portfolio, position_risk, crypto = case
    checks = {
        check.code: check
        for check in evaluate_exposure_limits(
            projection,
            portfolio=portfolio,
            position_risk=position_risk,
            crypto=crypto,
        )
    }
    risk_equity = min(projection.equity, projection.authorized_risk_equity)
    expected_caps = {
        "total_gross_exposure": min(
            percentage(risk_equity, portfolio.max_total_gross_exposure_pct),
            portfolio.max_gross_exposure_usd,
        ),
        "position_notional": percentage(risk_equity, position_risk.max_position_notional_pct),
        "correlated_group_exposure": percentage(
            risk_equity, position_risk.max_correlated_group_exposure_pct
        ),
        "total_crypto_exposure": percentage(risk_equity, crypto.max_total_crypto_exposure_pct),
        "single_crypto_exposure": percentage(risk_equity, crypto.max_single_crypto_exposure_pct),
    }
    observed = {
        "total_gross_exposure": projection.gross_exposure,
        "position_notional": projection.position_notional,
        "correlated_group_exposure": projection.correlated_group_exposure,
        "total_crypto_exposure": projection.crypto_exposure,
        "single_crypto_exposure": projection.single_crypto_exposure,
    }

    for code, configured_cap in expected_caps.items():
        if checks[code].allowed:
            assert observed[code] <= configured_cap

    if checks["open_position_count"].allowed:
        assert projection.open_position_count <= portfolio.max_open_positions
    if checks["cash_reserve"].allowed:
        reserve = percentage(projection.equity, portfolio.min_cash_reserve_pct)
        assert projection.cash >= reserve >= 0


@given(authorized=POSITIVE_MONEY, growth=POSITIVE_MONEY)
@settings(deadline=None, max_examples=300)
def test_equity_gain_cannot_raise_authorized_percentage_exposure_caps(
    authorized: Decimal,
    growth: Decimal,
) -> None:
    portfolio = PortfolioSettings(
        expected_starting_equity_usd=Decimal("1"),
        live_account_equity_ceiling_usd=Decimal("1"),
        max_total_gross_exposure_pct=Decimal("60"),
        min_cash_reserve_pct=Decimal("40"),
        max_open_positions=5,
        max_gross_exposure_usd=Decimal("1000000000"),
    )
    position_risk = PositionRiskSettings(
        max_risk_per_trade_pct=Decimal("0.5"),
        max_position_notional_pct=Decimal("15"),
        max_correlated_group_exposure_pct=Decimal("25"),
        minimum_reward_to_initial_risk=Decimal("1"),
        averaging_down_allowed=False,
        pyramiding_allowed=False,
    )
    crypto = CryptoSettings(
        enabled=True,
        max_total_crypto_exposure_pct=Decimal("20"),
        max_single_crypto_exposure_pct=Decimal("10"),
        initial_symbol_allowlist=("PROPERTY",),
        max_spread_pct=Decimal("100"),
        leverage_allowed=False,
        reconciliation_quantity_tolerance=Decimal("0"),
    )

    def projection(equity: Decimal) -> ExposureProjection:
        return ExposureProjection(
            account_id=AccountId("property-account"),
            intent_id=OrderIntentId("property-intent"),
            instrument_id=InstrumentId("property-instrument"),
            asset_class=AssetClass.CRYPTO,
            correlation_group="property-group",
            equity=equity,
            authorized_risk_equity=authorized,
            cash=authorized / Decimal("2"),
            gross_exposure=Decimal("0"),
            open_position_count=0,
            position_notional=Decimal("0"),
            correlated_group_exposure=Decimal("0"),
            crypto_exposure=Decimal("0"),
            single_crypto_exposure=Decimal("0"),
            observed_at=OBSERVED_AT,
        )

    baseline = {
        check.code: check
        for check in evaluate_exposure_limits(
            projection(authorized),
            portfolio=portfolio,
            position_risk=position_risk,
            crypto=crypto,
        )
    }
    higher = {
        check.code: check
        for check in evaluate_exposure_limits(
            projection(authorized + growth),
            portfolio=portfolio,
            position_risk=position_risk,
            crypto=crypto,
        )
    }

    for code in (
        "total_gross_exposure",
        "position_notional",
        "correlated_group_exposure",
        "total_crypto_exposure",
        "single_crypto_exposure",
    ):
        assert higher[code].configured_limit == baseline[code].configured_limit
    assert Decimal(higher["cash_reserve"].configured_limit or "NaN") > Decimal(
        baseline["cash_reserve"].configured_limit or "NaN"
    )
