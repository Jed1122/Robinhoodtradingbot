"""Deterministic, secret-safe mapping for append-only audit events."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.capabilities.sanitization import (
    name_is_sensitive,
    text_contains_sensitive_material,
)
from trading_bot.domain.events import AuditEvent
from trading_bot.domain.identifiers import AuditEventId
from trading_bot.logging import contains_registered_secret, redact_secrets
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import AuditEventRow

__all__ = ["serialize_audit_details"]


def _validate_safe_event_text(value: str) -> None:
    if text_contains_sensitive_material(value) or redact_secrets(
        None,
        "audit-screen",
        {"value": value},
    ) != {"value": value}:
        raise PersistenceDataError("audit event contains unsafe text")


def _validate_safe_identifier(value: str) -> None:
    if type(value) is not str or not value or contains_registered_secret(value):
        raise PersistenceDataError("audit event contains an unsafe identifier")


def serialize_audit_details(event: AuditEvent) -> str:
    """Serialize ordered detail pairs canonically after fail-closed secret screening."""
    if type(event) is not AuditEvent:
        raise PersistenceDataError("audit event must use the canonical domain record")

    _validate_safe_event_text(event.category)
    _validate_safe_event_text(event.actor)
    _validate_safe_event_text(event.reason_code)
    for key, value in event.details:
        if (
            name_is_sensitive(key)
            or text_contains_sensitive_material(key)
            or text_contains_sensitive_material(value)
            or redact_secrets(None, "audit-screen", {key: value}) != {key: value}
        ):
            raise PersistenceDataError("audit event contains unsafe details")

    try:
        return json.dumps(
            [list(detail) for detail in event.details],
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PersistenceDataError("audit details cannot be serialized canonically") from exc


def _audit_event_row(
    event: AuditEvent,
    *,
    corrects_id: AuditEventId | None = None,
) -> AuditEventRow:
    """Map one immutable domain event to its durable append-only row."""
    if type(event) is not AuditEvent:
        raise PersistenceDataError("audit event must use the canonical domain record")
    _validate_safe_identifier(event.id)
    _validate_safe_identifier(event.correlation_id)
    if corrects_id is not None:
        _validate_safe_identifier(corrects_id)
    return AuditEventRow(
        id=event.id,
        occurred_at=event.occurred_at,
        category=event.category,
        actor=event.actor,
        reason_code=event.reason_code,
        correlation_id=event.correlation_id,
        config_hash=event.config_hash,
        code_hash=event.code_hash,
        data_hash=event.data_hash,
        sanitized_details_json=serialize_audit_details(event),
        corrects_id=corrects_id,
    )


def _stage_audit_event(
    session: AsyncSession,
    event: AuditEvent,
    *,
    corrects_id: AuditEventId | None = None,
) -> None:
    """Stage an audit event in the caller-owned transaction without committing it."""
    session.add(_audit_event_row(event, corrects_id=corrects_id))
