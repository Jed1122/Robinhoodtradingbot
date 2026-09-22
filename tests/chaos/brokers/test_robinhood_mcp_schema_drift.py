from tests.unit.brokers.test_robinhood_mcp_schema_gate import expected_tools
from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, compare_mcp_schema


def test_output_field_removal_fails_closed() -> None:
    expected = expected_tools()[0]
    changed = DeclaredMcpTool.create(
        expected.name,
        expected.description,
        expected.input_schema,
        {"type": "object", "properties": {}},
    )
    report = compare_mcp_schema((changed,), (expected,))
    assert not report.live_ready and report.incompatible


def test_enum_change_fails_closed() -> None:
    expected = expected_tools()[0]
    changed = DeclaredMcpTool.create(
        expected.name,
        expected.description,
        {"type": "object", "properties": {"side": {"enum": ["buy"]}}},
        expected.output_schema,
    )
    assert compare_mcp_schema((changed,), (expected,)).incompatible
