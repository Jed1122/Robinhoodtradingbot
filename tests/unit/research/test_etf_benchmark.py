"""Independent cash-flow expectations for a non-executable daily-price reference."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest

D = Decimal
SHA = "a" * 64
OTHER_SHA = "b" * 64


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_benchmark")
    except ModuleNotFoundError:
        pytest.fail("daily-price benchmark mathematical API is missing")


def bar(day=2, opening="100", close="100", source_hash=SHA):
    return api().EtfBenchmarkBar(date(2020, 1, day), D(opening), D(close), source_hash)


def distribution(ex=3, pay=5, amount=".2", source_hash=SHA):
    return api().EtfBenchmarkDistribution(
        date(2020, 1, ex), date(2020, 1, pay), D(amount), source_hash
    )


def request(**changes):
    values = {
        "bars": (bar(2), bar(6, close="101")),
        "distributions": (),
        "initial_cash": D("500"),
        "entry_notional": D("10.01"),
        "per_side_cost_bps": D("10"),
        "entry_fee": D(".01"),
        "estimated_exit_fee": D(".01"),
    }
    values.update(changes)
    return api().EtfBenchmarkRequest(**values)


def test_entry_uses_first_opening_and_counts_embedded_cost_once():
    result = api().run_etf_benchmark(request())
    assert result.entry_price == D("100.1")
    assert result.shares == D(".1")
    assert result.fees_paid == D(".01")
    assert result.embedded_entry_cost == D(".01")
    first, last = result.points
    assert first.cash == D("489.98")
    assert first.close_midpoint_nav == D("499.98")
    assert first.marked_pnl == D("-.02")
    assert first.estimated_liquidation_cost == D(".02")
    assert first.liquidation_proxy == D("499.96")
    assert last.cash == D("489.98")
    assert last.shares == D(".1")
    assert last.close_midpoint_nav == D("500.08")
    assert last.liquidation_proxy == D("500.0599")
    assert result.estimated_terminal_liquidation_cost == D(".0201")
    assert result.realized_trading_pnl is None


def test_close_price_does_not_determine_hypothetical_entry():
    result = api().run_etf_benchmark(request(bars=(bar(2, "100", "200"),)))
    assert result.shares == D(".1")
    assert result.points[0].cash == D("489.98")
    assert result.points[0].close_midpoint_nav == D("509.98")


def test_entry_on_ex_date_is_not_entitled_and_gap_payment_uses_actual_pay_date():
    inputs = request(
        distributions=(distribution(2, 4, "9"), distribution(3, 5, ".2")),
        bars=(bar(2), bar(4), bar(6)),
    )
    result = api().run_etf_benchmark(inputs)
    assert result.points[0].dividend_receivable == 0
    assert result.points[1].dividend_receivable == D(".02")
    assert result.points[1].cash == D("489.98")
    assert result.points[1].close_midpoint_nav == D("500")
    assert result.points[2].cash == D("490")
    assert result.points[2].dividend_receivable == 0
    assert result.points[2].dividends_received == D(".02")
    assert result.dividends_received == D(".02")
    assert len(result.dividend_payments) == 1
    assert result.dividend_payments[0].pay_date == date(2020, 1, 5)
    assert result.dividend_payments[0].amount == D(".02")


def test_dividend_receivable_stays_open_beyond_end_without_sale_or_settlement():
    result = api().run_etf_benchmark(
        request(distributions=(distribution(3, 9),), bars=(bar(2), bar(4)))
    )
    assert result.dividends_receivable == D(".02")
    assert result.dividends_received == 0
    assert result.dividend_payments == ()
    assert result.points[-1].cash == D("489.98")
    assert result.points[-1].shares == D(".1")
    assert result.points[-1].close_midpoint_nav == D("500")
    assert result.points[-1].liquidation_proxy == D("499.98")
    assert result.fees_paid == D(".01")
    assert result.realized_trading_pnl is None


def test_zero_allocation_retains_cash_without_entry_or_exit_fees():
    result = api().run_etf_benchmark(
        request(entry_notional=D("0"), distributions=(distribution(),))
    )
    assert result.entry_price is None
    assert result.shares == result.fees_paid == result.embedded_entry_cost == 0
    assert result.estimated_terminal_liquidation_cost == 0
    assert result.dividend_payments == ()
    assert result.dividends_received == result.dividends_receivable == 0
    for point in result.points:
        assert point.cash == point.cash_reference_nav == D("500")
        assert point.liquidation_proxy == point.close_midpoint_nav == D("500")
        assert point.marked_pnl == 0


def test_cash_reference_is_unchanged_despite_equity_and_dividend_outcomes():
    result = api().run_etf_benchmark(request(distributions=(distribution(),)))
    assert tuple(point.cash_reference_nav for point in result.points) == (D("500"), D("500"))


def test_future_bars_and_actions_do_not_rewrite_earlier_prefix_or_its_hash():
    short = api().run_etf_benchmark(request(bars=(bar(2), bar(4))))
    extended = api().run_etf_benchmark(
        request(
            bars=(bar(2), bar(4), bar(6, "999", "999", OTHER_SHA)),
            distributions=(distribution(5, 6, "8", OTHER_SHA),),
        )
    )
    assert extended.points[:2] == short.points
    assert extended.input_hash != short.input_hash
    assert extended.result_hash != short.result_hash


def test_fixed_context_ignores_ambient_precision_rounding_and_inexact_trap():
    inputs = request(entry_notional=D("15"), bars=(bar(2, "333", "337"),))
    baseline = api().run_etf_benchmark(inputs)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        repeated = api().run_etf_benchmark(inputs)
    assert repeated == baseline
    assert repeated.result_hash == baseline.result_hash


def test_zero_cost_at_unchanged_price_does_not_fabricate_rounding_loss():
    result = api().run_etf_benchmark(
        request(
            initial_cash=D("1"),
            entry_notional=D("1"),
            bars=(bar(2, "3", "3"),),
            per_side_cost_bps=D("0"),
            entry_fee=D("0"),
            estimated_exit_fee=D("0"),
        )
    )
    assert result.embedded_entry_cost == 0
    assert result.points[0].close_midpoint_nav == D("1")
    assert result.points[0].marked_pnl == 0


def test_all_records_are_permanently_non_executable_and_non_promotable():
    inputs = request(distributions=(distribution(),))
    result = api().run_etf_benchmark(inputs)
    records = (
        inputs,
        *inputs.bars,
        *inputs.distributions,
        result,
        *result.points,
        *result.dividend_payments,
    )
    for record in records:
        assert record.execution_enabled is False
        assert record.evidence_promotable is False
        assert record.source_kind == "daily-price-exploratory-benchmark-v1"
        with pytest.raises(FrozenInstanceError):
            record.execution_enabled = True
    assert "daily_bars_are_not_executable_fills" in result.limitations
    assert "costs_and_fractional_terms_uncalibrated" in result.limitations
    assert "sessions_quotes_and_settlement_unverified" in result.limitations
    assert "original_publication_chronology_waived_upstream" in result.limitations


@pytest.mark.parametrize(
    "field",
    ["initial_cash", "entry_notional", "per_side_cost_bps", "entry_fee", "estimated_exit_fee"],
)
@pytest.mark.parametrize(
    "value", [True, 0, 1.0, "1", D("NaN"), D("Infinity"), D("-1"), D("1E+513")]
)
def test_financial_inputs_reject_coercion_nonfinite_negative_and_unbounded(field, value):
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        request(**{field: value})


def test_cost_cap_and_cash_budget_are_enforced_without_selecting_notional():
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        request(per_side_cost_bps=D("100.0001"))
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        request(entry_notional=D("500"), entry_fee=D(".01"))
    result = api().run_etf_benchmark(request(per_side_cost_bps=D("100"), entry_notional=D("101")))
    assert result.shares == 1


@pytest.mark.parametrize("value", [True, datetime(2020, 1, 2), "2020-01-02", 1.0])
def test_dates_must_be_exact_dates_not_datetimes_or_coercible_values(value):
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().EtfBenchmarkBar(value, D("100"), D("100"), SHA)
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().EtfBenchmarkDistribution(value, date(2020, 1, 5), D("1"), SHA)
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().EtfBenchmarkDistribution(date(2020, 1, 3), value, D("1"), SHA)


@pytest.mark.parametrize("field", ["open", "close"])
@pytest.mark.parametrize("value", [True, 1.0, D("0"), D("-1"), D("NaN"), D("1E+513")])
def test_price_fields_require_positive_bounded_exact_decimals(field, value):
    row = {
        "session_date": date(2020, 1, 2),
        "open": D("100"),
        "close": D("100"),
        "source_hash": SHA,
    }
    row[field] = value
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().EtfBenchmarkBar(**row)


@pytest.mark.parametrize("value", [True, 1.0, D("-1"), D("NaN"), D("1E+513")])
def test_distribution_requires_nonnegative_bounded_exact_decimal(value):
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().EtfBenchmarkDistribution(date(2020, 1, 3), date(2020, 1, 5), value, SHA)


@pytest.mark.parametrize("value", [True, "A" * 64, "a" * 63, "a" * 65, "g" * 64])
def test_source_binding_requires_canonical_sha256(value):
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        bar(source_hash=value)
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        distribution(source_hash=value)


@pytest.mark.parametrize("which", ["bars", "distributions"])
def test_mutable_collections_and_unknown_nested_records_are_denied(which):
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        request(**{which: []})
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        request(**{which: ({"open": "100"},)})


def test_empty_oversized_duplicate_or_backward_bar_inputs_are_denied():
    for rows in ((), (bar(2), bar(2)), (bar(3), bar(2)), (bar(2),) * 10001):
        with pytest.raises(ValueError, match="etf_benchmark_invalid"):
            request(bars=rows)


def test_duplicate_conflicting_or_backward_distributions_are_denied():
    for rows in (
        (distribution(), distribution()),
        (distribution(), distribution(3, 6)),
        (distribution(4, 5), distribution(3, 5)),
        (distribution(),) * 10001,
    ):
        with pytest.raises(ValueError, match="etf_benchmark_invalid"):
            request(distributions=rows)
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        distribution(5, 3)


def test_run_revalidates_frozen_input_after_nested_tampering():
    inputs = request()
    object.__setattr__(inputs.bars[0], "open", D("NaN"))
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().run_etf_benchmark(inputs)


def test_run_denies_unknown_request_or_mutated_marker():
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().run_etf_benchmark({})
    inputs = request()
    object.__setattr__(inputs, "execution_enabled", True)
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().run_etf_benchmark(inputs)


def test_result_verifier_detects_balance_and_source_substitution():
    result = api().run_etf_benchmark(request())
    api().verify_etf_benchmark_result(result)
    corrupted = replace(
        result, points=(replace(result.points[0], cash=D("499")), *result.points[1:])
    )
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().verify_etf_benchmark_result(corrupted)
    altered = replace(
        result, request=replace(result.request, bars=(bar(2, source_hash=OTHER_SHA), bar(6)))
    )
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().verify_etf_benchmark_result(altered)


def test_result_hash_binds_every_assumption_and_source():
    inputs = request()
    result = api().run_etf_benchmark(inputs)
    for changes in (
        {"estimated_exit_fee": D(".02")},
        {"entry_fee": D(".02")},
        {"entry_notional": D("11")},
        {"per_side_cost_bps": D("20")},
        {"initial_cash": D("501")},
        {"bars": (bar(2, source_hash=OTHER_SHA), bar(6))},
        {"distributions": (distribution(),)},
    ):
        different = api().run_etf_benchmark(replace(inputs, **changes))
        assert different.input_hash != result.input_hash
        assert different.result_hash != result.result_hash


@pytest.mark.parametrize(
    "field",
    [
        "cash",
        "shares",
        "dividend_receivable",
        "dividends_received",
        "close_midpoint_nav",
        "liquidation_proxy",
        "marked_pnl",
        "estimated_liquidation_cost",
        "cash_reference_nav",
    ],
)
def test_output_point_rejects_coercible_numeric_substitution(field):
    result = api().run_etf_benchmark(request(entry_notional=D("0")))
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        replace(result.points[0], **{field: 0})


@pytest.mark.parametrize("which", ["point", "payment", "result"])
def test_verifier_rejects_forged_false_markers_that_compare_equal(which):
    result = api().run_etf_benchmark(request(distributions=(distribution(),)))
    record = {"point": result.points[0], "payment": result.dividend_payments[0], "result": result}[
        which
    ]
    object.__setattr__(record, "execution_enabled", 0)
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().verify_etf_benchmark_result(result)


def test_dividends_on_no_bar_dates_accrue_pay_once_and_do_not_reinvest():
    result = api().run_etf_benchmark(
        request(
            distributions=(
                distribution(1, 6, "8"),
                distribution(3, 6, ".2"),
                distribution(4, 4, ".3"),
            )
        )
    )
    assert tuple(payment.pay_date for payment in result.dividend_payments) == (
        date(2020, 1, 4),
        date(2020, 1, 6),
    )
    assert result.dividends_received == D(".05")
    assert result.shares == result.points[-1].shares == D(".1")
    assert result.points[-1].cash == D("490.03")


@pytest.mark.parametrize(
    "field",
    [
        "shares",
        "fees_paid",
        "embedded_entry_cost",
        "estimated_terminal_liquidation_cost",
        "dividends_received",
        "dividends_receivable",
        "entry_price",
    ],
)
def test_result_constructor_denies_inexact_numeric_fields(field):
    result = api().run_etf_benchmark(request())
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        replace(result, **{field: 0})


@pytest.mark.parametrize("field", ["points", "dividend_payments"])
def test_result_constructor_denies_mutable_or_unknown_nested_records(field):
    result = api().run_etf_benchmark(request())
    for value in ([], ({"cash": D("1")},)):
        with pytest.raises(ValueError, match="etf_benchmark_invalid"):
            replace(result, **{field: value})


def test_dividend_payment_constructor_denies_invalid_amount_date_and_hash():
    result = api().run_etf_benchmark(request(distributions=(distribution(),)))
    for changes in (
        {"amount": True},
        {"pay_date": datetime(2020, 1, 5)},
        {"source_hash": "A" * 64},
        {"pay_date": date(2020, 1, 1)},
    ):
        with pytest.raises(ValueError, match="etf_benchmark_invalid"):
            replace(result.dividend_payments[0], **changes)


def test_rounded_fractional_entitlement_is_credited_and_marked_without_cash_rounding():
    result = api().run_etf_benchmark(
        request(
            entry_notional=D("1"),
            bars=(bar(2, "3", "3"), bar(6, "3", "3")),
            distributions=(distribution(3, 5, "1"),),
            per_side_cost_bps=D("0"),
            entry_fee=D("0"),
            estimated_exit_fee=D("0"),
        )
    )
    assert result.dividends_received == D(".3333333333333333333333333333")
    assert result.points[-1].cash == D("499.3333333333333333333333333333")
    assert result.points[-1].close_midpoint_nav == D("500.3333333333333333333333333333")
    assert result.points[-1].marked_pnl == D(".3333333333333333333333333333")


def test_large_bounded_cash_cannot_swallow_dividend_or_cost():
    values = {
        "initial_cash": D("1E27"),
        "entry_notional": D("1"),
        "entry_fee": D("0"),
        "estimated_exit_fee": D("0"),
    }
    paid = api().run_etf_benchmark(
        request(**values, per_side_cost_bps=D("0"), distributions=(distribution(3, 5, ".01"),))
    )
    assert paid.points[-1].cash == D("999999999999999999999999999.0001")
    assert paid.points[0].cash == D("999999999999999999999999999")
    assert paid.points[-1].dividends_received == D(".0001")
    charged = api().run_etf_benchmark(request(**values, bars=(bar(2),)))
    assert charged.points[0].marked_pnl < 0
    assert charged.points[0].marked_pnl == -charged.embedded_entry_cost


def test_bounded_initial_cash_with_long_coefficient_retains_exact_cash_debit():
    result = api().run_etf_benchmark(
        request(
            initial_cash=D("10000000000000000000000000000.01"),
            entry_notional=D("1"),
            per_side_cost_bps=D("0"),
            bars=(bar(2),),
        )
    )
    assert result.points[0].cash == D("9999999999999999999999999999")
    assert result.points[0].marked_pnl == D("-.01")


@pytest.mark.parametrize(
    "capital", ["9999999999999999999999999999", "9.999999999999999999999999999"]
)
def test_unchanged_price_ratio_never_creates_multiplication_rounding_gain(capital):
    result = api().run_etf_benchmark(
        request(
            initial_cash=D(capital),
            entry_notional=D(capital),
            bars=(bar(2, "3", "3"),),
            per_side_cost_bps=D("0"),
            entry_fee=D("0"),
            estimated_exit_fee=D("0"),
        )
    )
    assert result.points[0].cash == 0
    assert result.points[0].close_midpoint_nav == D(capital)
    assert result.points[0].marked_pnl == 0


def test_unsupported_cost_precision_is_rejected_instead_of_swallowing_positive_cost():
    with pytest.raises(ValueError, match="etf_benchmark_invalid"):
        api().run_etf_benchmark(
            request(
                initial_cash=D("1E27"),
                entry_notional=D("1E27"),
                per_side_cost_bps=D("1E-27"),
                entry_fee=D("0"),
                estimated_exit_fee=D("0"),
                bars=(bar(2),),
            )
        )


def test_small_price_move_cannot_disappear_against_large_notional():
    result = api().run_etf_benchmark(
        request(
            initial_cash=D("1E27"),
            entry_notional=D("1E27"),
            per_side_cost_bps=D("0"),
            entry_fee=D("0"),
            estimated_exit_fee=D("0"),
            bars=(bar(2, "100", "100.00000000000000000000000000001"),),
        )
    )
    assert result.points[0].close_midpoint_nav == D("1000000000000000000000000000.0001")
    assert result.points[0].marked_pnl == D(".0001")


def test_ratios_exceeding_exact_context_are_disclosed_even_when_terminating():
    opening = str(2**1700)
    result = api().run_etf_benchmark(
        request(
            initial_cash=D("1E511"),
            entry_notional=D("1E511"),
            per_side_cost_bps=D("0"),
            entry_fee=D("0"),
            estimated_exit_fee=D("0"),
            bars=(bar(2, opening, opening),),
        )
    )
    assert len(result.shares.as_tuple().digits) == 28
    assert "mathematical_ratios_exceeding_exact_context_rounded_to_28_digits" in result.limitations
    assert result.points[0].marked_pnl == 0
    assert not result.evidence_promotable
