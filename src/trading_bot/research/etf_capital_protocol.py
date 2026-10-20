"""Closed scheduling variants; no source, execution, or promotion authority."""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from trading_bot.market_data.recording import content_hash

if TYPE_CHECKING:
    from trading_bot.research.etf_capital_signals import CapitalWalkForwardFold

ProtocolName = Literal["legacy-750x126-v1", "observed-252x84-v2"]


@dataclass(frozen=True, slots=True)
class CapitalStudyProtocol:
    """One named study, never caller-selected optimizer dimensions.

    This descriptor does not alter the legacy public entry points or their
    canonical preimages. New entry points must select the observed variant
    internally after admitting its separately versioned original inputs.
    """

    name: ProtocolName

    def __post_init__(self) -> None:
        self._parameters()

    def _parameters(self) -> tuple[int, int, date, date]:
        if type(self) is not CapitalStudyProtocol or type(self.name) is not str:
            raise ValueError("capital_study_protocol_invalid")
        if self.name == "legacy-750x126-v1":
            return 750, 126, date(2016, 1, 1), date(2024, 1, 1)
        if self.name == "observed-252x84-v2":
            return 252, 84, date(2023, 1, 1), date(2026, 1, 1)
        raise ValueError("capital_study_protocol_invalid")

    @property
    def training_count(self) -> int:
        return self._parameters()[0]

    @property
    def purge_count(self) -> int:
        self._parameters()
        return 20

    @property
    def embargo_count(self) -> int:
        self._parameters()
        return 20

    @property
    def fold_count(self) -> int:
        self._parameters()
        return 5

    @property
    def test_count_per_fold(self) -> int:
        return self._parameters()[1]

    @property
    def test_count(self) -> int:
        return self.fold_count * self.test_count_per_fold

    @property
    def test_start(self) -> int:
        return self.training_count + self.embargo_count

    @property
    def baseline_index(self) -> int:
        return self.test_start - 1

    @property
    def test_end(self) -> int:
        return self.test_start + self.test_count

    @property
    def tail_count(self) -> int:
        self._parameters()
        return 23

    @property
    def used_count(self) -> int:
        return self.test_end + self.tail_count

    @property
    def protocol_hash(self) -> str:
        return content_hash(
            (
                "capital-closed-study-schedule-v1",
                self.name,
                self._parameters(),
                self.purge_count,
                self.embargo_count,
                self.fold_count,
                self.tail_count,
            )
        )

    def folds(self, sessions: tuple[date, ...]) -> tuple["CapitalWalkForwardFold", ...]:
        from trading_bot.research.etf_capital_signals import CapitalWalkForwardFold

        training, test, earliest, latest = self._parameters()
        if (
            type(sessions) is not tuple
            or not self.used_count <= len(sessions) <= 4000
            or any(type(day) is not date for day in sessions)
            or tuple(sorted(set(sessions))) != sessions
            or sessions[0] < earliest
            or sessions[-1] >= latest
        ):
            raise ValueError("capital_folds_invalid")
        return tuple(
            CapitalWalkForwardFold(
                sessions[start : start + training],
                sessions[start : start + training - self.purge_count],
                sessions[start + training : start + self.test_start],
                sessions[start + self.test_start : start + self.test_start + test],
                sessions[
                    start + self.test_start + test : start
                    + self.test_start
                    + test
                    + self.tail_count
                ],
            )
            for start in (test * index for index in range(self.fold_count))
        )
