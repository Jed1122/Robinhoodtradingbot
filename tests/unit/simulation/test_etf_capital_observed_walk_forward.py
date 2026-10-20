"""Short protocol orchestration; doubled paths are not economic evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.unit.research.test_etf_capital_observed_prepared import observed_long_source
from tests.unit.simulation.test_etf_capital_walk_forward import request as legacy_request
from trading_bot.market_data.etf_capital_owned import _own_capital_observed_source
from trading_bot.research.etf_capital_prepared import _PreparedCapitalDay, _PreparedCapitalInput
from trading_bot.research.etf_capital_signals import capital_candidates


def request(source, **changes):
    from trading_bot.simulation import etf_capital_walk_forward as module

    cls = getattr(module, "CapitalObservedWalkForwardRequest", None)
    assert cls is not None, "observed walk-forward admission is missing"
    old = legacy_request(source)
    return replace(
        cls(
            source,
            old.initial_cash,
            old.instruments,
            old.episode_fee_bound,
            old.entry_fee,
            old.exit_fee,
            old.roundtrip_friction_pct,
        ),
        **changes,
    )


def run(value):
    from trading_bot.simulation import etf_capital_walk_forward as module

    return module.replay_capital_observed_walk_forward(value)


def test_observed_public_entrypoint_denies_invalid_originals_before_preparation(
    source, monkeypatch
):
    from trading_bot.simulation import etf_capital_walk_forward as module

    value = request(source)
    monkeypatch.setattr(
        module,
        "_prepare_owned_capital_days",
        lambda *a, **k: pytest.fail("bad source reached preparation"),
    )
    with pytest.raises(ValueError):
        run(replace(value, dataset=None))


def typed_prepared(owned):
    rows = owned.dataset.calendar.sessions
    return _PreparedCapitalInput(
        owned.source_hash,
        owned.dataset.config_hash,
        tuple(s.session_date for s in rows),
        tuple(
            _PreparedCapitalDay(s.session_date, s.closes_at, i, (), (), (), False, (), "b" * 64)
            for i, s in enumerate(rows[:715])
        ),
        "a" * 64,
    )


@pytest.fixture(scope="module")
def source():
    return observed_long_source(752)


@pytest.fixture(scope="module")
def owned(source):
    return _own_capital_observed_source(source)


@pytest.fixture
def probe(monkeypatch, source, owned):
    from trading_bot.simulation import etf_capital_walk_forward as module

    # Assert new public admission exists before patching anything.
    request(source)
    paths = []
    profits = {}
    incomplete = set()

    def replay(**kwargs):
        days, terms = kwargs["schedule"], kwargs["terms"]
        paths.append(kwargs)
        key = days[0].session, days[0].candidate
        close = next(
            s.closes_at for s in source.calendar.sessions if s.session_date == days[-1].session
        )
        return SimpleNamespace(
            account=SimpleNamespace(
                complete=key not in incomplete,
                quantity=D(0),
                cash=terms.initial_cash + profits.get(key, D(0)),
            ),
            points=(SimpleNamespace(at=close + timedelta(seconds=3)),),
            input_hash=str(len(paths) % 10) * 64,
        )

    def prepare(value, *, sessions):
        assert sessions == tuple(s.session_date for s in source.calendar.sessions[:715])
        return typed_prepared(value)

    monkeypatch.setattr(module, "_own_capital_observed_source", lambda _: owned)
    monkeypatch.setattr(module, "_prepare_owned_capital_days", prepare)
    monkeypatch.setattr(module, "_replay_prepared_capital_trajectory", replay)
    return SimpleNamespace(paths=paths, profits=profits, incomplete=incomplete)


def test_observed_full_schedule_and_37_unused_dates(source, probe):
    result = run(request(source))
    dates = tuple(s.session_date for s in source.calendar.sessions)
    assert result.used_sessions == dates[:715]
    assert result.unused_sessions == dates[715:] and len(result.unused_sessions) == 37
    assert len(result.folds) == 5 and all(len(f.training) == 28 for f in result.folds)
    assert len(result.fixed) == 28 and len(probe.paths) == 169
    assert tuple(f.training_cutoff for f in result.folds) == tuple(
        source.calendar.sessions[i].closes_at + timedelta(seconds=3)
        for i in (251, 335, 419, 503, 587)
    )
    assert tuple(f.selection_at for f in result.folds) == tuple(
        source.calendar.sessions[i].closes_at for i in (271, 355, 439, 523, 607)
    )
    assert all(p["terms"].roundtrip_friction_pct == D(".40") for p in probe.paths[:140])
    days = probe.paths[0]["schedule"]
    assert len(days) == 252 and days[231].entry_decision_allowed
    assert days[232].entry_submission_allowed
    assert all(not d.entry_decision_allowed for d in days[232:])
    for path in probe.paths[140:]:
        days = path["schedule"]
        assert tuple(d.session for d in days) == dates[271:715]
        assert days[355 - 271].entry_submission_allowed
        assert days[356 - 271].entry_decision_allowed
        assert days[690 - 271].entry_decision_allowed
        assert not days[691 - 271].entry_decision_allowed
        assert all(not d.entry_submission_allowed for d in days[692 - 271 :])


def test_observed_boundary_old_opening_then_new_close_and_incomplete_exclusion(source, probe):
    grid = capital_candidates()
    first = source.calendar.sessions[0].session_date
    probe.profits[(first, grid[0])] = D(999)
    probe.incomplete.add((first, grid[0]))
    probe.profits[(first, grid[1])] = D(1)
    result = run(request(source))
    assert result.folds[0].selection.selected == grid[1]
    assert result.folds[0].training[0].outcome.net_pnl is None
    chosen = probe.paths[140]
    boundary = 355 - 271
    assert chosen["opening_candidates"][boundary] == grid[1]
    assert chosen["schedule"][boundary].candidate is None
    assert chosen["opening_candidates"][boundary + 1] is None
    assert chosen["schedule"][boundary].entry_submission_allowed


def test_observed_public_boundary_denies_legacy_requests_sources_tokens_and_flags(
    source, owned, monkeypatch
):
    from tests.unit.market_data.test_etf_capital_dataset import dataset
    from trading_bot.simulation import etf_capital_walk_forward as module

    value = request(source)
    monkeypatch.setattr(
        module,
        "_prepare_owned_capital_days",
        lambda *a, **k: pytest.fail("invalid input reached preparation"),
    )
    with pytest.raises(ValueError):
        module.replay_capital_walk_forward(value)
    with pytest.raises(ValueError):
        run(legacy_request(source))
    for invalid in (dataset(), owned, typed_prepared(owned)):
        with pytest.raises(ValueError):
            run(replace(value, dataset=invalid))
    object.__setattr__(value, "economic_admitted", True)
    with pytest.raises(ValueError):
        run(value)


def test_observed_private_boundary_denies_cross_variant_ownership(source, owned):
    from tests.unit.market_data.test_etf_capital_dataset import dataset
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.simulation.etf_capital_walk_forward import _walk_forward_inputs

    value = request(source)
    with pytest.raises(ValueError):
        _walk_forward_inputs(value, _own_capital_source(dataset()))
    with pytest.raises(ValueError):
        _walk_forward_inputs(legacy_request(source), owned)
