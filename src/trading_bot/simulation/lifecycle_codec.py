"""Domain-separated hashes for validated synthetic lifecycle records."""

from decimal import DecimalException

from trading_bot.domain import DataHash
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.lifecycle_models import LifecycleErrorReason, deny


def lifecycle_hash(kind: str, payload: object) -> DataHash:
    try:
        if type(kind) is not str or not kind:
            deny(LifecycleErrorReason.HASH)
        return content_hash(
            {
                "namespace": "synthetic-order-lifecycle-v1",
                "kind": kind,
                "payload": payload,
            }
        )
    except (ValueError, TypeError, DecimalException):
        deny(LifecycleErrorReason.HASH)
