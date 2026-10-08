"""Pure ten-month regime calculation; no execution or risk capability."""

from datetime import datetime

from trading_bot.research.etf_monthly_protocol import (
    EtfMonthlyError,
    EtfMonthlySignal,
    EtfMonthObservation,
    _signal_hash,
    _signal_values,
)


def compute_etf_monthly_signal(
    observations: tuple[EtfMonthObservation, ...],
    *,
    decision_at: datetime,
) -> EtfMonthlySignal:
    try:
        average, latest, regime, hashes = _signal_values(observations, decision_at)
        return EtfMonthlySignal(
            decision_at,
            observations,
            average,
            latest,
            regime,
            hashes,
            _signal_hash(observations, decision_at),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None
