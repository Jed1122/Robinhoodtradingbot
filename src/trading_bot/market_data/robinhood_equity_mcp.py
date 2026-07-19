"""Equity market-data factory shares the broker evidence lock."""

from trading_bot.brokers.robinhood_equity_mcp import build_equity_read_adapter

build_equity_market_data = build_equity_read_adapter

__all__ = ["build_equity_market_data"]
