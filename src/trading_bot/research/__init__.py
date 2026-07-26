"""Offline research services."""

from trading_bot.research.equity_comparison import (
    EquityComparisonRequest,
    EquityResearchDataset,
    run_equity_candidate_comparison,
)
from trading_bot.research.metrics import PerformanceInput, PerformanceMetrics, calculate_performance
from trading_bot.research.report import (
    ResearchReport,
    build_research_report,
    render_json,
    render_markdown,
)

__all__ = [
    "EquityComparisonRequest",
    "EquityResearchDataset",
    "PerformanceInput",
    "PerformanceMetrics",
    "ResearchReport",
    "build_research_report",
    "calculate_performance",
    "render_json",
    "render_markdown",
    "run_equity_candidate_comparison",
]
