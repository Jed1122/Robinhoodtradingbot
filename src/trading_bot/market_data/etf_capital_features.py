"""Declared daily split-basis research projection, never execution evidence."""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.alpaca_capital_native import assess_capital_daily_pages
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_capital_actions import CapitalActionArchive, CapitalDistribution
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_inventory import capital_daily_inventory
from trading_bot.market_data.etf_source import _ceil_time
from trading_bot.market_data.recording import content_hash

_CONTEXT = Context(prec=64, rounding=ROUND_HALF_EVEN)
_ZONE = ZoneInfo("America/New_York")
_LIMITATIONS = (
    "supplied_latest_vintage_not_authenticated",
    "announcement_and_correction_chronology_unknown",
    "calendar_session_close_is_assumed_bar_availability",
    "raw_daily_ohlc_are_not_executable_quotes",
    "split_only_features_dividend_cash_accounted_separately",
    "declared_action_rows_do_not_establish_complete_coverage",
    "split_features_64_significant_digits_half_even_v2",
)


@dataclass(frozen=True, slots=True)
class CapitalFeatureProjection:
    archive_hash: str
    action_hash: str
    calendar_hash: str
    as_of_session: date
    raw_bars: tuple[Bar, ...]
    feature_bars: tuple[Bar, ...]
    distributions: tuple[CapitalDistribution, ...]
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for digest in (self.archive_hash, self.action_hash, self.calendar_hash):
            _require_sha256_hex(digest, "feature source")
        if (
            type(self.as_of_session) is not date
            or type(self.raw_bars) is not tuple
            or type(self.feature_bars) is not tuple
            or not 0 < len(self.raw_bars) == len(self.feature_bars) <= 4000
            or type(self.distributions) is not tuple
            or len(self.distributions) > 200
            or type(self.limitations) is not tuple
            or any(type(value) is not str for value in self.limitations)
            or self.limitations != _LIMITATIONS
            or self.source_qualified is not False
            or self.evidence_promotable is not False
            or self.execution_enabled is not False
        ):
            raise ValueError("capital_feature_projection_invalid")
        previous = None
        symbol = None
        for raw, feature in zip(self.raw_bars, self.feature_bars, strict=True):
            if type(raw) is not Bar or type(feature) is not Bar:
                raise ValueError("capital_feature_projection_invalid")
            raw.__post_init__()
            feature.__post_init__()
            if (
                raw.instrument_id != feature.instrument_id
                or raw.starts_at != feature.starts_at
                or raw.ends_at != feature.ends_at
                or raw.source != "alpaca-supplied-daily-session-assumption-v1"
                or feature.source != "capital-split-feature-assumption-v2"
                or raw.ends_at.astimezone(_ZONE).date() > self.as_of_session
                or (previous is not None and raw.ends_at <= previous)
                or (symbol is not None and raw.instrument_id != symbol)
            ):
                raise ValueError("capital_feature_projection_invalid")
            previous = raw.ends_at
            symbol = raw.instrument_id
        for distribution in self.distributions:
            if type(distribution) is not CapitalDistribution:
                raise ValueError("capital_feature_projection_invalid")
            distribution.__post_init__()
            if distribution.ex_date > self.as_of_session:
                raise ValueError("capital_feature_projection_invalid")

    @property
    def projection_hash(self) -> str:
        self.__post_init__()
        return content_hash(("capital-split-feature-projection-v2", self))


def capital_split_feature_bars(
    archive: CapitalDailyArchive,
    calendar: EtfCalendarArchive,
    actions: CapitalActionArchive,
    *,
    as_of_session: date,
) -> CapitalFeatureProjection:
    """Use only completed declared sessions/effective splits through as-of.

    This deliberately does not construct legacy CorporateAction objects with
    invented announcement timestamps. It is an assumption-based research basis.
    Distribution entitlement/payment accounting belongs to the account reducer.
    """
    if (
        type(archive) is not CapitalDailyArchive
        or type(calendar) is not EtfCalendarArchive
        or type(actions) is not CapitalActionArchive
        or type(as_of_session) is not date
    ):
        raise ValueError("capital_feature_projection_invalid")
    archive.__post_init__()
    replace(calendar)
    actions.__post_init__()
    if (
        actions.symbol != archive.request.symbol
        or actions.splits is None
        or actions.distributions is None
        or not actions.start <= as_of_session < actions.end
        or not assess_capital_daily_pages(archive.pages).pagination_complete
    ):
        raise ValueError("capital_feature_projection_invalid")
    capital_daily_inventory((archive,), calendar, start=actions.start, end=actions.end)
    all_sessions = {row.session_date for row in calendar.sessions}
    if any(row.effective_date not in all_sessions for row in actions.splits) or any(
        row.ex_date not in all_sessions for row in actions.distributions
    ):
        raise ValueError("capital_feature_projection_invalid")
    archive_hash = archive.archive_hash
    action_hash = actions.archive_hash
    calendar_hash = calendar.archive_hash
    sessions = {
        row.session_date: row
        for row in calendar.sessions
        if actions.start <= row.session_date <= as_of_session
    }
    if as_of_session not in sessions:
        raise ValueError("capital_feature_projection_invalid")
    raw: list[Bar] = []
    adjusted: list[Bar] = []
    observed: set[date] = set()
    with localcontext(_CONTEXT):
        for page in archive.pages:
            for record in page.records:
                day = _ceil_time(record.bar.timestamp_ns).astimezone(_ZONE).date()
                if day > as_of_session:
                    continue
                session = sessions[day]
                native = record.bar
                bar = Bar(
                    InstrumentId(record.symbol),
                    BarInterval.ONE_DAY,
                    session.opens_at,
                    session.closes_at,
                    native.open,
                    native.high,
                    native.low,
                    native.close,
                    Decimal(native.volume),
                    "alpaca-supplied-daily-session-assumption-v1",
                    DataHash(record.record_hash),
                )
                bar = replace(
                    bar,
                    data_hash=DataHash(
                        content_hash(
                            (
                                "capital-raw-session-bar-v1",
                                record.record_hash,
                                calendar_hash,
                                bar,
                            )
                        )
                    ),
                )
                factor = Decimal("1")
                for split in actions.splits:
                    if day < split.effective_date <= as_of_session:
                        factor *= split.new_shares_per_old_share
                        require_bounded_decimal(factor, "cumulative split factor", positive=True)
                feature = replace(
                    bar,
                    open=bar.open / factor,
                    high=bar.high / factor,
                    low=bar.low / factor,
                    close=bar.close / factor,
                    volume=bar.volume * factor,
                    source="capital-split-feature-assumption-v2",
                )
                for value in (
                    feature.open,
                    feature.high,
                    feature.low,
                    feature.close,
                    feature.volume,
                ):
                    require_bounded_decimal(value, "feature value", nonnegative=True)
                feature = replace(
                    feature,
                    data_hash=DataHash(
                        content_hash(
                            (
                                "capital-split-feature-bar-v2",
                                archive_hash,
                                action_hash,
                                calendar_hash,
                                as_of_session,
                                feature,
                            )
                        )
                    ),
                )
                raw.append(bar)
                adjusted.append(feature)
                observed.add(day)
    if observed != set(sessions):
        raise ValueError("capital_feature_projection_invalid")
    return CapitalFeatureProjection(
        archive_hash,
        action_hash,
        calendar_hash,
        as_of_session,
        tuple(raw),
        tuple(adjusted),
        tuple(row for row in actions.distributions if row.ex_date <= as_of_session),
    )
