"""Short fictional mandate/price-PnL tests, never brokerage or historical factories."""

import importlib
import importlib.util
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

D = Decimal
MODULE = "trading_bot.portfolio.stock_holding"
PIN = "a" * 64


def api():
    assert importlib.util.find_spec(MODULE) is not None, "pure stock holding helper is missing"
    return importlib.import_module(MODULE)


def mandate(*, first=None, sleeve="tactical"):
    return api().StockHoldingMandate(
        "episode-1",
        "instrument-1",
        "AXP",
        sleeve,
        first or datetime(2025, 1, 31, 15, 30, tzinfo=UTC),
        PIN,
    )


def lot(*, quantity="8", basis="800"):
    m = mandate()
    return api().StockHoldingLot(
        "lot-1",
        m.episode_id,
        m.instrument_id,
        "AXP",
        D(quantity),
        D(basis),
        m.first_fill_at,
        "b" * 64,
    )


def price(*, value="120", at=None):
    stamp = at or datetime(2025, 2, 28, 21, tzinfo=UTC)
    return api().StockHoldingPrice("instrument-1", "AXP", D(value), stamp, stamp, "c" * 64)


def gain():
    return api().StockRealizedPriceGain(
        "fill-sale-1",
        "episode-1",
        "instrument-1",
        "AXP",
        D(39),
        datetime(2025, 2, 15, 15, tzinfo=UTC),
        "d" * 64,
    )


def costs(*, bps="50", fee="1"):
    return api().StockSaleCostAssumptions(D(bps), D(fee), "e" * 64)


@pytest.mark.parametrize(
    ("year", "one", "two"),
    [(2025, date(2025, 2, 28), date(2025, 3, 31)), (2024, date(2024, 2, 29), date(2024, 3, 31))],
)
def test_anniversaries_clamp_independently_from_original_first_fill_date(year, one, two):
    actual = api().holding_anniversaries(mandate(first=datetime(year, 1, 31, 15, tzinfo=UTC)))
    assert actual == (one, two)


def test_anniversaries_use_new_york_date_across_utc_midnight_and_year_boundary():
    first = datetime(2025, 1, 1, 1, tzinfo=UTC)  # New York Dec31.
    assert api().holding_anniversaries(mandate(first=first)) == (
        date(2025, 1, 31),
        date(2025, 2, 28),
    )


def test_long_term_has_no_monthly_profit_deadline():
    assert api().holding_anniversaries(mandate(sleeve="long_term")) == (None, None)


def test_price_pnl_combines_prior_net_gain_and_remaining_basis_without_duplicate_fees():
    result = api().owned_price_pnl(
        mandate(),
        remaining_lots=(lot(),),
        realized_gains=(gain(),),
        price=price(),
        costs=costs(),
        cutoff=datetime(2025, 2, 28, 21, tzinfo=UTC),
    )
    assert result.status == "known" and result.price_pnl == D("193.2")
    assert result.remaining_quantity == 8 and result.remaining_basis == 800
    assert result.prior_net_realized_gain == 39
    assert result.remaining_sale_proceeds == D("954.2")


@pytest.mark.parametrize("missing", ["lots", "gains", "price", "costs"])
def test_unknown_price_pnl_inputs_stay_unknown_instead_of_zero(missing):
    values = dict(remaining_lots=(lot(),), realized_gains=(gain(),), price=price(), costs=costs())
    values[{"lots": "remaining_lots", "gains": "realized_gains"}.get(missing, missing)] = None
    result = api().owned_price_pnl(
        mandate(), **values, cutoff=datetime(2025, 2, 28, 21, tzinfo=UTC)
    )
    assert result.status == "unavailable" and result.price_pnl is None


def test_flat_episode_retains_realized_price_gain_without_new_sale_fee_or_price():
    result = api().owned_price_pnl(
        mandate(),
        remaining_lots=(),
        realized_gains=(gain(),),
        price=None,
        costs=None,
        cutoff=datetime(2025, 2, 28, 21, tzinfo=UTC),
    )
    assert result.status == "known" and result.price_pnl == 39
    assert result.remaining_sale_proceeds == 0


