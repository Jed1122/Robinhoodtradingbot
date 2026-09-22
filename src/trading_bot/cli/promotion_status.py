"""Read-only, non-authoritative promotion evidence inventory."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.market_data import content_hash
from trading_bot.monitoring.promotion import (
    PromotionEvaluator,
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
)

_OBSERVATION_STAGES = (
    PromotionStage.PAPER,
    PromotionStage.SHADOW,
    PromotionStage.MICRO_LIVE,
    PromotionStage.NORMAL_LIVE,
)
_PREVIEW_STAGES = _OBSERVATION_STAGES
_REQUIRED_TABLES = frozenset(
    {
        "execution_leases",
        "live_authorizations",
        "live_leases",
        "promotion_evidence",
        "promotion_observations",
        "research_acceptance_evidence",
        "submission_attempts",
    }
)
_ELIGIBILITY_QUERIES = {
    "promotion_evidence": (
        "SELECT eligible, COUNT(*) AS count FROM promotion_evidence GROUP BY eligible"
    ),
    "research_acceptance_evidence": (
        "SELECT eligible, COUNT(*) AS count FROM research_acceptance_evidence GROUP BY eligible"
    ),
}
_COUNT_QUERIES = {
    "execution_leases": "SELECT COUNT(*) AS count FROM execution_leases",
    "live_authorizations": "SELECT COUNT(*) AS count FROM live_authorizations",
    "live_leases": "SELECT COUNT(*) AS count FROM live_leases",
    "submission_attempts": "SELECT COUNT(*) AS count FROM submission_attempts",
}


class PromotionStatusUnavailable(RuntimeError):
    """Raised when a trustworthy read-only inventory cannot be produced."""


def _validated_ledger_path(ledger: Path) -> Path:
    try:
        metadata = ledger.lstat()
        parent_metadata = ledger.parent.lstat()
    except OSError as exc:
        raise PromotionStatusUnavailable("ledger path is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise PromotionStatusUnavailable("ledger is not a service-owned regular file")
    if metadata.st_mode & 0o077:
        raise PromotionStatusUnavailable("ledger permissions are too broad")
    if not stat.S_ISDIR(parent_metadata.st_mode) or parent_metadata.st_uid != os.geteuid():
        raise PromotionStatusUnavailable("ledger parent is not a service-owned directory")
    if parent_metadata.st_mode & 0o022:
        raise PromotionStatusUnavailable("ledger parent permissions are too broad")
    try:
        resolved = ledger.resolve(strict=True)
    except OSError as exc:
        raise PromotionStatusUnavailable("ledger path cannot be resolved") from exc
    for suffix in ("-journal", "-wal"):
        if Path(f"{resolved}{suffix}").exists():
            raise PromotionStatusUnavailable("ledger has an unresolved SQLite sidecar")
    return resolved


def _open_immutable(ledger: Path) -> sqlite3.Connection:
    resolved = _validated_ledger_path(ledger)
    uri = f"file:{quote(str(resolved), safe='/')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
    except sqlite3.Error as exc:
        raise PromotionStatusUnavailable("ledger cannot be opened read-only") from exc
    return connection


def _exact_text(row: Mapping[str, object], name: str) -> str:
    value = row[name]
    if type(value) is not str or not value:
        raise PromotionStatusUnavailable("ledger contains invalid text")
    return value


def _exact_bool(row: Mapping[str, object], name: str) -> bool:
    value = row[name]
    if type(value) is not int or value not in (0, 1):
        raise PromotionStatusUnavailable("ledger contains an invalid boolean")
    return bool(value)


def _utc_timestamp(row: Mapping[str, object], name: str) -> datetime:
    value = _exact_text(row, name)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise PromotionStatusUnavailable("ledger contains an invalid timestamp") from exc
    return require_utc(parsed)


def _reason_codes(row: Mapping[str, object]) -> tuple[str, ...]:
    try:
        raw: object = json.loads(_exact_text(row, "reason_codes_json"))
    except (TypeError, ValueError) as exc:
        raise PromotionStatusUnavailable("ledger contains invalid reason codes") from exc
    if type(raw) is not list or any(type(item) is not str or not item for item in raw):
        raise PromotionStatusUnavailable("ledger contains invalid reason codes")
    return tuple(raw)


def _observation(row: Mapping[str, object]) -> PromotionObservation:
    try:
        identity = PromotionIdentity(
            account_fingerprint=_exact_text(row, "account_fingerprint"),
            provider_evidence_hash=_exact_text(row, "provider_evidence_hash"),
            strategy_version=_exact_text(row, "strategy_version"),
            strategy_eligibility_hash=_exact_text(row, "strategy_eligibility_hash"),
            config_hash=_exact_text(row, "config_hash"),
            code_hash=_exact_text(row, "code_hash"),
        )
        return PromotionObservation(
            stage=PromotionStage(_exact_text(row, "stage")),
            cycle_id=_exact_text(row, "cycle_id"),
            identity=identity,
            started_at=_utc_timestamp(row, "started_at"),
            completed_at=_utc_timestamp(row, "completed_at"),
            data_hash=_exact_text(row, "data_hash"),
            identity_verified=_exact_bool(row, "identity_verified"),
            provider_evidence_verified=_exact_bool(row, "provider_evidence_verified"),
            strategy_eligible=_exact_bool(row, "strategy_eligible"),
            authenticated_reads=_exact_bool(row, "authenticated_reads"),
            data_validated=_exact_bool(row, "data_validated"),
            outcomes_complete=_exact_bool(row, "outcomes_complete"),
            reconciliation_clean=_exact_bool(row, "reconciliation_clean"),
            fixture_data=_exact_bool(row, "fixture_data"),
            runtime_scope_valid=_exact_bool(row, "runtime_scope_valid"),
            order_state_known=_exact_bool(row, "order_state_known"),
            eligible=_exact_bool(row, "eligible"),
            reason_codes=_reason_codes(row),
            evidence_hash=_exact_text(row, "evidence_hash"),
        )
    except (TypeError, ValueError) as exc:
        raise PromotionStatusUnavailable("ledger contains an invalid observation") from exc


def _read_observations(connection: sqlite3.Connection) -> tuple[PromotionObservation, ...]:
    rows = connection.execute(
        """
        SELECT
            stage, cycle_id, account_fingerprint, provider_evidence_hash,
            strategy_version, strategy_eligibility_hash, config_hash, code_hash,
            data_hash, started_at, completed_at, identity_verified,
            provider_evidence_verified, strategy_eligible, authenticated_reads,
            data_validated, outcomes_complete, reconciliation_clean, fixture_data,
            runtime_scope_valid, order_state_known, eligible, reason_codes_json,
            evidence_hash
        FROM promotion_observations
        ORDER BY completed_at, stage, cycle_id
        """
    ).fetchall()
    return tuple(_observation(row) for row in rows)


def _eligibility_counts(connection: sqlite3.Connection, table: str) -> dict[str, int]:
    counts = {"eligible": 0, "ineligible": 0, "total": 0}
    try:
        query = _ELIGIBILITY_QUERIES[table]
    except KeyError as exc:
        raise PromotionStatusUnavailable("unsupported eligibility inventory") from exc
    rows = connection.execute(query)
    for row in rows:
        eligible = _exact_bool(row, "eligible")
        count = row["count"]
        if type(count) is not int or count < 0:
            raise PromotionStatusUnavailable("ledger contains an invalid count")
        counts["eligible" if eligible else "ineligible"] = count
        counts["total"] += count
    return counts


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    try:
        query = _COUNT_QUERIES[table]
    except KeyError as exc:
        raise PromotionStatusUnavailable("unsupported table inventory") from exc
    row = connection.execute(query).fetchone()
    if row is None or type(row["count"]) is not int or row["count"] < 0:
        raise PromotionStatusUnavailable("ledger contains an invalid count")
    return int(row["count"])


def _identity_hash(identity: PromotionIdentity) -> str:
    return str(
        content_hash(
            {
                "account_fingerprint": identity.account_fingerprint,
                "code_hash": identity.code_hash,
                "config_hash": identity.config_hash,
                "provider_evidence_hash": identity.provider_evidence_hash,
                "strategy_eligibility_hash": identity.strategy_eligibility_hash,
                "strategy_version": identity.strategy_version,
            }
        )
    )


def _stage_inventory(
    observations: tuple[PromotionObservation, ...], stage: PromotionStage
) -> dict[str, int]:
    matching = tuple(item for item in observations if item.stage is stage)
    eligible = sum(item.eligible for item in matching)
    return {
        "eligible": eligible,
        "ineligible": len(matching) - eligible,
        "total": len(matching),
    }


def _identity_series(
    loaded: LoadedConfig,
    observations: tuple[PromotionObservation, ...],
    now: datetime,
) -> list[dict[str, object]]:
    grouped: dict[PromotionIdentity, list[PromotionObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.identity, []).append(observation)
    evaluator = PromotionEvaluator(loaded.config.promotion)
    output: list[dict[str, object]] = []
    for identity, values in grouped.items():
        identity_observations = tuple(values)
        previews: dict[str, object] = {}
        for stage in _PREVIEW_STAGES:
            decision = evaluator.evaluate(
                stage=stage,
                identity=identity,
                observations=identity_observations,
                now=now,
            )
            previews[stage.value] = {
                "calendar_days": decision.evidence.calendar_days,
                "eligible": decision.eligible,
                "reasons": list(decision.reasons),
                "unique_observations": decision.evidence.unique_observations,
            }
        output.append(
            {
                "identity_hash": _identity_hash(identity),
                "observations": {
                    stage.value: _stage_inventory(identity_observations, stage)
                    for stage in _OBSERVATION_STAGES
                },
                "promotion_previews": previews,
            }
        )
    return sorted(output, key=lambda item: str(item["identity_hash"]))


def read_promotion_status(
    *,
    loaded: LoadedConfig,
    ledger: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return a sanitized preview; this function never grants or persists promotion."""

    observed_at = require_utc(now or datetime.now(UTC))
    connection: sqlite3.Connection | None = None
    try:
        connection = _open_immutable(ledger)
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if len(integrity) != 1 or integrity[0][0] != "ok":
            raise PromotionStatusUnavailable("ledger integrity check failed")
        available_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            if type(row[0]) is str
        }
        if not _REQUIRED_TABLES.issubset(available_tables):
            raise PromotionStatusUnavailable("ledger schema is incomplete")
        observations = _read_observations(connection)
        inventory: dict[str, object] = {
            "execution_leases": _table_count(connection, "execution_leases"),
            "live_authorizations": _table_count(connection, "live_authorizations"),
            "live_leases": _table_count(connection, "live_leases"),
            "promotion_evidence": _eligibility_counts(connection, "promotion_evidence"),
            "research_acceptance_evidence": _eligibility_counts(
                connection, "research_acceptance_evidence"
            ),
            "submission_attempts": _table_count(connection, "submission_attempts"),
        }
    except (OSError, sqlite3.Error) as exc:
        raise PromotionStatusUnavailable("ledger inventory failed") from exc
    finally:
        if connection is not None:
            connection.close()

    settings = loaded.config.promotion
    return {
        "configuration": {
            "config_hash": loaded.config_hash,
            "live_trading_enabled": loaded.config.live_trading_enabled,
            "mode": loaded.config.mode.value,
            "promotion_requirements": {
                "normal_min_combined_calendar_days": settings.normal_min_combined_calendar_days,
                "normal_min_valid_observations": settings.normal_min_valid_observations,
                "paper_min_eligible_unique_cycles": settings.paper_min_eligible_unique_cycles,
                "shadow_min_calendar_days": settings.shadow_min_calendar_days,
            },
            "start_paused": loaded.config.runtime.start_paused,
        },
        "identity_series": _identity_series(loaded, observations, observed_at),
        "inventory": inventory,
        "ledger_integrity": "ok",
        "live_activation_permitted": False,
        "status": "promotion_preview_only",
    }


__all__ = [
    "PromotionStatusUnavailable",
    "read_promotion_status",
]
