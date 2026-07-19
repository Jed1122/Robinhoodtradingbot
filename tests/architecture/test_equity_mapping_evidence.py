import ast
from pathlib import Path

ROOT = Path(__file__).parents[2] / "src/trading_bot/brokers"


def test_equity_mapper_has_no_provider_field_mapping_without_evidence() -> None:
    mapping = ROOT / "robinhood_equity_mapping.py"
    source = mapping.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id not in {"tuple"}
        for node in ast.walk(tree)
    )
    assert "VERIFIED_EQUITY_FIELDS: tuple[str, ...] = ()" in source
