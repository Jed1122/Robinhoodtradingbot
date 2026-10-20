"""Closed short-history scheduling without changing legacy admission."""

from datetime import date, datetime, timedelta
from importlib import import_module, util
from typing import Any

import pytest

from trading_bot.market_data.recording import canonical_json
from trading_bot.research.etf_capital_signals import capital_walk_forward_folds

_MODULE = "trading_bot.research.etf_capital_protocol"


def _protocol(name: object = "observed-252x84-v2") -> Any:
    assert util.find_spec(_MODULE) is not None, "explicit observed protocol is not implemented"
    return import_module(_MODULE).CapitalStudyProtocol(name)


def _dates(start: date, count: int) -> tuple[date, ...]:
    # Synthetic consecutive dates test indexing, not exchange-calendar evidence.
    return tuple(start + timedelta(days=i) for i in range(count))


def test_observed_folds_separate_training_purge_embargo_and_global_tail() -> None:
    sessions = _dates(date(2023, 1, 3), 752)
    protocol = _protocol()
    folds = protocol.folds(sessions)
    assert len(folds) == 5
    assert folds[0].train_sessions == sessions[:252]
    assert folds[0].selection_sessions == sessions[:232]
    assert folds[0].embargo_sessions == sessions[252:272]
    assert folds[0].test_sessions == sessions[272:356]
    assert folds[0].exit_only_sessions == sessions[356:379]
    assert folds[1].train_sessions == sessions[84:336]
    assert folds[1].test_sessions == sessions[356:440]
    assert folds[-1].train_sessions == sessions[336:588]
    assert folds[-1].selection_sessions == sessions[336:568]
    assert folds[-1].embargo_sessions == sessions[588:608]
    assert folds[-1].test_sessions == sessions[608:692]
    assert folds[-1].exit_only_sessions == sessions[692:715]
    assert tuple(d for fold in folds for d in fold.test_sessions) == sessions[272:692]
    assert sessions[protocol.baseline_index] == sessions[271]
    assert sessions[protocol.test_start : protocol.test_end] == sessions[272:692]
    assert sessions[protocol.test_end : protocol.used_count] == sessions[692:715]
    assert len(sessions[protocol.used_count :]) == 37
    assert protocol.training_count == 252
    assert protocol.purge_count == protocol.embargo_count == 20
    assert protocol.test_count == 420
    assert protocol.tail_count == 23


def test_observed_minimum_is_715_without_legacy_history_requirement() -> None:
    protocol = _protocol()
    sessions = _dates(date(2023, 1, 1), 715)
    assert protocol.folds(sessions)[-1].exit_only_sessions[-1] == sessions[-1]
    with pytest.raises(ValueError):
        protocol.folds(sessions[:-1])
    with pytest.raises(ValueError):
        capital_walk_forward_folds(sessions)


def test_legacy_protocol_matches_existing_fold_bytes_and_gate() -> None:
    protocol = _protocol("legacy-750x126-v1")
    sessions = _dates(date(2016, 1, 1), 1423)
    assert canonical_json(protocol.folds(sessions)) == canonical_json(
        capital_walk_forward_folds(sessions)
    )
    assert protocol.baseline_index == 769
    assert protocol.test_start == 770
    assert protocol.test_end == 1400
    assert protocol.used_count == 1423
    assert protocol.training_count == 750
    assert protocol.test_count_per_fold == 126
    assert protocol.test_count == 630
    with pytest.raises(ValueError):
        protocol.folds(sessions[:-1])
    with pytest.raises(ValueError):
        protocol.folds((*_dates(date(2020, 2, 1), 1423), date(2024, 1, 1)))
    with pytest.raises(ValueError):
        protocol.folds(_dates(date(2015, 12, 31), 1423))


@pytest.mark.parametrize("name", [None, True, 252, "", "observed-252x126-v2", "future-v3"])
def test_only_two_explicit_protocol_names_are_admitted(name: object) -> None:
    with pytest.raises(ValueError):
        _protocol(name)


def test_name_and_protocol_subclasses_cannot_expand_the_closed_contract() -> None:
    class Name(str):
        pass

    with pytest.raises(ValueError):
        _protocol(Name("observed-252x84-v2"))
    cls = type(_protocol())

    class Derived(cls):
        pass

    with pytest.raises(ValueError):
        Derived("observed-252x84-v2")


@pytest.mark.parametrize(
    "case", ["list", "duplicate", "reversed", "datetime", "early", "late", "excess", "empty"]
)
def test_invalid_observed_session_sequences_fail_closed(case: str) -> None:
    protocol = _protocol()
    sessions: Any = _dates(date(2023, 1, 1), 715)
    if case == "list":
        sessions = list(sessions)
    elif case == "duplicate":
        sessions = (sessions[0], *sessions)
    elif case == "reversed":
        sessions = tuple(reversed(sessions))
    elif case == "datetime":
        sessions = (datetime(2023, 1, 1), *sessions[1:])
    elif case == "early":
        sessions = (date(2022, 12, 31), *sessions[1:])
    elif case == "late":
        sessions = (*sessions, date(2026, 1, 1))
    elif case == "excess":
        sessions = _dates(date(2023, 1, 1), 4001)
    else:
        sessions = ()
    with pytest.raises(ValueError):
        protocol.folds(sessions)


def test_protocol_identity_binds_variant_and_rejects_forged_name() -> None:
    observed, legacy = _protocol(), _protocol("legacy-750x126-v1")
    assert observed.protocol_hash != legacy.protocol_hash
    assert observed.protocol_hash == _protocol().protocol_hash
    object.__setattr__(observed, "name", "forged")
    with pytest.raises(ValueError):
        observed.folds(_dates(date(2023, 1, 1), 715))
    with pytest.raises(ValueError):
        _ = observed.protocol_hash
