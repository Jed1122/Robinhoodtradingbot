from pathlib import Path

from trading_bot.cli.main import _emit

_emit("backtest", Path("configs/backtest.yaml"), 20260710)
