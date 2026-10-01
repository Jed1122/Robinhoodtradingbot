"""Immutable, non-executing ETF fixture-prefix observations.

These are not the full historical account/ledger records. No order, fill,
settlement, or production/promotion observation can be constructed here.
"""

from dataclasses import dataclass, field
from datetime import UTC
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.etf_source import _ceil_time
from trading_bot.market_data.recording import content_hash
from trading_bot.strategies.protocol import StrategyAction, StrategyDecision


class EtfHistoryError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_history_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EtfHistoryError()


def _counter(value: int) -> None:
    _check(type(value) is int and 0 <= value < 2**63)


@dataclass(frozen=True, slots=True)
class EtfDecisionObservation:
    study_hash: DataHash
    source_hash: DataHash
    source_ordinal: int
    observed_at_ns: int
    selected_bar_hashes: tuple[DataHash, ...]
    visible_bar_count: int
    cadence_index: int | None
    signal: StrategyDecision | None
    reasons: tuple[str, ...]
    admission_allowed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.study_hash, "study")
        _require_sha256_hex(self.source_hash, "source")
        _counter(self.source_ordinal)
        _counter(self.observed_at_ns)
        _counter(self.visible_bar_count)
        _check(type(self.selected_bar_hashes) is tuple and len(self.selected_bar_hashes) <= 100)
        for digest in self.selected_bar_hashes:
            _require_sha256_hex(digest, "selected bar")
        _check(len(set(self.selected_bar_hashes)) == len(self.selected_bar_hashes))
        if self.cadence_index is not None:
            _counter(self.cadence_index)
        if self.signal is not None:
            _check(type(self.signal) is StrategyDecision)
            _check(
                type(self.signal.instrument_id) is str
                and self.signal.instrument_id == "SPY"
                and type(self.signal.action) is StrategyAction
            )
            require_utc(self.signal.decided_at)
            _check(
                self.signal.decided_at.tzinfo is UTC
                and self.signal.decided_at == _ceil_time(self.observed_at_ns)
            )
            require_bounded_decimal(self.signal.score, "signal score", nonnegative=True)
            _check(
                type(self.signal.reason_codes) is tuple
                and all(type(item) is str for item in self.signal.reason_codes)
            )
            _check(type(self.signal.strategy_version) is str and bool(self.signal.strategy_version))
            _require_sha256_hex(self.signal.config_hash, "signal config")
            _require_sha256_hex(self.signal.data_hash, "signal data")
        _check(type(self.reasons) is tuple and all(type(item) is str for item in self.reasons))
        _check(
            "synthetic_inputs_only" in self.reasons and "execution_not_implemented" in self.reasons
        )
        _check(self.admission_allowed is False)

    @property
    def on_cadence(self) -> bool:
        return self.cadence_index is not None and self.cadence_index % 5 == 0

    @property
    def decision_hash(self) -> DataHash:
        return content_hash({"schema": "etf-fixture-decision-v1", "observation": self})


@dataclass(frozen=True, slots=True)
class EtfDecisionCheckpoint:
    study_hash: DataHash
    initial_cash: Decimal
    processed_count: int
    last_ordinal: int | None
    last_available_at_ns: int | None
    prefix_hash: DataHash
    decisions_hash: DataHash
    paused: Literal[True] = field(default=True, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(
            self.paused is True
            and self.execution_enabled is False
            and self.evidence_promotable is False
        )
        for digest in (self.study_hash, self.prefix_hash, self.decisions_hash):
            _require_sha256_hex(digest, "checkpoint identity")
        require_bounded_decimal(self.initial_cash, "initial cash", positive=True)
        _check(self.initial_cash in (Decimal("500"), Decimal("1000")))
        _counter(self.processed_count)
        _check((self.last_ordinal is None) == (self.processed_count == 0))
        _check((self.last_available_at_ns is None) == (self.processed_count == 0))
        if self.last_ordinal is not None:
            _counter(self.last_ordinal)
        if self.last_available_at_ns is not None:
            _counter(self.last_available_at_ns)


@dataclass(frozen=True, slots=True)
class EtfFixturePrefixResult:
    checkpoint: EtfDecisionCheckpoint
    decisions: tuple[EtfDecisionObservation, ...]
    cash: Decimal
    risk_equity_reference: Decimal
    shares: Decimal = field(default=Decimal("0"), init=False)
    reserved_cash: Decimal = field(default=Decimal("0"), init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    account_replay_complete: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.checkpoint) is EtfDecisionCheckpoint)
        _check(type(self.decisions) is tuple)
        _check(all(type(item) is EtfDecisionObservation for item in self.decisions))
        self.checkpoint.__post_init__()
        for observation in self.decisions:
            observation.__post_init__()
            _check(observation.study_hash == self.checkpoint.study_hash)
        require_bounded_decimal(self.cash, "cash", positive=True)
        require_bounded_decimal(self.risk_equity_reference, "risk reference", positive=True)
        _check(self.risk_equity_reference == Decimal("100"))
        _check(self.cash == self.checkpoint.initial_cash)
        _check(content_hash(self.decisions) == self.checkpoint.decisions_hash)

    @property
    def result_hash(self) -> DataHash:
        return content_hash({"schema": "etf-fixture-prefix-v1", "result": self})
