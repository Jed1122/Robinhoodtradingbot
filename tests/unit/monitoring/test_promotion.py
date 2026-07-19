from trading_bot.monitoring.promotion import (
    PromotionEvaluator,
    PromotionEvidence,
    PromotionStage,
)


def test_normal_requires_30_days_and_100_observations() -> None:
    evidence = PromotionEvidence(PromotionStage.NORMAL, 99, 29, True, True, True, True)
    decision = PromotionEvaluator().evaluate(evidence)
    assert not decision.eligible and not decision.override_allowed