def test_price_pnl_owns_full_decimal_context_and_source_identity():
    m = api()
    args = dict(
        remaining_lots=(lot(),),
        realized_gains=(gain(),),
        price=price(),
        costs=costs(),
        cutoff=datetime(2025, 2, 28, 21, tzinfo=UTC),
    )
    expected = m.owned_price_pnl(mandate(), **args)
    with localcontext() as context:
        context.prec, context.rounding, context.capitals = 4, ROUND_DOWN, 0
        actual = m.owned_price_pnl(mandate(), **args)
        assert actual == expected and actual.evidence_hash == expected.evidence_hash


def test_duplicate_or_foreign_lot_ownership_rejects():
    from dataclasses import replace

    m = api()
    for rows in ((lot(), lot()), (replace(lot(), episode_id="foreign"),)):
        with pytest.raises(ValueError):
            m.owned_price_pnl(
                mandate(),
                remaining_lots=rows,
                realized_gains=(),
                price=price(),
                costs=costs(),
                cutoff=datetime(2025, 2, 28, 21, tzinfo=UTC),
            )


def session(day, *, status="known_regular"):
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    close = datetime.combine(day, datetime.min.time().replace(hour=16), ny).astimezone(UTC)
    opened = datetime.combine(day, datetime.min.time().replace(hour=9, minute=30), ny).astimezone(
        UTC
    )
    return api().StockRegularSession(
        status,
        opened if status == "known_regular" else None,
        close if status == "known_regular" else None,
        close + timedelta(seconds=5),
        "f" * 64,
    )


def continuation_fact(proof, status="active"):
    if status == "unknown" or proof.status != "known_regular":
        return None
    return api().StockContinuationEvidence(
        "episode-1",
        "instrument-1",
        "AXP",
        status,
        proof.closes_at,
        proof.observed_at,
        proof.observed_at + timedelta(hours=1),
        "3" * 64,
    )


def review(
    day,
    *,
    continuation="active",
    value="120",
    proof=None,
    selected=None,
    missing_price=False,
    missing_lots=False,
    protective=None,
    reviewed_at=None,
):
    m = api()
    proof = proof or session(day)
    clock = reviewed_at or proof.observed_at + timedelta(seconds=5)
    evidence = continuation_fact(proof, continuation)
    if evidence is not None and clock >= evidence.expires_at:
        evidence = None
    return m.evaluate_stock_holding(
        selected or mandate(),
        reviewed_at=clock,
        session=proof,
        remaining_lots=None if missing_lots else (lot(),),
        realized_gains=(),
        price=None if missing_price else price(value=value, at=proof.closes_at),
        costs=costs(bps="0"),
        continuation=evidence,
        protective_evidence=protective,
    )


@pytest.mark.parametrize("continuation", ["active", "inactive", "unknown"])
def test_pre_month_one_entry_or_continuation_false_alone_cannot_force_short_exit(continuation):
    result = review(date(2025, 2, 27), continuation=continuation, value="90")
    assert result.action == "HOLD" and result.reason == "before_month_one"
    assert result.partial_profit_reductions_allowed is True
    assert result.execute_not_before is None


def test_month_one_positive_owned_pnl_and_known_continuation_allows_extension():
    result = review(date(2025, 2, 28))
    assert result.action == "HOLD" and result.reason == "positive_price_pnl_and_active_continuation"
    assert result.phase == "month_one" and result.review_state == "due"
    assert result.review_session_at == datetime(2025, 2, 28, 21, tzinfo=UTC)
    assert result.review_delayed is False and result.extension_approved is True


@pytest.mark.parametrize("value", ["90", "100.125"])
def test_month_one_nonpositive_net_price_pnl_proposes_exit_without_fake_next_open(value):
    result = review(date(2025, 2, 28), value=value)
    assert result.action == "EXIT" and result.reason == "nonpositive_owned_price_pnl"
    assert result.execution_timing == "next_eligible_market_opportunity"
    assert result.execute_not_before is None and result.execution_authorized is False


