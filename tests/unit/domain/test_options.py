"""Options identity and financial boundaries; all contracts are synthetic."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.enums import Side
from trading_bot.domain.options import (
    ExerciseStyle,
    OptionContract,
    OptionKind,
    OptionLeg,
    OptionQuote,
    OptionSession,
    OptionsOrderIntent,
    OptionStructure,
    PositionEffect,
    SettlementKind,
    SettlementTiming,
    StructureKind,
    executable_quote_reasons,
)
from trading_bot.domain.options_serialization import (
    canonical_options_intent_payload,
    options_intent_from_payload,
    options_intent_sha256,
)

D = Decimal
NOW = datetime(2026, 9, 18, 15, tzinfo=UTC)


def contract(**changes: object) -> OptionContract:
    original = OptionContract(
        contract_id="synthetic-call-100",
        standardized_id="SYN261016C00100000",
        underlying="SYN",
        kind=OptionKind.CALL,
        strike=D("100"),
        expiration=date(2026, 10, 16),
        last_trading_at=datetime(2026, 10, 16, 20, tzinfo=UTC),
        settlement_at=datetime(2026, 10, 19, 20, tzinfo=UTC),
        exercise_style=ExerciseStyle.AMERICAN,
        settlement_kind=SettlementKind.SHARES,
        settlement_timing=SettlementTiming.PM,
        premium_multiplier=D("100"),
        deliverable_units=D("100"),
        deliverable_symbol="SYN",
        adjusted=False,
        tick_size=D("0.01"),
        eligible_sessions=(
            OptionSession(
                "SYN-2026-09-18",
                NOW,
                NOW + timedelta(hours=5),
                date(2026, 9, 18),
                "America/New_York",
            ),
        ),
        available_at=NOW - timedelta(days=1),
        data_hash="a" * 64,
        currency="USD",
    )
    return replace(original, **changes)


def intent() -> OptionsOrderIntent:
    return OptionsOrderIntent(
        intent_id="synthetic-intent-1",
        account_scope="synthetic-research",
        structure=OptionStructure(
            StructureKind.LONG_CALL,
            (OptionLeg(contract(), Side.BUY, PositionEffect.OPEN, 1),),
        ),
        quantity=1,
        limit_price=D("0.25"),
        net_effect="debit",
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        strategy_version="unvalidated-momentum-20-100-v1",
        config_hash="b" * 64,
        data_hash="c" * 64,
        exit_policy_version="synthetic-exit-v1",
        order_type="limit",
        time_in_force="day",
    )


def quote(**changes: object) -> OptionQuote:
    return replace(
        OptionQuote(
            "synthetic-call-100",
            D("0.20"),
            D("0.25"),
            1,
            1,
            NOW,
            NOW,
            NOW,
            "synthetic",
            "d" * 64,
            (),
            "SYN",
        ),
        **changes,
    )


def test_records_are_frozen_and_complete_units_are_not_fractional() -> None:
    with pytest.raises(FrozenInstanceError):
        intent().quantity = 2  # type: ignore[misc]
    for bad in (True, 0, -1, D("1"), 1.0):
        with pytest.raises(DomainValidationError):
            replace(intent(), quantity=bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"adjusted": True},
        {"premium_multiplier": D("NaN")},
        {"strike": 100.0},
        {"deliverable_units": D("50")},
        {"deliverable_symbol": "OTHER"},
        {"eligible_sessions": ()},
        {"last_trading_at": datetime(2026, 10, 16, 20)},
        {"settlement_at": NOW},
        {"data_hash": "invalid"},
        {"kind": "call"},
        {"expiration": NOW},
    ],
)
def test_contract_rejects_unsupported_or_incomplete_identity(changes: dict[str, object]) -> None:
    with pytest.raises((DomainValidationError, ValueError)):
        contract(**changes)


def test_zero_bid_is_observation_but_not_executable_entry() -> None:
    observed = quote(bid=D("0"))
    assert observed.bid == 0
    assert executable_quote_reasons(
        contract(),
        observed,
        as_of=NOW,
        max_age_seconds=D("5"),
        max_underlying_skew_seconds=D("2"),
        allow_locked=False,
    ) == ("zero_bid",)


def test_contract_currency_and_order_semantics_are_not_inferred() -> None:
    assert contract().currency == "USD"
    assert intent().order_type == "limit"
    assert intent().time_in_force == "day"
    with pytest.raises(DomainValidationError):
        contract(currency="EUR")
    with pytest.raises(DomainValidationError):
        replace(intent(), order_type="market")
    with pytest.raises(DomainValidationError):
        replace(intent(), time_in_force="gtc")


def test_session_identity_and_underlying_are_explicit() -> None:
    session = contract().eligible_sessions[0]
    with pytest.raises(DomainValidationError):
        replace(session, exchange_timezone="made-up")
    with pytest.raises(DomainValidationError):
        replace(session, trading_date=NOW)
    assert "underlying_mismatch" in executable_quote_reasons(
        contract(),
        quote(underlying="OTHER"),
        as_of=NOW,
        max_age_seconds=D("5"),
        max_underlying_skew_seconds=D("2"),
        allow_locked=False,
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"bid": D("0.25")}, "locked_quote"),
        ({"ask_size": None}, "missing_depth"),
        ({"ask_size": 0}, "empty_depth"),
        ({"event_at": NOW - timedelta(seconds=6)}, "stale_quote"),
        ({"received_at": NOW + timedelta(seconds=1)}, "future_observation"),
        ({"underlying_event_at": NOW - timedelta(seconds=3)}, "underlying_skew"),
        ({"contract_id": "different"}, "contract_mismatch"),
        ({"quality_flags": ("delayed",)}, "quality_flags"),
        ({"ask": D("0.251")}, "off_tick"),
    ],
)
def test_execution_quality_is_explicit(changes: dict[str, object], reason: str) -> None:
    assert reason in executable_quote_reasons(
        contract(),
        quote(**changes),
        as_of=NOW,
        max_age_seconds=D("5"),
        max_underlying_skew_seconds=D("2"),
        allow_locked=False,
    )


def test_locked_quotes_require_explicit_policy_and_crossed_are_invalid() -> None:
    assert not executable_quote_reasons(
        contract(),
        quote(bid=D("0.25")),
        as_of=NOW,
        max_age_seconds=D("5"),
        max_underlying_skew_seconds=D("2"),
        allow_locked=True,
    )
    with pytest.raises(DomainValidationError):
        quote(bid=D("0.26"))


def test_spread_sides_are_explicit_and_naked_or_mismatched_legs_are_rejected() -> None:
    low = contract()
    high = contract(
        contract_id="synthetic-call-105", standardized_id="SYN261016C00105000", strike=D("105")
    )
    legs = (
        OptionLeg(low, Side.BUY, PositionEffect.OPEN, 1),
        OptionLeg(high, Side.SELL, PositionEffect.OPEN, 1),
    )
    assert OptionStructure(StructureKind.DEBIT_VERTICAL, legs).legs == legs
    with pytest.raises(DomainValidationError):
        OptionStructure(StructureKind.LONG_CALL, (legs[1],))
    with pytest.raises(DomainValidationError):
        OptionStructure(StructureKind.DEBIT_VERTICAL, (legs[0], replace(legs[1], ratio=2)))
    with pytest.raises(DomainValidationError):
        OptionStructure(
            StructureKind.DEBIT_VERTICAL,
            (legs[0], replace(legs[1], contract=replace(high, expiration=date(2026, 10, 17)))),
        )
    closed = tuple(
        replace(
            leg, effect=PositionEffect.CLOSE, side=Side.SELL if leg.side is Side.BUY else Side.BUY
        )
        for leg in legs
    )
    assert OptionStructure(StructureKind.DEBIT_VERTICAL, closed).legs == closed


def test_serialization_is_versioned_exact_roundtrip_and_rejects_unknown_fields() -> None:
    original = intent()
    payload = canonical_options_intent_payload(original)
    assert payload["schema"] == "options-order-intent-v1"
    assert payload["quantity"] == 1
    assert payload["limit_price"] == "0.25"
    assert options_intent_from_payload(payload) == original
    assert options_intent_sha256(replace(original, limit_price=D("0.250"))) == (
        options_intent_sha256(original)
    )
    assert options_intent_sha256(replace(original, quantity=2)) != options_intent_sha256(original)
    for corrupted in (
        {**payload, "schema": "options-order-intent-v2"},
        {**payload, "quantity": True},
        {**payload, "limit_price": 0.25},
        {**payload, "unexpected": "ignored?"},
    ):
        with pytest.raises(DomainValidationError):
            options_intent_from_payload(corrupted)


def test_bounded_large_decimals_do_not_depend_on_ambient_decimal_precision() -> None:
    large = D("1" + "0" * 100)
    original = replace(intent(), limit_price=large)
    assert options_intent_from_payload(canonical_options_intent_payload(original)) == original
    assert "off_tick" not in executable_quote_reasons(
        contract(),
        quote(bid=large, ask=large),
        as_of=NOW,
        max_age_seconds=D("5"),
        max_underlying_skew_seconds=D("2"),
        allow_locked=True,
    )


def test_day_intent_cannot_outlive_its_specific_session() -> None:
    with pytest.raises(DomainValidationError):
        replace(intent(), expires_at=NOW + timedelta(hours=6))
    with pytest.raises(DomainValidationError):
        replace(contract().eligible_sessions[0], trading_date=date(2026, 9, 19))


@pytest.mark.parametrize(
    "changes",
    [
        {"limit_price": D("0.255")},
        {"net_effect": "credit"},
        {"expires_at": NOW},
        {"created_at": NOW - timedelta(days=2)},
        {"config_hash": "bad"},
        {"exit_policy_version": ""},
    ],
)
def test_intents_reject_invalid_price_effect_or_identity(changes: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        replace(intent(), **changes)
