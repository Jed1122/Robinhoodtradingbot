"""Enforce one-way submission-attempt provenance and outcome semantics.

Revision ID: 0003_submission_attempt_guards
Revises: 0002_append_only_guards
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_submission_attempt_guards"
down_revision: str | Sequence[str] | None = "0002_append_only_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "submission_attempts"
_INSERT_TRIGGER = "trg_submission_attempts_contract_insert"
_UPDATE_TRIGGER = "trg_submission_attempts_contract_update"

_IMMUTABLE_COLUMNS = (
    "id",
    "intent_id",
    "review_id",
    "account_id",
    "instrument_id",
    "deduplication_key",
    "provider",
    "provider_client_reference",
    "fencing_token",
    "attempt_started_at",
    "execution_mode",
    "live_lease_id",
    "live_lease_evidence_hash",
)


def _mode_provenance(prefix: str = "") -> str:
    return f"""
    (
        ({prefix}execution_mode IN ('micro_live', 'normal_live')
         AND {prefix}fencing_token > 0
         AND {prefix}live_lease_id IS NOT NULL
         AND {prefix}live_lease_evidence_hash IS NOT NULL)
        OR
        ({prefix}execution_mode IN ('backtest', 'simulation', 'paper', 'shadow')
         AND {prefix}fencing_token = 0
         AND {prefix}live_lease_id IS NULL
         AND {prefix}live_lease_evidence_hash IS NULL)
    )
    """


def _pending(prefix: str = "") -> str:
    return f"""
    {prefix}outcome_class = 'pending'
    AND {prefix}completed_at IS NULL
    AND {prefix}sanitized_response_hash IS NULL
    """


def _terminal(prefix: str = "") -> str:
    return f"""
    {prefix}outcome_class IN ('accepted', 'rejected', 'ambiguous')
    AND {prefix}completed_at IS NOT NULL
    AND {prefix}completed_at >= {prefix}attempt_started_at
    AND (
        {prefix}outcome_class = 'ambiguous'
        OR {prefix}sanitized_response_hash IS NOT NULL
    )
    """


def _known_outcome_has_order(prefix: str = "") -> str:
    return f"""
    (
        {prefix}outcome_class = 'ambiguous'
        OR (
            {prefix}outcome_class = 'accepted'
            AND EXISTS (
                SELECT 1 FROM orders
                WHERE submission_attempt_id = {prefix}id
                  AND state IN ('submitted', 'partially_filled', 'filled')
            )
        )
        OR (
            {prefix}outcome_class = 'rejected'
            AND EXISTS (
                SELECT 1 FROM orders
                WHERE submission_attempt_id = {prefix}id
                  AND state = 'rejected'
            )
        )
    )
    """


def _insert_trigger_sql() -> str:
    return f"""
    CREATE TRIGGER "{_INSERT_TRIGGER}"
    BEFORE INSERT ON "{_TABLE}"
    WHEN NOT ({_mode_provenance("NEW.")} AND {_pending("NEW.")})
    BEGIN
        SELECT RAISE(ROLLBACK, 'submission attempt contract rejected');
    END
    """


def _update_trigger_sql() -> str:
    immutable_changed = "\n        OR ".join(
        f'NEW."{column}" IS NOT OLD."{column}"' for column in _IMMUTABLE_COLUMNS
    )
    return f"""
    CREATE TRIGGER "{_UPDATE_TRIGGER}"
    BEFORE UPDATE ON "{_TABLE}"
    WHEN NOT (
        OLD.outcome_class = 'pending'
        AND OLD.completed_at IS NULL
        AND OLD.sanitized_response_hash IS NULL
        AND NOT ({immutable_changed})
        AND {_mode_provenance("NEW.")}
        AND {_terminal("NEW.")}
        AND {_known_outcome_has_order("NEW.")}
    )
    BEGIN
        SELECT RAISE(ROLLBACK, 'submission attempt contract rejected');
    END
    """


def _invalid_existing_count() -> int:
    connection = op.get_bind()
    statement = sa.text(
        f'SELECT count(*) FROM "{_TABLE}" WHERE NOT ({_mode_provenance()} AND {_pending()})'  # nosec B608
    )
    return int(connection.execute(statement).scalar_one())


def upgrade() -> None:
    if _invalid_existing_count() != 0:
        raise RuntimeError("existing submission attempts violate the durable contract")
    op.execute(_insert_trigger_sql())
    op.execute(_update_trigger_sql())


def downgrade() -> None:
    op.execute(f'DROP TRIGGER "{_UPDATE_TRIGGER}"')
    op.execute(f'DROP TRIGGER "{_INSERT_TRIGGER}"')
