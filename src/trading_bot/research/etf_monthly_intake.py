"""Bound retained native inputs to the distinct monthly adaptive research policy."""

from decimal import Decimal

from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_issuer_distributions import EtfIssuerDistributionArchive
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_exploratory_intake import (
    _PROJECTION,
    project_etf_exploratory_inputs,
)
from trading_bot.research.etf_monthly_protocol import (
    EtfMonthlyError,
    EtfMonthlyProtocol,
    EtfMonthlyRequest,
    _check,
)
from trading_bot.research.etf_monthly_study import EtfMonthlyStudy, monthly_policy


def etf_monthly_source_plan_hash(
    archive: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    issuer: EtfIssuerDistributionArchive,
) -> str:
    return content_hash(
        {
            "schema": "etf-monthly-development-intake-v1",
            "bar_archive": archive.archive_hash,
            "calendar": calendar.archive_hash,
            "issuer": issuer.archive_hash,
            "projection": _PROJECTION,
            "price_basis": "unadjusted-no-splits-assumption",
            "evaluation": "adaptive-development-before-2024-only",
            "atr_warmup": 100,
            "monthly_window": 10,
            "anchor": "2016-10-31",
            "availability": "calendar-close-assumption-not-publication-evidence",
            "qualification": False,
        }
    )


def make_etf_monthly_request(
    study: EtfMonthlyStudy,
    archive: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    issuer: EtfIssuerDistributionArchive,
) -> EtfMonthlyRequest:
    try:
        monthly_policy(study)
        _check(study.source_plan_hash == etf_monthly_source_plan_hash(archive, calendar, issuer))
        sessions, bars, distributions = project_etf_exploratory_inputs(archive, calendar, issuer)
        protocol = EtfMonthlyProtocol(
            study,
            sessions,
            calendar.archive_hash,
            archive.archive_hash,
            issuer.archive_hash,
            Decimal("5"),
            Decimal(".01"),
            Decimal(".10"),
        )
        return EtfMonthlyRequest(protocol, bars, distributions, Decimal("500"))
    except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError):
        raise EtfMonthlyError() from None
