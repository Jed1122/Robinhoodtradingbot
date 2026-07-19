"""Point-in-time universe membership with announcement-time visibility."""

from dataclasses import dataclass
from datetime import datetime

from trading_bot.domain import InstrumentId


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    instrument_id: InstrumentId
    effective_at: datetime
    announced_at: datetime
    included: bool


class PointInTimeUniverse:
    def __init__(
        self,
        memberships: tuple[UniverseMembership, ...],
        *,
        history_complete: bool,
    ) -> None:
        self._memberships = memberships
        self.history_complete = history_complete

    def members_at(self, as_of: datetime) -> tuple[InstrumentId, ...]:
        state: dict[InstrumentId, bool] = {}
        visible = sorted(
            (
                item
                for item in self._memberships
                if item.announced_at <= as_of and item.effective_at <= as_of
            ),
            key=lambda item: (item.effective_at, item.announced_at, item.instrument_id),
        )
        for item in visible:
            state[item.instrument_id] = item.included
        return tuple(sorted(instrument for instrument, included in state.items() if included))

    @property
    def eligibility_reasons(self) -> tuple[str, ...]:
        return () if self.history_complete else ("point_in_time_universe_unavailable",)


__all__ = ["PointInTimeUniverse", "UniverseMembership"]
