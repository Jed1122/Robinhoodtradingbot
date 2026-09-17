"""Point-in-time universe membership with announcement-time visibility."""

from dataclasses import dataclass
from datetime import datetime

from trading_bot.clock import DomainValidationError, require_utc
from trading_bot.domain import InstrumentId
from trading_bot.domain.decimal_utils import _require_exact_bool, _require_nonempty, _require_tuple


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    instrument_id: InstrumentId
    effective_at: datetime
    announced_at: datetime
    included: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.instrument_id, "instrument_id")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        object.__setattr__(self, "announced_at", require_utc(self.announced_at))
        _require_exact_bool(self.included, "included")


class PointInTimeUniverse:
    def __init__(
        self,
        memberships: tuple[UniverseMembership, ...],
        *,
        history_complete: bool,
    ) -> None:
        _require_tuple(memberships, "memberships")
        _require_exact_bool(history_complete, "history_complete")
        seen: dict[tuple[InstrumentId, datetime, datetime], bool] = {}
        for item in memberships:
            if type(item) is not UniverseMembership:
                raise DomainValidationError("memberships must contain UniverseMembership records")
            key = (item.instrument_id, item.effective_at, item.announced_at)
            if key in seen and seen[key] != item.included:
                # Input order is not evidence of which contradictory record is authoritative.
                raise DomainValidationError("membership records conflict at the same timestamps")
            seen[key] = item.included
        self._memberships = memberships
        self.history_complete = history_complete

    def members_at(self, as_of: datetime) -> tuple[InstrumentId, ...]:
        as_of = require_utc(as_of)
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
        _require_exact_bool(self.history_complete, "history_complete")
        return () if self.history_complete else ("point_in_time_universe_unavailable",)


__all__ = ["PointInTimeUniverse", "UniverseMembership"]