def test_month_one_inactive_continuation_and_unknown_extension_have_distinct_reasons():
    inactive = review(date(2025, 2, 28), continuation="inactive")
    unknown = review(date(2025, 2, 28), continuation="unknown")
    assert inactive.action == "EXIT" and inactive.reason == "continuation_inactive"
    assert unknown.action == "REVIEW" and unknown.reason == "continuation_unknown"
    assert inactive.extension_approved is unknown.extension_approved is False
    missing = review(date(2025, 2, 28), missing_price=True)
    assert missing.action == "REVIEW" and missing.reason == "owned_price_pnl_unavailable"


def test_month_two_requires_disposal_proposal_even_with_unknown_profit_and_continuation():
    result = review(date(2025, 3, 31), missing_price=True, continuation="unknown")
    assert result.action == "EXIT" and result.reason == "two_calendar_month_terminal_review"
    assert result.phase == "month_two" and result.terminal_anniversary == date(2025, 3, 31)
    assert result.execute_not_before is None


def test_delayed_first_observed_close_is_not_claimed_to_be_first_eligible_session():
    result = review(date(2025, 3, 3))
    assert result.review_delayed is True
    assert result.first_eligible_session_verified is False
    assert result.review_session_at == datetime(2025, 3, 3, 21, tzinfo=UTC)
    assert result.first_anniversary == date(2025, 2, 28)


def test_anniversary_without_supported_completed_close_is_explicitly_awaiting():
    proof = session(date(2025, 2, 27))
    result = review(
        date(2025, 2, 27), proof=proof, reviewed_at=datetime(2025, 3, 1, 15, tzinfo=UTC)
    )
    assert result.action == "REVIEW" and result.review_state == "awaiting_completed_close"
    assert result.reason == "anniversary_awaiting_supported_completed_close"


def test_unknown_calendar_proof_never_invents_an_execution_clock():
    proof = session(date(2025, 3, 31), status="unknown")
    result = review(date(2025, 3, 31), proof=proof, missing_price=True)
    assert result.action == "REVIEW" and result.review_state == "unknown_session"
    assert result.review_session_at is result.execute_not_before is None


def test_new_york_dst_changes_review_utc_clock_but_not_anniversary_dates():
    result = review(date(2025, 3, 31))
    assert result.review_session_at == datetime(2025, 3, 31, 20, tzinfo=UTC)
    assert result.first_anniversary == date(2025, 2, 28)


def test_long_term_never_gets_monthly_profit_liquidation():
    result = review(date(2025, 3, 31), selected=mandate(sleeve="long_term"), value="999")
    assert result.action == "HOLD" and result.reason == "long_term_has_no_monthly_profit_deadline"
    assert result.first_anniversary is result.terminal_anniversary is None
    assert result.partial_profit_reductions_allowed is False


def test_explicit_protective_evidence_can_exit_before_month_one():
    m = api()
    safety = m.StockProtectiveEvidence(
        "episode-1",
        "instrument-1",
        "AXP",
        datetime(2025, 2, 10, 21, tzinfo=UTC),
        "protective_stop",
        "1" * 64,
    )
    result = review(date(2025, 2, 10), protective=safety)
    assert result.action == "EXIT" and result.reason == "protective_stop"
    assert result.review_state == "protective" and result.execute_not_before is None


def test_unknown_ownership_does_not_turn_terminal_review_into_an_order():
    result = review(date(2025, 3, 31), missing_lots=True)
    assert result.action == "REVIEW" and result.reason == "remaining_owned_position_unknown"


def test_review_hash_and_false_authority_are_independent_of_ambient_context():
    result = review(date(2025, 3, 31))
    expected = result.evidence_hash
    with localcontext() as context:
        context.prec, context.rounding, context.capitals = 4, ROUND_DOWN, 0
        assert review(date(2025, 3, 31)) == result
        assert result.evidence_hash == expected
    assert result.execution_authorized is result.live_authorized is result.order_created is False
    assert result.performance_proven is False


