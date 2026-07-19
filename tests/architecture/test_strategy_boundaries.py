import ast
from pathlib import Path

ROOT = Path(__file__).parents[2] / "src/trading_bot/strategies"


def test_strategies_cannot_import_brokers_or_execution() -> None:
    violations = []
    for path in ROOT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (
                    node.module.startswith("trading_bot.brokers")
                    or node.module.startswith("trading_bot.execution")
                )
            ):
                violations.append(f"{path.name}:{node.lineno}")
    assert violations == []
