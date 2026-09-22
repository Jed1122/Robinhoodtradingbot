"""Optional replay inputs preserve sizing and reject ambiguous exit-policy ownership."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from tests.integration.simulation.test_decision_cycle import NOW, request
from tests.unit.risk.test_sizing import instrument, settings
from trading_bot.domain import (
    AssetClass,
    ConfigHash,
    DataHash,
    DomainValidationError,
    InstrumentId,
    OrderIntentId,
    Position,
    Side,
)
from trading_bot.portfolio import ExitPolicy, IntentPlanner, PortfolioConstructor, TargetPosition
from trading_bot.strategies import StrategyAction, StrategyDecision

ID = InstrumentId("synthetic-equity")
OTHER = InstrumentId("synthetic-other")
POLICY = ExitPolicy("exit-v1", "atr", D(1), D(2), 10)


def decision(identifier=ID, action=StrategyAction.ENTER_LONG):
    return StrategyDecision(
        identifier,
        NOW,
        action,
        D(1),
        ("synthetic",),
        "candidate-v1",
        ConfigHash("c" * 64),
        DataHash("d" * 64),
    )


def construct(decisions=None, **policies):
    return PortfolioConstructor().construct(
        (decision(),) if decisions is None else decisions,
        request().portfolio,
        as_of=NOW,
        config_hash=ConfigHash("c" * 64),
        exposure_multiplier=D("0.5"),
        **policies,
    )


def planning():
    config = settings()
    original = request().intent_context
    return replace(
        original,
        instruments=(instrument(id=ID, asset_class=AssetClass.EQUITY),),
        prices=((ID, D(10)),),
        position_risk=config.position_risk,
        activity=config.activity,
    )


def test_injected_ids_reach_both_buy_and_sell_without_changing_sizing():
    ids = iter((OrderIntentId("replay-buy"), OrderIntentId("replay-sell")))
    planner = IntentPlanner(id_factory=lambda: next(ids))
    target = construct(exit_policy=POLICY)
    context = planning()
    buy = planner.plan(target, context)[0]
    legacy = IntentPlanner().plan(target, context)[0]
    assert buy.id == "replay-buy"
    assert buy.side is Side.BUY
    assert replace(buy, id=legacy.id) == legacy
    position = Position(
        context.account_id,
        ID,
        AssetClass.EQUITY,
        D("0.2"),
        D(10),
        D(2),
        NOW,
        DataHash("e" * 64),
    )
    held = replace(context, portfolio=replace(context.portfolio, positions=(position,)))
    exit_target = replace(target, positions=(TargetPosition(ID, D(0), None, "candidate-v1"),))
    sell = planner.plan(exit_target, held)[0]
    assert sell.id == "replay-sell"
    assert sell.side is Side.SELL
    assert sell.quantity == D("0.2")


def test_injected_factory_is_not_called_for_denied_averaging_down():
    def forbidden():
        raise AssertionError("denied entry must not consume an intent ID")

    context = planning()
    position = Position(
        context.account_id,
        ID,
        AssetClass.EQUITY,
        D("0.2"),
        D(10),
        D(2),
        NOW,
        DataHash("e" * 64),
    )
    held = replace(context, portfolio=replace(context.portfolio, positions=(position,)))
    assert IntentPlanner(id_factory=forbidden).plan(construct(exit_policy=POLICY), held) == ()


def test_per_instrument_policies_preserve_target_allocations():
    other_policy = replace(POLICY, stop_distance_per_unit=D(3), version="exit-other")
    target = construct(
        (decision(), decision(OTHER)),
        exit_policy=None,
        exit_policies=((OTHER, other_policy), (ID, POLICY)),
    )
    by_id = {item.instrument_id: item for item in target.positions}
    assert by_id[ID].exit_policy == POLICY
    assert by_id[OTHER].exit_policy == other_policy
    assert by_id[ID].target_notional == by_id[OTHER].target_notional == D(25)
    assert target.cash_target == D(50)


def test_one_per_instrument_policy_preserves_legacy_target_hash():
    assert construct(exit_policy=None, exit_policies=((ID, POLICY),)) == construct(
        exit_policy=POLICY
    )


@pytest.mark.parametrize(
    "policies",
    [
        {},
        {"exit_policy": None},
        {"exit_policy": POLICY, "exit_policies": ((ID, POLICY),)},
        {"exit_policy": None, "exit_policies": ((ID, POLICY), (ID, POLICY))},
        {"exit_policy": None, "exit_policies": ((OTHER, POLICY),)},
        {"exit_policy": None, "exit_policies": ((ID, object()),)},
        {"exit_policy": None, "exit_policies": [(ID, POLICY)]},
    ],
)
def test_ambiguous_missing_or_malformed_policy_map_is_rejected(policies):
    with pytest.raises(DomainValidationError):
        construct(**policies)


def test_exit_only_targets_do_not_require_an_entry_policy():
    target = construct(
        (decision(action=StrategyAction.EXIT_LONG),), exit_policy=None, exit_policies=()
    )
    assert target.positions[0].target_notional == 0
    assert target.positions[0].exit_policy is None
