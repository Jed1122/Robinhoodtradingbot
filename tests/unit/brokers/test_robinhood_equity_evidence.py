from __future__ import annotations

from dataclasses import replace

import pytest

from trading_bot.brokers.robinhood_equity_evidence import (
    EXPECTED_EQUITY_WRITE_ARGUMENTS,
    EXPECTED_EQUITY_WRITE_SCHEMA_SHA256,
    EXPECTED_TOOL_ARGUMENTS,
    EquityEvidenceError,
    validate_equity_write_tool_declarations,
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


def _write_declarations() -> tuple[DeclaredMcpTool, ...]:
    observed = []
    for name, (properties, required) in sorted(EXPECTED_EQUITY_WRITE_ARGUMENTS.items()):
        input_schema: JsonValue = {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: {"type": "string"} for key in sorted(properties)},
            "required": sorted(required),
        }
        observed.append(
            DeclaredMcpTool(
                name,
                None,
                input_schema,
                {},
                EXPECTED_EQUITY_WRITE_SCHEMA_SHA256[name],
            )
        )
    return tuple(observed)


def test_equity_write_declaration_gate_binds_exact_current_contracts() -> None:
    evidence_hash = validate_equity_write_tool_declarations(_write_declarations())

    assert len(str(evidence_hash)) == 64


@pytest.mark.parametrize(
    "field",
    ("properties", "required", "additionalProperties", "type"),
)
def test_equity_write_declaration_gate_rejects_input_shape_drift(field: str) -> None:
    declarations = list(_write_declarations())
    review = declarations[-1]
    assert type(review.input_schema) is dict
    changed = dict(review.input_schema)
    if field == "properties":
        changed[field] = {"account_number": {"type": "string"}}
    elif field == "required":
        changed[field] = ["account_number"]
    elif field == "additionalProperties":
        changed[field] = True
    else:
        changed[field] = "array"
    declarations[-1] = replace(review, input_schema=changed)

    with pytest.raises(EquityEvidenceError, match=r"incompatible|changed"):
        validate_equity_write_tool_declarations(tuple(declarations))


def test_equity_write_declaration_gate_rejects_full_schema_hash_drift() -> None:
    declarations = list(_write_declarations())
    declarations[0] = replace(declarations[0], schema_sha256="f" * 64)

    with pytest.raises(EquityEvidenceError, match="changed"):
        validate_equity_write_tool_declarations(tuple(declarations))


def test_equity_write_declaration_gate_rejects_missing_or_duplicate_tools() -> None:
    declarations = _write_declarations()

    with pytest.raises(EquityEvidenceError, match="missing"):
        validate_equity_write_tool_declarations(declarations[1:])
    with pytest.raises(EquityEvidenceError, match="duplicate"):
        validate_equity_write_tool_declarations((*declarations, declarations[0]))
