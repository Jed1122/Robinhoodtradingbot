from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.config.models import PromotionSettings
from trading_bot.domain import DomainValidationError
from trading_bot.monitoring.promotion import (
    MicroOrderReviewEvidence,
    PromotionEvaluator,
    PromotionExternalEvidence,
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
    TimedPromotionEvidence,
)

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
EVALUATED_AT = NOW + timedelta(days=10)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def settings(
    *,
    paper_cycles: int = 2,
    shadow_days: int = 2,
    normal_days: int = 3,
    normal_observations: int = 3,
) -> PromotionSettings:
    return PromotionSettings(
        paper_min_eligible_unique_cycles=paper_cycles,
        shadow_min_calendar_days=shadow_days,
        micro_order_review_interval=10,
        normal_min_combined_calendar_days=normal_days,
        normal_min_valid_observations=normal_observations,
        clean_reconciliation_required=True,
        no_critical_security_findings_required=True,
        current_manual_acknowledgement_required=True,
        pause_on_unknown_order_state=True,
    )


def identity(*, code_hash: str = HASH_F) -> PromotionIdentity:
    return PromotionIdentity(HASH_A, HASH_B, "strategy-v1", HASH_C, HASH_D, code_hash)


def timed_evidence(
    evidence_hash: str,
    *,
    observed_at: datetime = NOW,
    expires_at: datetime = EVALUATED_AT + timedelta(days=1),
) -> TimedPromotionEvidence:
    return TimedPromotionEvidence(evidence_hash, observed_at, expires_at)


def complete_external(
    *,
    total_micro_orders: int = 10,
    reviewed_through_order: int = 10,
    review_interval: int = 10,
) -> PromotionExternalEvidence:
    return PromotionExternalEvidence(
        security_clearance=timed_evidence(HASH_A),
        manual_acknowledgement=timed_evidence(HASH_B),
        micro_runtime_controls=timed_evidence(HASH_C),
        micro_order_review=MicroOrderReviewEvidence(
            attestation=timed_evidence(HASH_D),
            total_micro_orders=total_micro_orders,
            reviewed_through_order=reviewed_through_order,
            review_interval=review_interval,
        ),
        slippage_assessment=timed_evidence(HASH_E),
        drawdown_assessment=timed_evidence(HASH_F),
    )


def observation(
    stage: PromotionStage,
    cycle_seed: str,
    *,
    when: datetime = NOW,
    bound_identity: PromotionIdentity | None = None,
    reconciliation_clean: bool = True,
    data_hash: str = HASH_E,
) -> PromotionObservation:
    return PromotionObservation.create(
        stage=stage,
        cycle_id=cycle_seed * 64,
        identity=bound_identity or identity(),
        started_at=when,
        completed_at=when + timedelta(seconds=1),
        data_hash=data_hash,
        identity_verified=True,
        provider_evidence_verified=True,
        strategy_eligible=True,
        authenticated_reads=stage is not PromotionStage.PAPER,
        data_validated=True,
        outcomes_complete=True,
        reconciliation_clean=reconciliation_clean,
        fixture_data=False,
        runtime_scope_valid=True,
        order_state_known=True,
    )


def test_paper_progress_uses_configured_threshold_and_unique_cycles() -> None:
    first = observation(PromotionStage.PAPER, "1")
    decision = PromotionEvaluator(settings(paper_cycles=2)).evaluate(
        stage=PromotionStage.PAPER,
        identity=identity(),
        observations=(first, first),
        now=EVALUATED_AT,
    )

    assert not decision.eligible
    assert decision.reasons == ("insufficient_paper_cycles",)
    assert decision.evidence.unique_observations == 1


def test_shadow_days_are_distinct_utc_dates_not_elapsed_duration() -> None:
    first = observation(PromotionStage.SHADOW, "1", when=NOW)
    same_day = observation(PromotionStage.SHADOW, "2", when=NOW + timedelta(hours=8))
    next_day = observation(PromotionStage.SHADOW, "3", when=NOW + timedelta(days=1))
    evaluator = PromotionEvaluator(settings(shadow_days=2))

    insufficient = evaluator.evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(first, same_day),
        now=EVALUATED_AT,
    )
    complete = evaluator.evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(first, same_day, next_day),
        now=EVALUATED_AT,
    )

    assert insufficient.evidence.calendar_days == 1
    assert not insufficient.eligible
    assert complete.evidence.calendar_days == 2
    assert complete.eligible


def test_micro_live_requires_paper_shadow_security_and_acknowledgement() -> None:
    observations = (
        observation(PromotionStage.PAPER, "1"),
        observation(PromotionStage.PAPER, "2"),
        observation(PromotionStage.SHADOW, "3"),
        observation(PromotionStage.SHADOW, "4", when=NOW + timedelta(days=1)),
    )
    evaluator = PromotionEvaluator(settings())

    missing_external = evaluator.evaluate(
        stage=PromotionStage.MICRO_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
    )
    complete = evaluator.evaluate(
        stage=PromotionStage.MICRO_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=complete_external(),
    )

    assert missing_external.reasons == (
        "security_clearance_missing",
        "manual_acknowledgement_missing",
        "micro_runtime_controls_missing",
    )
    assert complete.eligible and not complete.override_allowed


