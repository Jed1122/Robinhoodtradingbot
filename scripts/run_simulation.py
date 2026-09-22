from pathlib import Path

from trading_bot.cli.main import _emit

_emit("simulation", Path("configs/simulation.yaml"), 20260710)
