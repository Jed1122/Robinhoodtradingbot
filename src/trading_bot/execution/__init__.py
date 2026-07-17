"""Broker-neutral execution primitives."""

from trading_bot.execution.exclusion import (
    InProcessSubmissionExclusion,
    SubmissionAlreadyInProgress,
    SubmissionExclusion,
)
from trading_bot.execution.idempotency import derive_deduplication_key
from trading_bot.execution.review import (
    OrderReviewMismatch,
    OrderReviewService,
    review_matches_intent,
)
from trading_bot.execution.service import (
    DuplicateSubmissionAttempt,
    ExecutionResult,
    ExecutionService,
    PretradeContextLoader,
    PretradeEvaluator,
    UnitOfWorkFactory,
)
from trading_bot.execution.state_machine import InvalidOrderTransition, transition

__all__ = [
    "DuplicateSubmissionAttempt",
    "ExecutionResult",
    "ExecutionService",
    "InProcessSubmissionExclusion",
    "InvalidOrderTransition",
    "OrderReviewMismatch",
    "OrderReviewService",
    "PretradeContextLoader",
    "PretradeEvaluator",
    "SubmissionAlreadyInProgress",
    "SubmissionExclusion",
    "UnitOfWorkFactory",
    "derive_deduplication_key",
    "review_matches_intent",
    "transition",
]
