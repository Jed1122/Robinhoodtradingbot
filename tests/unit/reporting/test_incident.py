from trading_bot.reporting.incident import mask_account


def test_account_is_masked() -> None:
    assert mask_account("RHC1234567") == "***4567"