def test_identity_drift_resets_progress() -> None:
    old = observation(PromotionStage.PAPER, "1", bound_identity=identity(code_hash=HASH_E))
    decision = PromotionEvaluator(settings(paper_cycles=1)).evaluate(
        stage=PromotionStage.PAPER,
        identity=identity(),
        observations=(old,),
        now=EVALUATED_AT,
    )

    assert not decision.eligible
    assert decision.evidence.unique_observations == 0


def test_latest_ineligible_observation_blocks_stale_progress() -> None:
    clean = observation(PromotionStage.SHADOW, "1")
    dirty = observation(
        PromotionStage.SHADOW,
        "2",
        when=NOW + timedelta(minutes=1),
        reconciliation_clean=False,
    )
    decision = PromotionEvaluator(settings(shadow_days=1)).evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(clean, dirty),
        now=EVALUATED_AT,
    )

    assert not decision.eligible
    assert "latest_observation_ineligible" in decision.reasons


def test_equal_timestamp_ineligible_observation_blocks_independent_of_input_order() -> None:
    clean = observation(PromotionStage.SHADOW, "1")
    dirty = observation(
        PromotionStage.SHADOW,
        "2",
        reconciliation_clean=False,
    )
    evaluator = PromotionEvaluator(settings(shadow_days=1))

    decisions = tuple(
        evaluator.evaluate(
            stage=PromotionStage.SHADOW,
            identity=identity(),
            observations=values,
            now=EVALUATED_AT,
        )
        for values in ((clean, dirty), (dirty, clean))
    )

    assert all(not decision.eligible for decision in decisions)
    assert all("latest_observation_ineligible" in decision.reasons for decision in decisions)


def test_conflicting_cycle_is_quarantined_and_canonical_independent_of_input_order() -> None:
    first = observation(PromotionStage.SHADOW, "1")
    conflicting = observation(
        PromotionStage.SHADOW,
        "1",
        data_hash="0" * 64,
    )
    other_conflicting = observation(
        PromotionStage.SHADOW,
        "1",
        data_hash="9" * 64,
    )
    evaluator = PromotionEvaluator(settings(shadow_days=1))

    decisions = tuple(
        evaluator.evaluate(
            stage=PromotionStage.SHADOW,
            identity=identity(),
            observations=values,
            now=EVALUATED_AT,
        )
        for values in ((first, conflicting), (conflicting, first))
    )

    assert all(not decision.eligible for decision in decisions)
    assert all("conflicting_cycle_evidence" in decision.reasons for decision in decisions)
    assert all(decision.evidence.unique_observations == 0 for decision in decisions)
    assert decisions[0].evidence_hash == decisions[1].evidence_hash
    other_decision = evaluator.evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(first, other_conflicting),
        now=EVALUATED_AT,
    )
    assert decisions[0].evidence_hash != other_decision.evidence_hash


def test_normal_live_combines_paper_shadow_and_micro_live_evidence() -> None:
    observations = (
        observation(PromotionStage.PAPER, "1", when=NOW),
        observation(PromotionStage.SHADOW, "2", when=NOW + timedelta(days=1)),
        observation(PromotionStage.MICRO_LIVE, "3", when=NOW + timedelta(days=2)),
    )

    decision = PromotionEvaluator(
        settings(
            paper_cycles=1,
            shadow_days=1,
            normal_days=3,
            normal_observations=3,
        )
    ).evaluate(
        stage=PromotionStage.NORMAL_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=complete_external(),
    )

    assert decision.eligible
    assert decision.evidence.unique_observations == 3
    assert decision.evidence.calendar_days == 3


def test_normal_live_observations_cannot_bootstrap_normal_promotion() -> None:
    observations = (
        observation(PromotionStage.MICRO_LIVE, "1", when=NOW),
        observation(PromotionStage.NORMAL_LIVE, "2", when=NOW + timedelta(days=1)),
        observation(PromotionStage.NORMAL_LIVE, "3", when=NOW + timedelta(days=2)),
    )

    decision = PromotionEvaluator(settings(normal_days=3, normal_observations=3)).evaluate(
        stage=PromotionStage.NORMAL_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=complete_external(),
    )

    assert not decision.eligible
    assert "insufficient_connected_observations" in decision.reasons
    assert "insufficient_connected_calendar_days" in decision.reasons
    assert observation(
        PromotionStage.NORMAL_LIVE, "2", when=NOW + timedelta(days=1)
    ).evidence_hash not in (decision.evidence.observation_hashes)


def test_normal_live_observation_cannot_mask_latest_ineligible_micro_evidence() -> None:
    clean = observation(PromotionStage.MICRO_LIVE, "1", when=NOW)
    dirty = observation(
        PromotionStage.MICRO_LIVE,
        "2",
        when=NOW + timedelta(days=1),
        reconciliation_clean=False,
    )
    later_normal = observation(
        PromotionStage.NORMAL_LIVE,
        "3",
        when=NOW + timedelta(days=2),
    )

    decision = PromotionEvaluator(settings(normal_days=1, normal_observations=1)).evaluate(
        stage=PromotionStage.NORMAL_LIVE,
        identity=identity(),
        observations=(clean, dirty, later_normal),
        now=EVALUATED_AT,
        external=complete_external(),
    )

    assert not decision.eligible
    assert "latest_observation_ineligible" in decision.reasons
    assert later_normal.evidence_hash not in decision.evidence.observation_hashes


