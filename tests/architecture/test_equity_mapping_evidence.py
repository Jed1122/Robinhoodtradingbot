import json
from pathlib import Path

from trading_bot.brokers.robinhood_equity_evidence import EXPECTED_TOOL_ARGUMENTS
from trading_bot.brokers.robinhood_equity_mapping import (
    AUTHENTICATED_SHAPE_PATH,
    AUTHENTICATED_SHAPE_SHA256,
    VERIFIED_EQUITY_FIELDS,
    mapping_ready,
)


def test_equity_mapping_is_bound_to_sanitized_authenticated_shape_evidence() -> None:
    artifact = json.loads(AUTHENTICATED_SHAPE_PATH.read_text(encoding="utf-8"))

    assert mapping_ready()
    assert artifact["contains_account_data"] is False
    assert artifact["shape_sha256"] == AUTHENTICATED_SHAPE_SHA256
    assert set(artifact["tools"]) == set(EXPECTED_TOOL_ARGUMENTS)
    assert VERIFIED_EQUITY_FIELDS


def test_unobserved_position_and_order_rows_remain_explicitly_empty_only() -> None:
    artifact = json.loads(AUTHENTICATED_SHAPE_PATH.read_text(encoding="utf-8"))
    tools = artifact["tools"]

    positions = tools["get_equity_positions"]["fields"]["data"]["fields"]["positions"]
    orders = tools["get_equity_orders"]["fields"]["data"]["fields"]["orders"]
    assert positions == {"type": "array", "cardinality": "empty", "items": []}
    assert orders == {"type": "array", "cardinality": "empty", "items": []}
    assert not any(
        path.startswith("get_equity_positions.data.positions[].")
        or path.startswith("get_equity_orders.data.orders[].")
        for path in VERIFIED_EQUITY_FIELDS
    )


def test_authenticated_account_shape_tracks_declared_unsettled_funds_string() -> None:
    artifact = json.loads(AUTHENTICATED_SHAPE_PATH.read_text(encoding="utf-8"))
    fields = artifact["tools"]["get_accounts"]["fields"]["data"]["fields"][
        "accounts"
    ]["items"][0]["fields"]

    assert fields["unsettled_funds"] == {"type": "string", "nullable": False}


def test_authenticated_shape_artifact_lives_with_provider_adapter_not_fixtures() -> None:
    expected_parent = Path("src/trading_bot/brokers/schema_snapshots").resolve()
    assert AUTHENTICATED_SHAPE_PATH.resolve().parent == expected_parent
