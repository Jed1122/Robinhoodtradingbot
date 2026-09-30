"""Strict replay contracts bind synthetic values, not production permissions."""

import warnings
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.market_data._bundle_fixtures import ID
from trading_bot.domain import AssetClass, InstrumentId, TimestampSource
from trading_bot.simulation.configured_models import SyntheticBarWindow
from trading_bot.simulation.equity_replay_codec import encode_order_outcome, replay_identity
from trading_bot.simulation.equity_replay_models import (
    ReplayCandidate,
    ReplayDecision,
    ReplayOrderOutcome,
    ReplaySession,
    ReplayValidationError,
)
from trading_bot.simulation.events import EventCursor

from ._equity_replay_fixtures import LATER, NOW, STOP, loaded, market, request


class Hostile:
    def __str__(self):
        raise AssertionError("must not stringify unknown input")

    def __repr__(self):
        raise AssertionError("must not represent unknown input")


def test_request_detaches_config_and_derives_only_a_synthetic_account():
    original = loaded()
    value = request(loaded=original)
    assert value.loaded == original
    assert value.loaded is not original
    assert value.loaded.config is not original.config
    assert value.account_id == "synthetic:equity-fixture"
    assert value.source_kind == "synthetic-equity-replay-v1"
    for name in ("assumptions_validated", "evidence_promotable", "production_pretrade_eligible"):
        assert getattr(value, name) is False
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, True)
        with pytest.raises((TypeError, ValueError), match="init=False"):
            replace(value, **{name: True})
        assert getattr(value, name) is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace", "account-real"),
        ("namespace", Hostile()),
        ("seed", True),
        ("seed", -1),
        ("loaded", Hostile()),
        ("candidate", Hostile()),
        ("bundle", Hostile()),
        ("snapshot_settings", Hostile()),
        ("instruments", []),
        ("sessions", []),
        ("decisions", []),
        ("markets", []),
        ("initial_cash", D(-1)),
        ("initial_cash", D("NaN")),
        ("initial_cash", 100),
        ("starts_at", NOW.replace(tzinfo=None)),
        ("starts_at", NOW.astimezone(timezone(timedelta(hours=1)))),
        ("end_at", NOW - timedelta(seconds=1)),
    ],
)
def test_bad_request_types_and_values_are_sanitized(field, value):
    with pytest.raises(ReplayValidationError, match=r"^replay_[a-z_]+$"):
        request(**{field: value})


@pytest.mark.parametrize("mode", ["paper", "backtest", "micro_live", "normal_live"])
def test_only_simulation_configuration_is_accepted(mode):
    with pytest.raises(ReplayValidationError):
        request(loaded=loaded(mode))


def test_config_identity_and_enabled_flags_are_revalidated():
    original = loaded()
    for corrupt in (
        replace(original, config_hash="f" * 64),
        replace(original, canonical_json=b"{}"),
        replace(original, config=original.config.model_copy(update={"live_trading_enabled": True})),
        replace(
            original,
            config=original.config.model_copy(
                update={
                    "simulation": original.config.simulation.model_copy(
                        update={"evidence_promotable": True}
                    )
                }
            ),
        ),
    ):
        with pytest.raises(ReplayValidationError):
            request(loaded=corrupt)


@pytest.mark.parametrize(
    "changes",
    [
        {"strategy_id": "arbitrary"},
        {"short_window": 21},
        {"long_window": 101},
        {"top_n": 1},
        {"exposure_multiplier": D("0.1")},
    ],
)
def test_candidate_must_belong_to_canonical_grid(changes):
    with pytest.raises(ReplayValidationError):
        request(candidate=replace(request().candidate, **changes))


def test_relative_strength_uses_configured_top_n():
    candidate = ReplayCandidate("equity_relative_strength", 20, 100, 2, D(1))
    assert request(candidate=candidate).candidate == candidate
    with pytest.raises(ReplayValidationError):
        request(candidate=replace(candidate, top_n=3))


def test_history_requirement_cannot_be_lowered():
    value = request()
    with pytest.raises(ReplayValidationError):
        replace(value, snapshot_settings=replace(value.snapshot_settings, minimum_bars=2))


