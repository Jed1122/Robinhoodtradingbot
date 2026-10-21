from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.hybrid.inputs import ResearchInputs, present_research

NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)


def test_imported_prices_are_explicitly_nonqualified_and_source_labeled():
    bundle = ResearchInputs.model_validate(
        {
            "provider": "declared_import",
            "received_at": NOW,
            "source_reference": "licensed-local-export",
            "facts": [],
            "prices": {
                "SPY": [
                    {"completed_at": NOW - timedelta(days=2), "open": "100", "close": "101"},
                    {"completed_at": NOW - timedelta(days=1), "open": "101", "close": "102"},
                ]
            },
        }
    )
    report = present_research(bundle, NOW)
    assert report["sources"][0]["name"] == "licensed-local-export"
    assert report["qualified"] is False
    assert report["strategy_status"]
    with pytest.raises(ValueError):
        present_research(bundle, NOW - timedelta(days=3))


def test_future_prices_and_oversize_universe_rejected():
    with pytest.raises(ValueError):
        ResearchInputs.model_validate(
            {
                "provider": "declared_import",
                "received_at": NOW,
                "source_reference": "export",
                "facts": [],
                "prices": {
                    "SPY": [
                        {"completed_at": NOW + timedelta(days=1), "open": "100", "close": "101"}
                    ]
                },
            }
        )
