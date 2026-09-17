"""Finite synthetic replay inputs; not a broker runtime or promotion authority."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from itertools import pairwise
from typing import Literal, NoReturn

from trading_bot.clock import require_utc
from trading_bot.config import AppConfig, LoadedConfig, SafetyEnvelope, enforce_safety_envelope
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.models import StrictModel
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BarInterval,
    ExecutionMode,
    Instrument,
    InstrumentId,
    TimestampSource,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.bundle_models import SnapshotSettings
from trading_bot.market_data.bundle_verify import VerifiedBundle
from trading_bot.simulation.configured_models import SyntheticBarWindow, SyntheticMarketEvent
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_accounting import _context

SOURCE_KIND: Literal["synthetic-equity-replay-v1"] = "synthetic-equity-replay-v1"
_LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z")
_NAMESPACE = re.compile(r"synthetic:[a-z0-9][a-z0-9_-]{0,63}\Z")


class ReplayValidationError(ValueError):
    """Stable local reason only; never interpolate rejected input."""


def deny(reason: str = "replay_input_invalid") -> NoReturn:
    raise ReplayValidationError(reason) from None


@contextmanager
def checked() -> Iterator[None]:
    try:
        with localcontext(_context(exact=True)):
            yield
    except ReplayValidationError:
        raise
    except (ValueError, TypeError, AttributeError, OverflowError, DecimalException):
        deny()


def label(value: object) -> None:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        deny()


def utc(value: datetime) -> None:
    if type(value) is not datetime:
        deny()
    require_utc(value)


@dataclass(frozen=True, slots=True)
class ReplayCandidate:
    strategy_id: str
    short_window: int
    long_window: int
    top_n: int | None
    exposure_multiplier: Decimal

    def __post_init__(self) -> None:
        with checked():
            if (
                type(self.strategy_id) is not str
                or self.strategy_id not in {"equity_momentum", "equity_relative_strength"}
                or type(self.short_window) is not int
                or type(self.long_window) is not int
                or not 2 <= self.short_window < self.long_window
            ):
                deny("replay_candidate_invalid")
            if self.strategy_id == "equity_momentum":
                if self.top_n is not None:
                    deny("replay_candidate_invalid")
            elif type(self.top_n) is not int or self.top_n <= 0:
                deny("replay_candidate_invalid")
            require_bounded_decimal(self.exposure_multiplier, "multiplier", nonnegative=True)
            if self.exposure_multiplier > 1:
                deny("replay_candidate_invalid")


@dataclass(frozen=True, slots=True)
class ReplaySession:
    """Declared fixture slots, known independently of delivered quote contents."""

    instrument_id: InstrumentId
    window: SyntheticBarWindow
    opportunity_times: tuple[datetime, ...]

    def __post_init__(self) -> None:
        with checked():
            label(self.instrument_id)
            if (
                type(self.window) is not SyntheticBarWindow
                or type(self.opportunity_times) is not tuple
            ):
                deny()
            self.window.__post_init__()
            for at in self.opportunity_times:
                utc(at)
                if not self.window.starts_at <= at < self.window.ends_at:
                    deny("replay_ordering_invalid")
            if any(left >= right for left, right in pairwise(self.opportunity_times)):
                deny("replay_ordering_invalid")


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    event_id: str
    cursor: EventCursor

    def __post_init__(self) -> None:
        with checked():
            label(self.event_id)
            if self.event_id.startswith("sim:") or type(self.cursor) is not EventCursor:
                deny()
            self.cursor.__post_init__()
            utc(self.cursor.occurred_at)


def _configuration(loaded: LoadedConfig) -> LoadedConfig:
    if (
        type(loaded) is not LoadedConfig
        or type(loaded.config) is not AppConfig
        or type(loaded.safety_envelope) is not SafetyEnvelope
        or type(loaded.canonical_json) is not bytes
    ):
        deny("replay_config_invalid")
    _config_tree(loaded.config)
    _config_tree(loaded.safety_envelope)
    _require_sha256_hex(loaded.config_hash, "config_hash")
    config = AppConfig.model_validate(loaded.config.model_dump())
    envelope = SafetyEnvelope.model_validate(loaded.safety_envelope.model_dump())
    enforce_safety_envelope(config, envelope)
    canonical, digest = hash_loaded_config(config, envelope)
    if canonical != loaded.canonical_json or digest != loaded.config_hash:
        deny("replay_config_identity_invalid")
    if (
        config.mode is not ExecutionMode.SIMULATION
        or config.live_trading_enabled
        or config.simulation.assumptions_validated
        or config.simulation.evidence_promotable
    ):
        deny("replay_mode_unsupported")
    return LoadedConfig(config, envelope, canonical, digest)


def _config_tree(value: StrictModel) -> None:
    """Do not let model_copy-injected objects reach Pydantic's warning formatter."""
    fields = type(value).model_fields
    if set(value.__dict__) != set(fields):
        deny("replay_config_invalid")
    for name, field_info in fields.items():
        child, expected = getattr(value, name), field_info.annotation
        if isinstance(expected, type) and issubclass(expected, StrictModel):
            if type(child) is not expected:
                deny("replay_config_invalid")
            _config_tree(child)
        else:
            _config_scalar(child)


