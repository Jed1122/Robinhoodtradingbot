import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

import httpx


class AlertType(StrEnum):
    PROCESS_START = "process_start"
    PROCESS_STOP = "process_stop"
    STALE_DATA = "stale_data"
    BROKER_DISAGREEMENT = "broker_disagreement"
    KILL_SWITCH = "kill_switch"
    AUTH_FAILURE = "auth_failure"
    DATABASE_ERROR = "database_error"
    UNEXPECTED_RESTART = "unexpected_restart"


@dataclass(frozen=True, slots=True)
class Alert:
    type: AlertType
    reason_code: str
    observed_at: datetime
    details: tuple[tuple[str, str], ...] = ()


class AlertSink(Protocol):
    async def send(self, alert: Alert) -> None: ...


def _safe(alert: Alert) -> dict[str, object]:
    unsafe = {"x-api-key", "authorization", "account_id", "token", "secret"}
    details = {
        key: "<redacted>" if key.lower() in unsafe else value for key, value in alert.details
    }
    return {
        "type": alert.type.value,
        "reason_code": alert.reason_code,
        "observed_at": alert.observed_at.isoformat(),
        "details": details,
    }


class WebhookAlertSink:
    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        self._client, self._url = client, url

    async def send(self, alert: Alert) -> None:
        response = await self._client.post(self._url, json=_safe(alert), timeout=5)
        response.raise_for_status()


class AlertService:
    def __init__(self, sink: AlertSink) -> None:
        self._sink, self._sent = sink, set[str]()

    async def emit(self, alert: Alert) -> None:
        digest = hashlib.sha256(repr(asdict(alert)).encode()).hexdigest()
        if digest not in self._sent:
            await self._sink.send(alert)
            self._sent.add(digest)


__all__ = ["Alert", "AlertService", "AlertSink", "AlertType", "WebhookAlertSink"]
