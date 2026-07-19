from trading_bot.simulation.engine import EventPriority


def test_event_priority_is_complete_and_stable() -> None:
    assert tuple(EventPriority) == (
        EventPriority.CORPORATE_AND_SESSION,
        EventPriority.MARKET_DATA,
        EventPriority.BROKER_UPDATE,
        EventPriority.STRATEGY_CYCLE,
        EventPriority.RECONCILIATION,
        EventPriority.REPORTING,
    )
