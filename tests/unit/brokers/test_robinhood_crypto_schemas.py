import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_bot.brokers.robinhood_crypto_schemas import (
    CryptoAccountsResponse,
    CryptoOrdersResponse,
    TradingPairsResponse,
)

FIXTURES = Path(__file__).parents[2] / "fixtures/robinhood_crypto"


def test_trading_pair_decimal_fields_remain_exact() -> None:
    dto = TradingPairsResponse.model_validate_json((FIXTURES / "trading_pairs.json").read_text())
    assert dto.results[0].asset_increment == Decimal("0.00000001")


def test_unknown_provider_field_fails_schema() -> None:
    payload = json.loads((FIXTURES / "accounts.json").read_text())
    payload["results"][0]["unreviewed_field"] = "value"
    with pytest.raises(ValidationError):
        CryptoAccountsResponse.model_validate(payload)


def test_embedded_execution_schema_is_strict() -> None:
    response = CryptoOrdersResponse.model_validate_json((FIXTURES / "orders.json").read_text())
    assert len(response.results[0].executions) == 2
