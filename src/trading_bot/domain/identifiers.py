"""Strongly typed identifiers and content-hash aliases."""

import uuid
from typing import NewType

AccountId = NewType("AccountId", str)
InstrumentId = NewType("InstrumentId", str)
OrderIntentId = NewType("OrderIntentId", str)
ClientOrderId = NewType("ClientOrderId", str)
ReviewId = NewType("ReviewId", str)
SubmissionAttemptId = NewType("SubmissionAttemptId", str)
OrderId = NewType("OrderId", str)
BrokerOrderId = NewType("BrokerOrderId", str)
FillId = NewType("FillId", str)
OrderTransitionId = NewType("OrderTransitionId", str)
RunId = NewType("RunId", str)
AuthorizationId = NewType("AuthorizationId", str)
ReconciliationId = NewType("ReconciliationId", str)
LeaseId = NewType("LeaseId", str)
AuditEventId = NewType("AuditEventId", str)
EvidenceId = NewType("EvidenceId", str)
ConfigVersionId = NewType("ConfigVersionId", str)
CorrelationId = NewType("CorrelationId", str)
ConfigHash = NewType("ConfigHash", str)
DataHash = NewType("DataHash", str)
CodeHash = NewType("CodeHash", str)


def new_order_intent_id() -> OrderIntentId:
    """Create the sole UUIDv4-backed durable client-visible intent identifier."""
    return OrderIntentId(str(uuid.uuid4()))
