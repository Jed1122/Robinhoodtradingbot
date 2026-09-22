from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import AppConfig, LoadedConfig, load_config
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.research.equity_comparison import (
    EquityComparisonRequest,
    EquityResearchDataset,
    run_equity_candidate_comparison,
)
from trading_bot.research.report import report_integrity_reason_codes
from trading_bot.research.validation import (
    ResearchAcceptancePolicy,
    assess_research,
)

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"
START = datetime(2026, 1, 1, tzinfo=UTC)
SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")


def config() -> LoadedConfig:
    loaded = load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "backtest.yaml",
        CONFIGS / "safety-envelope.yaml",
        {},
    )
    raw = loaded.config.model_dump()
    raw["research"].update(
        {
            "walk_forward_folds": 2,
            "embargo_bars": 1,
            "monte_carlo_iterations": 20,
            "history_calendar_days": 100,
            "minimum_history_bars": 30,
            "minimum_test_bars_per_fold": 10,
            "minimum_independent_opportunities": 5,
            "maximum_stressed_drawdown_pct": Decimal("100"),
            "minimum_positive_walk_forward_folds": 1,
            "maximum_single_opportunity_profit_contribution_pct": Decimal("100"),
            "maximum_monte_carlo_loss_probability_pct": Decimal("100"),
            "minimum_benchmark_excess_return_pct": Decimal("0"),
        }
    )
    raw["equity_strategies"].update(
        {
            "short_windows": [2, 3],
            "long_windows": [4, 5],
            "research_relative_strength_top_n": [1, 2],
            "research_rebalance_bars": 2,
        }
    )
    configured = AppConfig.model_validate(raw)
    canonical, config_hash = hash_loaded_config(
        configured,
        loaded.safety_envelope,
    )
    return LoadedConfig(
        config=configured,
        safety_envelope=loaded.safety_envelope,
        canonical_json=canonical,
        config_hash=config_hash,
    )


def bars(symbol: str, *, count: int = 40) -> tuple[Bar, ...]:
    multiplier = {
        "SPY": Decimal("1"),
        "QQQ": Decimal("1.5"),
        "IWM": Decimal("0.25"),
        "DIA": Decimal("0.5"),
    }[symbol]
    result = []
    for index in range(count):
        close = Decimal("100") + Decimal(index) * multiplier
        starts_at = START + timedelta(days=index)
        result.append(
            Bar(
                InstrumentId(symbol),
                BarInterval.ONE_DAY,
                starts_at,
                starts_at + timedelta(days=1),
                close - Decimal("0.1"),
                close + Decimal("1"),
                close - Decimal("1"),
                close,
                Decimal("1000000"),
                "fixture",
                DataHash(f"{SYMBOLS.index(symbol) * 1000 + index + 1:064x}"),
            )
        )
    return tuple(result)


def request(
    *,
    selected_symbols: tuple[str, ...] = SYMBOLS,
    tainted: bool = False,
) -> EquityComparisonRequest:
    configured = config()
    values = []
    for symbol in selected_symbols:
        rows = bars(symbol)
        if tainted and symbol == "SPY":
            rows = (
                rows[0].__class__(
                    **{
                        **{
                            field: getattr(rows[0], field)
                            for field in rows[0].__dataclass_fields__
                        },
                        "interpolated": True,
                    }
                ),
                *rows[1:],
            )
        values.append((symbol, rows))
    dataset = EquityResearchDataset(
        as_of=START + timedelta(days=41),
        requested_start=START,
        requested_end=START + timedelta(days=41),
        bars_by_symbol=tuple(values),
        raw_hashes=tuple(DataHash(character * 64) for character in "abcd"),
        provider_evidence_hash="e" * 64,
    )
    return EquityComparisonRequest(
        loaded=configured,
        code_hash="1" * 64,
        code_clean=True,
        run_id="run",
        dataset=dataset,
    )


def test_comparison_is_deterministic_cost_stressed_and_nonpromotable() -> None:
    first = run_equity_candidate_comparison(request())
    second = run_equity_candidate_comparison(request())

    assert first == second
    assert first.run.universe_symbols == SYMBOLS
    assert len(first.attempts) == 8
    for attempt in first.attempts:
        assert attempt.metrics is not None
        assert attempt.stressed_metrics is not None
        assert (
            attempt.stressed_metrics.total_return_pct.value
            <= attempt.metrics.total_return_pct.value
        )

    assessment = assess_research(
        first,
        ResearchAcceptancePolicy(
            5,
            Decimal("100"),
            1,
            Decimal("100"),
            Decimal("100"),
            Decimal("0"),
            research_assumptions_validated=False,
            research_evidence_promotable=False,
        ),
    )
    assert not assessment.eligible
    assert {
        "point_in_time_universe_unavailable",
        "corporate_action_coverage_incomplete",
        "research_assumptions_unvalidated",
        "research_promotion_disabled",
    } <= set(assessment.reason_codes)


def test_partial_universe_is_rejected_without_metrics() -> None:
    report = run_equity_candidate_comparison(
        request(selected_symbols=("SPY", "QQQ", "IWM"))
    )

    assert "configured_universe_data_incomplete" in report.run.run_reason_codes
    assert all(attempt.metrics is None for attempt in report.attempts)
    assert report_integrity_reason_codes(report) == ()


def test_tainted_interpolation_is_retained_as_a_rejection_reason() -> None:
    report = run_equity_candidate_comparison(request(tainted=True))

    assert (
        "interpolation_status_unverified_or_interpolated"
        in report.run.run_reason_codes
    )


def test_request_rejects_config_object_hash_mismatch() -> None:
    complete = request()
    raw = complete.loaded.config.model_dump()
    raw["equity_strategies"]["research_candidate_strategy_ids"] = [
        "equity_momentum"
    ]
    forged = replace(
        complete.loaded,
        config=AppConfig.model_validate(raw),
    )

    with pytest.raises(ValueError, match="configuration identity"):
        replace(complete, loaded=forged)
