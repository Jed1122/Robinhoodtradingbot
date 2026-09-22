"""Fail-closed runtime migration entry point for the service-owned ledger."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from alembic import command
from alembic.config import Config

from trading_bot.persistence.base import PersistenceConfigurationError


def migrate_sqlite_ledger(
    ledger_path: str | Path,
    *,
    alembic_ini: str | Path,
    migrations_dir: str | Path,
) -> str:
    ledger = Path(ledger_path)
    parent = ledger.parent
    try:
        parent_metadata = parent.lstat()
    except OSError as exc:
        raise PersistenceConfigurationError("ledger parent directory is unavailable") from exc
    if not stat.S_ISDIR(parent_metadata.st_mode) or parent_metadata.st_uid != os.geteuid():
        raise PersistenceConfigurationError("ledger parent must be a service-owned directory")
    if parent_metadata.st_mode & 0o022:
        raise PersistenceConfigurationError("ledger parent cannot be group or world writable")
    if ledger.exists() or ledger.is_symlink():
        metadata = ledger.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PersistenceConfigurationError("ledger must be a service-owned regular file")
        if metadata.st_mode & 0o077:
            raise PersistenceConfigurationError("ledger must use mode 0600 or stricter")

    configuration_path = Path(alembic_ini).resolve(strict=True)
    scripts = Path(migrations_dir).resolve(strict=True)
    if not configuration_path.is_file() or not scripts.is_dir():
        raise PersistenceConfigurationError("migration resources are unavailable")
    database_url = f"sqlite+aiosqlite:///{ledger.resolve()}"
    config = Config(str(configuration_path))
    config.set_main_option("script_location", str(scripts))
    config.set_main_option("sqlalchemy.url", database_url)
    previous_umask = os.umask(0o077)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        raise PersistenceConfigurationError("ledger migration failed") from exc
    finally:
        os.umask(previous_umask)
    try:
        os.chmod(ledger, 0o600)
    except OSError as exc:
        raise PersistenceConfigurationError("ledger permissions could not be secured") from exc
    return database_url


__all__ = ["migrate_sqlite_ledger"]