def test_review_information_cutoff_includes_later_protective_source_without_inventing_price():
    m = api()
    proof = session(date(2025, 2, 10))
    later = proof.closes_at + timedelta(minutes=1)
    safety = m.StockProtectiveEvidence(
        "episode-1",
        "instrument-1",
        "AXP",
        later,
        "protective_stop",
        "1" * 64,
    )
    result = review(
        date(2025, 2, 10), proof=proof, protective=safety, reviewed_at=later + timedelta(seconds=1)
    )
    assert result.information_cutoff >= safety.observed_at
    assert result.review_session_at == proof.closes_at


@pytest.mark.parametrize("changed", ["lot_after_mark", "gain_after_mark"])
def test_known_price_pnl_cannot_mark_later_owned_activity_at_an_earlier_price(changed):
    from dataclasses import replace

    m = api()
    mark = price()
    rows, gains = (lot(),), (gain(),)
    if changed == "lot_after_mark":
        rows = (replace(lot(), acquired_at=mark.at + timedelta(seconds=1)),)
    else:
        gains = (replace(gain(), at=mark.at + timedelta(seconds=1)),)
    with pytest.raises(ValueError, match="mark"):
        m.owned_price_pnl(
            mandate(),
            remaining_lots=rows,
            realized_gains=gains,
            price=mark,
            costs=costs(),
            cutoff=mark.at + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    "changed", ["foreign_symbol", "foreign_gain", "duplicate_gain", "future_price"]
)
def test_foreign_or_noncausal_owned_values_fail_closed(changed):
    from dataclasses import replace

    m = api()
    mark, rows, gains = price(), (lot(),), (gain(),)
    if changed == "foreign_symbol":
        rows = (replace(lot(), symbol="KO"),)
    elif changed == "foreign_gain":
        gains = (replace(gain(), instrument_id="foreign"),)
    elif changed == "duplicate_gain":
        gains = (gain(), gain())
    else:
        mark = replace(
            mark, at=mark.at + timedelta(days=1), received_at=mark.received_at + timedelta(days=1)
        )
    with pytest.raises(ValueError):
        m.owned_price_pnl(
            mandate(),
            remaining_lots=rows,
            realized_gains=gains,
            price=mark,
            costs=costs(),
            cutoff=datetime(2025, 2, 28, 21, tzinfo=UTC),
        )


def test_incomplete_session_and_mismatched_price_cannot_be_used_as_completed_review():
    from dataclasses import replace

    m = api()
    proof = session(date(2025, 2, 28))
    with pytest.raises(ValueError, match="session"):
        replace(proof, observed_at=proof.closes_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="future_session"):
        review(date(2025, 2, 28), proof=proof, reviewed_at=proof.observed_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="completed_session"):
        m.evaluate_stock_holding(
            mandate(),
            reviewed_at=proof.observed_at,
            session=proof,
            remaining_lots=(lot(),),
            realized_gains=(),
            price=price(at=proof.closes_at - timedelta(days=1)),
            costs=costs(),
            continuation=continuation_fact(proof),
        )


def test_result_cannot_promote_its_authority_and_does_not_create_orders():
    result = review(date(2025, 3, 31))
    object.__setattr__(result, "live_authorized", True)
    with pytest.raises(ValueError, match="scope"):
        _ = result.evidence_hash


def test_missing_ownership_is_distinct_from_a_known_flat_position():
    m = api()
    proof = session(date(2025, 3, 31))
    result = m.evaluate_stock_holding(
        mandate(),
        reviewed_at=proof.observed_at,
        session=proof,
        remaining_lots=(),
        realized_gains=(),
        price=None,
        costs=None,
        continuation=None,
    )
    assert result.action == "HOLD" and result.reason == "no_remaining_owned_shares"
    assert result.price_pnl.price_pnl == 0


def test_tampered_input_is_revalidated_and_source_hashes_change_identity():
    from dataclasses import replace

    selected = mandate()
    original = review(date(2025, 3, 31), selected=selected)
    changed = review(date(2025, 3, 31), selected=replace(selected, first_fill_hash="2" * 64))
    assert changed.input_evidence_hash != original.input_evidence_hash
    object.__setattr__(selected, "first_fill_at", datetime(2025, 1, 1))
    with pytest.raises(ValueError):
        review(date(2025, 3, 31), selected=selected)


