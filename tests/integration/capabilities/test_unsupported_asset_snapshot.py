"""Declared options tools remain locked metadata, not broker connectivity."""

from datetime import UTC, datetime

import pytest
from mcp import types

from trading_bot.capabilities import capture_tools_snapshot
from trading_bot.capabilities.models import (
    CapabilityAssetClass,
    EvidenceLevel,
    OperationKind,
)

OPERATIONS = {
    "get_option_chains": OperationKind.READ,
    "get_option_instruments": OperationKind.READ,
    "get_option_historicals": OperationKind.READ,
    "get_option_quotes": OperationKind.READ,
    "get_option_positions": OperationKind.READ,
    "get_option_orders": OperationKind.READ,
    "review_option_order": OperationKind.REVIEW,
    "place_option_order": OperationKind.PLACE,
    "cancel_option_order": OperationKind.CANCEL,
}


class FakeDeclarations:
    async def list_tools(self, cursor=None, *, params=None):
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=name,
                    description="Fabricated declaration for a metadata test, no tool was invoked",
                    inputSchema={"type": "object"},
                )
                for name in OPERATIONS
            ]
        )


@pytest.mark.asyncio
async def test_options_classification_is_explicit_and_locked() -> None:
    snapshot = await capture_tools_snapshot(
        FakeDeclarations(), observed_at=datetime(2026, 9, 18, tzinfo=UTC)
    )
    for record in snapshot.manifest.records:
        assert record.asset_class is CapabilityAssetClass.OPTIONS
        assert record.operation_kind is OPERATIONS[record.operation]
        assert record.locked_reason is not None
        assert not record.satisfies(EvidenceLevel.SCHEMA_DECLARED)
        assert record.evidence[0].level is EvidenceLevel.SCHEMA_DECLARED
        assert "Codex-session" in " ".join(record.limitations)
    assert snapshot.manifest.verifications == ()
