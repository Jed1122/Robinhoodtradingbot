"""Development panel arithmetic and original-owner projection boundaries."""

from datetime import date, timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request
from trading_bot.research.etf_capital_panel_models import CapitalPanelLabel
from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory


def test_paired_columns_use_fixed_capital_not_prior_nav_and_keep_all_dates():
    from trading_bot.research.etf_capital_panel import _paired_column

    candidate = (D(100), D(99), *((D(101),) * 629))
    cash = (D(100),) * 631
    value = _paired_column(candidate, cash, D(100))
    assert value == (D("-.01"), D(".02"), *((D(0),) * 628))
    # Zero/negative NAV is a valid paired USD increment, not a truncated return.
    assert _paired_column((D(1), D(0), *((D(-1),) * 629)), cash, D(100))[:3] == (
        D("-.01"),
        D("-.01"),
        D(0),
    )
    with localcontext() as context:
        context.prec = 3
        assert _paired_column(candidate, cash, D(100)) == value


@pytest.mark.parametrize(
    "candidate,reference",
    (
        ((D(100),) * 630, (D(100),) * 631),
        ((D(100),) * 631, (D(100),) * 630),
        ((100,) * 631, (D(100),) * 631),
        ((D("NaN"),) * 631, (D(100),) * 631),
    ),
)
def test_wrong_column_dimension_or_value_denies(candidate, reference):
    from trading_bot.research.etf_capital_panel import _paired_column

    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        _paired_column(candidate, reference, D(100))


def family_inputs():
    dates = tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(630))
    capitals = tuple(map(D, ("100", "250", "500", "1000", "5000", "10000")))
    costs = tuple(map(D, (".05", ".10", ".20", ".40")))
    labels = tuple(
        CapitalPanelLabel(capital, cost, path, role)
        for capital in capitals
        for cost in costs
        for path in range(29)
        for role in ("full_spy", "managed_spy", "matched_spy", "cash")
    )
    return dates, capitals, costs, labels, ((D(0),) * 630,) * 2784


def test_complete_joint_family_retains_2784_ordered_columns():
    from trading_bot.research.etf_capital_panel import _build_family

    dates, capitals, costs, labels, columns = family_inputs()
    value = _build_family(
        "trading",
        dates,
        labels,
        columns,
        capitals=capitals,
        frictions=costs,
        seed=20260710,
        draws=1,
    )
    assert len(value.labels) == len(value.columns) == len(value.column_hashes) == 2784
    assert value.labels[0] == CapitalPanelLabel(D(100), D(".05"), 0, "full_spy")
    assert value.labels[3] == CapitalPanelLabel(D(100), D(".05"), 0, "cash")
    assert value.labels[-1] == CapitalPanelLabel(D(10000), D(".40"), 28, "cash")
    assert tuple(b.comparisons for b in value.bands) == (2784, 2784)
    assert tuple(b.observations for b in value.bands) == (630, 630)
    assert all(b.independent_opportunities is None for b in value.bands)


@pytest.mark.parametrize("change", ("missing", "order", "value", "kind", "clock"))
def test_entire_family_denies_bad_path_order_or_dimension_before_math(change):
    from trading_bot.research.etf_capital_panel import _build_family

    dates, capitals, costs, labels, columns = family_inputs()
    if change == "missing":
        labels, columns = labels[:-1], columns[:-1]
    if change == "order":
        labels = (labels[1], labels[0], *labels[2:])
    if change == "value":
        columns = ((D(0),) * 629, *columns[1:])
    if change == "clock":
        dates = (dates[1], dates[0], *dates[2:])
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        _build_family(
            "reduced" if change == "kind" else "trading",
            dates,
            labels,
            columns,
            capitals=capitals,
            frictions=costs,
            seed=20260710,
            draws=1,
        )


@pytest.fixture(scope="module")
def original():
    return replay_capital_trajectory(request(long_source(206)))


def test_final_projection_keeps_tail_separate_from_test_cutoff(original):
    from trading_bot.research.etf_capital_panel import _retain_final

    value = _retain_final(original, initial_cash=D(100), test_count=3)
    assert value.complete is True and value.quantity == 0
    assert value.trading_pnl == D(".05495")
    assert value.tail_cash_change == 0 and value.tail_fee_change == 0
    assert value.account_hash == original.account.economic_hash
    assert value.risk_hash == original.risk.result_hash


@pytest.mark.parametrize("fee", (D(100), D(101), 0, D("NaN")))
def test_full_spy_fee_precondition_denies_before_preparation(fee):
    from tests.unit.simulation.test_etf_capital_walk_forward import request as walk_request
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.research.etf_capital_panel import CapitalEconomicPanelRequest, _panel_inputs

    source = long_source(206)
    terms = walk_request(source)
    panel = CapitalEconomicPanelRequest(source, terms.instruments, D(101), fee, D(0), None, None)
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        _panel_inputs(panel, _own_capital_source(source))


def test_request_cannot_supply_saved_balances_or_qualification_flags():
    from trading_bot.research.etf_capital_panel import CapitalEconomicPanelRequest

    with pytest.raises(TypeError):
        CapitalEconomicPanelRequest(None, (), None, D(0), D(0), None, None, initial_cash=D(100))
    with pytest.raises(TypeError):
        CapitalEconomicPanelRequest(None, (), None, D(0), D(0), None, None, economic_admitted=True)
