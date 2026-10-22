"""Explicit observed-data views; original native archives remain unchanged."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import ConfigHash
from trading_bot.market_data.alpaca_capital_native import (
    CapitalDailyBar,
    assess_capital_daily_pages,
)
from trading_bot.market_data.etf_calendar import EtfCalendarArchive, EtfCalendarSession
from trading_bot.market_data.etf_capital_actions import CapitalActionArchive
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_features import (
    CapitalFeatureProjection,
    _capital_features_at,
    _capital_raw_bar,
    _CapitalFeatureSource,
)
from trading_bot.market_data.etf_capital_inventory import capital_daily_inventory
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _CONTEXT, _config

_ZONE = ZoneInfo("America/New_York")
_LIMITATIONS = (
    "supplied_action_rows_only_coverage_unverified",
    "conditional_on_no_unobserved_actions",
    "empty_split_tuple_is_zero_observations_not_verified_zero_activity",
    "latest_vintage_not_point_in_time",
    "announcement_and_correction_chronology_unknown",
    "accepted_access_and_retention_terms_unverified",
    "raw_daily_ohlc_are_not_executable_quotes",
    "adaptive_previously_used_or_use_uncertain_development_only",
)


def _check(ok: bool) -> None:
    if not ok:
        raise ValueError("capital_observed_input_invalid")


def _utc(value: datetime) -> None:
    _check(type(value) is datetime and value.tzinfo is UTC)


@dataclass(frozen=True, slots=True)
class CapitalObservedActionModel:
    """A hashed conditional model, not an action-completeness attestation."""

    kind: Literal["observed-actions-only-v1"] = "observed-actions-only-v1"
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)
    actions_qualified: Literal[False] = field(default=False, init=False)
    access_qualified: Literal[False] = field(default=False, init=False)
    terms_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self) is CapitalObservedActionModel)
        _check(type(self.kind) is str and self.kind == "observed-actions-only-v1")
        _check(
            type(self.limitations) is tuple
            and all(type(item) is str for item in self.limitations)
            and self.limitations == _LIMITATIONS
        )
        _check(
            self.actions_qualified is False
            and self.access_qualified is False
            and self.terms_qualified is False
        )

    @property
    def model_hash(self) -> str:
        self.__post_init__()
        return content_hash(("capital-observed-action-model-v1", self))


@dataclass(frozen=True, slots=True, repr=False)
class CapitalDailyRangeView:
    archive: CapitalDailyArchive
    calendar: EtfCalendarArchive
    start: date
    end: date
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _selected_records(self)

    @property
    def selected_records(self) -> tuple[CapitalDailyBar, ...]:
        return _selected_records(self)

    @property
    def view_hash(self) -> str:
        records = _selected_records(self)
        return content_hash(
            (
                "capital-original-preserving-range-view-v1",
                self.archive.archive_hash,
                self.calendar.archive_hash,
                self.start,
                self.end,
                "half-open-new-york-midnight-session-date",
                tuple(row.record_hash for row in records),
                self.source_qualified,
                self.evidence_promotable,
            )
        )


def _selected_records(view: CapitalDailyRangeView) -> tuple[CapitalDailyBar, ...]:
    """Recompute selection from full originals; no caller-supplied row authority."""
    _check(type(view) is CapitalDailyRangeView)
    _check(type(view.archive) is CapitalDailyArchive)
    _check(type(view.calendar) is EtfCalendarArchive)
    _check(type(view.start) is date and type(view.end) is date)
    _check(date(2016, 1, 1) <= view.start < view.end <= date(2026, 1, 1))
    _check(view.source_qualified is False and view.evidence_promotable is False)
    archive, calendar = view.archive, view.calendar
    _check(type(archive.received_at) is tuple and type(calendar.sessions) is tuple)
    for clock in archive.received_at:
        _utc(clock)
    for session in calendar.sessions:
        _check(type(session) is EtfCalendarSession)
        _utc(session.opens_at)
        _utc(session.closes_at)
    # Existing calendar admission checks the full fixed source-kind/limitations
    # contract. Missing archives remain unknown in this validation-only call.
    capital_daily_inventory((), calendar, start=view.start, end=view.end)
    archive.__post_init__()
    _check(
        archive.request.start_ns <= _ns(datetime.combine(view.start, time(), UTC))
        and archive.request.end_ns >= _ns(datetime.combine(view.end, time(), UTC))
    )
    _check(assess_capital_daily_pages(archive.pages).pagination_complete is True)
    expected = tuple(
        row.session_date for row in calendar.sessions if view.start <= row.session_date < view.end
    )
    selected: list[CapitalDailyBar] = []
    observed: list[date] = []
    for page in archive.pages:
        for record in page.records:
            # Validate the original init=False chronology marker before any copy.
            record.bar.__post_init__()
            instant = _ceil_time(record.bar.timestamp_ns).astimezone(_ZONE)
            _check(
                instant.time() == time() and _ns(instant.astimezone(UTC)) == record.bar.timestamp_ns
            )
            if view.start <= instant.date() < view.end:
                selected.append(record)
                observed.append(instant.date())
    _check(tuple(observed) == expected)
    return tuple(selected)


def _capital_range_feature_source(
    view: CapitalDailyRangeView,
    actions: CapitalActionArchive,
    *,
    as_of_session: date,
) -> _CapitalFeatureSource:
    """New validated source factory for the unchanged feature arithmetic."""
    records = _selected_records(view)
    _check(type(actions) is CapitalActionArchive and type(as_of_session) is date)
    _utc(actions.received_at)
    actions.__post_init__()
    _check(
        actions.symbol == view.archive.request.symbol
        and actions.start == view.start
        and actions.end == view.end
        and actions.start <= as_of_session < actions.end
        and actions.splits is not None
        and actions.distributions is not None
    )
    sessions = {row.session_date: row for row in view.calendar.sessions}
    _check(as_of_session in sessions)
    # __post_init__ already denied unknown collections, but retain explicit
    # narrowing for static checks and do not silently substitute empty tuples.
    if actions.splits is None or actions.distributions is None:
        raise ValueError("capital_observed_input_invalid")
    _check(all(row.effective_date in sessions for row in actions.splits))
    _check(all(row.ex_date in sessions for row in actions.distributions))
    calendar_hash = view.calendar.archive_hash
    with localcontext(_CONTEXT):
        rows = tuple(
            (day, _capital_raw_bar(record, sessions[day], calendar_hash))
            for record in records
            if (day := _ceil_time(record.bar.timestamp_ns).astimezone(_ZONE).date())
            <= as_of_session
        )
    return _CapitalFeatureSource(
        view.archive,
        view.calendar,
        actions,
        view.archive.archive_hash,
        actions.archive_hash,
        calendar_hash,
        rows,
    )


def capital_range_feature_bars(
    view: CapitalDailyRangeView, actions: CapitalActionArchive, *, as_of_session: date
) -> CapitalFeatureProjection:
    """Preserve native source hashes; the enclosing view binds range selection."""
    return _capital_features_at(
        _capital_range_feature_source(view, actions, as_of_session=as_of_session),
        as_of_session=as_of_session,
    )


@dataclass(frozen=True, slots=True, repr=False)
class CapitalObservedDataset:
    canonical_config: bytes
    config_hash: ConfigHash
    archives: tuple[CapitalDailyArchive, ...]
    actions: tuple[CapitalActionArchive, ...]
    calendar: EtfCalendarArchive
    action_model: CapitalObservedActionModel = field(default_factory=CapitalObservedActionModel)
    start: date = field(default=date(2023, 1, 1), init=False)
    end: date = field(default=date(2026, 1, 1), init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self) is CapitalObservedDataset)
        _check(type(self.canonical_config) is bytes and len(self.canonical_config) <= 65536)
        _check(type(self.action_model) is CapitalObservedActionModel)
        self.action_model.__post_init__()
        _check(
            type(self.start) is date
            and type(self.end) is date
            and self.start == date(2023, 1, 1)
            and self.end == date(2026, 1, 1)
        )
        _check(
            self.source_qualified is False
            and self.evidence_promotable is False
            and self.execution_enabled is False
        )
        with localcontext(_CONTEXT):
            loaded = restore_loaded_config(self.canonical_config, self.config_hash)
            universe = _config(loaded).capital_research.universe
        _check(type(self.archives) is tuple and len(self.archives) == len(universe))
        _check(type(self.actions) is tuple and len(self.actions) == len(universe))
        _check(all(type(row) is CapitalDailyArchive for row in self.archives))
        _check(all(type(row) is CapitalActionArchive for row in self.actions))
        _check(tuple(row.request.symbol for row in self.archives) == universe)
        _check(tuple(row.symbol for row in self.actions) == universe)
        for archive in self.archives:
            CapitalDailyRangeView(archive, self.calendar, self.start, self.end)
        _check(
            sum(len(page.records) for archive in self.archives for page in archive.pages) <= 20000
        )
        for action in self.actions:
            _utc(action.received_at)
            action.__post_init__()
            _check(action.start == self.start and action.end == self.end)
            _check(action.splits is not None and action.distributions is not None)

    @property
    def dataset_hash(self) -> str:
        self.__post_init__()
        return content_hash(
            (
                "capital-observed-development-dataset-v2",
                self.config_hash,
                self.start,
                self.end,
                tuple(
                    CapitalDailyRangeView(a, self.calendar, self.start, self.end).view_hash
                    for a in self.archives
                ),
                tuple(a.archive_hash for a in self.actions),
                self.calendar.archive_hash,
                self.action_model.model_hash,
                self.source_qualified,
                self.evidence_promotable,
                self.execution_enabled,
            )
        )


def capital_observed_features(
    dataset: CapitalObservedDataset, *, as_of_session: date
) -> tuple[CapitalFeatureProjection, ...]:
    _check(type(dataset) is CapitalObservedDataset)
    dataset.__post_init__()
    return tuple(
        capital_range_feature_bars(
            CapitalDailyRangeView(archive, dataset.calendar, dataset.start, dataset.end),
            action,
            as_of_session=as_of_session,
        )
        for archive, action in zip(dataset.archives, dataset.actions, strict=True)
    )


def build_capital_observed_dataset(
    *,
    loaded: LoadedConfig,
    archives: tuple[CapitalDailyArchive, ...],
    actions: tuple[CapitalActionArchive, ...],
    calendar: EtfCalendarArchive,
) -> CapitalObservedDataset:
    """Canonicalize the fixed universe; do not turn observations into qualification."""
    with localcontext(_CONTEXT):
        universe = _config(loaded).capital_research.universe
        _check(type(archives) is tuple and type(actions) is tuple)
        _check(len(archives) == len(actions) == len(universe))
        _check(all(type(row) is CapitalDailyArchive for row in archives))
        _check(all(type(row) is CapitalActionArchive for row in actions))
        captured: dict[str, CapitalDailyArchive] = {row.request.symbol: row for row in archives}
        facts: dict[str, CapitalActionArchive] = {row.symbol: row for row in actions}
        _check(set(captured) == set(facts) == set(universe))
        result = CapitalObservedDataset(
            loaded.canonical_json,
            loaded.config_hash,
            tuple(captured[symbol] for symbol in universe),
            tuple(facts[symbol] for symbol in universe),
            calendar,
        )
        last = max(
            row.session_date
            for row in calendar.sessions
            if result.start <= row.session_date < result.end
        )
        capital_observed_features(result, as_of_session=last)
        return result
