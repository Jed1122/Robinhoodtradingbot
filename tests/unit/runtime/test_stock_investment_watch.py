"""Owned refresh inventory composition; fictional snapshots and no account I/O."""

import importlib
from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.portfolio.test_stock_allocation import NOW, context, exposure


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_investment_watch")
    except ModuleNotFoundError:
        pytest.fail("source-bound portfolio watch adapter missing")


def watch(account=None, **changes):
    return api().stock_research_watch_from_portfolio(
        context() if account is None else account,
        now=NOW,
        maximum_symbols=9,
        **changes,
    )


def test_actual_owned_names_and_explicit_watch_names_preserve_source_clock_and_hash():
    source = context(cash="900", equity="1000", exposures=(exposure("ALFA"),))
    result = watch(source, watch_symbols=("ALFA", "BETA"))
    assert result.held_symbols == ("ALFA",) and result.watch_symbols == ("BETA",)
    assert result.as_of == source.as_of and result.expires_at == source.expires_at
    assert result.source_sha256 == source.evidence_hash


def test_empty_inventory_requires_an_actual_valid_flat_snapshot():
    assert watch().held_symbols == ()
    with pytest.raises(ValueError):
        api().stock_research_watch_from_portfolio(None, now=NOW, maximum_symbols=9)


@pytest.mark.parametrize("kind", ("expired", "reconciliation", "position_join", "cash"))
def test_unverified_or_inconsistent_context_cannot_publish_a_watch(kind):
    source = context(cash="900", equity="1000", exposures=(exposure("ALFA"),))
    if kind == "expired":
        source = replace(source, as_of=NOW - timedelta(hours=2), expires_at=NOW)
    elif kind == "reconciliation":
        source = replace(source, reconciliation_hash=None)
    elif kind == "position_join":
        source = replace(source, exposures=())
    else:
        source = replace(source, account=replace(source.account, cash=source.account.cash + 1))
    with pytest.raises(ValueError):
        watch(source)


def test_capacity_is_never_filled_by_silently_dropping_owned_names():
    source = context(cash="900", equity="1000", exposures=(exposure("ALFA"),))
    with pytest.raises(ValueError):
        watch(source, watch_symbols=tuple(f"S{x}" for x in range(9)))
