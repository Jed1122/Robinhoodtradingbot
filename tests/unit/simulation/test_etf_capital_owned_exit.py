"""Owner-private facts preserve public execution/risk semantics, not authority."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.simulation.test_etf_capital_daily_exit import AT, exit_request
from tests.unit.simulation.test_etf_capital_daily_owner import run
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation import etf_capital_daily_exit as exits
from trading_bot.simulation import etf_capital_risk as risk
from trading_bot.simulation.events import EventCursor


def value(outcome="filled"):
    from datetime import timedelta

    changes = {"outcome": outcome}
    if outcome in ("rejected", "unfilled"):
        changes.update(
            fill_fraction=D(0),
            side_fee=D(0),
            lifecycle_cursors=(EventCursor(7, AT + timedelta(seconds=1)),),
        )
    elif outcome == "partial":
        changes["fill_fraction"] = D(".5")
    return exit_request(**changes)


def facts_tuple(result):
    return (
        result.assumed_price,
        result.events,
        result.observations,
        result.account,
        result.input_hash,
    )


@pytest.mark.parametrize("outcome", ["filled", "partial", "rejected", "unfilled"])
def test_owned_exit_facts_equal_complete_public_fields(outcome):
    request = value(outcome)
    expected = exits.simulate_capital_daily_exit(request)
    with localcontext() as context:
        context.prec = 3
        actual = exits._simulate_owned_capital_daily_exit(request, progress=risk._RiskProgress())
    assert facts_tuple(actual) == facts_tuple(expected)
    assert not actual.source_qualified and not actual.cost_qualified
    assert not actual.execution_enabled and not actual.economic_admitted
    assert not actual.evidence_promotable


def test_owned_exit_validates_both_original_and_generated_tapes_without_full_hash(monkeypatch):
    request = value()
    expected = exits.simulate_capital_daily_exit(request)
    original = risk._replay_risk_points
    rendered = []
    frontiers = []
    progress = risk._RiskProgress()

    def points(**kwargs):
        frontiers.append((len(kwargs["events"]), kwargs["_last_only"], kwargs["_progress"]))
        return original(**kwargs)

    real_render = risk._risk_result

    def render(*args, **kwargs):
        rendered.append(1)
        return real_render(*args, **kwargs)

    monkeypatch.setattr(exits, "_replay_risk_points", points, raising=False)
    monkeypatch.setattr(risk, "_risk_result", render)
    actual = exits._simulate_owned_capital_daily_exit(request, progress=progress)
    assert facts_tuple(actual) == facts_tuple(expected)
    assert frontiers == [(3, True, progress), (6, True, progress)]
    assert rendered == []


def test_owned_exit_rejects_invalid_generated_suffix(monkeypatch):
    request = value()
    original = exits._generate_capital_daily_exit

    def invalid_suffix(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(
            result,
            observations=(
                *result.observations[:-1],
                replace(result.observations[-1], source_count=len(result.events) + 1),
            ),
        )

    monkeypatch.setattr(exits, "_generate_capital_daily_exit", invalid_suffix)
    progress = risk._RiskProgress()
    with pytest.raises(ValueError):
        exits._simulate_owned_capital_daily_exit(request, progress=progress)
    monkeypatch.setattr(exits, "_generate_capital_daily_exit", original)
    actual = exits._simulate_owned_capital_daily_exit(request, progress=progress)
    assert facts_tuple(actual) == facts_tuple(exits.simulate_capital_daily_exit(request))


def test_owned_exit_rejects_conflicting_original_before_generating_facts(monkeypatch):
    request = value()
    fill = request.events[-1]
    request = replace(
        request,
        events=(*request.events, replace(fill, fill=replace(fill.fill, price=D(99)))),
        observations=(
            *request.observations[:-1],
            replace(request.observations[-1], source_count=4),
        ),
    )
    original = exits._generate_capital_daily_exit
    generated = []

    def generate(*args, **kwargs):
        generated.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(exits, "_generate_capital_daily_exit", generate)
    with pytest.raises(ValueError):
        exits._simulate_owned_capital_daily_exit(request, progress=risk._RiskProgress())
    assert generated == []


def test_mutating_returned_facts_cannot_poison_original_risk_continuation():
    request = value()
    expected = exits.simulate_capital_daily_exit(request)
    progress = risk._RiskProgress()
    actual = exits._simulate_owned_capital_daily_exit(request, progress=progress)
    object.__setattr__(actual.account, "cash", D(999))
    repeated = exits._simulate_owned_capital_daily_exit(request, progress=progress)
    assert facts_tuple(repeated) == facts_tuple(expected)


@pytest.mark.parametrize("progress", [None, False, {}])
def test_private_progress_is_never_a_caller_account_or_untyped_token(progress):
    with pytest.raises(ValueError):
        exits._simulate_owned_capital_daily_exit(value(), progress=progress)


@pytest.mark.parametrize("outcome", ["filled", "partial", "rejected", "unfilled"])
def test_owned_exit_keeps_unpaid_distribution_outside_spendable_cash(outcome):
    from datetime import timedelta

    from trading_bot.simulation.etf_capital_action_events import CapitalDistributionEntitled

    request = value(outcome)
    opening = request.events[0].request.order
    action_at = AT - timedelta(seconds=5)
    entitlement = CapitalDistributionEntitled(
        "receivable",
        EventCursor(5, action_at),
        opening.account_id,
        opening.id,
        "SPY",
        "distribution",
        "e" * 64,
        D(1),
        D(99),
        AT.date() + timedelta(days=2),
    )
    request = replace(
        request,
        events=(*request.events, entitlement),
        observations=(
            *request.observations[:-1],
            risk.CapitalRiskObservation(EventCursor(6, action_at), 4, None, False, False),
            replace(request.observations[-1], cursor=EventCursor(7, AT), source_count=4),
        ),
        submitted=EventCursor(8, AT),
        lifecycle_cursors=tuple(
            replace(cursor, sequence=cursor.sequence + 2) for cursor in request.lifecycle_cursors
        ),
    )
    expected = exits.simulate_capital_daily_exit(request)
    actual = exits._simulate_owned_capital_daily_exit(request, progress=risk._RiskProgress())
    assert facts_tuple(actual) == facts_tuple(expected)
    assert actual.account.distribution_receivable == D(".199")
    assert not actual.account.complete
    assert actual.account.available_cash <= actual.account.cash


@pytest.mark.parametrize(
    "changes,expected_hash",
    [
        ({}, "53b36d68811a0d2e14a8177b26e73a066f9268318f253e7ffd5374eaba336a32"),
        (
            {"exit_outcome": "partial", "exit_fill_fraction": D(".5")},
            "cd3e8eaa25d5f3eb22044c07fc79123b0e71f8a09b1694a7bc9695053e4b1e7a",
        ),
        (
            {"exit_outcome": "rejected", "exit_fill_fraction": D(0), "exit_fee": D(0)},
            "708b1fbe949b977712b25f362cdf052e1c448f0b1ff164ca957cec031aa80f33",
        ),
        (
            {"exit_outcome": "unfilled", "exit_fill_fraction": D(0), "exit_fee": D(0)},
            "6bdcec9245b9a3e9a87ddeb21c96dd1c82d696a08819a42cdc6946c4a8f1c525",
        ),
    ],
)
def test_owner_avoids_public_exit_graph_and_preserves_parent_result(
    changes, expected_hash, monkeypatch
):
    from trading_bot.simulation import etf_capital_daily_owner as owner

    public_calls = []
    original = exits.simulate_capital_daily_exit

    def public(request):
        public_calls.append(1)
        return original(request)

    monkeypatch.setattr(owner, "simulate_capital_daily_exit", public, raising=False)
    result = run(**changes)
    assert content_hash(result) == expected_hash
    assert not result.account.complete
    assert result.account.fees == (
        D(".01") if changes.get("exit_outcome") in ("rejected", "unfilled") else D(".03")
    )
    assert public_calls == []
    from tests.unit.research.test_etf_capital_feasibility import loaded

    assert result.risk == risk.replay_capital_action_risk(
        loaded=loaded(),
        initial_cash=D(100),
        events=result.events,
        observations=result.observations,
    )
