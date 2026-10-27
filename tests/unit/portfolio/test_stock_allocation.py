"""Short fictional cash allocation contexts; no broker or actual portfolio."""

import importlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain.accounts import (
    AccountSnapshot,
    AssetBuyingPower,
    PortfolioSnapshot,
    Position,
)
from trading_bot.domain.enums import AssetClass

D = Decimal
NOW = datetime(2026, 10, 26, 20, tzinfo=UTC)
MODULE = "trading_bot.portfolio.stock_allocation"


def api():
    assert importlib.util.find_spec(MODULE) is not None, "pure stock allocation planner missing"
    return importlib.import_module(MODULE)


def candidate(
    symbol, *, sleeve="long_term", issuer=None, sector="technology", priority=0, status="eligible"
):
    return api().StockAllocationCandidate(
        "instrument-" + symbol,
        symbol,
        issuer or "issuer-" + symbol,
        sleeve,
        sector,
        "stock",
        priority,
        status,
        "a" * 64,
        "b" * 64,
        NOW,
        NOW + timedelta(minutes=5),
    )


def exposure(
    symbol,
    *,
    origin="position",
    sleeve="long_term",
    issuer=None,
    sector="technology",
    notional="100",
    reserve="0",
    reference=None,
):
    return api().StockAllocationExposure(
        reference or origin + "-" + symbol,
        origin,
        "instrument-" + symbol,
        symbol,
        issuer or "issuer-" + symbol,
        sleeve,
        sector,
        "stock",
        D(notional),
        D(reserve),
        "c" * 64,
    )


def context(
    *,
    cash="1000",
    equity="1000",
    bp="1000",
    unleveraged=None,
    tax="0",
    account_type="cash",
    exposures=(),
):
    held = tuple(x for x in exposures if x.origin == "position")
    positions = tuple(
        Position(
            "account-1",
            x.instrument_id,
            AssetClass.EQUITY,
            D(1),
            None,
            x.remaining_notional,
            NOW,
            "d" * 64,
        )
        for x in held
    )
    gross = sum((p.market_value for p in positions), D(0))
    account = AccountSnapshot(
        "account-1",
        "active",
        D(equity),
        D(cash),
        (AssetBuyingPower(AssetClass.EQUITY, D(bp)),),
        False,
        NOW,
        "e" * 64,
    )
    portfolio = PortfolioSnapshot(
        "account-1", positions, D(cash), D(equity), gross, gross, D(0), D(0), D(0), NOW, "f" * 64
    )
    return api().StockAllocationContext(
        account,
        portfolio,
        account_type,
        "USD",
        D(bp) if unleveraged is None else D(unleveraged),
        None if tax is None else D(tax),
        "1" * 64,
        tuple(exposures),
        NOW,
        NOW + timedelta(minutes=5),
        "2" * 64,
    )


def plan(ctx=None, candidates=()):
    return api().plan_stock_allocations(ctx or context(), tuple(candidates), now=NOW)


def test_default_1000_context_allocates_capped_cash_without_requiring_a_long_term_stop():
    result = plan(
        candidates=(
            candidate("AXP"),
            candidate("KO", sector="staples"),
            candidate("MCO", sleeve="tactical", sector="financials"),
        )
    )
    assert result.status == "planned" and result.cash_cap == 900
    assert [(p.symbol, p.cash_ceiling) for p in result.proposals] == [
        ("AXP", D(100)),
        ("KO", D(100)),
        ("MCO", D(40)),
    ]
    assert result.remaining_cash_cap == 660 and result.total_proposed == 240
    assert (
        result.execution_authorized is result.reservations_created is result.orders_created is False
    )


def test_insufficient_candidates_leave_cash_instead_of_filling_75_percent_with_one_stock():
    result = plan(candidates=(candidate("AXP"),))
    assert result.proposals[0].cash_ceiling == 100 and result.remaining_cash_cap == 800


