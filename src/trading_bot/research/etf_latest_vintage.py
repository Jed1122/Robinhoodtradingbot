"""Fixed native-price research, with explicit latest-vintage limitations.

This is a runnable signal diagnostic, not an executable price replay. Raw daily
aggregation starts are projected to the following local midnight conservatively;
that is a documented research completion assumption, not a session-close record.
Holdout bars are retained in the archive but never evaluated by this command.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, timedelta
from decimal import Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.domain import Bar, BarInterval, ConfigHash, InstrumentId
from trading_bot.market_data.alpaca_native import AlpacaBarRecord
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_exploratory_intake import validate_etf_exploratory_archive
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.lifecycle_accounting import _context
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    HistoricalSlice,
    StrategyAction,
    StrategyContext,
)

_NEW_YORK = ZoneInfo("America/New_York")


class EtfLatestVintageError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_latest_vintage_invalid")


def latest_vintage_source_plan_hash(archive: EtfNativeBarsArchive) -> str:
    return content_hash(
        {
            "schema": "etf-latest-vintage-protocol-v1",
            "archive_hash": archive.archive_hash,
            "availability": "latest-vintage-original-timeline-waived",
            "completion_assumption": "following-new-york-midnight",
            "evaluation": "development-only-before-2024",
            "signal": "fixed-20-100",
            "cadence": 5,
            "orders": "denied-no-executable-data",
            "parameter_search": False,
        }
    )


@dataclass(frozen=True, slots=True)
class EtfLatestVintageRequest:
    study: EtfStudy
    archive: EtfNativeBarsArchive

    def __post_init__(self) -> None:
        try:
            _policy(self.study)
            if self.study.source_plan_hash != latest_vintage_source_plan_hash(self.archive):
                raise EtfLatestVintageError()
            validate_etf_exploratory_archive(self.archive, start=self.study.requested_start,
                                            end=self.study.requested_end)
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfLatestVintageError() from None


@dataclass(frozen=True, slots=True)
class EtfLatestVintageResult:
    study_hash: str
    archive_hash: str
    development_records: int
    retained_holdout_records: int
    evaluated_observations: int
    rebalance_candidates: int
    positive_signal_observations: int
    decision_input_hashes: tuple[str, ...]
    decisions_hash: str
    reasons: tuple[str, ...]
    admitted_entries: Literal[0] = field(default=0, init=False)
    source_kind: Literal["alpaca-sip-latest-vintage-v1"] = field(
        default="alpaca-sip-latest-vintage-v1", init=False
    )
    economic_verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def result_hash(self) -> str:
        return content_hash({"schema": "etf-latest-vintage-result-v1", "result": self})


def _bar(row: AlpacaBarRecord) -> Bar:
    starts = _ceil_time(row.timestamp_ns)
    ends = (starts.astimezone(_NEW_YORK) + timedelta(days=1)).astimezone(UTC)
    return Bar(
        InstrumentId("SPY"),
        BarInterval.ONE_DAY,
        starts,
        ends,
        row.open,
        row.high,
        row.low,
        row.close,
        Decimal(row.volume),
        "alpaca-sip-latest-vintage",
        content_hash(row),
    )


def run_latest_vintage_etf(request: EtfLatestVintageRequest) -> EtfLatestVintageResult:
    try:
        if type(request) is not EtfLatestVintageRequest:
            raise EtfLatestVintageError()
        replace(request)
        policy = _policy(request.study)
        rows = tuple(
            row
            for row in request.archive.bars
            if row.timestamp_ns < _ns(request.study.holdout_start)
        )
        inputs: list[str] = []
        decisions = []
        candidates = positive = 0
        warmup = policy.config.research.minimum_history_bars
        with localcontext(_context(exact=False)):
            for index in range(warmup, len(rows)):
                selected = rows[index - 100 : index]
                input_hash = content_hash(tuple(row.record_hash for row in selected))
                inputs.append(input_hash)
                at = _ceil_time(rows[index].timestamp_ns)
                history = HistoricalSlice(
                    InstrumentId("SPY"),
                    tuple(_bar(row) for row in selected),
                    None,
                    content_hash(input_hash),
                )
                vector = FeaturePipeline(short_window=20, long_window=100).compute(
                    history, as_of=at
                )
                snapshot = FeatureSnapshot(at, (vector,), content_hash(vector))
                context = StrategyContext(
                    at, snapshot, ConfigHash(request.study.config_hash), (InstrumentId("SPY"),)
                )
                decision = MomentumStrategy(short_window=20, long_window=100).decide(context)[0]
                decisions.append(decision)
                positive += decision.action is StrategyAction.ENTER_LONG
                if (index - warmup) % request.study.rebalance_sessions == 0:
                    candidates += 1
        reasons = (
            *request.archive.limitations,
            "costs_and_fractional_execution_unqualified",
            "matched_after_cost_execution_outcomes_unavailable",
            "parameter_stability_unmeasured",
            "holdout_not_evaluated",
        )
        if not inputs:
            reasons += ("study_warmup_incomplete",)
        return EtfLatestVintageResult(
            request.study.study_hash,
            request.archive.archive_hash,
            len(rows),
            len(request.archive.bars) - len(rows),
            len(inputs),
            candidates,
            positive,
            tuple(inputs),
            content_hash(tuple(decisions)),
            reasons,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError):
        raise EtfLatestVintageError() from None
