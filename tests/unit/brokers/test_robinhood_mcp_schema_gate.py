import json
from pathlib import Path

from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, compare_mcp_schema

FIXTURE = Path(__file__).parents[2] / "fixtures/mcp/generic_tools_list.json"


def expected_tools() -> tuple[DeclaredMcpTool, ...]:
    item = json.loads(FIXTURE.read_text())["tools"][0]
    return (
        DeclaredMcpTool.create(
            item["name"], item["description"], item["inputSchema"], item["outputSchema"]
        ),
    )


def test_identical_schema_is_live_ready() -> None:
    report = compare_mcp_schema(expected_tools(), expected_tools())
    assert report.live_ready and not report.incompatible


def test_removed_required_tool_disables_capability() -> None:
    report = compare_mcp_schema((), expected_tools())
    assert not report.live_ready and report.incompatible


def test_added_required_argument_disables_capability() -> None:
    original = expected_tools()[0]
    changed_input = dict(original.input_schema)  # type: ignore[arg-type]
    changed_input["required"] = ["symbols", "account"]
    changed = DeclaredMcpTool.create(
        original.name, original.description, changed_input, original.output_schema
    )
    assert compare_mcp_schema((changed,), (original,)).incompatible
