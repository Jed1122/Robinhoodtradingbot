from __future__ import annotations

import pytest

from trading_bot.brokers.robinhood_equity_evidence import (
    EXPECTED_TOOL_ARGUMENTS,
    EquityEvidenceError,
    validate_read_tool_declarations,
)
from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, JsonValue


def _declarations(get_accounts_input: JsonValue) -> tuple[DeclaredMcpTool, ...]:
    observed = []
    for name, (properties, required) in sorted(EXPECTED_TOOL_ARGUMENTS.items()):
        input_schema: JsonValue = (
            get_accounts_input
            if name == "get_accounts"
            else {
                "type": "object",
                "properties": {key: {} for key in sorted(properties)},
                "required": sorted(required),
            }
        )
        observed.append(DeclaredMcpTool.create(name, None, input_schema, {}))
    return tuple(observed)


def test_declaration_gate_accepts_closed_zero_argument_object() -> None:
    evidence_hash = validate_read_tool_declarations(
        _declarations({"type": "object", "additionalProperties": False})
    )

    assert len(str(evidence_hash)) == 64


def test_declaration_gate_rejects_open_zero_argument_object() -> None:
    with pytest.raises(EquityEvidenceError, match="incompatible"):
        validate_read_tool_declarations(_declarations({"type": "object"}))
