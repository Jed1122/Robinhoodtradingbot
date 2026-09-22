from datetime import timedelta

from trading_bot.runtime.scheduler import default_schedule


def test_crypto_reconciliation_defaults_to_sixty_seconds() -> None:
    assert default_schedule().job("crypto_reconcile").interval == timedelta(seconds=60)
