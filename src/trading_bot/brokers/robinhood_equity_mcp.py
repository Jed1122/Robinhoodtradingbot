"""Fail-closed equity capability factory requiring two independent evidence levels."""

from trading_bot.brokers.robinhood_equity_mapping import mapping_ready
from trading_bot.brokers.robinhood_mcp_transport import RobinhoodMcpTransport
from trading_bot.capabilities.models import CapabilityManifest, EvidenceLevel

REQUIRED_EQUITY_READ_OPERATIONS = (
    "get_accounts",
    "get_equity_positions",
    "get_equity_orders",
    "get_equity_quotes",
    "get_equity_tradability",
)


class CapabilityNotVerified(RuntimeError):
    pass


def build_equity_read_adapter(
    manifest: CapabilityManifest, transport: RobinhoodMcpTransport
) -> object:
    del transport
    for operation in REQUIRED_EQUITY_READ_OPERATIONS:
        try:
            record = manifest.find(provider="robinhood-trading", operation=operation)
        except LookupError:
            raise CapabilityNotVerified(f"{operation} requires schema-declared evidence") from None
        if not record.satisfies(EvidenceLevel.SCHEMA_DECLARED):
            raise CapabilityNotVerified(f"{operation} requires schema-declared evidence")
        if not record.satisfies(EvidenceLevel.AUTHENTICATED_READ_VERIFIED):
            raise CapabilityNotVerified(
                f"{operation} requires authenticated-read-verified evidence"
            )
    if not mapping_ready():
        raise CapabilityNotVerified("authenticated response mapping evidence is unavailable")
    raise CapabilityNotVerified("equity adapter remains locked pending reviewed mapper")


__all__ = ["REQUIRED_EQUITY_READ_OPERATIONS", "CapabilityNotVerified", "build_equity_read_adapter"]
