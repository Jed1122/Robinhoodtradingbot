import pytest

from trading_bot.brokers.robinhood_equity_mcp import (
    CapabilityNotVerified,
    build_equity_read_adapter,
)
from trading_bot.capabilities.models import CapabilityManifest


def test_equity_adapter_cannot_build_without_schema_evidence() -> None:
    with pytest.raises(CapabilityNotVerified, match="schema-declared"):
        build_equity_read_adapter(CapabilityManifest(records=()), None)  # type: ignore[arg-type]
