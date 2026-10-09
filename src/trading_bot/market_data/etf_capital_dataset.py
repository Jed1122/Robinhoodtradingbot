"""Canonical-policy-bound supplied development datasets, not promotion evidence."""

from dataclasses import dataclass, field
from datetime import date
from decimal import localcontext
from typing import Literal

from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import ConfigHash
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_capital_actions import CapitalActionArchive
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_features import (
    CapitalFeatureProjection,
    capital_split_feature_bars,
)
from trading_bot.market_data.etf_capital_inventory import capital_daily_inventory
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _CONTEXT, _config


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_research_dataset_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class CapitalResearchDataset:
    canonical_config: bytes
    config_hash: ConfigHash
    start: date
    end: date
    archives: tuple[CapitalDailyArchive, ...]
    actions: tuple[CapitalActionArchive, ...]
    calendar: EtfCalendarArchive
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.canonical_config) is bytes and len(self.canonical_config) <= 65536)
        with localcontext(_CONTEXT):
            loaded = restore_loaded_config(self.canonical_config, self.config_hash)
            policy = _config(loaded).capital_research
        _check(type(self.start) is date and type(self.end) is date)
        # This contract is for adaptive development only, not the prospective final.
        _check(date(2016, 1, 1) <= self.start < self.end <= date(2024, 1, 1))
        _check(type(self.archives) is tuple and len(self.archives) == len(policy.universe))
        _check(type(self.actions) is tuple and len(self.actions) == len(policy.universe))
        _check(all(type(row) is CapitalDailyArchive for row in self.archives))
        _check(all(type(row) is CapitalActionArchive for row in self.actions))
        _check(tuple(row.request.symbol for row in self.archives) == policy.universe)
        _check(tuple(row.symbol for row in self.actions) == policy.universe)
        for archive in self.archives:
            archive.__post_init__()
        _check(sum(len(page.records) for row in self.archives for page in row.pages) <= 20000)
        inventory = capital_daily_inventory(
            self.archives, self.calendar, start=self.start, end=self.end
        )
        _check(
            all(
                row.missing_session_count == 0 and row.pagination_complete is True
                for row in inventory.symbols
            )
        )
        for action in self.actions:
            action.__post_init__()
            _check(action.start == self.start and action.end == self.end)
            _check(action.splits is not None and action.distributions is not None)
        _check(
            self.source_qualified is False
            and self.evidence_promotable is False
            and self.execution_enabled is False
        )

    @property
    def dataset_hash(self) -> str:
        self.__post_init__()
        return content_hash(
            (
                "capital-supplied-development-dataset-v1",
                self.config_hash,
                self.start,
                self.end,
                tuple(row.archive_hash for row in self.archives),
                tuple(row.archive_hash for row in self.actions),
                self.calendar.archive_hash,
                self.source_qualified,
                self.evidence_promotable,
                self.execution_enabled,
            )
        )


def build_capital_dataset(
    *,
    loaded: LoadedConfig,
    archives: tuple[CapitalDailyArchive, ...],
    actions: tuple[CapitalActionArchive, ...],
    calendar: EtfCalendarArchive,
    start: date,
    end: date,
) -> CapitalResearchDataset:
    """Canonicalize symbol order; all supplied coverage remains unqualified."""
    config = _config(loaded)
    _check(type(archives) is tuple and type(actions) is tuple)
    _check(len(archives) == len(actions) == len(config.capital_research.universe))
    _check(all(type(row) is CapitalDailyArchive for row in archives))
    _check(all(type(row) is CapitalActionArchive for row in actions))
    captured: dict[str, CapitalDailyArchive] = {row.request.symbol: row for row in archives}
    facts: dict[str, CapitalActionArchive] = {row.symbol: row for row in actions}
    universe = config.capital_research.universe
    _check(set(captured) == set(facts) == set(universe))
    result = CapitalResearchDataset(
        loaded.canonical_json,
        loaded.config_hash,
        start,
        end,
        tuple(captured[symbol] for symbol in universe),
        tuple(facts[symbol] for symbol in universe),
        calendar,
    )
    # Validate raw OHLC/action/calendar semantics once; never retain a terminal
    # normalized slice for earlier decisions. Consumers request their own as-of.
    last = max(row.session_date for row in calendar.sessions if start <= row.session_date < end)
    capital_dataset_features(result, as_of_session=last)
    return result


def capital_dataset_features(
    dataset: CapitalResearchDataset,
    *,
    as_of_session: date,
) -> tuple[CapitalFeatureProjection, ...]:
    _check(type(dataset) is CapitalResearchDataset)
    dataset.__post_init__()
    _check(type(as_of_session) is date and dataset.start <= as_of_session < dataset.end)
    return tuple(
        capital_split_feature_bars(archive, dataset.calendar, action, as_of_session=as_of_session)
        for archive, action in zip(dataset.archives, dataset.actions, strict=True)
    )
