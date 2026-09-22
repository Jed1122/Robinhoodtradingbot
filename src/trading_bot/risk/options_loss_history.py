"""Synthetic loss-history observer, never an entry authorization or market-data attestation.

Session boundaries and liquidation marks are declared fixture inputs. Real-source calendar,
cash-flow completeness and valuation authentication are separate, still-locked capabilities.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig, enforce_safety_envelope
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import AccountId, ExecutionMode
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_exact_bool,
    _require_nonempty,
    _require_sha256_hex,
    require_bounded_decimal,
)


@dataclass(frozen=True, slots=True)
class OptionsLossPoint:
    event_id: str
    account_id: AccountId
    config_hash: str
    observed_at: datetime
    session_id: str
    session_open: datetime
    session_close: datetime
    previous_session_close: datetime | None
    liquidation_equity: Decimal
    cumulative_external_flows: Decimal
    source_hash: str
    complete: bool

    def __post_init__(self) -> None:
        for value, name in (
            (self.event_id, "event"),
            (self.session_id, "session"),
            (self.account_id, "account"),
        ):
            _require_nonempty(value, name)
            if len(value) > 128:
                raise DomainValidationError("risk identity exceeds bound")
        if not self.account_id.startswith("synthetic:"):
            raise DomainValidationError("synthetic account identity required")
        _require_sha256_hex(self.config_hash, "configuration")
        _require_sha256_hex(self.source_hash, "source")
        _require_exact_bool(self.complete, "complete")
        require_bounded_decimal(self.liquidation_equity, "liquidation equity")
        require_bounded_decimal(self.cumulative_external_flows, "external flows")
        for stamp in (self.observed_at, self.session_open, self.session_close):
            require_utc(stamp)
        if not self.session_open <= self.observed_at <= self.session_close:
            raise DomainValidationError("observation outside declared session")
        if self.session_open >= self.session_close:
            raise DomainValidationError("empty session")
        if self.previous_session_close is not None:
            require_utc(self.previous_session_close)
            if self.previous_session_close >= self.session_open:
                raise DomainValidationError("prior session must precede current session")


@dataclass(frozen=True, slots=True)
class OptionsLossReport:
    flow_adjusted_equity: Decimal
    reference_equity: Decimal
    peak_equity: Decimal
    daily_loss_usd: Decimal | None
    weekly_loss_usd: Decimal | None
    drawdown_loss_usd: Decimal
    daily_halt: bool
    weekly_halt: bool
    drawdown_halt: bool
    entry_reasons: tuple[str, ...]

    @property
    def paused(self) -> Literal[True]:
        return True

    @property
    def production_eligible(self) -> Literal[False]:
        return False

    @property
    def economic_evidence(self) -> Literal[False]:
        return False


def _week(stamp: datetime) -> datetime:
    return stamp.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=stamp.weekday()
    )


def _loss(basis: Decimal | None, equity: Decimal) -> Decimal | None:
    return None if basis is None else max(Decimal(0), basis - equity)


def _breached(basis: Decimal | None, equity: Decimal, limit: Decimal) -> bool:
    # Cross multiplication avoids rounding a percentage at the limit. Zero means no budget.
    return basis is not None and (
        basis <= 0 or max(Decimal(0), basis - equity) * 100 >= basis * limit
    )


def _validate(loaded: LoadedConfig, points: tuple[OptionsLossPoint, ...]) -> None:
    if type(loaded) is not LoadedConfig:
        raise DomainValidationError("canonical configuration required")
    enforce_safety_envelope(loaded.config, loaded.safety_envelope)
    canonical, digest = hash_loaded_config(loaded.config, loaded.safety_envelope)
    if canonical != loaded.canonical_json or digest != loaded.config_hash:
        raise DomainValidationError("configuration identity mismatch")
    c = loaded.config
    if (
        not c.options.enabled
        or c.live_trading_enabled
        or c.mode not in (ExecutionMode.BACKTEST, ExecutionMode.SIMULATION, ExecutionMode.PAPER)
    ):
        raise DomainValidationError("offline options configuration required")
    if type(points) is not tuple or not 1 <= len(points) <= c.options.replay_max_records:
        raise DomainValidationError("bounded nonempty observation tuple required")
    if any(type(p) is not OptionsLossPoint for p in points):
        raise DomainValidationError("validated observations required")
    first = points[0]
    if (
        first.observed_at != first.session_open
        or first.cumulative_external_flows != 0
        or first.liquidation_equity <= 0
        or not first.complete
    ):
        raise DomainValidationError("complete unfunded genesis at session open required")


def evaluate_options_loss_history(
    loaded: LoadedConfig, points: tuple[OptionsLossPoint, ...], *, as_of: datetime
) -> OptionsLossReport:
    """Reconstruct latches from the entire immutable history; never accepts a reset flag."""
    _validate(loaded, points)
    require_utc(as_of)
    with localcontext() as ctx:
        ctx.prec = 2048
        return _evaluate(loaded, points, as_of)


def _evaluate(
    loaded: LoadedConfig, points: tuple[OptionsLossPoint, ...], as_of: datetime
) -> OptionsLossReport:
    first = last = points[0]
    initial = adjusted = peak = first.liquidation_equity
    daily_basis: Decimal | None = initial
    weekly_basis: Decimal | None = initial
    daily_halt = weekly_halt = drawdown_halt = gap = False
    seen: dict[str, OptionsLossPoint] = {}
    sessions = {first.session_id}
    limits = loaded.config.loss_limits
    for point in points:
        if point.account_id != first.account_id or point.config_hash != str(loaded.config_hash):
            raise DomainValidationError("account/configuration identity changed")
        if point.event_id in seen:
            if seen[point.event_id] != point:
                raise DomainValidationError("conflicting duplicate risk event")
            continue
        if seen and point.observed_at <= last.observed_at:
            raise DomainValidationError("risk clock must advance")
        if point.session_id == last.session_id:
            if (point.session_open, point.session_close, point.previous_session_close) != (
                last.session_open,
                last.session_close,
                last.previous_session_close,
            ):
                raise DomainValidationError("session identity changed")
        else:
            if point.session_id in sessions or point.session_open <= last.session_close:
                raise DomainValidationError("overlapping or reused session")
            closed = (
                point.previous_session_close == last.session_close
                and last.observed_at == last.session_close
                and last.complete
            )
            gap = gap or not closed
            daily_basis = adjusted if closed else None
            daily_halt = False if closed else daily_halt
            if _week(point.session_open) != _week(last.session_open):
                weekly_basis = adjusted if closed else None
            sessions.add(point.session_id)
        gap = gap or not point.complete
        adjusted = point.liquidation_equity - point.cumulative_external_flows
        peak = max(peak, adjusted)
        daily_halt = daily_halt or _breached(daily_basis, adjusted, limits.max_daily_loss_pct)
        weekly_halt = weekly_halt or _breached(weekly_basis, adjusted, limits.max_weekly_loss_pct)
        drawdown_halt = drawdown_halt or _breached(
            peak, adjusted, limits.max_peak_to_trough_drawdown_pct
        )
        seen[point.event_id] = point
        last = point
    if as_of < last.observed_at:
        raise DomainValidationError("evaluation precedes risk evidence")
    age = as_of - last.observed_at
    # Avoid float conversion at a strict freshness boundary.
    age_seconds = Decimal(age.days * 86400 + age.seconds) + Decimal(age.microseconds) / 1000000
    reasons = tuple(
        name
        for triggered, name in (
            (daily_halt, "daily_loss_latched"),
            (weekly_halt, "weekly_loss_latched"),
            (drawdown_halt, "drawdown_latched"),
            (gap, "risk_history_incomplete"),
            (
                age_seconds > loaded.config.freshness.max_account_snapshot_age_seconds,
                "risk_observation_stale",
            ),
            (as_of >= last.session_close, "outside_session"),
        )
        if triggered
    )
    return OptionsLossReport(
        adjusted,
        min(initial, max(Decimal(0), last.liquidation_equity)),
        peak,
        _loss(daily_basis, adjusted),
        _loss(weekly_basis, adjusted),
        max(Decimal(0), peak - adjusted),
        daily_halt,
        weekly_halt,
        drawdown_halt,
        reasons,
    )
