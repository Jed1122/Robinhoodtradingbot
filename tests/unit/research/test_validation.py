from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.unit.research.test_metrics import source
from trading_bot.research.metrics import calculate_performance
from trading_bot.research.report import ResearchAttempt, ResearchRunRecord, build_research_report
from trading_bot.research.validation import (
    LabeledObservation,
    ResearchAcceptancePolicy,
    assess_research,
    purged_splits,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_purged_split_has_no_label_overlap() -> None:
    observations = tuple(
        LabeledObservation(
            NOW + timedelta(days=index), NOW + timedelta(days=index + 2), Decimal(index)
        )
        for index in range(8)
    )
    split = purged_splits(observations, train_size=4, test_size=2)[0]
    assert all(item.label_ends_at < split.test[0].observed_at for item in split.train)


def report(*, expectancy_positive: bool = True):
    metrics = calculate_performance(source((Decimal("0.01"), Decimal("-0.01"))))
    if not expectancy_positive:
        metrics = calculate_performance(
            replace(
                source((Decimal("-0.01"), Decimal("-0.02"))),
                trade_pnl=(Decimal("-1"), Decimal("-2")),
            )
        )
    run = ResearchRunRecord("run", "strategy-v1", "a" * 64, "b" * 64, "c" * 64, (), (), (), True)
    return build_research_report(
        run,
        attempts=(
            ResearchAttempt(
                "momentum", "d" * 64, "accepted", ("edge_persistence_rationale",), metrics
            ),
        ),
    )


def test_research_gate_accepts_complete_positive_evidence() -> None:
    assessment = assess_research(report(), ResearchAcceptancePolicy(3, Decimal("50")))
    assert assessment.eligible and assessment.promotable


def test_research_gate_fails_closed_on_nonpositive_expectancy() -> None:
    assessment = assess_research(
        report(expectancy_positive=False), ResearchAcceptancePolicy(3, Decimal("50"))
    )
    assert not assessment.eligible
