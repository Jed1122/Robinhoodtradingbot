from pathlib import Path

import trading_bot.research.prediction as prediction


def test_prediction_research_exports_no_place_method() -> None:
    assert not any(name.startswith("place") for name in dir(prediction))


def test_prediction_research_has_no_broker_import() -> None:
    assert "trading_bot.brokers" not in Path(prediction.__file__).read_text(encoding="utf-8")
