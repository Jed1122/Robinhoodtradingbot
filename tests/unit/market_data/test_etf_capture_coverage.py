"""Pure request planning: transport declarations never become market qualification."""

import importlib
from dataclasses import FrozenInstanceError, replace

import pytest

DAY = 86_400_000_000_000


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_capture_coverage")
    except ModuleNotFoundError:
        pytest.fail("pure native capture coverage planner is not implemented")


def interval(start, end):
    return api().CaptureInterval(start, end)


def attempt(start, end, status="complete_nonempty", identity="a", records=1, pages=1):
    return api().CaptureAttempt(interval(start, end), identity * 64, status, records, pages)


def plan(required=((0, 16),), attempts=(), maximum=16, minimum=1):
    return api().plan_quote_coverage(
        tuple(interval(*row) for row in required),
        tuple(attempts),
        maximum_window_ns=maximum,
        minimum_window_ns=minimum,
    )


def bounds(intervals):
    return tuple((row.start_ns, row.end_ns) for row in intervals)


def test_missing_requests_use_exact_deterministic_bisection():
    result = plan(required=((0, 17),), maximum=5)
    assert bounds(result.missing_requests) == ((0, 4), (4, 8), (8, 12), (12, 17))
    assert result.missing_request_count == 4
    assert result.required_duration_ns == 17
    assert not result.blocked_intervals


def test_only_complete_nonempty_spans_remove_requested_intervals():
    result = plan(attempts=(attempt(3, 6), attempt(8, 16, identity="b")))
    assert bounds(result.missing_requests) == ((0, 3), (6, 8))
    assert bounds(result.covered_intervals) == ((3, 6), (8, 16))
    assert result.covered_duration_ns == 11
    assert result.record_count_known_total == 2


def test_one_nanosecond_gap_is_not_rounded_away():
    result = plan(attempts=(attempt(0, 8), attempt(9, 16, identity="b")))
    assert bounds(result.missing_requests) == ((8, 9),)


def test_empty_completion_stops_reacquisition_without_counting_coverage():
    result = plan(attempts=(attempt(4, 12, "complete_empty", records=0),))
    assert bounds(result.missing_requests) == ((0, 4), (12, 16))
    assert bounds(result.empty_intervals) == ((4, 12),)
    assert result.covered_duration_ns == 0
    assert result.empty_attempt_count == 1


@pytest.mark.parametrize("status", ["failed", "uncertain"])
def test_failure_or_uncertainty_blocks_overlapping_required_span(status):
    result = plan(required=((5, 20),), attempts=(attempt(0, 10, status, records=None, pages=None),))
    assert bounds(result.blocked_intervals) == ((5, 10),)
    assert bounds(result.missing_requests) == ((10, 20),)
    assert result.record_count_known_total == 0
    assert result.record_count_unknown_attempts == 1
    assert result.page_count_unknown_attempts == 1


def test_absent_and_measured_zero_counts_have_distinct_plan_identity():
    unknown = plan(attempts=(attempt(0, 16, "uncertain", records=None, pages=None),))
    observed = plan(attempts=(attempt(0, 16, "uncertain", records=0, pages=0),))
    assert unknown.plan_hash != observed.plan_hash
    assert unknown.record_count_unknown_attempts == 1
    assert observed.record_count_unknown_attempts == 0


def test_page_limit_does_not_credit_any_observed_prefix():
    result = plan(attempts=(attempt(0, 16, "page_limit", records=128000, pages=128),))
    assert bounds(result.missing_requests) == ((0, 8), (8, 16))
    assert result.covered_duration_ns == 0
    assert result.page_limit_attempt_count == 1


def test_nested_page_limits_resume_only_unfinished_exact_children():
    result = plan(
        attempts=(
            attempt(0, 16, "page_limit"),
            attempt(0, 8, "page_limit", identity="b"),
            attempt(0, 4, identity="c"),
            attempt(8, 16, identity="d"),
        )
    )
    assert bounds(result.missing_requests) == ((4, 8),)
    assert bounds(result.covered_intervals) == ((0, 4), (8, 16))


def test_valid_deeper_children_need_not_invent_intermediate_attempts():
    result = plan(attempts=(attempt(0, 16, "page_limit"), attempt(0, 4, identity="b")))
    assert bounds(result.missing_requests) == ((4, 8), (8, 16))


def test_page_limit_partial_scope_never_expands_or_uses_arbitrary_clipped_child():
    result = plan(required=((3, 11),), attempts=(attempt(0, 16, "page_limit"),), minimum=2)
    assert bounds(result.missing_requests) == ((4, 8), (8, 10))
    assert bounds(result.blocked_intervals) == ((3, 4), (10, 11))


def test_page_limit_that_cannot_split_above_minimum_is_blocked():
    result = plan(required=((0, 7),), attempts=(attempt(0, 7, "page_limit"),), minimum=4)
    assert not result.missing_requests
    assert bounds(result.blocked_intervals) == ((0, 7),)


def test_one_nanosecond_page_limit_cannot_be_retried():
    result = plan(required=((0, 1),), attempts=(attempt(0, 1, "page_limit"),))
    assert not result.missing_requests
    assert bounds(result.blocked_intervals) == ((0, 1),)


def test_unrequested_failed_interval_does_not_block_another_scope():
    result = plan(required=((16, 24),), attempts=(attempt(0, 16, "failed", records=None),))
    assert bounds(result.missing_requests) == ((16, 24),)
    assert not result.blocked_intervals


