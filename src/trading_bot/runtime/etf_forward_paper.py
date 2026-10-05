"""Versioned transport-free forward economic owner; never qualifying paper.

Inputs are explicitly fictional account/cycle facts. Retained native observations
must not be relabeled here. A canonical policy reference is not accepted research.
The complete consumed tape is necessary to reconstruct all economic/risk history.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountResult, _run
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.lifecycle_accounting import _context

MAX_CYCLES = 1000
MAX_EVENTS = 10000
MAX_JOINT_BYTES = 8 * 1048576
_FORWARD_START = datetime(2026, 1, 1, tzinfo=UTC)


class ForwardPaperError(ValueError):
    def __init__(self) -> None:
        super().__init__("forward_paper_invalid")


def _check(ok: bool) -> None:
    if not ok:
        raise ForwardPaperError()


@dataclass(frozen=True, slots=True)
class ForwardPaperPlan:
    policy: EtfStudy
    starts_at: datetime
    ends_at: datetime
    initial_cash: Decimal
    schema: Literal["etf-forward-paper-v1"] = field(default="etf-forward-paper-v1", init=False)

    def __post_init__(self) -> None:
        _policy(self.policy)
        for at in (self.starts_at, self.ends_at):
            _check(type(at) is datetime)
            require_utc(at)
        _check(_FORWARD_START <= self.starts_at < self.ends_at)
        _check(self.ends_at - self.starts_at <= timedelta(days=31))
        require_bounded_decimal(self.initial_cash, "forward cash", positive=True)
        _check(self.initial_cash in self.policy.capital_tiers)
        _check(self.schema == "etf-forward-paper-v1")

    @property
    def plan_hash(self) -> str:
        return content_hash(("etf-forward-paper-plan-v1", self))


@dataclass(frozen=True, slots=True)
class ForwardPaperCycle:
    at_ns: int
    received_monotonic_ns: int
    source_hash: str
    strategy_state_hash: str
    events: tuple[EtfAccountEvent, ...]

    def __post_init__(self) -> None:
        for value in (self.at_ns, self.received_monotonic_ns):
            _check(type(value) is int and 0 < value < 2**63)
        for digest in (self.source_hash, self.strategy_state_hash):
            _require_sha256_hex(digest, "forward diagnostic binding")
        _check(type(self.events) is tuple and len(self.events) <= MAX_EVENTS)
        for event in self.events:
            _check(type(event) is EtfAccountEvent)
            replace(event)
            _check(event.at_ns <= self.at_ns)

    @property
    def cycle_id(self) -> str:
        return content_hash(("etf-forward-paper-cycle-v1", self))


@dataclass(frozen=True, slots=True)
class ForwardPaperTape:
    plan: ForwardPaperPlan
    cycles: tuple[ForwardPaperCycle, ...]
    source_kind: Literal["synthetic-forward-paper-v1"] = field(
        default="synthetic-forward-paper-v1", init=False
    )

    def __post_init__(self) -> None:
        _check(type(self.plan) is ForwardPaperPlan)
        _check(replace(self.plan) == self.plan)
        _check(type(self.cycles) is tuple and len(self.cycles) <= MAX_CYCLES)
        _check(self.source_kind == "synthetic-forward-paper-v1")
        previous: ForwardPaperCycle | None = None
        last: EtfAccountEvent | None = None
        seen: dict[str, str] = {}
        count = 0
        for cycle in self.cycles:
            _check(type(cycle) is ForwardPaperCycle)
            _check(replace(cycle) == cycle)
            _check(_ns(self.plan.starts_at) <= cycle.at_ns < _ns(self.plan.ends_at))
            if previous is not None:
                _check(previous.at_ns <= cycle.at_ns)
                _check(previous.received_monotonic_ns < cycle.received_monotonic_ns)
            for event in cycle.events:
                count += 1
                _check(count <= MAX_EVENTS)
                _check(_ns(self.plan.starts_at) <= event.at_ns < _ns(self.plan.ends_at))
                if event.event_id in seen:
                    _check(seen[event.event_id] == event.event_hash)
                    continue
                if last is not None:
                    _check(last.ordinal < event.ordinal and last.at_ns <= event.at_ns)
                seen[event.event_id] = event.event_hash
                last = event
            previous = cycle
        try:
            # Admission includes replayed state and envelope, not just event count
            # or input bytes. Use the largest supported sequence's encoded width.
            _joint_bytes(MAX_CYCLES, "0" * 64, self, _replay(self))
        except (
            ValueError,
            TypeError,
            ArithmeticError,
            AttributeError,
            RuntimeError,
            RecursionError,
        ):
            raise ForwardPaperError() from None


@dataclass(frozen=True, slots=True)
class _ForwardAccountInput:
    study: EtfStudy
    initial_cash: Decimal
    events: tuple[EtfAccountEvent, ...]
    run_id: str


@dataclass(frozen=True, slots=True)
class ForwardPaperState:
    plan_hash: str
    cycle_count: int
    prefix_hash: str
    source_cursor: tuple[int, int, str] | None
    strategy_state_hash: str | None
    account: EtfAccountResult
    paused: Literal[True] = field(default=True, init=False)
    qualifying_paper: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    costs_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _joint_bytes(
    sequence: int, previous: str, tape: ForwardPaperTape, state: ForwardPaperState
) -> bytes:
    body = canonical_json(
        {
            "schema": "etf-forward-paper-joint-v1",
            "sequence": sequence,
            "previous_hash": previous,
            "cycle_count": state.cycle_count,
            "tape": tape,
            "state": state,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()
    _check(len(body) <= MAX_JOINT_BYTES)
    return body


def _replay(tape: ForwardPaperTape) -> ForwardPaperState:
    """Pure reducer over structurally validated facts; no recursive construction."""
    plan = tape.plan
    events = tuple(event for cycle in tape.cycles for event in cycle.events)
    inputs = _ForwardAccountInput(
        plan.policy,
        plan.initial_cash,
        events,
        content_hash(("etf-forward-paper-account-v1", plan.plan_hash)),
    )
    with localcontext(_context(exact=True)):
        account = _run(inputs, len(events), origin=plan.starts_at)
    account = replace(account, study_hash=plan.plan_hash)
    last = tape.cycles[-1] if tape.cycles else None
    return ForwardPaperState(
        plan.plan_hash,
        len(tape.cycles),
        content_hash(("etf-forward-paper-prefix-v1", plan.plan_hash, tape.cycles)),
        None if last is None else (last.at_ns, last.received_monotonic_ns, last.source_hash),
        None if last is None else last.strategy_state_hash,
        account,
    )


def replay_forward_paper(tape: ForwardPaperTape) -> ForwardPaperState:
    """Reconstruct all explicit economic facts, never infer missing outcomes."""
    try:
        _check(type(tape) is ForwardPaperTape)
        _check(replace(tape) == tape)
        return _replay(tape)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError, RecursionError):
        raise ForwardPaperError() from None
