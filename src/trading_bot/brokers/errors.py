"""Broker-neutral errors with no transport or secret-bearing state."""

from trading_bot.capabilities.models import UnsupportedCapabilityError

__all__ = [
    "BrokerSubmissionAmbiguous",
    "BrokerUnavailable",
    "SchemaDriftError",
    "UnsupportedCapabilityError",
]


class BrokerUnavailable(RuntimeError):
    """Raised when a broker capability cannot safely serve a request."""

    def __init__(self) -> None:
        super().__init__("broker capability is unavailable")


class BrokerSubmissionAmbiguous(RuntimeError):
    """Raised when a submission outcome cannot be determined safely."""

    def __init__(self) -> None:
        super().__init__("broker submission outcome is ambiguous")


class SchemaDriftError(RuntimeError):
    """Raised when observed provider data no longer matches a reviewed schema."""

    def __init__(self) -> None:
        super().__init__("broker schema does not match the reviewed contract")
