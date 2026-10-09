"""Original synthetic prefix equivalence; no persisted state adoption."""

from decimal import Decimal as D

import pytest

from tests.unit.simulation.test_etf_capital_account import script
from trading_bot.simulation.etf_capital_account import replay_capital_account


def prefixes(events):
    from trading_bot.simulation.etf_capital_account import replay_capital_account_prefixes

    return replay_capital_account_prefixes(initial_cash=D("100"), events=events)


def test_all_prefixes_preserve_existing_values_and_v1_hashes():
    events = script()
    expected = tuple(
        replay_capital_account(initial_cash=D("100"), events=events[:count])
        for count in range(len(events) + 1)
    )
    assert prefixes(events) == expected
    assert tuple(p.cash for p in prefixes(events)) == tuple(
        map(
            D,
            (
                "100",
                "100",
                "100",
                "90.06",
                "90.06",
                "90.06",
                "90.06",
                "90.06",
                "100.11",
                "100.11",
                "100.11",
            ),
        )
    )
    assert all(not p.execution_enabled and not p.evidence_promotable for p in expected)


def test_duplicate_delivery_still_has_one_result_per_original_prefix():
    events = script()
    original = (*events[:3], events[2], *events[3:])
    values = prefixes(original)
    assert len(values) == len(original) + 1
    assert values[3] == values[4]
    assert values[-1] == replay_capital_account(initial_cash=D("100"), events=events)


def test_no_valid_partial_results_escape_an_invalid_final_event():
    events = script()
    with pytest.raises(ValueError):
        prefixes((*events, object()))


def test_genesis_empty_prefix_retains_existing_identity():
    assert prefixes(()) == (replay_capital_account(initial_cash=D("100"), events=()),)


def test_certified_original_v1_hash_preimages_are_unchanged():
    values = prefixes(script())
    assert tuple(values[n].economic_hash for n in (0, 3, 8, 10)) == (
        "4849ac56925413aa4f2a7923d4cc3bceefa23d3599078af32ef43eb6f3f35ad3",
        "c359bfed8e7674273af99899faba95e3ad6b72de7255e502889cc6f0834eef2e",
        "9971ef423a945440ed2b453b108b4df8ac4140c6985e03f8e5813707db029c08",
        "1213ed107e0b282c94fbc5014fee3751107d965c0e412bc94159cdaa3fc18ce8",
    )


def test_risk_consumes_one_complete_original_reducer_pass(monkeypatch):
    import trading_bot.simulation.etf_capital_account as account
    from tests.unit.simulation.test_etf_capital_risk import point, run

    original = account._replay
    calls = []

    def counted(*args, **kwargs):
        calls.append(len(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(account, "_replay", counted)
    value = run(script(), (point(0, 0), point(1, 3, "99"), point(2, 10)))
    assert value.points[-1].equity == D("100.11")
    assert calls == [10]


def test_checkpoint_restoration_consumes_one_original_reducer_pass(tmp_path, monkeypatch):
    import trading_bot.simulation.etf_capital_account as account
    from tests.integration.persistence.test_etf_capital_checkpoint import advance

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    first = advance(root, 3)
    second = advance(root, 8, first.head_hash)
    original = account._replay
    calls = []

    def counted(*args, **kwargs):
        calls.append(len(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(account, "_replay", counted)
    final = advance(root, 10, second.head_hash)
    assert final.result.cash == D("100.11")
    assert final.sequence == 3
    assert calls == [10]
