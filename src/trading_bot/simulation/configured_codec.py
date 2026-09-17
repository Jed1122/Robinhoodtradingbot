"""Content addressing and event-keyed synthetic random streams."""

import random

from trading_bot.domain import DataHash
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.configured_models import SOURCE_KIND, ConfiguredErrorReason, checked


def configured_hash(kind: str, payload: object) -> DataHash:
    with checked(ConfiguredErrorReason.HASH):
        return content_hash({"namespace": SOURCE_KIND, "kind": kind, "payload": payload})


def keyed_rng(base: DataHash, event: DataHash, purpose: str) -> random.Random:
    digest = configured_hash("random_stream", {"base": base, "event": event, "purpose": purpose})
    # Synthetic modeling only; never used for security tokens or capabilities.
    return random.Random(int(digest, 16))  # nosec B311