def test_long_and_tactical_targets_share_one_cash_cap():
    names = ("AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH", "II", "JJ")
    longs = tuple(
        candidate(s, sector="sector-" + str(i // 2), priority=i) for i, s in enumerate(names)
    )
    tacs = tuple(
        candidate(s + "T", sleeve="tactical", sector="tactical-" + str(i), priority=i)
        for i, s in enumerate(names[:4])
    )
    result = plan(candidates=(*longs, *tacs))
    assert sum((x.cash_ceiling for x in result.proposals if x.sleeve == "long_term"), D(0)) == 750
    assert sum((x.cash_ceiling for x in result.proposals if x.sleeve == "tactical"), D(0)) == 150
    assert result.total_proposed == 900 and result.remaining_cash_cap == 0


def test_broker_pending_holds_are_not_subtracted_twice_but_local_holds_are():
    rows = (
        exposure("KO", origin="broker_pending", sector="staples"),
        exposure("MCO", origin="local_reserved", sector="financials", reserve="101"),
    )
    result = plan(context(bp="900", tax="25", exposures=rows))
    assert result.cash_cap == 674  # 900 -100 strategic -25tax -101local.
    assert result.remaining_cash_cap == 674


def test_pending_and_owned_issuer_exposure_count_toward_company_and_sector_caps():
    rows = (exposure("GOOG", notional="60"),)
    result = plan(
        context(cash="940", exposures=rows),
        (candidate("GOOGL", issuer="issuer-GOOG"), candidate("MSFT")),
    )
    assert [x.cash_ceiling for x in result.proposals] == [D(40), D(100)]


def test_held_pending_and_cross_sleeve_symbols_cannot_receive_overlapping_new_entries():
    rows = (exposure("KO", origin="broker_pending", sector="staples"),)
    result = plan(
        context(bp="900", exposures=rows),
        (
            candidate("KO", sleeve="tactical", sector="staples"),
            candidate("AXP"),
            candidate("AXP", sleeve="tactical"),
        ),
    )
    assert [(x.symbol, x.sleeve) for x in result.proposals] == [("AXP", "long_term")]
    assert {x.reason for x in result.denials} >= {
        "held_or_pending_symbol",
        "proposed_symbol_overlap",
    }


@pytest.mark.parametrize("account_type", [None, "margin"])
def test_unknown_or_margin_account_type_blocks_without_cash_inference(account_type):
    result = plan(context(account_type=account_type), (candidate("AXP"),))
    assert result.status == "blocked" and result.proposals == ()


def test_supplied_cash_buying_power_cannot_exceed_broker_equity_buying_power():
    result = plan(context(unleveraged="1001"), (candidate("AXP"),))
    assert result.status == "blocked" and "contradictory_buying_power" in result.reason_codes


def test_unknown_current_encumbrance_blocks_and_empty_candidates_are_a_valid_cash_choice():
    result = plan(context(tax=None), (candidate("AXP"),))
    assert result.status == "blocked" and not result.proposals
    empty = plan()
    assert empty.status == "planned" and empty.proposals == () and empty.total_proposed == 0


def test_existing_cross_sleeve_owned_pending_symbol_blocks_new_entry_planning():
    rows = (
        exposure("AXP"),
        exposure("AXP", origin="local_reserved", sleeve="tactical", notional="5", reserve="5"),
    )
    result = plan(
        context(cash="900", bp="895", exposures=rows), (candidate("KO", sector="staples"),)
    )
    assert result.status == "blocked" and not result.proposals
    assert "existing_cross_sleeve_symbol" in result.reason_codes


def test_sector_cap_includes_broker_pending_and_prior_proposals():
    rows = (
        exposure("AXP", notional="200"),
        exposure("MCO", origin="broker_pending", notional="40"),
    )
    result = plan(
        context(cash="800", bp="760", exposures=rows), (candidate("KO"), candidate("CVX"))
    )
    assert [(x.symbol, x.cash_ceiling) for x in result.proposals] == [("CVX", D(10))]
    assert any(x.reason == "sector_cap_reached" for x in result.denials)


@pytest.mark.parametrize("changed", ["sector", "issuer", "reservation", "source"])
def test_unknown_owned_exposure_blocks_context(changed):
    row = exposure("AXP")
    row = replace(
        row,
        **{
            dict(
                sector="sector",
                issuer="issuer_id",
                reservation="local_cash_reservation",
                source="source_hash",
            )[changed]: None
        },
    )
    result = plan(context(cash="900", exposures=(row,)), (candidate("KO", sector="staples"),))
    assert result.status == "blocked" and result.proposals == ()


def test_unknown_candidate_is_denied_without_discarding_supported_other_candidates():
    result = plan(
        candidates=(replace(candidate("AXP"), sector=None), candidate("KO", sector="staples"))
    )
    assert [x.symbol for x in result.proposals] == ["KO"]
    assert result.denials[0].reason == "candidate_metadata_unknown"


@pytest.mark.parametrize("changed", ["expired_context", "expired_candidate", "future_candidate"])
def test_source_expiry_and_future_decisions_do_not_create_spendable_authority(changed):
    ctx, row = context(), candidate("AXP")
    if changed == "expired_context":
        result = api().plan_stock_allocations(ctx, (row,), now=ctx.expires_at)
    elif changed == "expired_candidate":
        row = replace(row, as_of=NOW - timedelta(minutes=1), expires_at=NOW)
        result = plan(ctx, (row,))
    else:
        row = replace(row, as_of=NOW + timedelta(seconds=1))
        result = plan(ctx, (row,))
    assert not result.proposals
    assert result.status == ("blocked" if changed == "expired_context" else "planned")


def test_position_metadata_is_an_exact_join_not_an_extra_value_ledger():
    ctx = context(cash="900", exposures=(exposure("AXP"),))
    with pytest.raises(ValueError, match="join"):
        plan(replace(ctx, exposures=()), (candidate("KO"),))
    with pytest.raises(ValueError, match="value"):
        plan(
            replace(ctx, exposures=(replace(ctx.exposures[0], remaining_notional=D(99)),)),
            (candidate("KO"),),
        )


def test_duplicate_or_conflicting_candidate_identity_cannot_create_double_budgets():
    row = candidate("AXP")
    assert plan(candidates=(row, row)).proposals == plan(candidates=(row,)).proposals
    with pytest.raises(ValueError, match="conflicting_duplicate"):
        plan(candidates=(row, replace(row, priority=1)))
    with pytest.raises(ValueError, match="identity_conflict"):
        plan(
            candidates=(
                row,
                replace(candidate("KO"), instrument_id=row.instrument_id, sleeve="tactical"),
            )
        )


def test_broker_reflected_cash_hold_cannot_be_subtracted_as_local_cash_again():
    with pytest.raises(ValueError, match="broker_reflected"):
        exposure("AXP", origin="broker_pending", reserve="1")
    with pytest.raises(ValueError, match="below_exposure"):
        exposure("AXP", origin="local_reserved", reserve="99")


def test_manual_limits_can_only_be_stricter_and_do_not_increase_targets():
    m = api()
    with pytest.raises(ValueError, match="hard_cap"):
        m.StockAllocationLimits(company_cap=D(".11"))
    with pytest.raises(ValueError, match="reserve"):
        m.StockAllocationLimits(strategic_reserve=D(".09"))
    result = m.plan_stock_allocations(
        context(),
        (candidate("AXP"),),
        now=NOW,
        limits=m.StockAllocationLimits(company_cap=D(".05")),
    )
    assert result.proposals[0].cash_ceiling == 50


def test_debit_ceilings_round_down_to_cents_and_own_the_decimal_context():
    from decimal import ROUND_DOWN, localcontext

    ctx = context(equity="1000.09", cash="1000.09", bp="1000.09")
    result = plan(ctx, (candidate("AXP"),))
    assert result.cash_cap == D("900.08") and result.proposals[0].cash_ceiling == D("100.00")
    with localcontext() as precision:
        precision.prec, precision.rounding, precision.capitals = 4, ROUND_DOWN, 0
        actual = plan(ctx, (candidate("AXP"),))
        assert actual == result and actual.evidence_hash == result.evidence_hash


def test_candidate_order_does_not_change_priority_allocation_results():
    rows = (candidate("KO", priority=1, sector="staples"), candidate("AXP", priority=0))
    assert plan(candidates=rows).proposals == plan(candidates=tuple(reversed(rows))).proposals


def test_unknown_equity_buying_power_and_unsupported_exposure_fail_closed():
    ctx = context()
    duplicate = replace(
        ctx.account, buying_power=(*ctx.account.buying_power, *ctx.account.buying_power)
    )
    assert plan(replace(ctx, account=duplicate)).status == "blocked"
    held = context(cash="900", exposures=(exposure("AXP"),))
    result = plan(
        replace(held, exposures=(replace(held.exposures[0], instrument_kind="unsupported"),))
    )
    assert result.status == "blocked"


def test_result_cannot_claim_reservations_or_order_authority():
    result = plan(candidates=(candidate("AXP"),))
    object.__setattr__(result, "reservations_created", True)
    with pytest.raises(ValueError, match="scope"):
        _ = result.evidence_hash


@pytest.mark.parametrize(("cash", "equity"), [("600", "1000"), ("600", "600.000001")])
def test_unexplained_equity_cannot_hide_exposure_or_become_new_entry_capacity(cash, equity):
    result = plan(context(cash=cash, bp=cash, equity=equity), (candidate("AXP"),))
    assert result.status == "blocked" and result.proposals == ()
    assert "unexplained_portfolio_equity" in result.reason_codes


def test_future_nested_position_cannot_be_used_inside_an_older_current_portfolio():
    ctx = context(cash="900", exposures=(exposure("AXP"),))
    future = replace(ctx.portfolio.positions[0], observed_at=NOW + timedelta(days=1))
    nested = replace(ctx.portfolio, positions=(future,))
    with pytest.raises(ValueError, match="position"):
        plan(replace(ctx, portfolio=nested), (candidate("KO", sector="staples"),))


def test_nested_position_is_revalidated_instead_of_trusting_parent_type_only():
    ctx = context(cash="900", exposures=(exposure("AXP"),))
    object.__setattr__(ctx.portfolio.positions[0], "observed_at", datetime(2026, 10, 26))
    with pytest.raises(ValueError):
        plan(ctx, (candidate("KO", sector="staples"),))


def test_duplicate_position_instrument_ids_do_not_get_silently_dict_overwritten():
    ctx = context(cash="900", exposures=(exposure("AXP"),))
    duplicate = replace(
        ctx.portfolio, positions=(*ctx.portfolio.positions, *ctx.portfolio.positions)
    )
    with pytest.raises(ValueError, match="duplicate_current_position"):
        plan(replace(ctx, portfolio=duplicate), (candidate("KO", sector="staples"),))
