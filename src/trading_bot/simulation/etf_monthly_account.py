"""Versioned monthly wrapper over the one credential-free economic reducer."""

from dataclasses import dataclass, replace
from decimal import Decimal

from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_monthly_study import EtfMonthlyStudy, monthly_policy
from trading_bot.simulation.etf_account import (
    EtfAccountError,
    EtfAccountEvent,
    EtfAccountResult,
    EtfPendingAdmission,
    _AccountStepper,
    _admit_pending,
    _check,
    _run,
)


@dataclass(frozen=True, slots=True)
class EtfMonthlyAccountRequest:
    study: EtfMonthlyStudy
    initial_cash: Decimal
    events: tuple[EtfAccountEvent, ...]

    def __post_init__(self) -> None:
        monthly_policy(self.study)
        require_bounded_decimal(self.initial_cash, "initial cash", positive=True)
        _check(self.initial_cash in self.study.capital_tiers)
        _check(type(self.events) is tuple and len(self.events) <= 10000)
        for event in self.events:
            _check(type(event) is EtfAccountEvent)
            replace(event)
            _check(_ns(self.study.requested_start) <= event.at_ns < _ns(self.study.requested_end))

    @property
    def run_id(self) -> str:
        return content_hash(
            ("etf-monthly-account-run-v1", self.study.study_hash, self.initial_cash)
        )


class EtfMonthlyAccountStepper(_AccountStepper):
    def __init__(self, request: EtfMonthlyAccountRequest) -> None:
        _check(type(request) is EtfMonthlyAccountRequest)
        super().__init__(replace(request))


def replay_etf_monthly_account(request: EtfMonthlyAccountRequest) -> EtfAccountResult:
    try:
        _check(type(request) is EtfMonthlyAccountRequest)
        return _run(replace(request), len(request.events))
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError):
        raise EtfAccountError() from None


def admit_etf_monthly_pending_intent(
    request: EtfMonthlyAccountRequest, candidate: EtfAccountEvent
) -> EtfPendingAdmission:
    current = replay_etf_monthly_account(request)
    return _admit_pending(request, candidate, current)