def test_duplicate_instrument_unknown_session_and_non_equity_deny():
    value = request()
    for instruments in (
        value.instruments * 2,
        (replace(value.instruments[0], asset_class=AssetClass.CRYPTO),),
        (replace(value.instruments[0], observed_at=LATER),),
        (replace(value.instruments[0], symbol="OTHER"),),
    ):
        with pytest.raises(ReplayValidationError):
            replace(value, instruments=instruments)
    with pytest.raises(ReplayValidationError):
        replace(
            value, sessions=(replace(value.sessions[0], instrument_id=InstrumentId("unknown")),)
        )


@pytest.mark.parametrize("times", [(LATER, LATER), (STOP,), (NOW - timedelta(seconds=1),)])
def test_session_slots_are_unique_ordered_and_inside_window(times):
    with pytest.raises(ReplayValidationError):
        ReplaySession(ID, SyntheticBarWindow(NOW, STOP), times)


def test_undeclared_duplicate_slot_and_overlapping_session_deny():
    value = request()
    with pytest.raises(ReplayValidationError):
        replace(value, sessions=(replace(value.sessions[0], opportunity_times=()),))
    with pytest.raises(ReplayValidationError):
        replace(value, sessions=value.sessions * 2)
    with pytest.raises(ReplayValidationError):
        replace(value, markets=(market(), market("another", 3)))


def test_conflicting_redelivery_and_non_synthetic_timestamp_deny():
    value = request()
    with pytest.raises(ReplayValidationError):
        replace(value, markets=(market(), replace(market(), available_quantity=D(5))))
    bad = replace(
        market(), quote=replace(market().quote, timestamp_source=TimestampSource.PROVIDER)
    )
    with pytest.raises(ReplayValidationError):
        replace(value, markets=(bad,))


def test_duplicate_delivery_changes_receipts_not_economic_identity():
    value = request()
    duplicate = replace(value, markets=value.markets * 2)
    normal_hashes = replay_identity(value)
    duplicate_hashes = replay_identity(duplicate)
    assert normal_hashes.input_hash == duplicate_hashes.input_hash
    assert normal_hashes.delivery_hash != duplicate_hashes.delivery_hash
    assert normal_hashes.run_key == duplicate_hashes.run_key


def test_future_delivery_changes_audit_hash_not_stable_run_key():
    extra_at = LATER + timedelta(seconds=2)
    original = request(
        sessions=(ReplaySession(ID, SyntheticBarWindow(NOW, STOP), (LATER, extra_at)),)
    )
    extended = replace(original, markets=(*original.markets, market("later", 3, extra_at)))
    assert replay_identity(original).run_key == replay_identity(extended).run_key
    assert replay_identity(original).input_hash != replay_identity(extended).input_hash


def test_identity_does_not_depend_on_ambient_decimal_precision():
    value = request(initial_cash=D("1234.56789"))
    normal = replay_identity(value)
    with localcontext() as context:
        context.prec = 2
        assert replay_identity(value) == normal


def test_decision_time_order_and_cross_stream_sequence_collisions_deny():
    value = request()
    for decisions in (
        value.decisions * 2,
        (ReplayDecision("decision-2", EventCursor(2, NOW)),),
        (ReplayDecision("decision-2", EventCursor(1, NOW - timedelta(seconds=1))),),
        (ReplayDecision("quote-1", EventCursor(1, NOW)),),
    ):
        with pytest.raises(ReplayValidationError):
            replace(value, decisions=decisions)


def test_outcome_encoding_is_closed_and_does_not_stringify_unknown_objects():
    outcome = ReplayOrderOutcome("intent-1", True, ("reserved",), "order-1")
    assert encode_order_outcome(outcome) == {
        "source_kind": "synthetic-equity-replay-v1",
        "intent_id": "intent-1",
        "accepted": True,
        "reasons": ("reserved",),
        "order_id": "order-1",
    }
    with pytest.raises(ReplayValidationError):
        encode_order_outcome(Hostile())
    with pytest.raises(ReplayValidationError):
        replace(outcome, accepted=False)
    with pytest.raises(ReplayValidationError):
        replace(outcome, reasons=(Hostile(),))


def test_unknown_nested_configuration_is_rejected_before_pydantic_serialization():
    original = loaded()
    for field, value in (("simulation", Hostile()), ("mode", Hostile())):
        corrupt = replace(original, config=original.config.model_copy(update={field: value}))
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            with pytest.raises(ReplayValidationError):
                request(loaded=corrupt)
        assert not emitted, "unknown input must not reach serializer warning text"