def _config_scalar(value: object) -> None:
    if type(value) is tuple:
        for item in value:
            _config_scalar(item)
    elif type(value) is Decimal:
        require_bounded_decimal(value, "config_value")
    elif value is not None and type(value) not in (str, int, bool, BarInterval, ExecutionMode):
        deny("replay_config_invalid")


@dataclass(frozen=True, slots=True)
class EquityStrategyReplayRequest:
    namespace: str
    loaded: LoadedConfig
    seed: int
    candidate: ReplayCandidate
    bundle: VerifiedBundle
    snapshot_settings: SnapshotSettings
    instruments: tuple[Instrument, ...]
    sessions: tuple[ReplaySession, ...]
    decisions: tuple[ReplayDecision, ...]
    markets: tuple[SyntheticMarketEvent, ...]
    starts_at: datetime
    end_at: datetime
    initial_cash: Decimal
    source_kind: Literal["synthetic-equity-replay-v1"] = field(default=SOURCE_KIND, init=False)
    assumptions_validated: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    production_pretrade_eligible: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        with checked():
            if type(self.namespace) is not str or _NAMESPACE.fullmatch(self.namespace) is None:
                deny("replay_namespace_invalid")
            if type(self.seed) is not int or self.seed < 0:
                deny()
            for values in (self.instruments, self.sessions, self.decisions, self.markets):
                if type(values) is not tuple:
                    deny()
            if not self.instruments or not self.sessions or not self.decisions:
                deny()
            utc(self.starts_at)
            utc(self.end_at)
            if self.starts_at > self.end_at:
                deny("replay_ordering_invalid")
            require_bounded_decimal(self.initial_cash, "cash", nonnegative=True)
            object.__setattr__(self, "loaded", _configuration(self.loaded))
            self._candidate_and_history()
            self._instruments()
            self._events()

    @property
    def account_id(self) -> AccountId:
        return AccountId(self.namespace)

    def _candidate_and_history(self) -> None:
        if (
            type(self.candidate) is not ReplayCandidate
            or type(self.snapshot_settings) is not SnapshotSettings
        ):
            deny()
        self.candidate.__post_init__()
        self.snapshot_settings.__post_init__()
        settings, candidate = self.loaded.config.equity_strategies, self.candidate
        if (
            candidate.strategy_id not in settings.research_candidate_strategy_ids
            or candidate.short_window not in settings.short_windows
            or candidate.long_window not in settings.long_windows
            or candidate.exposure_multiplier not in settings.regime_multipliers
            or (
                candidate.strategy_id == "equity_relative_strength"
                and (
                    candidate.top_n not in settings.research_relative_strength_top_n
                    or candidate.short_window != min(settings.short_windows)
                )
            )
        ):
            deny("replay_candidate_invalid")
        if (
            self.snapshot_settings.interval is not settings.bar_interval
            or self.snapshot_settings.history_start >= self.starts_at
            or self.snapshot_settings.minimum_bars
            < self.loaded.config.research.minimum_history_bars
        ):
            deny("replay_history_invalid")

    def _instruments(self) -> None:
        if type(self.bundle) is not VerifiedBundle:
            deny("replay_bundle_invalid")
        self.bundle.envelope.__post_init__()
        mappings = {item.instrument_id: item.symbol for item in self.bundle.envelope.instruments}
        seen: set[str] = set()
        for instrument in self.instruments:
            if type(instrument) is not Instrument:
                deny()
            instrument.__post_init__()
            label(instrument.id)
            if (
                instrument.id in seen
                or mappings.get(instrument.id) != instrument.symbol
                or instrument.asset_class is not AssetClass.EQUITY
                or instrument.observed_at > self.starts_at
            ):
                deny("replay_instrument_invalid")
            for value in (
                instrument.price_increment,
                instrument.quantity_increment,
                instrument.minimum_quantity,
                instrument.minimum_notional,
                instrument.maximum_quantity,
            ):
                if value is not None:
                    require_bounded_decimal(value, "instrument_value", positive=True)
            seen.add(instrument.id)

    def _events(self) -> None:
        known = {item.id for item in self.instruments}
        slots: dict[tuple[InstrumentId, datetime], ReplaySession] = {}
        ends: dict[InstrumentId, datetime] = {}
        for session in self.sessions:
            if type(session) is not ReplaySession:
                deny()
            session.__post_init__()
            if session.instrument_id not in known:
                deny("replay_session_invalid")
            prior_end = ends.get(session.instrument_id)
            if prior_end is not None and session.window.starts_at < prior_end:
                deny("replay_session_invalid")
            ends[session.instrument_id] = session.window.ends_at
            for at in session.opportunity_times:
                slots[(session.instrument_id, at)] = session
        if set(ends) != known:
            deny("replay_session_invalid")
        identifiers: set[str] = set()
        sequences: set[int] = set()
        previous: EventCursor | None = None
        for decision in self.decisions:
            if type(decision) is not ReplayDecision:
                deny()
            decision.__post_init__()
            if decision.event_id in identifiers:
                deny("replay_duplicate_conflict")
            self._cursor(decision.cursor, previous, sequences)
            identifiers.add(decision.event_id)
            previous = decision.cursor
        previous = None
        occupied: set[tuple[InstrumentId, datetime]] = set()
        seen: dict[str, SyntheticMarketEvent] = {}
        for event in self.markets:
            if type(event) is not SyntheticMarketEvent:
                deny()
            event.__post_init__()
            label(event.event_id)
            if event.event_id in seen:
                if seen[event.event_id] != event:
                    deny("replay_duplicate_conflict")
                continue
            if event.event_id in identifiers:
                deny("replay_duplicate_conflict")
            self._cursor(event.cursor, previous, sequences)
            slot = (event.quote.instrument_id, event.cursor.occurred_at)
            declared_session = slots.get(slot)
            if (
                declared_session is None
                or slot in occupied
                or event.clock.asset_class is not AssetClass.EQUITY
                or event.quote.timestamp_source is not TimestampSource.SIMULATED
                or event.window.starts_at < declared_session.window.starts_at
                or event.window.ends_at > declared_session.window.ends_at
            ):
                deny("replay_market_invalid")
            occupied.add(slot)
            seen[event.event_id] = event
            previous = event.cursor

    def _cursor(
        self, cursor: EventCursor, previous: EventCursor | None, sequences: set[int]
    ) -> None:
        if (
            cursor.sequence in sequences
            or not self.starts_at <= cursor.occurred_at <= self.end_at
            or (
                previous is not None
                and (
                    cursor.sequence <= previous.sequence
                    or cursor.occurred_at < previous.occurred_at
                )
            )
        ):
            deny("replay_ordering_invalid")
        sequences.add(cursor.sequence)


@dataclass(frozen=True, slots=True)
class ReplayOrderOutcome:
    intent_id: str
    accepted: bool
    reasons: tuple[str, ...]
    order_id: str | None

    def __post_init__(self) -> None:
        with checked():
            label(self.intent_id)
            if (
                type(self.accepted) is not bool
                or type(self.reasons) is not tuple
                or not self.reasons
            ):
                deny()
            for reason in self.reasons:
                label(reason)
            if self.accepted:
                label(self.order_id)
            elif self.order_id is not None:
                deny()
