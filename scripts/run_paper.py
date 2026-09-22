from pathlib import Path

from trading_bot.cli.main import _emit

_emit("paper", Path("configs/paper.yaml"), 20260710)
