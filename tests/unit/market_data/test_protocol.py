import inspect

from trading_bot.market_data import MarketDataProvider


def test_market_data_provider_declares_complete_read_surface() -> None:
    assert {
        name
        for name, value in vars(MarketDataProvider).items()
        if name.startswith("get_") and inspect.isfunction(value)
    } == {
        "get_quote",
        "get_executable_quote",
        "get_bars",
        "get_market_clock",
        "get_corporate_actions",
        "get_earnings_calendar",
        "get_instrument_metadata",
        "get_spread_estimate",
    }
