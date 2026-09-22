import pytest

from trading_bot.brokers.robinhood_equity_mcp import (
    CapabilityNotVerified,
    build_equity_read_adapter,
)
from trading_bot.capabilities.models import CapabilityManifest


def test_equity_write_prerequisite_remains_external() -> None:
    with pytest.raises(CapabilityNotVerified, match="requires schema-declared evidence"):
        build_equity_read_adapter(CapabilityManifest(()), None)  # type: ignore[arg-type]