def test_input_order_cannot_change_plan_or_hash():
    attempts = (attempt(0, 8), attempt(16, 24, identity="b"))
    first = plan(required=((0, 16), (16, 32)), attempts=attempts)
    second = plan(required=((16, 32), (0, 16)), attempts=tuple(reversed(attempts)))
    assert first == second
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_hash_binds_request_policy_and_attempt_evidence():
    original = plan(attempts=(attempt(0, 16),))
    assert original.plan_hash != plan(attempts=(attempt(0, 16, identity="b"),)).plan_hash
    assert original.plan_hash != plan(attempts=(attempt(0, 16, records=2),)).plan_hash
    assert original.plan_hash != plan(attempts=(attempt(0, 16),), maximum=8).plan_hash
    assert original.plan_hash != plan(attempts=(attempt(0, 16),), minimum=2).plan_hash


def test_complete_requested_coverage_remains_unqualified_and_immutable():
    result = plan(attempts=(attempt(0, 16),))
    assert not result.missing_requests
    assert result.source_qualified is False
    assert result.cost_qualified is False
    assert result.execution_enabled is False
    assert result.evidence_promotable is False
    assert result.market_coverage_complete is False
    with pytest.raises(FrozenInstanceError):
        result.required = ()
    with pytest.raises(TypeError):
        api().CaptureAttempt(
            interval(0, 16), "a" * 64, "complete_nonempty", 1, 1, source_qualified=True
        )


@pytest.mark.parametrize(
    "start,end",
    [
        (True, 2),
        (0, False),
        (0.0, 2),
        (0, 2.0),
        (-1, 1),
        (2, 2),
        (3, 2),
        (DAY - 1, DAY + 1),
        (0, 2**63),
    ],
)
def test_interval_denies_inexact_or_cross_utc_day_bounds(start, end):
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        interval(start, end)


def test_exact_utc_midnight_boundary_is_allowed_without_crossing_days():
    result = plan(required=((DAY - 3, DAY), (DAY, DAY + 3)), maximum=3)
    assert bounds(result.missing_requests) == ((DAY - 3, DAY), (DAY, DAY + 3))


@pytest.mark.parametrize(
    "changes",
    [
        {"manifest_sha256": "A" * 64},
        {"manifest_sha256": "secret"},
        {"status": "qualified"},
        {"status": True},
        {"record_count": True},
        {"record_count": -1},
        {"record_count": 128001},
        {"page_count": 129},
        {"page_count": False},
        {"record_count": 1001, "page_count": 1},
        {"record_count": 0},
        {"record_count": None},
        {"page_count": None},
        {"status": "complete_empty", "record_count": 1},
        {"status": "page_limit", "record_count": None},
    ],
)
def test_attempt_denies_conflicting_status_or_counts(changes):
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        replace(attempt(0, 16), **changes)


@pytest.mark.parametrize(
    "maximum,minimum", [(0, 1), (1, 0), (2, 3), (True, 1), (8, 1.0), (DAY + 1, 1)]
)
def test_invalid_window_policy_denies(maximum, minimum):
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        plan(maximum=maximum, minimum=minimum)


@pytest.mark.parametrize(
    "attempts",
    [
        lambda: (attempt(0, 10), attempt(9, 16, identity="b")),
        lambda: (attempt(0, 10), attempt(10, 16)),
        lambda: (attempt(0, 16), attempt(0, 16, identity="b")),
        lambda: (attempt(0, 16), attempt(0, 8, identity="b")),
        lambda: (attempt(0, 16, "failed"), attempt(0, 8, identity="b")),
        lambda: (attempt(0, 16, "page_limit"), attempt(0, 7, identity="b")),
        lambda: (attempt(0, 16, "page_limit"), attempt(7, 12, identity="b")),
    ],
)
def test_overlapping_or_reused_attempt_identity_denies(attempts):
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        plan(attempts=attempts())


def test_required_intervals_cannot_overlap_or_repeat():
    for ranges in (((0, 16), (15, 20)), ((0, 16), (0, 16))):
        with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
            plan(required=ranges)


@pytest.mark.parametrize("field", ["required", "attempts"])
def test_arbitrary_containers_are_not_parsed_as_inputs(field):
    kwargs = {"required": (interval(0, 16),), "attempts": ()}
    kwargs[field] = {"credential_file": "not opened"}
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        api().plan_quote_coverage(**kwargs, maximum_window_ns=16, minimum_window_ns=1)


def test_forged_nested_input_is_revalidated():
    item = attempt(0, 16)
    object.__setattr__(item.request, "end_ns", True)
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        plan(attempts=(item,))


def test_derived_more_than_1024_requests_in_one_day_denies():
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        plan(required=((0, 1025),), maximum=1)


def test_4001_required_days_deny_without_building_unbounded_output():
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        plan(required=tuple((day * DAY, day * DAY + 1) for day in range(4001)))


def test_1025_attempts_in_one_day_deny():
    attempts = tuple(
        api().CaptureAttempt(interval(i, i + 1), f"{i:064x}", "complete_nonempty", 1, 1)
        for i in range(1025)
    )
    with pytest.raises(ValueError, match="etf_capture_coverage_invalid"):
        plan(required=((0, 1025),), attempts=attempts)


def test_empty_required_scope_has_no_implicit_acquisition():
    result = plan(required=())
    assert not result.missing_requests
    assert result.required_duration_ns == 0


def test_planner_cannot_open_files_or_construct_network(monkeypatch):
    m = api()
    import builtins
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("pure planning attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    result = m.plan_quote_coverage((m.CaptureInterval(0, 16),), (), 8, 1)
    assert bounds(result.missing_requests) == ((0, 8), (8, 16))
