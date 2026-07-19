import inspect
from pathlib import Path

from trading_bot.runtime.shadow import build_shadow_application


def test_shadow_builder_has_no_place_capability() -> None:
    assert "broker_place" not in inspect.signature(build_shadow_application).parameters


def test_shadow_module_does_not_import_place_protocol() -> None:
    source = Path("src/trading_bot/runtime/shadow.py").read_text()
    assert "BrokerPlace" not in source
