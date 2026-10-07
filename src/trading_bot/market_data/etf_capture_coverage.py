"""Pure, bounded native quote request planning, not acquisition or source admission.

Inputs are declarations supplied by an acquisition owner. This module does not
verify receipts, select study sessions, inspect clocks, access files or grant
authority. Complete request spans never prove market or executable coverage.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from trading_bot.market_data.recording import content_hash

_DAY_NS = 86_400_000_000_000
_MAX_DAYS = 4000
_MAX_DAY_INTERVALS = 1024
_MAX_INTERVALS = _MAX_DAYS * _MAX_DAY_INTERVALS
_STATUSES = frozenset(("complete_nonempty", "complete_empty", "page_limit", "failed", "uncertain"))
type CaptureStatus = Literal[
    "complete_nonempty", "complete_empty", "page_limit", "failed", "uncertain"
]


class CaptureCoverageError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_capture_coverage_invalid")


def _require(condition: bool) -> None:
    if not condition:
        raise CaptureCoverageError()


def _integer(value: object, maximum: int, minimum: int = 0) -> None:
    _require(type(value) is int and minimum <= value <= maximum)


@dataclass(frozen=True, slots=True, order=True)
class CaptureInterval:
    """Exact half-open nanosecond interval wholly within one UTC day."""

    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        _integer(self.start_ns, 2**63 - 1)
        _integer(self.end_ns, 2**63 - 1)
        _require(self.start_ns < self.end_ns)
        _require(self.start_ns // _DAY_NS == (self.end_ns - 1) // _DAY_NS)


@dataclass(frozen=True, slots=True)
class CaptureAttempt:
    """Manifest-bound outcome declaration; absent counts are never filled with zero."""

    request: CaptureInterval
    manifest_sha256: str
    status: CaptureStatus
    record_count: int | None
    page_count: int | None

    def __post_init__(self) -> None:
        _require(type(self.request) is CaptureInterval)
        self.request.__post_init__()
        _require(
            type(self.manifest_sha256) is str
            and re.fullmatch(r"[a-f0-9]{64}", self.manifest_sha256) is not None
        )
        _require(type(self.status) is str and self.status in _STATUSES)
        if self.record_count is not None:
            _integer(self.record_count, 128000)
        if self.page_count is not None:
            _integer(self.page_count, 128)
        if self.record_count is not None and self.page_count is not None:
            _require(self.record_count <= self.page_count * 1000)
        if self.status in ("complete_nonempty", "complete_empty", "page_limit"):
            _require(self.record_count is not None and self.page_count is not None)
            _require(self.page_count is not None and self.page_count > 0)
        if self.status == "complete_nonempty":
            _require(self.record_count is not None and self.record_count > 0)
        if self.status == "complete_empty":
            _require(self.record_count == 0)


@dataclass(frozen=True, slots=True)
class QuoteCoveragePlan:
    required: tuple[CaptureInterval, ...]
    attempts: tuple[CaptureAttempt, ...]
    maximum_window_ns: int
    minimum_window_ns: int
    missing_requests: tuple[CaptureInterval, ...]
    covered_intervals: tuple[CaptureInterval, ...]
    empty_intervals: tuple[CaptureInterval, ...]
    blocked_intervals: tuple[CaptureInterval, ...]
    schema: Literal["etf-native-capture-coverage-v1"] = field(
        default="etf-native-capture-coverage-v1", init=False
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    market_coverage_complete: Literal[False] = field(default=False, init=False)

    @property
    def plan_hash(self) -> str:
        return content_hash(self)

    @property
    def missing_request_count(self) -> int:
        return len(self.missing_requests)

    @property
    def required_duration_ns(self) -> int:
        return sum(row.end_ns - row.start_ns for row in self.required)

    @property
    def covered_duration_ns(self) -> int:
        return sum(row.end_ns - row.start_ns for row in self.covered_intervals)

    @property
    def empty_attempt_count(self) -> int:
        return sum(row.status == "complete_empty" for row in self.attempts)

    @property
    def page_limit_attempt_count(self) -> int:
        return sum(row.status == "page_limit" for row in self.attempts)

    @property
    def record_count_known_total(self) -> int:
        return sum(row.record_count for row in self.attempts if row.record_count is not None)

    @property
    def record_count_unknown_attempts(self) -> int:
        return sum(row.record_count is None for row in self.attempts)

    @property
    def page_count_known_total(self) -> int:
        return sum(row.page_count for row in self.attempts if row.page_count is not None)

    @property
    def page_count_unknown_attempts(self) -> int:
        return sum(row.page_count is None for row in self.attempts)


def _bounded(rows: tuple[CaptureInterval, ...], *, disjoint: bool) -> None:
    _require(type(rows) is tuple and len(rows) <= _MAX_INTERVALS)
    counts: Counter[int] = Counter()
    previous: CaptureInterval | None = None
    for row in rows:
        _require(type(row) is CaptureInterval)
        row.__post_init__()
        day = row.start_ns // _DAY_NS
        counts[day] += 1
        _require(counts[day] <= _MAX_DAY_INTERVALS and len(counts) <= _MAX_DAYS)
        if previous is not None and disjoint:
            _require(previous.end_ns <= row.start_ns)
        previous = row


def _dyadic_descendant(parent: CaptureInterval, child: CaptureInterval) -> bool:
    start, end = parent.start_ns, parent.end_ns
    while end - start > 1:
        middle = (start + end) // 2
        if child.end_ns <= middle:
            end = middle
        elif child.start_ns >= middle:
            start = middle
        else:
            return False
        if child.start_ns == start and child.end_ns == end:
            return True
    return False


def _attempt_roots(attempts: tuple[CaptureAttempt, ...]) -> tuple[CaptureInterval, ...]:
    """Only page-limited ancestors may overlap exact bisection descendants."""
    _bounded(tuple(row.request for row in attempts), disjoint=False)
    digests: set[str] = set()
    stack: list[CaptureAttempt] = []
    roots = []
    for item in attempts:
        _require(item.manifest_sha256 not in digests)
        digests.add(item.manifest_sha256)
        while stack and stack[-1].request.end_ns <= item.request.start_ns:
            stack.pop()
        if stack:
            parent = stack[-1]
            _require(
                parent.status == "page_limit" and _dyadic_descendant(parent.request, item.request)
            )
        elif item.status == "page_limit":
            roots.append(item.request)
        stack.append(item)
    return tuple(roots)


def _merge(rows: tuple[CaptureInterval, ...]) -> tuple[CaptureInterval, ...]:
    merged: list[CaptureInterval] = []
    for row in sorted(rows):
        if (
            merged
            and merged[-1].end_ns == row.start_ns
            and merged[-1].start_ns // _DAY_NS == row.start_ns // _DAY_NS
        ):
            merged[-1] = CaptureInterval(merged[-1].start_ns, row.end_ns)
        else:
            merged.append(row)
    return tuple(merged)


def _intersections(
    left: tuple[CaptureInterval, ...], right: tuple[CaptureInterval, ...]
) -> tuple[CaptureInterval, ...]:
    result = []
    first = second = 0
    while first < len(left) and second < len(right):
        a, b = left[first], right[second]
        start, end = max(a.start_ns, b.start_ns), min(a.end_ns, b.end_ns)
        if start < end:
            result.append(CaptureInterval(start, end))
        if a.end_ns <= b.end_ns:
            first += 1
        else:
            second += 1
    return _merge(tuple(result))


def _subtract(
    required: tuple[CaptureInterval, ...], excluded: tuple[CaptureInterval, ...]
) -> tuple[CaptureInterval, ...]:
    result = []
    index = 0
    for row in required:
        cursor = row.start_ns
        while index < len(excluded) and excluded[index].end_ns <= cursor:
            index += 1
        current = index
        while current < len(excluded) and excluded[current].start_ns < row.end_ns:
            other = excluded[current]
            if cursor < other.start_ns:
                result.append(CaptureInterval(cursor, other.start_ns))
            cursor = max(cursor, other.end_ns)
            current += 1
        if cursor < row.end_ns:
            result.append(CaptureInterval(cursor, row.end_ns))
    return tuple(result)


def _requests(
    gaps: tuple[CaptureInterval, ...],
    roots: tuple[CaptureInterval, ...],
    limited: tuple[CaptureInterval, ...],
    maximum: int,
    minimum: int,
) -> tuple[tuple[CaptureInterval, ...], tuple[CaptureInterval, ...]]:
    requests: list[CaptureInterval] = []
    blocked: list[CaptureInterval] = []
    counts: Counter[int] = Counter()
    limits_by_day: dict[int, list[CaptureInterval]] = {}
    for row in limited:
        limits_by_day.setdefault(row.start_ns // _DAY_NS, []).append(row)

    def append(target: list[CaptureInterval], row: CaptureInterval) -> None:
        day = row.start_ns // _DAY_NS
        counts[day] += 1
        _require(counts[day] <= _MAX_DAY_INTERVALS and len(counts) <= _MAX_DAYS)
        target.append(row)

    def expand(node: CaptureInterval, gap: CaptureInterval) -> None:
        start, end = max(node.start_ns, gap.start_ns), min(node.end_ns, gap.end_ns)
        if start >= end:
            return
        width = node.end_ns - node.start_ns
        forced = any(
            node.start_ns <= row.start_ns and row.end_ns <= node.end_ns
            for row in limits_by_day.get(node.start_ns // _DAY_NS, ())
        )
        if (
            start == node.start_ns
            and end == node.end_ns
            and minimum <= width <= maximum
            and not forced
        ):
            append(requests, node)
            return
        middle = (node.start_ns + node.end_ns) // 2
        if middle - node.start_ns < minimum or node.end_ns - middle < minimum:
            append(blocked, CaptureInterval(start, end))
            return
        expand(CaptureInterval(node.start_ns, middle), gap)
        expand(CaptureInterval(middle, node.end_ns), gap)

    # Root page-limited requests are disjoint; descendants are visited through
    # their original tree, never by slicing an arbitrary failed request prefix.
    for gap in _subtract(gaps, roots):
        expand(gap, gap)
    root_index = 0
    for gap in gaps:
        while root_index < len(roots) and roots[root_index].end_ns <= gap.start_ns:
            root_index += 1
        current = root_index
        while current < len(roots) and roots[current].start_ns < gap.end_ns:
            expand(roots[current], gap)
            current += 1
    return tuple(sorted(requests)), _merge(tuple(blocked))


def plan_quote_coverage(
    required: tuple[CaptureInterval, ...],
    attempts: tuple[CaptureAttempt, ...],
    maximum_window_ns: int,
    minimum_window_ns: int,
) -> QuoteCoveragePlan:
    """Plan only unattempted request spans; never authorize transport or retries.

    ``page_limit`` can yield exact bisection descendants. Failed/uncertain spans
    block, and empty completed spans stop reacquisition without becoming covered.
    Historical declarations may predate today's minimum window policy; the policy
    constrains newly proposed requests, not previously retained facts.
    """
    try:
        _integer(maximum_window_ns, _DAY_NS, 1)
        _integer(minimum_window_ns, maximum_window_ns, 1)
        _require(type(required) is tuple and type(attempts) is tuple)
        _require(len(required) <= _MAX_INTERVALS and len(attempts) <= _MAX_INTERVALS)
        _bounded(required, disjoint=False)
        required = tuple(sorted(required))
        _bounded(required, disjoint=True)
        for attempt in attempts:
            _require(type(attempt) is CaptureAttempt)
            attempt.__post_init__()
        attempts = tuple(
            sorted(attempts, key=lambda row: (row.request.start_ns, -row.request.end_ns))
        )
        roots = _attempt_roots(attempts)
        _require(
            len(
                {row.start_ns // _DAY_NS for row in required}
                | {row.request.start_ns // _DAY_NS for row in attempts}
            )
            <= _MAX_DAYS
        )

        def selected(statuses: tuple[str, ...]) -> tuple[CaptureInterval, ...]:
            return tuple(row.request for row in attempts if row.status in statuses)

        covered = _intersections(required, selected(("complete_nonempty",)))
        empty = _intersections(required, selected(("complete_empty",)))
        blocked = _intersections(required, selected(("failed", "uncertain")))
        gaps = _subtract(required, tuple(sorted((*covered, *empty, *blocked))))
        requests, unsplittable = _requests(
            gaps, roots, selected(("page_limit",)), maximum_window_ns, minimum_window_ns
        )
        blocked = _merge((*blocked, *unsplittable))
        output = tuple(sorted((*requests, *covered, *empty, *blocked)))
        _bounded(output, disjoint=True)
        _require(
            sum(row.end_ns - row.start_ns for row in output)
            == sum(row.end_ns - row.start_ns for row in required)
        )
        return QuoteCoveragePlan(
            required,
            attempts,
            maximum_window_ns,
            minimum_window_ns,
            requests,
            covered,
            empty,
            blocked,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise CaptureCoverageError() from None