def test_unbound_active_continuation_enum_cannot_approve_an_extension():
    m = api()
    proof = session(date(2025, 2, 28))
    with pytest.raises(ValueError, match="continuation"):
        m.evaluate_stock_holding(
            mandate(),
            reviewed_at=proof.observed_at,
            session=proof,
            remaining_lots=(lot(),),
            realized_gains=(),
            price=price(at=proof.closes_at),
            costs=costs(),
            continuation="active",
        )


@pytest.mark.parametrize(
    "change",
    ["owner", "symbol", "future_information", "future_receipt", "expired", "missing_source"],
)
def test_known_continuation_is_bound_to_owned_source_and_current_completed_cutoff(change):
    from dataclasses import replace

    m = api()
    proof = session(date(2025, 2, 28))
    supplied = m.StockContinuationEvidence(
        "episode-1",
        "instrument-1",
        "AXP",
        "active",
        proof.closes_at,
        proof.observed_at,
        proof.observed_at + timedelta(hours=1),
        "3" * 64,
    )
    clock = proof.observed_at
    with pytest.raises(ValueError):
        if change == "owner":
            supplied = replace(supplied, episode_id="foreign")
        elif change == "symbol":
            supplied = replace(supplied, symbol="KO")
        elif change == "future_information":
            supplied = replace(supplied, information_at=proof.closes_at + timedelta(seconds=1))
        elif change == "future_receipt":
            supplied = replace(supplied, received_at=proof.observed_at + timedelta(seconds=1))
        elif change == "expired":
            supplied = replace(supplied, expires_at=proof.observed_at + timedelta(seconds=1))
            clock = supplied.expires_at
        else:
            supplied = replace(supplied, source_hash=None)
        m.evaluate_stock_holding(
            mandate(),
            reviewed_at=clock,
            session=proof,
            remaining_lots=(lot(),),
            realized_gains=(),
            price=price(at=proof.closes_at),
            costs=costs(),
            continuation=supplied,
        )


def test_minor_long_term_concentration_reduction_does_not_become_full_liquidation():
    m = api()
    selected = mandate(sleeve="long_term")
    safety = m.StockProtectiveEvidence(
        "episode-1",
        "instrument-1",
        "AXP",
        datetime(2025, 3, 31, 20, tzinfo=UTC),
        "concentration_reduction",
        "4" * 64,
    )
    result = review(date(2025, 3, 31), selected=selected, protective=safety)
    assert result.action == "REVIEW" and result.reason == "portfolio_reduction_plan_required"
    assert result.execution_timing is result.execute_not_before is None


@pytest.mark.parametrize(
    ("day", "sleeve", "digest"),
    [
        (
            date(2025, 2, 27),
            "tactical",
            "7531dfc4398fc48f144cb5be0c8017a5d4f912a1eec9fcad321a2873e2725078",
        ),
        (
            date(2025, 2, 28),
            "tactical",
            "806b800faeddde4063dd5c3a9b3a3e0b59fccf418d7f18dec2ee8acf6a926933",
        ),
        (
            date(2025, 3, 31),
            "tactical",
            "784f5f720e7f48b7b9174cbde32e55947bd8758d377341aa2230d68d06dfe2ad",
        ),
        (
            date(2025, 3, 31),
            "long_term",
            "9818e5040de16e44ed00944873624806a6e797cea611228a002078720b5aac4c",
        ),
    ],
)
def test_legacy_review_output_hashes_remain_literal_compatible(day, sleeve, digest):
    assert review(day, selected=mandate(sleeve=sleeve)).evidence_hash == digest


