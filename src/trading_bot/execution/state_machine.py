"""Execution-facing re-export of the canonical domain order state machine."""

from trading_bot.domain.order_state_machine import (
    _TRANSITIONS as _DOMAIN_TRANSITIONS,
)
from trading_bot.domain.order_state_machine import (
    InvalidOrderTransition,
    transition,
)

_TRANSITIONS = _DOMAIN_TRANSITIONS

__all__ = ["InvalidOrderTransition", "transition"]
