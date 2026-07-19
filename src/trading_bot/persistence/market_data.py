"""Durable market-data quarantine sink."""

import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.domain import ConfigHash
from trading_bot.market_data.validation import DataQualityEvent
from trading_bot.persistence.models import DataQualityEventRow


class SqlDataQualityStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, config_hash: ConfigHash
    ) -> None:
        self._factory = session_factory
        self._config_hash = config_hash

    async def append_all(self, events: tuple[DataQualityEvent, ...]) -> None:
        if not events:
            return
        async with self._factory.begin() as session:
            session.add_all(
                [
                    DataQualityEventRow(
                        id=event.id,
                        instrument_id=event.instrument_id,
                        occurred_at=event.occurred_at,
                        code=event.code,
                        severity=event.severity,
                        reason=event.reason,
                        sanitized_details_json=json.dumps(
                            dict(event.details), sort_keys=True, separators=(",", ":")
                        ),
                        data_hash=event.data_hash,
                        config_hash=self._config_hash,
                    )
                    for event in events
                ]
            )


__all__ = ["SqlDataQualityStore"]