def receipt_review(
    *,
    day=date(2025, 2, 28),
    selected=None,
    clock=None,
    mark_at=None,
    information_at=None,
    expires_at=None,
    missing_price=False,
    missing_continuation=False,
    maximum_age=120,
    basis="receipt_snapshot_v1",
    protective=None,
    value="120",
):
    m = api()
    proof = session(day)
    clock = clock or proof.observed_at + timedelta(minutes=5)
    observed = mark_at or clock - timedelta(minutes=1)
    analytical = information_at or clock - timedelta(seconds=2)
    continuation = (
        None
        if missing_continuation
        else m.StockContinuationEvidence(
            "episode-1",
            "instrument-1",
            "AXP",
            "active",
            analytical,
            max(analytical, clock - timedelta(seconds=1)),
            expires_at or clock + timedelta(hours=1),
            "3" * 64,
        )
    )
    return m.evaluate_stock_holding(
        selected or mandate(),
        reviewed_at=clock,
        session=proof,
        remaining_lots=(lot(),),
        realized_gains=(),
        price=None if missing_price else price(value=value, at=observed),
        costs=costs(bps="0"),
        continuation=continuation,
        protective_evidence=protective,
        review_basis=basis,
        maximum_snapshot_age_minutes=maximum_age,
    )


def test_receipt_snapshot_uses_actual_analytical_and_original_receipt_clocks():
    result = receipt_review()
    assert result.action == "HOLD" and result.extension_approved
    assert result.review_basis == "receipt_snapshot_v1"
    assert result.maximum_snapshot_age_minutes == 120
    assert result.review_session_at < result.information_cutoff == result.reviewed_at
    assert result.valuation_disclosures == (
        "indicative_provider_receipt_snapshot",
        "not_completed_close_or_trade_timestamp",
        "not_executable_quote",
        "no_price_or_execution_guarantee",
    )
    assert result.policy_version == "current-stock-calendar-month-holding-receipt-snapshot-v1"
    assert result.execute_not_before is None
    assert result.execution_authorized is result.live_authorized is result.order_created is False


@pytest.mark.parametrize("missing", ("price", "continuation"))
def test_receipt_snapshot_missing_extension_evidence_remains_review(missing):
    result = receipt_review(
        missing_price=missing == "price", missing_continuation=missing == "continuation"
    )
    assert result.action == "REVIEW" and not result.extension_approved
    if missing == "price":
        assert result.price_pnl.status == "unavailable"


@pytest.mark.parametrize("age", (120, 121))
def test_receipt_snapshot_age_boundary_is_exclusive_without_refreshing_old_marks(age):
    proof = session(date(2025, 2, 28))
    clock = proof.closes_at + timedelta(minutes=130)
    result = receipt_review(clock=clock, mark_at=clock - timedelta(minutes=age))
    assert result.action == "REVIEW" and not result.extension_approved
    assert result.price_pnl.status == "unavailable" and result.price_pnl.price_pnl is None


def test_receipt_snapshot_inside_declared_age_can_extend():
    proof = session(date(2025, 2, 28))
    clock = proof.closes_at + timedelta(minutes=130)
    assert receipt_review(clock=clock, mark_at=clock - timedelta(minutes=119)).extension_approved


@pytest.mark.parametrize("stale", ("price", "continuation"))
def test_receipt_snapshot_pre_session_or_expired_current_evidence_cannot_extend(stale):
    proof = session(date(2025, 2, 28))
    if stale == "price":
        result = receipt_review(mark_at=proof.closes_at - timedelta(seconds=1))
    else:
        clock = proof.closes_at + timedelta(minutes=5)
        result = receipt_review(clock=clock, expires_at=clock)
    assert result.action == "REVIEW" and not result.extension_approved


def test_receipt_snapshot_pre_session_analysis_is_unknown_not_backdated_to_close():
    proof = session(date(2025, 2, 28))
    result = receipt_review(information_at=proof.closes_at - timedelta(seconds=1))
    assert result.action == "REVIEW" and result.continuation == "unknown"


@pytest.mark.parametrize("future", ("price", "analysis"))
def test_receipt_snapshot_future_facts_are_rejected(future):
    proof = session(date(2025, 2, 28))
    clock = proof.closes_at + timedelta(minutes=5)
    with pytest.raises(ValueError):
        receipt_review(
            clock=clock,
            **{"mark_at" if future == "price" else "information_at": clock + timedelta(seconds=1)},
        )


