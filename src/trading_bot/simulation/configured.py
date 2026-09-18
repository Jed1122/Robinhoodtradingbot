"""Compatibility entry point for one-shot, synthetic-only order simulation."""

from trading_bot.simulation.configured_models import ConfiguredOrderRequest
from trading_bot.simulation.configured_results import ConfiguredOrderResult
from trading_bot.simulation.configured_session import ConfiguredOrderSession


def simulate_configured_order(request: ConfiguredOrderRequest) -> ConfiguredOrderResult:
    """Use the same transition authority as incremental replay, with legacy hashes."""
    session = ConfiguredOrderSession(request)
    return session.advance_to(request.end_at)


__all__ = ["ConfiguredOrderSession", "simulate_configured_order"]
