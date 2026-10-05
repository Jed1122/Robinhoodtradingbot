"""Source chunks are not terminal market events or trading authority."""

import importlib
from dataclasses import replace
from datetime import timedelta
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


@pytest.mark.parametrize("chunk_size", [1, 10000])
@pytest.mark.parametrize("resume", [False, True])
def test_duplicate_session_date_cannot_accelerate_settlement(chunk_size, resume):
    context = request()
    events = list(context.dataset.events)
    opening = next(event for event in events if event.kind == "session")
    assert opening.clock is not None
    events[-1] = replace(
        events[-1],
        event_at_ns=opening.event_at_ns + 1_000_000_000,
        available_at_ns=opening.event_at_ns + 1_000_000_000,
        clock=replace(opening.clock, observed_at=opening.clock.observed_at + timedelta(seconds=1)),
    )
    with pytest.raises(ValueError):
        replace(context.dataset, events=tuple(events))
    checkpoint = None
    if resume:
        checkpoint = run(context, events, through_count=len(events) - 1, chunk_size=chunk_size)
        assert checkpoint.candidate.account.unsettled
        assert not checkpoint.candidate.account.complete
    with pytest.raises(ValueError, match=r"^etf_incremental_history_invalid$"):
        run(context, events, checkpoint=checkpoint, chunk_size=chunk_size)


@pytest.mark.parametrize("resume", [False, True])
def test_source_reason_cardinality_overflow_returns_no_result(monkeypatch, resume):
    module = importlib.import_module("trading_bot.simulation.etf_incremental_history")
    monkeypatch.setattr(module, "MAX_SOURCE_REASONS", 8, raising=False)
    context = request(close=False, reasons=("blocked-0",))
    template = context.dataset.events[-1]
    events = list(context.dataset.events[:-1])
    events.extend(
        replace(
            template,
            ordinal=template.ordinal + index,
            event_at_ns=template.event_at_ns + index,
            available_at_ns=template.available_at_ns + index,
            execution_reasons=(f"blocked-{index}",),
        )
        for index in range(9)
    )
    prefix = run(context, events, through_count=len(events) - 1, chunk_size=1)
    assert dict(prefix.candidate_decision_counts)["blocked-0"] == 2
    assert len(dict(prefix.candidate_decision_counts)) <= 10
    with pytest.raises(ValueError, match=r"^etf_incremental_history_invalid$"):
        run(context, events, checkpoint=prefix if resume else None, chunk_size=1)


@pytest.mark.parametrize("kind", ["bar", "dividend_ex"])
@pytest.mark.parametrize("resume", [False, True])
def test_nonquote_baseline_overflow_returns_no_result(monkeypatch, kind, resume):
    module = importlib.import_module("trading_bot.simulation.etf_incremental_history")
    monkeypatch.setattr(module, "MAX_BASELINE_EVENTS", 3, raising=False)
    context = request(close=False)
    template = context.dataset.events[0]
    values = {"kind": kind}
    if kind == "dividend_ex":
        values.update(bar=None, cash_per_share=Decimal(".1"))
    events = tuple(
        replace(
            template,
            ordinal=index,
            event_at_ns=template.event_at_ns + (index if kind == "dividend_ex" else 0),
            available_at_ns=template.available_at_ns + index + (1 if kind == "dividend_ex" else 0),
            **values,
            **({"action_id": content_hash(index)} if kind == "dividend_ex" else {}),
        )
        for index in range(4)
    )
    prefix = run(context, events, through_count=3, chunk_size=1)
    with pytest.raises(ValueError, match=r"^etf_incremental_history_invalid$"):
        run(context, events, checkpoint=prefix if resume else None, chunk_size=1)
