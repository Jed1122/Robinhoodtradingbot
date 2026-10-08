"""Monthly selection is a new offline route, not a production/config loophole."""

import importlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.unit.research.test_etf_study import CONFIGS, loaded
from trading_bot.config import load_config
from trading_bot.domain import ExecutionMode

ID = "spy-cash-monthly-sma10-protected-development-v1"
GOLDENS = Path(__file__).parents[2] / "fixtures/etf/monthly/legacy-hashes.json"


def monthly_loaded(**overrides):
    return load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "etf/monthly/simulation.yaml",
        CONFIGS / "safety-envelope.yaml",
        overrides,
    )


def test_legacy_literal_hashes_and_policy_are_preserved():
    from tests.unit.simulation.test_etf_daily_screen import request
    from trading_bot.research.etf_daily_economics import (
        etf_daily_economic_plan_hash,
        run_etf_daily_economics,
    )
    from trading_bot.simulation.etf_daily_screen import run_etf_daily_screen

    expected = json.loads(GOLDENS.read_bytes())
    req = request()
    assert req.protocol.study.windows == (20, 100)
    assert req.protocol.study.rebalance_sessions == 5
    actual = {
        "config": req.protocol.study.config_hash,
        "study": req.protocol.study.study_hash,
        "protocol": req.protocol.protocol_hash,
        "request": req.request_hash,
        "result": run_etf_daily_screen(req).result_hash,
        "economic_plan": etf_daily_economic_plan_hash(req.protocol),
        "economic_result": run_etf_daily_economics(req).result_hash,
    }
    assert actual == {key: expected[key] for key in actual}


def test_monthly_profile_uses_existing_graph_and_limits():
    new, old = monthly_loaded(), loaded()
    c = new.config
    assert type(c) is type(old.config)
    assert set(type(c).model_fields) == set(type(old.config).model_fields)
    assert c.mode is ExecutionMode.SIMULATION and c.runtime.start_paused
    assert c.live_trading_enabled is False and c.options.enabled is False
    assert c.crypto.enabled is False and c.prediction_markets.simulation_enabled is False
    assert c.equity_strategies.etf_pilot.enabled is False
    assert c.equity_strategies.research_candidate_strategy_ids == (ID,)
    assert c.equity_strategies.research_universe_symbols == ("SPY",)
    assert c.portfolio == old.config.portfolio
    assert c.position_risk == old.config.position_risk
    assert c.activity == old.config.activity
    assert c.portfolio.expected_starting_equity_usd == Decimal("100")
    assert c.activity.max_order_notional_usd == Decimal("15")


def test_legacy_intake_and_paired_math_hashes():
    from tests.fixtures.etf.monthly.fixtures import legacy_package
    from tests.unit.research.test_etf_daily_economics_adversarial import scored
    from tests.unit.research.test_etf_daily_intake import frozen
    from tests.unit.simulation.test_etf_daily_screen import request
    from trading_bot.market_data.recording import content_hash
    from trading_bot.research.etf_daily_intake import (
        etf_daily_source_plan_hash,
        make_etf_daily_request,
    )
    from trading_bot.simulation.etf_daily_screen import run_etf_daily_screen

    expected = json.loads(GOLDENS.read_bytes())
    p = legacy_package()
    req = make_etf_daily_request(frozen(p), p.archive, p.calendar, p.issuer)
    assert etf_daily_source_plan_hash(p.archive, p.calendar, p.issuer) == expected["source_plan"]
    assert req.protocol.protocol_hash == expected["projected_protocol"]
    assert req.request_hash == expected["projected_request"]
    score = scored(run_etf_daily_screen(request(200)))
    assert content_hash(score) == expected["paired_score"]
    assert score.uncertainty.paired_input_hash == expected["paired_input"]
    assert score.uncertainty.paired_report_hash == expected["paired_report"]


@pytest.mark.parametrize("value", ["paper", "shadow", "micro_live", "live"])
def test_monthly_selection_denies_nonoffline(value):
    monthly_loaded()  # Missing profile is not evidence that the guard works.
    with pytest.raises(ValueError):
        monthly_loaded(TRADING_BOT__MODE=value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("RESEARCH_CANDIDATE_STRATEGY_IDS", f"[{ID}, equity_momentum]"),
        ("RESEARCH_UNIVERSE_SYMBOLS", "[SPY, QQQ]"),
        ("ETF_PILOT__ENABLED", "true"),
    ],
)
def test_monthly_selection_denies_mixed_candidates(name, value):
    monthly_loaded()
    with pytest.raises(ValueError):
        monthly_loaded(**{"TRADING_BOT__EQUITY_STRATEGIES__" + name: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"TRADING_BOT__RUNTIME__START_PAUSED": "false"},
        {"LIVE_TRADING_ENABLED": "true"},
        {"TRADING_BOT__CRYPTO__ENABLED": "true"},
        {"TRADING_BOT__OPTIONS__ENABLED": "true"},
        {"TRADING_BOT__PREDICTION_MARKETS__SIMULATION_ENABLED": "true"},
    ],
)
def test_monthly_selection_is_write_incapable(overrides):
    monthly_loaded()
    with pytest.raises(ValueError):
        monthly_loaded(**overrides)


def test_monthly_profile_cannot_feed_legacy_equity_comparison():
    from trading_bot.research.equity_comparison import EquityComparisonRequest

    with pytest.raises(ValueError, match="monthly"):
        EquityComparisonRequest(monthly_loaded(), "a" * 64, True, "fixture", None)


def test_restore_existing_canonical_graph_and_exact_keys():
    restore = importlib.import_module("trading_bot.config.loader").restore_loaded_config
    old = loaded()
    assert restore(old.canonical_json, old.config_hash) == old
    doc = json.loads(old.canonical_json)
    del doc["config"]["mode"]
    with pytest.raises(ValueError):
        restore(json.dumps(doc).encode(), old.config_hash)
    with pytest.raises(ValueError):
        restore(old.canonical_json, "0" * 64)
    with pytest.raises(ValueError):
        restore(b" " * (1048576 + 1), old.config_hash)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_root",
        "extra_nested",
        "null",
        "numeric_decimal",
        "trailing_whitespace",
        "invalid_json",
        "wrong_type",
    ],
)
def test_restore_denies_noncanonical_preimages(mutation):
    restore = importlib.import_module("trading_bot.config.loader").restore_loaded_config
    old = loaded()
    doc = json.loads(old.canonical_json)
    if mutation == "extra_root":
        doc["extra"] = 1
    elif mutation == "extra_nested":
        doc["config"]["portfolio"]["extra"] = 1
    elif mutation == "null":
        doc["config"]["mode"] = None
    elif mutation == "numeric_decimal":
        doc["config"]["portfolio"]["expected_starting_equity_usd"] = 100
    body = json.dumps(doc).encode()
    if mutation == "trailing_whitespace":
        body = old.canonical_json + b"\n"
    elif mutation == "invalid_json":
        body = b"{"
    elif mutation == "wrong_type":
        body = old.canonical_json.decode()
    with pytest.raises(ValueError):
        restore(body, old.config_hash)
