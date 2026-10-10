"""Hand-calculated passive references; fabricated originals, not real evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import Inexact, localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit


def source(prices=("100", "20", "10", "10"), *, splits=(), distributions=()):
    original = long_source(len(prices), flat=True)
    spy, *rest = original.archives
    page = spy.pages[0]
    records = tuple(
        replace(
            record,
            bar=replace(
                record.bar,
                open=D(price),
                high=D(price),
                low=D(price),
                close=D(price),
                vwap=D(price),
            ),
        )
        for record, price in zip(page.records, prices, strict=True)
    )
    actions = original.actions
    return replace(
        original,
        archives=(replace(spy, pages=(replace(page, records=records),)), *rest),
        actions=(replace(actions[0], splits=splits, distributions=distributions), *actions[1:]),
    )


def request(original, **changes):
    from trading_bot.research.etf_capital_passive import CapitalPassiveRequest

    dates = tuple(row.session_date for row in original.calendar.sessions)
    return replace(
        CapitalPassiveRequest(original, D(100), dates[1:], D(".10"), D(0), D(0)), **changes
    )


def run(value):
    from trading_bot.research.etf_capital_passive import run_capital_passive_reference

    return run_capital_passive_reference(value)


def test_forward_split_preserves_value_and_changes_only_raw_quantity():
    original = long_source(4, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    value = run(request(source(splits=(CapitalSplit(dates[2], D(2), "a" * 64),))))
    assert value.baseline_session == dates[0]
    assert value.session_dates == dates[1:]
    assert value.raw_quantities == (
        D("4.997501249375312343828085957"),
        D("9.995002498750624687656171914"),
        D("9.995002498750624687656171914"),
    )
    assert tuple(p.close_midpoint_nav for p in value.kernel_result.points) == (
        D("99.95002498750624687656171914"),
        D("99.95002498750624687656171914"),
        D("99.95002498750624687656171914"),
    )
    assert value.kernel_result.request.bars[1].close == 20
    assert value.reference_kind == "full_mathematical_spy"
    assert value.realized_trading_pnl is None
    assert not any(
        (
            value.source_qualified,
            value.cost_qualified,
            value.execution_enabled,
            value.economic_admitted,
            value.evidence_promotable,
        )
    )


def test_reverse_split_and_entry_date_split_are_not_double_applied():
    original = long_source(4, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    value = run(
        request(
            source(
                ("100", "20", "40", "40"),
                splits=(
                    CapitalSplit(dates[1], D(2), "a" * 64),
                    CapitalSplit(dates[2], D(".5"), "b" * 64),
                ),
            ),
            roundtrip_friction_pct=D(".40"),
        )
    )
    assert value.raw_quantities == (
        D("4.990019960079840319361277445"),
        D("2.4950099800399201596806387225"),
        D("2.4950099800399201596806387225"),
    )
    assert tuple(p.close_midpoint_nav for p in value.kernel_result.points) == (
        D("99.80039920159680638722554890"),
        D("99.80039920159680638722554890"),
        D("99.80039920159680638722554890"),
    )


def test_dividend_uses_ex_date_quantity_not_later_pay_date_split():
    original = long_source(6, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    # Entry Jan3, ex Jan6 at five shares; split Jan7; payment Jan11 (Sunday),
    # outside supplied Jan9 horizon. Entitlement remains receivable, never paid.
    dividend = CapitalDistribution(
        dates[2], dates[2], dates[-1] + timedelta(days=2), D(1), "c" * 64
    )
    current = source(
        ("100", "20", "19", "9.5", "9.5", "9.5"),
        splits=(CapitalSplit(dates[3], D(2), "a" * 64),),
        distributions=(dividend,),
    )
    value = run(request(current))
    assert value.kernel_result.request.distributions[0].cash_per_share == 1
    assert value.kernel_result.dividends_received == 0
    assert value.kernel_result.dividends_receivable == D("4.997501249375312343828085957")
    # Existing kernel rounds each nonterminating ratio, then adds cash/value
    # exactly; 94.95252373813093453273363318 + 4.997501249375312343828085957.
    assert value.kernel_result.points[-1].close_midpoint_nav == D("99.950024987506246876561719137")
    assert value.kernel_result.dividend_payments == ()


def test_paid_weekend_entitlement_is_cash_once_without_reinvestment():
    original = long_source(8, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    dividend = CapitalDistribution(dates[2], dates[2], dates[5] + timedelta(days=2), D(1), "c" * 64)
    current = source(("100", "20", "19", "19", "19", "19", "19", "19"), distributions=(dividend,))
    value = run(request(current))
    assert len(value.kernel_result.dividend_payments) == 1
    assert value.kernel_result.dividends_received == D("4.997501249375312343828085957")
    assert value.kernel_result.dividends_receivable == 0
    assert len(set(value.raw_quantities)) == 1


def test_first_entry_ex_date_has_no_entitlement_and_fee_friction_paid_once():
    original = long_source(4, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    dividend = CapitalDistribution(dates[1], dates[1], dates[2], D(1), "c" * 64)
    value = run(
        request(
            source(("100", "20", "20", "20"), distributions=(dividend,)),
            entry_fee=D(1),
            estimated_exit_fee=D(".5"),
        )
    )
    assert value.kernel_result.request.entry_notional == 99
    assert value.kernel_result.fees_paid == 1
    assert value.kernel_result.dividends_received == value.kernel_result.dividends_receivable == 0
    assert all(p.cash == 0 for p in value.kernel_result.points)
    assert value.kernel_result.points[-1].close_midpoint_nav == D("98.95052473763118440779610195")
    assert value.kernel_result.estimated_terminal_liquidation_cost == D(
        ".549475262368815592203898050975"
    )


def test_later_effective_split_cannot_change_earlier_reference_values():
    original = long_source(4, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    before = run(request(source(), sessions=dates[1:3]))
    after = run(
        request(source(splits=(CapitalSplit(dates[3], D(2), "a" * 64),)), sessions=dates[1:3])
    )
    assert before.raw_quantities == after.raw_quantities
    assert tuple(p.close_midpoint_nav for p in before.kernel_result.points) == tuple(
        p.close_midpoint_nav for p in after.kernel_result.points
    )
    assert before.input_hash != after.input_hash


@pytest.mark.parametrize(
    "field,value",
    (
        ("initial_cash", D(101)),
        ("initial_cash", 100),
        ("roundtrip_friction_pct", D(0)),
        ("roundtrip_friction_pct", D(".01")),
        ("entry_fee", D(-1)),
        ("entry_fee", D(101)),
        ("estimated_exit_fee", None),
        ("estimated_exit_fee", D("NaN")),
    ),
)
def test_invalid_declared_terms_deny_without_exposing_inputs(field, value):
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(request(source(), **{field: value}))


@pytest.mark.parametrize("indices", ((0, 1), (1, 3), (2, 1), (1, 1), ()))
def test_no_missing_baseline_gap_duplicate_or_reversed_session_is_invented(indices):
    original = source()
    dates = tuple(row.session_date for row in original.calendar.sessions)
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(request(original, sessions=tuple(dates[i] for i in indices)))


def test_ambient_precision_traps_do_not_change_reference():
    value = request(source())
    expected = run(value)
    with localcontext() as context:
        context.prec = 3
        context.Emax = 1
        context.traps[Inexact] = True
        assert run(value) == expected


def test_mutated_flags_unknown_actions_and_prepared_tokens_are_not_laundered():
    original = source()
    value = request(original)
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(value)
    object.__setattr__(original.actions[0], "splits", None)
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(request(original))
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(object())


def test_coincident_post_entry_actions_remain_unsupported():
    original = long_source(4, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    current = source(
        splits=(CapitalSplit(dates[2], D(2), "a" * 64),),
        distributions=(CapitalDistribution(dates[2], dates[2], dates[3], D(1), "c" * 64),),
    )
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(request(current))


def test_no_split_result_equals_unchanged_kernel_with_raw_prices():
    from trading_bot.research.etf_benchmark import (
        EtfBenchmarkBar,
        EtfBenchmarkRequest,
        run_etf_benchmark,
    )

    value = run(request(source(("100", "20", "21", "22"))))
    # The kernel receives raw prices unchanged when every factor is1; hashes
    # are original source identifiers, not fabricated execution quotes.
    expected = run_etf_benchmark(
        EtfBenchmarkRequest(
            tuple(
                EtfBenchmarkBar(day, D(price), D(price), bar.source_hash)
                for day, price, bar in zip(
                    value.session_dates,
                    ("20", "21", "22"),
                    value.kernel_result.request.bars,
                    strict=True,
                )
            ),
            (),
            D(100),
            D(100),
            D(5),
            D(0),
            D(0),
        )
    )
    assert value.kernel_result == expected
    assert value.kernel_result.points[-1].close_midpoint_nav == D("109.9450274862568715642178911")


@pytest.mark.parametrize(
    "friction,bps", ((".05", "2.5"), (".10", "5"), (".20", "10"), (".40", "20"))
)
def test_whole_percent_roundtrip_converts_to_halfside_bps_once(friction, bps):
    value = run(request(source(), roundtrip_friction_pct=D(friction)))
    assert value.kernel_result.request.per_side_cost_bps == D(bps)


@pytest.mark.parametrize("capital", ("100", "250", "500", "1000", "5000", "10000"))
def test_all_six_balances_remain_separate_mathematical_allocations(capital):
    value = run(request(source(), initial_cash=D(capital)))
    assert value.kernel_result.request.entry_notional == D(capital)
    assert all(p.cash_reference_nav == D(capital) for p in value.kernel_result.points)
    assert not value.economic_admitted and not value.execution_enabled


def test_oversized_intermediate_split_product_denies_not_truncates():
    original = long_source(4, flat=True)
    dates = tuple(row.session_date for row in original.calendar.sessions)
    current = source(
        splits=(
            CapitalSplit(dates[2], D("1e511"), "a" * 64),
            CapitalSplit(dates[3], D("1e-510"), "b" * 64),
        )
    )
    with pytest.raises(ValueError, match=r"^capital_passive_reference_invalid$"):
        run(request(current))
