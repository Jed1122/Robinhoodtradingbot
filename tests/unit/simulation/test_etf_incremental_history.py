"""Source chunks are not terminal market events or trading authority."""

import importlib
from dataclasses import replace
from decimal import Decimal, getcontext

import pytest

from tests.unit.simulation.test_etf_native_history import request
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_native_history import run_etf_history


def run(context, source, **kwargs):
    try:
        module = importlib.import_module("trading_bot.simulation.etf_incremental_history")
    except ModuleNotFoundError:
        pytest.fail("incremental source replay is missing")
    return module.run_incremental_etf_history(
        context, iter(source), catalog_hash="a" * 64, **kwargs
    )


@pytest.mark.parametrize("chunk_size", [1, 2, 17, 10000])
def test_chunk_boundaries_preserve_complete_lifecycle_and_exact_hashes(chunk_size):
    context = request(partial=True)
    expected = run_etf_history(context)
    actual = run(context, context.dataset.events, chunk_size=chunk_size)
    assert actual.candidate == expected.candidate
    assert actual.constrained_benchmark == expected.constrained_benchmark
    assert actual.source_count == expected.source_count
    assert actual.source_prefix_hash == expected.source_prefix_hash
    assert actual.source_exhausted
    assert not actual.execution_enabled and not actual.evidence_promotable


def test_checkpoint_is_reverified_once_then_same_owner_continues():
    context = request(partial=True)
    events = context.dataset.events
    prefix = run(context, events, through_count=len(events) - 3, chunk_size=3)
    assert not prefix.source_exhausted
    assert "source_ends_inside_session" not in prefix.candidate.reasons
    resumed = run(context, events, checkpoint=prefix, chunk_size=7)
    assert resumed == run(context, events, chunk_size=2)
    with pytest.raises(ValueError):
        run(context, events, checkpoint=replace(prefix, source_prefix_hash="b" * 64))
    changed = list(events)
    changed[0] = replace(changed[0], source_hash="c" * 64)
    with pytest.raises(ValueError):
        run(context, changed, checkpoint=prefix)


def test_boolean_checkpoint_count_is_not_an_integer_cursor():
    context = request()
    prefix = run(context, context.dataset.events, through_count=1)
    with pytest.raises(ValueError):
        run(context, context.dataset.events, checkpoint=replace(prefix, source_count=True))


def test_more_than_legacy_source_bound_retains_bounded_decisions():
    context = request(close=False, reasons=("unverified",))
    template = context.dataset.events[-1]

    def source():
        yield from context.dataset.events[:-1]
        for index in range(150001):
            yield replace(
                template,
                ordinal=template.ordinal + index,
                event_at_ns=template.event_at_ns + index,
                available_at_ns=template.available_at_ns + index,
            )

    result = run(context, source())
    assert result.source_count == len(context.dataset.events) - 1 + 150001
    assert len(result.candidate.decisions) == 10000
    # One original quote precedes the replaced tail quote series.
    assert dict(result.candidate_decision_counts)["unverified"] == 150002
    assert result.candidate.account.cash == Decimal("500")
    assert not result.candidate.account.orders


def test_late_source_failure_returns_no_completed_result():
    context = request()

    def source():
        yield from context.dataset.events
        raise OSError("private provider context must not escape")

    with pytest.raises(ValueError, match=r"^etf_incremental_history_invalid$"):
        run(context, source(), chunk_size=1)


def test_source_chronology_denies_before_resetting_owner():
    context = request()
    with pytest.raises(ValueError):
        run(context, (*context.dataset.events, context.dataset.events[0]), chunk_size=1)


def test_checkpoint_boundary_does_not_leak_decimal_context():
    context = request()
    before = getcontext().prec
    try:
        getcontext().prec = 8
        run(context, context.dataset.events, through_count=10, chunk_size=2)
        assert getcontext().prec == 8
    finally:
        getcontext().prec = before


def test_holdout_is_not_evaluated():
    context = request(close=False)
    event = context.dataset.events[-1]
    from trading_bot.market_data.etf_source import _ns

    future = replace(
        event,
        ordinal=event.ordinal + 1,
        event_at_ns=_ns(context.study.holdout_start),
        available_at_ns=_ns(context.study.holdout_start),
        source_hash=content_hash("sealed holdout"),
    )
    result = run(context, (*context.dataset.events, future), chunk_size=1)
    assert result.source_count == len(context.dataset.events)
    assert result.holdout_boundary_reached and not result.source_exhausted


@pytest.mark.parametrize(
    "kwargs", [{"chunk_size": 0}, {"chunk_size": True}, {"chunk_size": 10001}, {"through_count": 0}]
)
def test_invalid_bounded_configuration_denies(kwargs):
    context = request()
    with pytest.raises(ValueError):
        run(context, context.dataset.events, **kwargs)
