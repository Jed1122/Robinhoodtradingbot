"""Original-dataset trajectory controls; fabricated inputs, no qualification."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument
from tests.unit.research.test_etf_capital_prepared import long_source
from trading_bot.domain import InstrumentId
from trading_bot.research.etf_capital_signals import CapitalCandidate


@pytest.fixture(scope="module")
def source():
    return long_source(206)


def request(source, *, count=6, **changes):
    from trading_bot.simulation.etf_capital_trajectory import (
        CapitalTrajectoryDay,
        CapitalTrajectoryRequest,
    )

    sessions = source.calendar.sessions[199 : 199 + count]
    candidate = CapitalCandidate("momentum", 20, 100, 2)
    days = tuple(
        CapitalTrajectoryDay(
            s.session_date,
            candidate,
            index == 0,
            True,
            index == 0
            or s.opens_at.isocalendar()[:2] != sessions[index - 1].opens_at.isocalendar()[:2],
        )
        for index, s in enumerate(sessions)
    )
    terms = tuple(
        instrument(
            id=InstrumentId("fixture-" + symbol),
            symbol=symbol,
            observed_at=sessions[0].opens_at,
            price_increment=D(".000001"),
        )
        for symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF")
    )
    return replace(
        CapitalTrajectoryRequest(
            source, D(100), days, terms, D(".1"), D(".01"), D(".02"), D(".10")
        ),
        **changes,
    )


def run(value):
    from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory

    return replay_capital_trajectory(value)


def test_prior_close_cannot_trade_its_own_open(source):
    result = run(request(source, count=1))
    assert result.events == () and result.account.cash == D(100)
    assert result.points[0].policy.action == "entry"


def test_owned_next_open_size_and_adverse_price_have_literal_cash(source):
    result = run(request(source, count=2))
    assert result.account.quantity == D(".05")
    assert result.account.cash == D("84.9825")
    assert result.points[-1].equity == D("99.9825")
    assert result.account.fees == D(".01")
    assert result.points[-1].opening.stop_distance == 8
    assert result.points[-1].opening.symbol == "IEF"
    assert not result.account.complete


def test_owned_holding_exit_settlement_and_finality_are_not_end_forced(source):
    result = run(request(source, count=4))
    assert result.account.cash == D("100.05495")
    assert result.account.quantity == 0 and result.account.unsettled_proceeds == D("15.07245")
    assert result.account.complete is False
    complete = run(request(source))
    assert complete.account.cash == complete.account.available_cash == D("100.05495")
    assert complete.account.fees == D(".03") and complete.account.complete is True
    assert not complete.source_qualified and not complete.cost_qualified
    assert not complete.execution_enabled and not complete.economic_admitted
    assert not complete.evidence_promotable


def test_cash_selection_invalidates_unsubmitted_entry(source):
    value = request(source, count=2)
    days = (value.days[0], replace(value.days[1], candidate=None))
    result = run(replace(value, days=days))
    assert result.events == () and result.account.cash == 100
    assert result.points[-1].policy is None


def test_cash_to_candidate_still_waits_for_its_next_open(source):
    value = request(source, count=3)
    days = (
        replace(value.days[0], candidate=None),
        replace(value.days[1], entry_decision_allowed=True),
        value.days[2],
    )
    result = run(replace(value, days=days))
    assert result.points[0].policy is None
    assert result.points[1].account.quantity == 0
    assert result.account.quantity == D(".05")
    assert result.account.cash == D("84.932475")


def test_original_overnight_split_invalidates_pending_entry_without_fake_action(source):
    from tests.unit.config.test_capital_research import capital_loaded
    from trading_bot.market_data.etf_capital_actions import CapitalSplit
    from trading_bot.market_data.etf_capital_dataset import build_capital_dataset

    # Fabricated action and prices test invalidation only, not market evidence.
    day = source.calendar.sessions[200].session_date
    actions = (
        *source.actions[:4],
        replace(source.actions[4], splits=(CapitalSplit(day, D(2), "a" * 64),)),
    )
    changed = build_capital_dataset(
        loaded=capital_loaded(),
        archives=source.archives,
        actions=actions,
        calendar=source.calendar,
        start=source.start,
        end=source.end,
    )
    result = run(request(changed, count=2))
    assert result.points[0].policy.action == "entry"
    assert result.events == () and result.account.cash == 100


def test_new_selection_preserves_original_held_maximum_hold(source):
    value = request(source, count=4)
    replacement = CapitalCandidate("mean_reversion", 5, 0, 20)
    days = (*value.days[:2], *(replace(d, candidate=replacement) for d in value.days[2:]))
    result = run(replace(value, days=days))
    assert result.points[2].policy.reason == "maximum_hold"
    assert result.points[2].opening.candidate == value.days[0].candidate
    assert result.account.quantity == 0 and result.account.cash == D("100.05495")


@pytest.mark.parametrize("change", ("missing", "duplicate", "backward"))
def test_original_calendar_schedule_must_be_contiguous(source, change):
    value = request(source, count=3)
    days = {
        "missing": (value.days[0], value.days[2]),
        "duplicate": (value.days[0], value.days[0]),
        "backward": (value.days[1], value.days[0]),
    }[change]
    with pytest.raises(ValueError):
        run(replace(value, days=days))


@pytest.mark.parametrize(
    "outcome,fraction,quantity", (("unfilled", "0", "0"), ("partial", ".5", ".025"))
)
def test_incomplete_original_order_retains_obligations(source, outcome, fraction, quantity):
    result = run(
        request(source, entry_outcome=outcome, entry_fill_fraction=D(fraction), entry_fee=D(0))
    )
    assert result.account.quantity == D(quantity)
    assert result.account.complete is False
    assert result.account.available_cash < result.account.cash


def test_unknown_fee_bound_denies_rather_than_inventing_zero(source):
    result = run(request(source, count=2, episode_fee_bound=None))
    assert result.events == () and result.account.cash == 100


def test_absent_assumed_weekly_review_preserves_shared_gate(source):
    value = request(source, count=2)
    value = replace(value, days=tuple(replace(d, weekly_review_assumed=False) for d in value.days))
    result = run(value)
    assert result.events == () and result.account.cash == 100
    assert result.risk.points[-1].decision.reason_code == "weekly_reset_review_required"


def test_assumed_review_is_exact_boolean_and_identity_bound(source):
    value = request(source, count=1)
    without = replace(value, days=(replace(value.days[0], weekly_review_assumed=False),))
    assert run(value).input_hash != run(without).input_hash
    object.__setattr__(value.days[0], "weekly_review_assumed", 1)
    with pytest.raises(ValueError):
        run(value)


def test_next_week_absent_review_does_not_auto_approve_held_exit(source):
    value = request(source, count=4)
    days = (*value.days[:3], replace(value.days[3], weekly_review_assumed=False))
    result = run(replace(value, days=days))
    assert result.account.quantity == D(".05")
    assert result.account.cash == D("84.9825")
    assert result.risk.points[-1].decision.reason_code == "weekly_reset_review_required"


def test_legacy_public_owner_v5_literal_hashes_survive_shared_loop_extraction():
    from tests.unit.simulation.test_etf_capital_daily_owner import run as legacy_run

    result = legacy_run(4)
    assert result.input_hash == "ef1c9e2c9339d09b2a6885a5864c2fb43d5ae377a655a43b4ee336c8b05b5f4a"
    assert (
        result.account.economic_hash
        == "72bdfa38e01616283e9c9cf0698d424eb1f7863896f110bc6b7a2b9a8d1c44c7"
    )


def test_public_original_route_does_not_admit_prepared_or_saved_state(source):
    value = request(source, count=1)
    with pytest.raises(ValueError):
        run(replace(value, dataset=object()))
    with pytest.raises(ValueError):
        run(replace(value, instruments=(value.instruments[0],) * 5))
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError):
        run(value)


def test_owned_decimal_context_does_not_depend_on_ambient_precision(source):
    value = request(source, count=2)
    expected = run(value)
    with localcontext() as ctx:
        ctx.prec = 3
        assert run(value) == expected


def test_public_trajectory_validates_original_and_owned_copy_once_each(source, monkeypatch):
    from trading_bot.market_data import etf_capital_owned as module

    validate = module._validate_originals
    validated = []

    def record(original):
        validated.append(original)
        return validate(original)

    monkeypatch.setattr(module, "_validate_originals", record)
    result = run(request(source))
    assert result.account.cash == D("100.05495") and result.account.complete
    assert result.account.fees == D(".03")
    assert result.input_hash == "180d459ed3d3abddf44d6fa172c665b07a0f7d6687668844f58928e0bc6478a9"
    assert (
        result.account.economic_hash
        == "eb52ddad23b2ab35c99fe68473cfadb56299b0b5d5fea1b60c541cb21eb8e55a"
    )
    assert len(validated) == 2
    assert validated[0] is source and validated[1] is not source
    assert not result.source_qualified and not result.cost_qualified
    assert not result.execution_enabled and not result.evidence_promotable


@pytest.mark.parametrize("token", ("owned", "prepared"))
def test_public_trajectory_rejects_private_intermediate_source_tokens(source, token):
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.research.etf_capital_prepared import _prepare_capital_days

    value = request(source, count=1)
    invalid = (
        _own_capital_source(source)
        if token == "owned"
        else _prepare_capital_days(source, sessions=(value.days[0].session,))
    )
    with pytest.raises(ValueError, match="capital_trajectory_invalid"):
        run(replace(value, dataset=invalid))
