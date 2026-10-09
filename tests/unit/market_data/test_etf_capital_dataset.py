"""Five-symbol development datasets bind policy without granting eligibility."""

import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Inexact, localcontext

import pytest

from tests.unit.config.test_capital_research import capital_loaded
from tests.unit.market_data.test_alpaca_capital_native import body, request
from tests.unit.market_data.test_etf_capital_features import inputs
from tests.unit.market_data.test_etf_capital_inventory import calendar
from trading_bot.market_data.alpaca_capital_native import parse_capital_daily_page
from trading_bot.market_data.etf_capital_dataset import (
    build_capital_dataset,
    capital_dataset_features,
)


def sources():
    values = []
    for symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF"):
        captured, action = inputs()
        declared_request = request(symbol)
        wire = json.loads(body(symbol))
        first = wire["bars"][0]
        first.update(o=20, h=24, l=18, c=22, vw=21)
        wire["bars"] = [
            first,
            dict(first, t="2023-01-04T05:00:00Z", o=10, h=12, l=9, c=11, vw=10.5),
        ]
        raw = json.dumps(wire).encode()
        parsed = parse_capital_daily_page(
            raw, request=declared_request, expected_sha256=hashlib.sha256(raw).hexdigest()
        )
        values.append(
            (
                replace(captured, request=declared_request, pages=(parsed,)),
                replace(action, symbol=symbol),
            )
        )
    return tuple(row[0] for row in values), tuple(row[1] for row in values)


def dataset(archives=None, actions=None):
    captured, facts = sources()
    declared = calendar()
    declared = replace(declared, sessions=declared.sessions[:2])
    return build_capital_dataset(
        loaded=capital_loaded(),
        archives=captured if archives is None else archives,
        actions=facts if actions is None else actions,
        calendar=declared,
        start=date(2023, 1, 3),
        end=date(2023, 1, 6),
    )


def test_policy_bound_dataset_has_all_five_symbols_and_no_eligibility():
    result = dataset()
    assert result.config_hash == capital_loaded().config_hash
    assert tuple(value.request.symbol for value in result.archives) == (
        "SPY",
        "QQQ",
        "IWM",
        "SHY",
        "IEF",
    )
    assert (
        result.source_qualified is result.evidence_promotable is result.execution_enabled is False
    )
    assert len(capital_dataset_features(result, as_of_session=date(2023, 1, 3))[0].raw_bars) == 1


def test_dataset_hash_does_not_depend_on_archive_or_action_input_order():
    captured, actions = sources()
    assert (
        dataset(captured, actions).dataset_hash
        == dataset(tuple(reversed(captured)), tuple(reversed(actions))).dataset_hash
    )


def test_absent_or_duplicate_symbol_denies_dataset_construction():
    captured, actions = sources()
    with pytest.raises(ValueError):
        dataset(captured[:-1], actions)
    with pytest.raises(ValueError):
        dataset(captured, (*actions[:-1], actions[0]))


def test_unknown_action_inputs_and_window_mismatch_deny_dataset():
    captured, actions = sources()
    with pytest.raises(ValueError):
        dataset(captured, (replace(actions[0], splits=None), *actions[1:]))
    with pytest.raises(ValueError):
        dataset(captured, (replace(actions[0], start=date(2023, 1, 2)), *actions[1:]))


def test_projection_outside_declared_session_is_not_silently_clipped():
    with pytest.raises(ValueError):
        capital_dataset_features(dataset(), as_of_session=date(2023, 1, 5))


def test_altered_policy_identity_cannot_be_used_as_research_input():
    result = dataset()
    object.__setattr__(result, "config_hash", "a" * 64)
    with pytest.raises(ValueError):
        capital_dataset_features(result, as_of_session=date(2023, 1, 3))


def test_mutated_eligibility_flags_are_rejected_by_consumer():
    result = dataset()
    object.__setattr__(result, "source_qualified", True)
    with pytest.raises(ValueError):
        capital_dataset_features(result, as_of_session=date(2023, 1, 3))


@pytest.mark.parametrize("source", ["archive", "action"])
def test_mutated_source_flags_are_not_normalized_away(source):
    captured, facts = sources()
    selected = captured[0] if source == "archive" else facts[0]
    object.__setattr__(selected, "source_qualified", True)
    with pytest.raises(ValueError):
        dataset(captured, facts)


def test_development_contract_cannot_relabel_2024_as_development():
    with pytest.raises(ValueError):
        replace(dataset(), start=date(2024, 1, 1), end=date(2024, 2, 1))


def test_policy_restore_and_projection_do_not_use_ambient_decimal_context():
    reference = dataset().dataset_hash
    loaded = capital_loaded()
    captured, facts = sources()
    declared = calendar()
    declared = replace(declared, sessions=declared.sessions[:2])
    with localcontext() as context:
        context.prec = 2
        context.Emax = 1
        context.traps[Inexact] = True
        current = build_capital_dataset(
            loaded=loaded,
            archives=captured,
            actions=facts,
            calendar=declared,
            start=date(2023, 1, 3),
            end=date(2023, 1, 6),
        )
        assert current.dataset_hash == reference
        assert (
            capital_dataset_features(current, as_of_session=date(2023, 1, 3))[0].raw_bars[0].close
            == 22
        )
