"""Versioned latest-vintage supplied facts, not an authenticated action adapter.

Unknown announcement/correction clocks are not synthesized. Empty supplied
tuples report zero observations, never proof of complete action coverage.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_action_archive_invalid")


def _date(value: date) -> None:
    _check(type(value) is date and date(1990, 1, 1) <= value <= date(2100, 12, 31))


@dataclass(frozen=True, slots=True)
class CapitalSplit:
    effective_date: date
    new_shares_per_old_share: Decimal
    record_hash: str

    def __post_init__(self) -> None:
        _date(self.effective_date)
        require_bounded_decimal(self.new_shares_per_old_share, "split ratio", positive=True)
        _require_sha256_hex(self.record_hash, "action record")


@dataclass(frozen=True, slots=True)
class CapitalDistribution:
    ex_date: date
    record_date: date
    pay_date: date
    amount_per_share: Decimal
    record_hash: str

    def __post_init__(self) -> None:
        for value in (self.ex_date, self.record_date, self.pay_date):
            _date(value)
        _check(self.ex_date <= self.record_date <= self.pay_date)
        require_bounded_decimal(self.amount_per_share, "distribution", nonnegative=True)
        _require_sha256_hex(self.record_hash, "action record")


@dataclass(frozen=True, slots=True)
class CapitalActionArchive:
    symbol: Literal["SPY", "QQQ", "IWM", "SHY", "IEF"]
    source_hash: str
    start: date
    end: date
    received_at: datetime
    splits: tuple[CapitalSplit, ...] | None
    distributions: tuple[CapitalDistribution, ...] | None
    source_kind: Literal["supplied-latest-vintage-actions-v1"] = field(
        default="supplied-latest-vintage-actions-v1", init=False
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    point_in_time_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.symbol) is str and self.symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF"))
        _check(
            type(self.source_kind) is str
            and self.source_kind == "supplied-latest-vintage-actions-v1"
        )
        _require_sha256_hex(self.source_hash, "action source")
        _date(self.start)
        _date(self.end)
        _check(date(2016, 1, 1) <= self.start < self.end <= date(2026, 1, 1))
        require_utc(self.received_at)
        if self.splits is not None:
            _check(type(self.splits) is tuple and len(self.splits) <= 200)
            for row in self.splits:
                _check(type(row) is CapitalSplit)
                replace(row)
                _check(self.start <= row.effective_date < self.end)
            days = tuple(row.effective_date for row in self.splits)
            _check(days == tuple(sorted(set(days))))
        if self.distributions is not None:
            _check(type(self.distributions) is tuple and len(self.distributions) <= 200)
            for distribution in self.distributions:
                _check(type(distribution) is CapitalDistribution)
                replace(distribution)
                _check(self.start <= distribution.ex_date < self.end)
            ex_dates = tuple(row.ex_date for row in self.distributions)
            _check(ex_dates == tuple(sorted(set(ex_dates))))
        _check(
            self.source_qualified is False
            and self.point_in_time_qualified is False
            and self.evidence_promotable is False
        )

    @property
    def split_count(self) -> int | None:
        self.__post_init__()
        return None if self.splits is None else len(self.splits)

    @property
    def distribution_count(self) -> int | None:
        self.__post_init__()
        return None if self.distributions is None else len(self.distributions)

    @property
    def archive_hash(self) -> str:
        self.__post_init__()
        return content_hash(("capital-action-archive-v1", self))
