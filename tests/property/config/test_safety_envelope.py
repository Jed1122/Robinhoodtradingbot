"""Properties of the non-overridable directional safety envelope."""

from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_bot.config import UnsafeConfiguration, enforce_safety_envelope, load_config
from trading_bot.domain import ExecutionMode

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"


def loaded(mode: str = "micro_live"):  # type: ignore[no-untyped-def]
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / f"{mode}.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    )


@given(order_notional=st.decimals(min_value="5.01", max_value="100", places=2))
def test_micro_mode_cannot_exceed_five_dollars(order_notional: Decimal) -> None:
    pair = loaded()
    config = pair.config.model_copy(
        update={
            "activity": pair.config.activity.model_copy(
                update={"max_order_notional_usd": order_notional}
            )
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(config=config, envelope=pair.safety_envelope)


@given(gross=st.decimals(min_value="20.01", max_value="1000", places=2))
def test_micro_mode_cannot_exceed_twenty_dollars_gross(gross: Decimal) -> None:
    pair = loaded()
    config = pair.config.model_copy(
        update={
            "portfolio": pair.config.portfolio.model_copy(
                update={"max_gross_exposure_usd": gross}
            )
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(config=config, envelope=pair.safety_envelope)


@given(orders=st.integers(min_value=3, max_value=1000))
def test_micro_mode_cannot_exceed_two_daily_orders(orders: int) -> None:
    pair = loaded()
    config = pair.config.model_copy(
        update={
            "activity": pair.config.activity.model_copy(
                update={"max_new_orders_per_day": orders}
            )
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(config=config, envelope=pair.safety_envelope)


@given(delta=st.decimals(min_value="0.01", max_value="40", places=2))
def test_risk_maxima_may_only_decrease(delta: Decimal) -> None:
    pair = loaded("backtest")
    increased = pair.config.position_risk.model_copy(
        update={
            "max_risk_per_trade_pct": (
                pair.safety_envelope.position_risk.max_risk_per_trade_pct + delta
            )
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"position_risk": increased}),
            envelope=pair.safety_envelope,
        )


@given(delta=st.decimals(min_value="0.01", max_value="39.99", places=2))
def test_minimum_reserve_may_only_increase(delta: Decimal) -> None:
    pair = loaded("backtest")
    weakened = pair.config.portfolio.model_copy(
        update={
            "min_cash_reserve_pct": pair.safety_envelope.portfolio.min_cash_reserve_pct
            - delta
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"portfolio": weakened}),
            envelope=pair.safety_envelope,
        )


@given(delta=st.decimals(min_value="0.01", max_value="120", places=2))
def test_freshness_windows_may_only_shorten(delta: Decimal) -> None:
    pair = loaded("backtest")
    weakened = pair.config.freshness.model_copy(
        update={
            "max_executable_quote_age_seconds": (
                pair.safety_envelope.freshness.max_executable_quote_age_seconds + delta
            )
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"freshness": weakened}),
            envelope=pair.safety_envelope,
        )


@given(delta=st.integers(min_value=1, max_value=100000))
def test_authorization_windows_may_only_shorten(delta: int) -> None:
    pair = loaded("backtest")
    weakened = pair.config.authorization.model_copy(
        update={
            "live_lease_lifetime_seconds": (
                pair.safety_envelope.authorization.live_lease_lifetime_seconds + delta
            )
        }
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"authorization": weakened}),
            envelope=pair.safety_envelope,
        )


@given(days=st.integers(min_value=0, max_value=29))
def test_normal_promotion_days_cannot_be_lowered(days: int) -> None:
    pair = loaded("normal_live")
    weakened = pair.config.promotion.model_copy(
        update={"normal_min_combined_calendar_days": days}
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"promotion": weakened}),
            envelope=pair.safety_envelope,
        )


@given(observations=st.integers(min_value=0, max_value=99))
def test_normal_promotion_observations_cannot_be_lowered(observations: int) -> None:
    pair = loaded("normal_live")
    weakened = pair.config.promotion.model_copy(
        update={"normal_min_valid_observations": observations}
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"promotion": weakened}),
            envelope=pair.safety_envelope,
        )


@given(interval=st.integers(min_value=11, max_value=1000))
def test_micro_order_review_interval_cannot_be_lengthened(interval: int) -> None:
    pair = loaded("micro_live")
    weakened = pair.config.promotion.model_copy(
        update={"micro_order_review_interval": interval}
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"promotion": weakened}),
            envelope=pair.safety_envelope,
        )


def test_micro_order_review_interval_may_be_tightened() -> None:
    pair = loaded("micro_live")
    tightened = pair.config.promotion.model_copy(update={"micro_order_review_interval": 5})

    enforce_safety_envelope(
        config=pair.config.model_copy(update={"promotion": tightened}),
        envelope=pair.safety_envelope,
    )


@pytest.mark.parametrize("attempts", [0, -1])
def test_read_attempts_must_remain_at_least_one(attempts: int) -> None:
    pair = loaded("backtest")
    retry = pair.config.retry.model_copy(update={"read_attempts": attempts})

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"retry": retry}),
            envelope=pair.safety_envelope,
        )


@pytest.mark.parametrize("attempts", [0, 2, 3, 10])
def test_every_broker_write_attempt_count_is_exactly_one(attempts: int) -> None:
    pair = loaded("backtest")
    retry = pair.config.retry.model_copy(update={"write_attempts": attempts})

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"retry": retry}),
            envelope=pair.safety_envelope,
        )


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("position_risk", "averaging_down_allowed"),
        ("position_risk", "pyramiding_allowed"),
        ("equities", "margin_allowed"),
        ("equities", "short_sales_allowed"),
        ("equities", "options_allowed"),
        ("crypto", "leverage_allowed"),
        ("runtime", "automatic_live_activation_enabled"),
        ("runtime", "automatic_liquidation_enabled"),
    ],
)
def test_prohibited_features_cannot_be_enabled(section: str, field: str) -> None:
    pair = loaded("backtest")
    current = getattr(pair.config, section)
    changed = current.model_copy(update={field: True})

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={section: changed}),
            envelope=pair.safety_envelope,
        )


def test_prediction_live_is_rejected_even_if_model_validation_is_bypassed() -> None:
    pair = loaded("backtest")
    prediction = pair.config.prediction_markets.model_copy(update={"live_enabled": True})

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(
            config=pair.config.model_copy(update={"prediction_markets": prediction}),
            envelope=pair.safety_envelope,
        )


def test_mode_must_be_allowed_by_the_release_envelope() -> None:
    pair = loaded("backtest")
    envelope = pair.safety_envelope.model_copy(
        update={"allowed_modes": (ExecutionMode.PAPER,)}
    )

    with pytest.raises(UnsafeConfiguration):
        enforce_safety_envelope(config=pair.config, envelope=envelope)
