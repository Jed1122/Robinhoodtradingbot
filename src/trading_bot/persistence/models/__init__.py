"""Complete ORM registry for the approved durable ledger."""

from trading_bot.persistence.models.accounts import (
    AccountRow,
    DrawdownEventRow,
    EquityCurveRow,
    PortfolioSnapshotRow,
    PositionRow,
    RealizedPnlRow,
)
from trading_bot.persistence.models.decisions import (
    PromotionEvidenceRow,
    PromotionObservationRow,
    ResearchAcceptanceEvidenceRow,
    RiskEvaluationRow,
    StrategyDecisionRow,
)
from trading_bot.persistence.models.etf import EtfReplayEventRow
from trading_bot.persistence.models.market import (
    BarRow,
    DataQualityEventRow,
    FeatureRow,
    InstrumentRow,
    MarketSnapshotRow,
    SignalRow,
)
from trading_bot.persistence.models.operations import (
    AlertRow,
    AuditEventRow,
    ConfigurationVersionRow,
    ExecutionLeaseRow,
    HeartbeatRow,
    KillSwitchEventRow,
    LiveAuthorizationRow,
    LiveLeaseRow,
    ReconciliationEventRow,
    UsedNonceRow,
)
from trading_bot.persistence.models.options import OptionsRiskEventRow, OptionsTrialEventRow
from trading_bot.persistence.models.orders import (
    BrokerReviewRow,
    FillRow,
    OrderIntentRow,
    OrderRow,
    OrderTransitionRow,
    SubmissionAttemptRow,
)
from trading_bot.persistence.models.owned_economics import OwnedEconomicEventRow
from trading_bot.persistence.models.owned_orders import OwnedOrderEventRow

__all__ = [
    "AccountRow",
    "AlertRow",
    "AuditEventRow",
    "BarRow",
    "BrokerReviewRow",
    "ConfigurationVersionRow",
    "DataQualityEventRow",
    "DrawdownEventRow",
    "EquityCurveRow",
    "EtfReplayEventRow",
    "ExecutionLeaseRow",
    "FeatureRow",
    "FillRow",
    "HeartbeatRow",
    "InstrumentRow",
    "KillSwitchEventRow",
    "LiveAuthorizationRow",
    "LiveLeaseRow",
    "MarketSnapshotRow",
    "OptionsRiskEventRow",
    "OptionsTrialEventRow",
    "OrderIntentRow",
    "OrderRow",
    "OrderTransitionRow",
    "OwnedEconomicEventRow",
    "OwnedOrderEventRow",
    "PortfolioSnapshotRow",
    "PositionRow",
    "PromotionEvidenceRow",
    "PromotionObservationRow",
    "RealizedPnlRow",
    "ReconciliationEventRow",
    "ResearchAcceptanceEvidenceRow",
    "RiskEvaluationRow",
    "SignalRow",
    "StrategyDecisionRow",
    "SubmissionAttemptRow",
    "UsedNonceRow",
]
