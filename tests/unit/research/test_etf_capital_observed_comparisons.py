"""Observed comparisons reuse real small-path kernels, never saved outcomes."""

from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_observed_prepared import observed_long_source
from tests.unit.simulation.test_etf_capital_observed_walk_forward import request as walk_request
from trading_bot.market_data.etf_capital_owned import _own_capital_observed_source
from trading_bot.research.etf_capital_prepared import _prepare_owned_capital_days


@pytest.fixture(scope="module")
def source():
    return observed_long_source(206)


@pytest.fixture(scope="module")
def owned(source):
    return _own_capital_observed_source(source)


def passive_request(owned):
    from trading_bot.research import etf_capital_passive as module

    cls = getattr(module, "_CapitalObservedPassiveRequest", None)
    assert cls is not None, "observed passive input is missing"
    dates = tuple(s.session_date for s in owned.dataset.calendar.sessions)
    return cls(owned.dataset, D(100), dates[200:203], D(".10"), D(".01"), D(".02"))


def test_observed_passive_uses_only_selected_raw_values_and_legacy_public_stays_closed(owned):
    from trading_bot.research import etf_capital_passive as module

    request = passive_request(owned)
    kernel, quantities, baseline = module._capital_passive_values(owned, request)
    assert baseline == owned.dataset.calendar.sessions[199].session_date
    assert len(kernel.points) == len(quantities) == 3
    assert kernel.shares == (D(100) - D(".01")) / (D(300) * D("1.0005"))
    assert quantities == (kernel.shares,) * 3
    with pytest.raises(ValueError):
        module.run_capital_passive_reference(request)
    old = module.CapitalPassiveRequest(
        request.dataset,
        request.initial_cash,
        request.sessions,
        request.roundtrip_friction_pct,
        request.entry_fee,
        request.estimated_exit_fee,
    )
    with pytest.raises(ValueError):
        module._capital_passive_values(owned, old)


def test_observed_real_constrained_and_matched_share_engine_without_legacy_request_coercion(owned):
    from trading_bot.config.loader import restore_loaded_config
    from trading_bot.research.etf_capital_matched import (
        _capital_matched_values,
        _CapitalMatchedTerms,
    )
    from trading_bot.research.etf_capital_signals import capital_candidates
    from trading_bot.simulation import etf_capital_constrained as constrained
    from trading_bot.simulation.etf_capital_daily_owner import _CapitalOwnerTerms
    from trading_bot.simulation.etf_capital_trajectory import (
        CapitalTrajectoryDay,
        _replay_prepared_capital_trajectory,
    )

    cls = getattr(constrained, "_CapitalObservedConstrainedRequest", None)
    assert cls is not None, "observed constrained input is missing"
    source = owned.dataset
    dates = tuple(s.session_date for s in source.calendar.sessions)[199:206]
    prepared = _prepare_owned_capital_days(owned, sessions=dates)
    walk = walk_request(source)
    schedule = tuple(
        constrained.CapitalConstrainedDay(d, i < 2, i < 3, True) for i, d in enumerate(dates)
    )
    request = cls(source, D(100), schedule, walk.instruments, D(".1"), D(".01"), D(".02"), D(".10"))
    managed = constrained._replay_owned_capital_constrained(request, owned=owned, prepared=prepared)
    assert len(managed.points) == 7
    assert managed.points[0].account.quantity == 0
    assert managed.points[1].account.quantity > 0
    assert managed.execution_enabled is False
    with pytest.raises(ValueError):
        constrained.replay_capital_constrained(request)
    old = constrained.CapitalConstrainedRequest(
        source, D(100), schedule, walk.instruments, D(".1"), D(".01"), D(".02"), D(".10")
    )
    with pytest.raises(ValueError):
        constrained._replay_owned_capital_constrained(old, owned=owned, prepared=prepared)
    terms = _CapitalOwnerTerms(
        restore_loaded_config(source.canonical_config, source.config_hash),
        D(100),
        D(".1"),
        D(".01"),
        D(".02"),
        D(".10"),
        source.calendar,
        "filled",
        D(1),
        "filled",
        D(1),
    )
    candidate = capital_candidates()[0]
    frames = tuple(
        CapitalTrajectoryDay(d, candidate, i == 0, i < 2, True) for i, d in enumerate(dates)
    )
    result = _replay_prepared_capital_trajectory(
        source=source,
        source_hash=owned.source_hash,
        prepared=prepared,
        terms=terms,
        instruments=walk.instruments,
        schedule=frames,
    )
    matched = _capital_matched_values(
        owned, _CapitalMatchedTerms(D(100), D(".10"), D(".01"), D(".02")), result, dates[1:4]
    )
    assert matched.baseline_session == dates[0] and matched.session_dates == dates[1:4]
    assert len(matched.close_exposures) == 3 and D(0) <= matched.mean_exposure <= D(1)
    assert matched.source_hash == owned.source_hash and matched.evidence_promotable is False
