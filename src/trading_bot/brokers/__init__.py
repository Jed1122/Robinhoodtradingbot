"""Least-privilege broker capability contracts and safe errors."""

from trading_bot.brokers.errors import (
    BrokerSubmissionAmbiguous,
    BrokerUnavailable,
    SchemaDriftError,
    UnsupportedCapabilityError,
)
from trading_bot.brokers.protocols import BrokerCancelOnly, BrokerPlace, BrokerRead, BrokerReview

__all__ = [
    "BrokerCancelOnly",
    "BrokerPlace",
    "BrokerRead",
    "BrokerReview",
    "BrokerSubmissionAmbiguous",
    "BrokerUnavailable",
    "SchemaDriftError",
    "UnsupportedCapabilityError",
]