def test_normal_live_retains_paper_and_shadow_prerequisites() -> None:
    observations = (
        observation(PromotionStage.PAPER, "1", when=NOW),
        observation(PromotionStage.SHADOW, "2", when=NOW + timedelta(days=1)),
        observation(PromotionStage.MICRO_LIVE, "3", when=NOW + timedelta(days=2)),
    )

    decision = PromotionEvaluator(settings(normal_days=3, normal_observations=3)).evaluate(
        stage=PromotionStage.NORMAL_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=complete_external(),
    )

    assert not decision.eligible
    assert "insufficient_paper_cycles" in decision.reasons
    assert "insufficient_shadow_calendar_days" in decision.reasons


def test_latest_dirty_normal_observation_blocks_repromotion_without_counting() -> None:
    observations = (
        observation(PromotionStage.PAPER, "1", when=NOW),
        observation(PromotionStage.SHADOW, "2", when=NOW + timedelta(days=1)),
        observation(PromotionStage.MICRO_LIVE, "3", when=NOW + timedelta(days=2)),
        observation(
            PromotionStage.NORMAL_LIVE,
            "4",
            when=NOW + timedelta(days=3),
            reconciliation_clean=False,
        ),
    )

    decision = PromotionEvaluator(
        settings(
            paper_cycles=1,
            shadow_days=1,
            normal_days=3,
            normal_observations=3,
        )
    ).evaluate(
        stage=PromotionStage.NORMAL_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=complete_external(),
    )

    assert not decision.eligible
    assert "latest_normal_observation_ineligible" in decision.reasons
    assert decision.evidence.unique_observations == 3


def test_external_evidence_must_be_current_at_injected_evaluation_time() -> None:
    observations = (
        observation(PromotionStage.PAPER, "1"),
        observation(PromotionStage.PAPER, "2"),
        observation(PromotionStage.SHADOW, "3"),
        observation(PromotionStage.SHADOW, "4", when=NOW + timedelta(days=1)),
    )
    external = complete_external()
    expired = replace(
        external,
        manual_acknowledgement=timed_evidence(
            HASH_B,
            expires_at=EVALUATED_AT,
        ),
    )

    decision = PromotionEvaluator(settings()).evaluate(
        stage=PromotionStage.MICRO_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=expired,
    )

    assert not decision.eligible
    assert "manual_acknowledgement_expired" in decision.reasons


@pytest.mark.parametrize(
    ("external", "reason"),
    [
        (
            complete_external(total_micro_orders=10, reviewed_through_order=9),
            "micro_order_review_incomplete",
        ),
        (complete_external(review_interval=5), "micro_order_review_interval_mismatch"),
        (replace(complete_external(), slippage_assessment=None), "slippage_assessment_missing"),
        (replace(complete_external(), drawdown_assessment=None), "drawdown_assessment_missing"),
    ],
)
def test_normal_live_requires_complete_micro_review_and_performance_evidence(
    external: PromotionExternalEvidence,
    reason: str,
) -> None:
    observations = (
        observation(PromotionStage.PAPER, "1", when=NOW),
        observation(PromotionStage.SHADOW, "2", when=NOW + timedelta(days=1)),
        observation(PromotionStage.MICRO_LIVE, "3", when=NOW + timedelta(days=2)),
    )

    decision = PromotionEvaluator(settings(normal_days=3, normal_observations=3)).evaluate(
        stage=PromotionStage.NORMAL_LIVE,
        identity=identity(),
        observations=observations,
        now=EVALUATED_AT,
        external=external,
    )

    assert not decision.eligible
    assert reason in decision.reasons


def test_future_dated_observations_never_count_as_elapsed_evidence() -> None:
    future = observation(
        PromotionStage.SHADOW,
        "1",
        when=NOW + timedelta(days=1),
    )

    decision = PromotionEvaluator(settings(shadow_days=1)).evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(future,),
        now=NOW,
    )

    assert not decision.eligible
    assert decision.evidence.unique_observations == 0


def test_observation_eligibility_cannot_be_replaced_by_caller() -> None:
    dirty = observation(
        PromotionStage.SHADOW,
        "1",
        reconciliation_clean=False,
    )

    with pytest.raises(DomainValidationError, match="eligibility"):
        replace(dirty, eligible=True)


def test_decision_hash_and_eligibility_cannot_be_replaced_by_caller() -> None:
    decision = PromotionEvaluator(settings(shadow_days=1)).evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(observation(PromotionStage.SHADOW, "1"),),
        now=EVALUATED_AT,
    )

    with pytest.raises(DomainValidationError, match="hash"):
        replace(decision, evidence_hash="0" * 64)
    with pytest.raises(DomainValidationError, match="eligibility"):
        replace(decision, eligible=False)
