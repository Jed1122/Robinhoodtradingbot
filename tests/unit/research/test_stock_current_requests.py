"""Current-provider requests retain the complete whole-cycle budget and monitor scope."""

from copy import deepcopy
from datetime import timedelta

import pytest

from tests.unit.research.test_stock_current_screen import PROFILE
from tests.unit.research.test_stock_requests import NOW, TEN, policy
from trading_bot.research.stock_requests import enrichment_requests
from trading_bot.research.stock_screen import discovery_requests
from trading_bot.runtime import stock_research_worker as worker
from trading_bot.runtime.stock_capture import parse_stock_capture_plan


def current(symbols=TEN, settings=None):
    return enrichment_requests(
        symbols=symbols, as_of=NOW, policy=settings or policy(), worker_profile_id=PROFILE
    )


def test_current_enrichment_adds_same_session_vocabulary_and_all_named_stocks():
    legacy = enrichment_requests(symbols=TEN, as_of=NOW, policy=policy())
    new = current()
    assert len(new) == 27 and new[2:] == legacy
    assert new[0] == {"tool": "get_scanner_filter_specs", "arguments": {}}
    assert new[1] == {
        "tool": "preview_scan",
        "arguments": {
            "filters": [
                {
                    "filter_type": "FILTER_TYPE_INSTRUMENT_TYPE",
                    "predicate": "=",
                    "values": ["STOCK"],
                },
                {"expression": "symbol", "predicate": "ANY_OF", "values": list(TEN)},
            ],
            "columns": discovery_requests(policy(), worker_profile_id=PROFILE)[1]["arguments"][
                "columns"
            ],
        },
    }
    assert len(parse_stock_capture_plan(list(new))) == 27
    assert all(
        "FILTER_TYPE_LAST" not in str(row) and "FILTER_TYPE_MARKET_CAP" not in str(row)
        for row in new[:2]
    )


def test_current_capacity_changes_only_opt_in_profile():
    assert len(current(settings=policy(max_calls_per_cycle=27))) == 27
    with pytest.raises(ValueError):
        current(settings=policy(max_calls_per_cycle=26))
    twelve = tuple(f"NAME{i}" for i in range(12))
    with pytest.raises(ValueError):
        current(twelve, settings=policy(shortlist_count=12))
    assert (
        len(enrichment_requests(symbols=twelve, as_of=NOW, policy=policy(shortlist_count=12))) == 31
    )


def target_observation():
    request = current(("HELD", "WATCH"))[1]
    result = {
        "total_items": 2,
        "filters_applied": deepcopy(request["arguments"]["filters"]),
        "results": [
            {
                "ticker": s,
                "instrument_id": "id-" + s,
                "instrument_type": "EQUITY",
                "columns": {"Asset type": "STOCK", "Last": "1"},
            }
            for s in ("HELD", "WATCH")
        ],
    }
    return request | {
        "received_at": NOW.isoformat(),
        "observation_sha256": "a" * 64,
        "payload": {"data": {"result": result}},
    }


def test_target_coverage_accepts_low_price_held_stock_without_reapplying_entry_filters():
    worker._verify_targeted_preview(
        (target_observation(),), symbols=("HELD", "WATCH"), policy=policy(), as_of=NOW
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "count",
        "duplicate_id",
        "wrong_type",
        "filter",
        "columns",
        "future",
        "stale",
    ],
)
def test_targeted_gaps_or_identity_drift_cannot_claim_complete_refresh(mutation):
    obs = target_observation()
    result = obs["payload"]["data"]["result"]
    if mutation == "missing":
        result["results"].pop()
        result["total_items"] = 1
    elif mutation == "extra":
        result["results"][0]["ticker"] = "OTHER"
    elif mutation == "count":
        result["total_items"] = 3
    elif mutation == "duplicate_id":
        result["results"][1]["instrument_id"] = result["results"][0]["instrument_id"]
    elif mutation == "wrong_type":
        result["results"][0]["columns"]["Asset type"] = "ETF"
    elif mutation == "filter":
        result["filters_applied"].pop()
    elif mutation == "columns":
        obs["arguments"]["columns"].pop()
    elif mutation == "future":
        obs["received_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif mutation == "stale":
        obs["received_at"] = (NOW - timedelta(hours=3)).isoformat()
    with pytest.raises(ValueError):
        worker._verify_targeted_preview(
            (obs,), symbols=("HELD", "WATCH"), policy=policy(), as_of=NOW
        )
