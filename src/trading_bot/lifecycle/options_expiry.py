"""Explicit calendar-bound expiry deadlines. No exercise, close or stock orders."""

from dataclasses import dataclass
from datetime import date, datetime

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_exact_bool,
    _require_sha256_hex,
)
from trading_bot.domain.options import OptionContract, OptionSession, SettlementKind
from trading_bot.domain.options_account import observation_id, observation_rows


@dataclass(frozen=True, slots=True)
class OptionExpiryCalendar:
    """A supplied completeness assertion, not independent calendar certification.

    Coverage includes closed dates. Sessions are contract-eligible, ordered and
    complete within that range; production must separately verify their source.
    """

    contract_id: str
    coverage_start: date
    coverage_end: date
    sessions: tuple[OptionSession, ...]
    complete: bool
    known_at: datetime
    evidence_hash: str

    def __post_init__(self) -> None:
        observation_id(self.contract_id)
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise DomainValidationError("calendar coverage requires dates")
        if self.coverage_start > self.coverage_end:
            raise DomainValidationError("reversed calendar coverage")
        observation_rows(self.sessions, OptionSession)
        _require_exact_bool(self.complete, "complete")
        require_utc(self.known_at)
        _require_sha256_hex(self.evidence_hash, "evidence_hash")
        identifiers: set[str] = set()
        previous: OptionSession | None = None
        for session in self.sessions:
            if not self.coverage_start <= session.trading_date <= self.coverage_end:
                raise DomainValidationError("session outside declared coverage")
            if session.session_id in identifiers or (
                previous is not None
                and (
                    session.opens_at < previous.closes_at
                    or session.trading_date <= previous.trading_date
                    or session.exchange_timezone != previous.exchange_timezone
                )
            ):
                raise DomainValidationError("inconsistent calendar session ordering or identity")
            identifiers.add(session.session_id)
            previous = session


@dataclass(frozen=True, slots=True)
class OptionExpiryAssessment:
    contract_id: str
    exit_deadline: datetime | None
    reasons: tuple[str, ...]

    @property
    def action_required(self) -> bool:
        return bool(self.reasons)


def _preceding_session(
    contract: OptionContract,
    calendar: OptionExpiryCalendar | None,
    as_of: datetime,
) -> OptionSession | None:
    if calendar is None or (
        not calendar.complete
        or calendar.contract_id != contract.contract_id
        or calendar.known_at > as_of
        or contract.available_at > as_of
        or not calendar.coverage_start <= contract.expiration <= calendar.coverage_end
    ):
        return None
    # A contract's partial fixture list does not establish coverage, but known
    # observations inside the declared complete range may not contradict it.
    if any(
        session not in calendar.sessions
        for session in contract.eligible_sessions
        if calendar.coverage_start <= session.trading_date <= calendar.coverage_end
    ):
        return None
    for index, session in enumerate(calendar.sessions):
        if session.opens_at < contract.last_trading_at <= session.closes_at:
            if index == 0:
                return None
            return calendar.sessions[index - 1]
    return None


def assess_option_expiry(
    *,
    contract: OptionContract,
    calendar: OptionExpiryCalendar | None,
    as_of: datetime,
    has_exposure: bool,
    strategy_deadline: datetime | None = None,
) -> OptionExpiryAssessment:
    """Exit by the session preceding the contract's last eligible trading session.

    This is deliberately at least as conservative as the preceding-expiration
    policy. A reached deadline is an incident, never a synthetic fill or settlement.
    A cash-settlement policy needs separately verified reference/cutoff semantics.
    """
    if type(contract) is not OptionContract:
        raise DomainValidationError("exact OptionContract required")
    if calendar is not None and type(calendar) is not OptionExpiryCalendar:
        raise DomainValidationError("exact expiry calendar required")
    require_utc(as_of)
    _require_exact_bool(has_exposure, "has_exposure")
    if strategy_deadline is not None:
        require_utc(strategy_deadline)
    if not has_exposure:
        return OptionExpiryAssessment(contract.contract_id, None, ())
    if contract.settlement_kind is SettlementKind.CASH:
        return OptionExpiryAssessment(
            contract.contract_id, None, ("cash_settlement_policy_unverified",)
        )
    previous = _preceding_session(contract, calendar, as_of)
    if previous is None:
        return OptionExpiryAssessment(contract.contract_id, None, ("expiry_calendar_unverified",))
    deadline = previous.closes_at
    if strategy_deadline is not None:
        if strategy_deadline > deadline:
            raise DomainValidationError("strategy deadline cannot extend the expiry deadline")
        deadline = strategy_deadline
    reasons: list[str] = []
    if as_of >= deadline:
        reasons.append("expiry_exit_deadline_reached")
    elif as_of >= previous.opens_at:
        reasons.append("expiry_exit_session")
    if as_of >= contract.last_trading_at:
        reasons.append("last_trading_cutoff_reached")
    if as_of >= contract.settlement_at:
        reasons.append("settlement_reconciliation_required")
    return OptionExpiryAssessment(contract.contract_id, deadline, tuple(reasons))
