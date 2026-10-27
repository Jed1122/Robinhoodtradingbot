"""Owned stock monthly reviews composed with actual current decision clocks."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.runtime.test_stock_investment_evidence import NOW, PROFILE, inputs
from trading_bot.portfolio.stock_holding import (
    StockHoldingLot,
    StockHoldingMandate,
    StockRegularSession,
    StockSaleCostAssumptions,
)
from trading_bot.research.stock_investment_decisions import (
    CurrentInvestmentPolicy,
    rank_current_stocks,
)
from trading_bot.runtime.stock_investment_evidence import build_current_stock_evidence


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_investment_holdings")
    except ModuleNotFoundError:
        pytest.fail("current owned holding review composition missing")


def owned(*, sleeve="tactical", first=None):
    first = first or datetime(2026, 9, 25, 14, tzinfo=UTC)
    mandate = StockHoldingMandate(
        "episode-ALFA", "instrument-ALFA", "ALFA", sleeve, first, "a" * 64
    )
    lot = StockHoldingLot(
        "lot-ALFA",
        mandate.episode_id,
        mandate.instrument_id,
        "ALFA",
        Decimal(10),
        Decimal(1000),
        first,
        "b" * 64,
    )
    session = StockRegularSession(
        "known_regular", NOW - timedelta(hours=6, minutes=30), NOW, NOW, "c" * 64
    )
    return api().StockOwnedHoldingContext(
        mandate=mandate,
        remaining_lots=(lot,),
        realized_gains=(),
        session=session,
        costs=StockSaleCostAssumptions(Decimal(0), Decimal(0), "d" * 64),
        as_of=NOW,
        expires_at=NOW + timedelta(minutes=5),
        source_hash="e" * 64,
        reconciliation_hash="f" * 64,
        currency="USD",
    )


def current(*, sleeve="tactical", columns=None):
    batch = build_current_stock_evidence(
        inputs(held=("ALFA",), columns=columns),
        worker_profile_id=PROFILE,
        held_sleeves=(("ALFA", sleeve),),
    )
    ranking = rank_current_stocks(
        batch.stocks,
        as_of=NOW,
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
    )
    return batch, ranking


def review(context=None, *, sleeve="tactical", columns=None):
    batch, rankings = current(sleeve=sleeve, columns=columns)
    return api().review_current_stock_holdings(
        batch,
        rankings=rankings,
        owned=(owned(sleeve=sleeve) if context is None else context,),
        reviewed_at=NOW + timedelta(minutes=1),
    )


def test_profitable_first_month_extends_from_actual_lots_and_current_research():
    result = review()
    (item,) = result.reviews
    assert item.action == "HOLD" and item.extension_approved
    assert item.review_basis == "receipt_snapshot_v1"
    assert item.price_pnl.price_pnl == Decimal(200)
    assert item.reviewed_at == NOW + timedelta(minutes=1)
    assert "indicative_provider_receipt_snapshot" in item.valuation_disclosures
    assert not result.execution_authorized and not result.live_authorized


def test_terminal_month_proposes_exit_without_a_guessed_execution_timestamp():
    result = review(owned(first=datetime(2026, 8, 25, 14, tzinfo=UTC)))
    assert result.reviews[0].action == "EXIT"
    assert result.reviews[0].reason == "two_calendar_month_terminal_review"


def test_bad_entry_feature_before_first_month_is_hold_not_an_early_exit():
    result = review(
        owned(first=datetime(2026, 10, 1, 14, tzinfo=UTC)), columns={"Provider SMA 50": "130"}
    )
    assert result.reviews[0].action == "HOLD"
    assert not result.reviews[0].extension_approved


def test_long_term_holding_has_no_monthly_profit_deadline():
    result = review(
        owned(sleeve="long_term", first=datetime(2026, 8, 25, 14, tzinfo=UTC)), sleeve="long_term"
    )
    assert result.reviews[0].action == "HOLD"
    assert result.reviews[0].reason == "long_term_has_no_monthly_profit_deadline"


def test_missing_owned_lots_cannot_be_replaced_by_an_empty_or_fictional_position():
    result = review(replace(owned(), remaining_lots=None))
    assert result.reviews[0].action == "REVIEW"
    assert result.reviews[0].price_pnl.status == "unavailable"


def test_foreign_owned_lot_is_rejected_before_a_profit_or_exit_proposal():
    context = owned()
    foreign = replace(context.remaining_lots[0], instrument_id="different")
    with pytest.raises(ValueError, match="current_stock_holdings_invalid"):
        review(replace(context, remaining_lots=(foreign,)))


def test_missing_owned_context_is_an_explicit_gap():
    batch, rankings = current()
    result = api().review_current_stock_holdings(
        batch, rankings=rankings, owned=(), reviewed_at=NOW + timedelta(minutes=1)
    )
    assert result.reviews == () and result.needs == ("owned_holding_context_missing:ALFA",)


def test_foreign_price_reference_cannot_be_relabelled_as_an_owned_loss_and_exit():
    batch, _ = current()
    stock = batch.stocks[0]
    metrics = []
    for metric in stock.metrics:
        if metric.name == "scanner_price":
            metric = replace(
                metric,
                value=Decimal(80),
                refs=(replace(metric.refs[0], symbol="FOREIGN", instrument_id="foreign-id"),),
            )
        metrics.append(metric)
    stock = replace(stock, metrics=tuple(metrics))
    batch = replace(batch, stocks=(stock,))
    rankings = rank_current_stocks(
        batch.stocks,
        as_of=NOW,
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
    )
    assert rankings.assessments[0].continuation_status == "unknown"
    result = api().review_current_stock_holdings(
        batch, rankings=rankings, owned=(owned(),), reviewed_at=NOW + timedelta(minutes=1)
    )
    assert result.reviews[0].action == "REVIEW"
    assert result.reviews[0].price_pnl.status == "unavailable"
    assert "owned_price_evidence_unusable:ALFA" in result.needs


@pytest.mark.parametrize("quote_currency", ("", "EUR"))
def test_unknown_or_foreign_quote_currency_cannot_be_combined_with_owned_usd_basis(quote_currency):
    result = review(columns={"Quotation currency": quote_currency})
    assert result.reviews[0].action == "REVIEW"
    assert result.reviews[0].price_pnl.status == "unavailable"
    assert "owned_price_evidence_unusable:ALFA" in result.needs


def test_unknown_owned_money_currency_cannot_be_inferred_from_the_ticker_or_quote():
    result = review(replace(owned(), currency=None))
    assert result.reviews[0].action == "REVIEW"
    assert result.reviews[0].price_pnl.status == "unavailable"


def test_unrelated_missing_company_fact_does_not_erase_a_valid_owned_price():
    batch, _ = current(columns={"Last": "80"})
    stock = batch.stocks[0]
    stock = replace(
        stock,
        metrics=tuple(
            replace(metric, value=None) if metric.name == "net_income" else metric
            for metric in stock.metrics
        ),
    )
    batch = replace(batch, stocks=(stock,))
    rankings = rank_current_stocks(
        batch.stocks,
        as_of=NOW,
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
    )
    result = api().review_current_stock_holdings(
        batch, rankings=rankings, owned=(owned(),), reviewed_at=NOW + timedelta(minutes=1)
    )
    assert result.reviews[0].action == "EXIT"
    assert result.reviews[0].price_pnl.price_pnl == Decimal(-200)
    assert "owned_price_evidence_unusable:ALFA" not in result.needs
