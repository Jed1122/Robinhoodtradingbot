from decimal import Decimal

from trading_bot.research.monte_carlo import estimate_pbo, resample_trade_sequences


def test_seeded_trade_resampling_is_reproducible() -> None:
    trades = (Decimal("1"), Decimal("-1"), Decimal("2"))
    assert resample_trade_sequences(trades, samples=10, seed=7) == resample_trade_sequences(
        trades, samples=10, seed=7
    )


def test_pbo_reports_insufficient_combinations() -> None:
    assert estimate_pbo(((Decimal("1"),),), ((Decimal("1"),),)).status == "insufficient_sample"
