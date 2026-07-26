from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.unit.research.test_metrics import source
from trading_bot.market_data import ResearchDataManifest
from trading_bot.research.metrics import calculate_performance
from trading_bot.research.report import (
    ResearchAttempt,
    ResearchDatasetSnapshot,
    ResearchRunRecord,
    build_research_report,
    candidate_promotion_identity,
)
from trading_bot.research.validation import (
    LabeledObservation,
    ResearchAcceptancePolicy,
    assess_research,
    purged_splits,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)
PARAMETER_HASH = "d" * 64


def policy() -> ResearchAcceptancePolicy:
    return ResearchAcceptancePolicy(
        3,
        Decimal("50"),
        1,
        Decimal("100"),
        Decimal("100"),
        Decimal("0"),
        research_assumptions_validated=True,
        research_evidence_promotable=True,
    )


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
    snapshot = ResearchDatasetSnapshot(
        as_of=NOW,
        requested_start=NOW - timedelta(days=1),
        requested_end=NOW,
        bars_by_symbol=(),
        raw_hashes=(),
        provider_evidence_hash="e" * 64,
    )
    manifest = ResearchDataManifest.create(
        raw_hashes=(),
        cleaned_hashes=(),
        corporate_action_coverage="complete",
        point_in_time_universe=True,
    )
    strategy_id = "momentum"
    strategy_version = "strategy-v1"
    run = ResearchRunRecord(
        "run",
        candidate_promotion_identity(
            strategy_id,
            strategy_version,
            PARAMETER_HASH,
        ),
        "a" * 64,
        "b" * 64,
        str(manifest.manifest_hash),
        (),
        (),
        (),
        True,
        provider_evidence_hash=snapshot.provider_evidence_hash,
        data_manifest=manifest,
        dataset_snapshot=snapshot,
        selected_strategy_id=strategy_id,
        selected_strategy_version=strategy_version,
        selected_parameter_hash=PARAMETER_HASH,
    )
    return build_research_report(
        run,
        attempts=(
            ResearchAttempt(
                "momentum",
                PARAMETER_HASH,
                "accepted",
                ("edge_persistence_rationale",),
                metrics,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                stressed_metrics=metrics,
                fold_total_returns_pct=(Decimal("1"),),
                benchmark_total_return_pct=Decimal("0"),
                monte_carlo_loss_probability_pct=Decimal("0"),
                maximum_single_opportunity_profit_contribution_pct=Decimal("50"),
                parameter_neighbor_stressed_total_returns_pct=(Decimal("1"),),
            ),
        ),
    )


def test_research_gate_accepts_complete_positive_evidence() -> None:
    assessment = assess_research(report(), policy())
    assert assessment.eligible and assessment.promotable


def test_research_gate_fails_closed_on_nonpositive_expectancy() -> None:
    assessment = assess_research(
        report(expectancy_positive=False), policy()
    )
    assert not assessment.eligible


def test_research_gate_rejects_missing_stressed_metrics() -> None:
    complete = report()
    attempt = replace(complete.attempts[0], stressed_metrics=None)
    assessment = assess_research(
        build_research_report(complete.run, attempts=(attempt,)),
        policy(),
    )

    assert not assessment.eligible
    assert "missing_stressed_metrics" in assessment.reason_codes


def test_research_policy_defaults_fail_closed() -> None:
    fail_closed = ResearchAcceptancePolicy(
        3,
        Decimal("50"),
        1,
        Decimal("100"),
        Decimal("100"),
        Decimal("0"),
    )

    assessment = assess_research(report(), fail_closed)

    assert not assessment.eligible
    assert {
        "research_assumptions_unvalidated",
        "research_promotion_disabled",
    } <= set(assessment.reason_codes)
