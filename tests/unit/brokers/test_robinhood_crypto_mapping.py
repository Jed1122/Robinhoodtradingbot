from collections import Counter
from pathlib import Path

import pytest

from trading_bot.brokers.robinhood_crypto_mapping import (
    MaterialExecutionDrift,
    execution_key,
    map_executions,
)
from trading_bot.brokers.robinhood_crypto_schemas import CryptoOrdersResponse
from trading_bot.domain import DataHash

FIXTURE = Path(__file__).parents[2] / "fixtures/robinhood_crypto/orders.json"


def order():
    return CryptoOrdersResponse.model_validate_json(FIXTURE.read_text()).results[0]


def test_identical_execution_occurrences_receive_distinct_ordinals() -> None:
    value = order()
    assert execution_key(value, 0)[-1] == 0
    assert execution_key(value, 1)[-1] == 1
    fills = map_executions(value, data_hash=DataHash("a" * 64))
    assert len(fills) == 2 and fills[0].id != fills[1].id


def test_replay_and_reordering_create_no_duplicate_effect() -> None:
    value = order()
    base = execution_key(value, 0)[:-1]
    assert (
        map_executions(
            value, data_hash=DataHash("a" * 64), persisted_multiplicity=Counter({base: 2})
        )
        == ()
    )
    reordered = value.model_copy(update={"executions": tuple(reversed(value.executions))})
    assert (
        map_executions(
            reordered, data_hash=DataHash("a" * 64), persisted_multiplicity=Counter({base: 2})
        )
        == ()
    )


def test_cumulative_quantity_disagreement_is_material_drift() -> None:
    with pytest.raises(MaterialExecutionDrift):
        map_executions(
            order().model_copy(
                update={"filled_asset_quantity": order().filled_asset_quantity * 2}
            ),
            data_hash=DataHash("a" * 64),
        )