@pytest.mark.parametrize("age", (None, 0, 121, True, "120"))
def test_receipt_snapshot_requires_a_declared_bounded_exact_age_policy(age):
    with pytest.raises(ValueError, match=r"basis|snapshot"):
        receipt_review(maximum_age=age)


def test_legacy_review_basis_cannot_silently_accept_snapshot_inputs_or_age_policy():
    with pytest.raises(ValueError):
        receipt_review(basis="completed_close_v1", maximum_age=None)
    with pytest.raises(ValueError):
        receipt_review(basis="completed_close_v1", maximum_age=120)


def test_receipt_snapshot_preserves_terminal_protection_and_long_term_priorities():
    terminal = receipt_review(day=date(2025, 3, 31), missing_price=True, missing_continuation=True)
    assert terminal.action == "EXIT" and terminal.reason == "two_calendar_month_terminal_review"
    long = receipt_review(
        selected=mandate(sleeve="long_term"), missing_price=True, missing_continuation=True
    )
    assert long.action == "HOLD" and long.first_anniversary is long.terminal_anniversary is None
    proof = session(date(2025, 2, 10))
    stop = api().StockProtectiveEvidence(
        "episode-1", "instrument-1", "AXP", proof.closes_at, "protective_stop", "1" * 64
    )
    protected = receipt_review(
        day=date(2025, 2, 10), protective=stop, missing_price=True, missing_continuation=True
    )
    assert protected.action == "EXIT" and protected.reason == "protective_stop"
    assert protected.execution_authorized is protected.live_authorized is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("review_basis", "completed_close_v1"),
        ("maximum_snapshot_age_minutes", 999),
        ("valuation_disclosures", ()),
    ],
)
def test_receipt_snapshot_fixed_basis_disclosure_and_policy_cannot_be_changed(field, value):
    result = receipt_review()
    object.__setattr__(result, field, value)
    with pytest.raises(ValueError, match=r"scope|basis|snapshot"):
        _ = result.evidence_hash


def test_receipt_snapshot_hash_binds_policy_and_ignores_ambient_decimal_context():
    result = receipt_review()
    tighter = receipt_review(maximum_age=60)
    assert result.evidence_hash != tighter.evidence_hash
    assert result.input_evidence_hash != tighter.input_evidence_hash
    with localcontext() as decimal:
        decimal.prec, decimal.rounding, decimal.capitals = 3, ROUND_DOWN, 0
        assert receipt_review() == result and receipt_review().evidence_hash == result.evidence_hash


def test_receipt_snapshot_flat_episode_keeps_actual_prior_net_gain_without_a_price_need():
    m = api()
    proof = session(date(2025, 2, 28))
    clock = proof.closes_at + timedelta(minutes=130)
    result = m.evaluate_stock_holding(
        mandate(),
        reviewed_at=clock,
        session=proof,
        remaining_lots=(),
        realized_gains=(gain(),),
        price=price(at=proof.closes_at + timedelta(minutes=1)),
        costs=None,
        continuation=None,
        review_basis="receipt_snapshot_v1",
        maximum_snapshot_age_minutes=120,
    )
    assert result.action == "HOLD" and result.review_state == "flat"
    assert result.price_pnl.status == "known" and result.price_pnl.price_pnl == 39
    assert result.price_pnl.remaining_sale_proceeds == 0


def test_receipt_snapshot_unknown_session_does_not_invent_a_monthly_review_close():
    m = api()
    clock = datetime(2025, 2, 28, 21, 5, tzinfo=UTC)
    result = m.evaluate_stock_holding(
        mandate(),
        reviewed_at=clock,
        session=m.StockRegularSession("unknown", None, None, clock, "f" * 64),
        remaining_lots=(lot(),),
        realized_gains=(),
        price=price(at=clock),
        costs=costs(),
        continuation=None,
        review_basis="receipt_snapshot_v1",
        maximum_snapshot_age_minutes=120,
    )
    assert result.action == "REVIEW" and result.review_state == "unknown_session"
    assert result.review_session_at is result.execute_not_before is None
