from trading_bot.monitoring.promotion import PromotionDecision


def test_decision_has_no_activation_method() -> None:
    assert not hasattr(PromotionDecision, "activate")
