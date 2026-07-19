"""Least-privilege broker capability contracts and safe errors."""

from trading_bot.brokers.errors import (
    BrokerCancellationAmbiguous,
    BrokerSubmissionAmbiguous,
    BrokerUnavailable,
    SchemaDriftError,
    UnsupportedCapabilityError,
)
from trading_bot.brokers.fake import FakeBroker
from trading_bot.brokers.protocols import BrokerCancelOnly, BrokerPlace, BrokerRead, BrokerReview

__all__ = [
    "BrokerCancelOnly",
    "BrokerCancellationAmbiguous",
    "BrokerPlace",
    "BrokerRead",
    "BrokerReview",
    "BrokerSubmissionAmbiguous",
    "BrokerUnavailable",
    "FakeBroker",
    "SchemaDriftError",
    "UnsupportedCapabilityError",
]
