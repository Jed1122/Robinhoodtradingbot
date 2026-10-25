"""Fixed unprivileged stock observation/snapshot helper; no provider or execution."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.domain import CodeHash
from trading_bot.runtime.stock_dashboard_export import _directory, _inventory, _policy, _read
from trading_bot.runtime.stock_research_controls import StockResearchControls
from trading_bot.runtime.stock_snapshot_policy import (
    FULL_REPLAY_V1,
    RECOVERY_INTEGRITY_V1,
    SnapshotValidationPolicy,
)

_ROOT = Path("/var/lib/hybrid-stock-research")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")


def _source_inventory(
    directory: int, tree: str, *, count: int, total: int
) -> dict[str, tuple[int, ...]]:
    from trading_bot.runtime.stock_backup_files import _stamp
    from trading_bot.runtime.stock_snapshot_bundle import _file_limit

    rows: dict[str, tuple[int, ...]] = {}
    size = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(rows) >= count:
                raise ValueError
            limit = _file_limit(tree + "/" + entry.name)
            info = entry.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or not 0 <= info.st_size <= limit
            ):
                raise ValueError
            size += info.st_size
            if size > total:
                raise ValueError
            rows[entry.name] = _stamp(info)
    return rows


def _projected_snapshot_files(data_root: Path, *, archive_files: int, archive_bytes: int) -> int:
    """Count current copied files without creating missing source lock anchors.

    The caller holds the operations barrier. This is bounded admission against
    current metadata, not an inode reservation against unrelated filesystem users.
    """
    from trading_bot.runtime.stock_backup_files import _directory as private_directory
    from trading_bot.runtime.stock_snapshot_bundle import _MAXIMUM_FILES

    copied = 0
    for tree, count, total in (
        ("archive", min(archive_files, _MAXIMUM_FILES - 4), archive_bytes),
        ("exports", 63, 63 * 262144),
    ):
        with private_directory(data_root / tree, os.geteuid()) as directory:
            rows = _source_inventory(directory, tree, count=count, total=total)
            if rows != _source_inventory(directory, tree, count=count, total=total):
                raise ValueError
            # The snapshot lease creates and copies its mutex when absent.
            projected = len(rows) + (".stock-research.lock" not in rows)
            if projected > count:
                raise ValueError
            copied += projected
            # Three root records and the SQLite ledger also enter the bundle.
            if copied + 4 > _MAXIMUM_FILES:
                raise ValueError
    return copied


def read_local_stock_state(
    *, loaded: LoadedConfig, control_dir: Path, export_dir: Path, now: datetime
) -> dict[str, object]:
    """Observe original data/control clocks without refreshing projections.

    Caller holds the host operations lock. Both directories must belong to this
    effective UID. A malformed observation fails as a whole and cannot clear an
    incident. A validated absent projection is explicitly returned as missing.
    """
    try:
        _policy(loaded)
        at = require_utc(now)
        state = StockResearchControls(control_dir).read()
        if state.record.changed_at > at:
            raise ValueError
        with _directory(export_dir) as directory:
            _inventory(directory)
            try:
                export = _read(directory)
            except FileNotFoundError:
                export = None
            if export is not None and export.generated_at > at:
                raise ValueError
        return {
            "version": 1,
            "control": state.record.model_dump(mode="json"),
            "control_sha256": state.sha256,
            "projection": None if export is None else export.model_dump(mode="json"),
        }
    except Exception:
        raise ValueError("stock_local_state_unavailable") from None


def check_local_research_authority(
    *, loaded: LoadedConfig, code_hash: str, control_dir: Path
) -> dict[str, object]:
    """Check a bound research grant only; never resumes, refreshes or executes it."""
    try:
        _policy(loaded)
        if type(code_hash) is not str or _HEX.fullmatch(code_hash) is None:
            raise ValueError
        grant = StockResearchControls(control_dir).grant(
            config_hash=str(loaded.config_hash), code_hash=code_hash
        )
        return {
            "status": "running",
            "control_sha256": grant.state.sha256,
            "control_id": grant.state.record.control_id,
            "generation": grant.state.record.generation,
        }
    except Exception:
        raise ValueError("stock_local_state_unavailable") from None


async def create_local_snapshot_bundle(
    *,
    loaded: LoadedConfig,
    code_hash: str,
    data_root: Path,
    destination_root: Path,
    identifier: str,
    now: datetime,
    validation_policy: SnapshotValidationPolicy = FULL_REPLAY_V1,
) -> dict[str, object]:
    """Snapshot and package only; root encrypts after this process is reaped.

    Partial private staging is retained on failure and counts toward the four
    attempt limit. It is never treated as a completed encrypted backup.
    Caller holds the outer operations lock throughout admission and creation.
    """
    try:
        from trading_bot.runtime.stock_backup_files import _directory as private_directory
        from trading_bot.runtime.stock_snapshot import create_stock_snapshot
        from trading_bot.runtime.stock_snapshot_bundle import pack_snapshot

        policy = _policy(loaded)
        if (
            type(validation_policy) is not str
            or validation_policy not in {FULL_REPLAY_V1, RECOVERY_INTEGRITY_V1}
            or type(identifier) is not str
            or _ID.fullmatch(identifier) is None
            or type(code_hash) is not str
            or _HEX.fullmatch(code_hash) is None
        ):
            raise ValueError
        require_utc(now)
        with private_directory(destination_root, os.geteuid()) as directory:
            count = 0
            attempts: set[str] = set()
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    private = info.st_uid == os.geteuid()
                    if _ID.fullmatch(entry.name) is not None:
                        attempts.add(entry.name)
                        private = (
                            private
                            and stat.S_ISDIR(info.st_mode)
                            and stat.S_IMODE(info.st_mode) == 0o700
                        )
                    elif (
                        entry.name.endswith(".bundle")
                        and _ID.fullmatch(entry.name[:-7]) is not None
                    ):
                        attempts.add(entry.name[:-7])
                        private = (
                            private
                            and stat.S_ISREG(info.st_mode)
                            and info.st_nlink == 1
                            and stat.S_IMODE(info.st_mode) == 0o600
                            and info.st_size <= 2 * 1024**3
                        )
                    else:
                        private = False
                    count += 1
                    if not private or count >= 8:
                        raise ValueError
            if len(attempts) >= 4 or identifier in attempts:
                raise ValueError
            copied_files = _projected_snapshot_files(
                data_root,
                archive_files=policy.stock_worker.max_archive_files,
                archive_bytes=policy.stock_worker.max_archive_bytes,
            )
            space = os.fstatvfs(directory)
            # Reserve the worst-case snapshot, intermediate DB and bundled copy.
            required = 3 * (policy.stock_worker.max_archive_bytes + 256 * 1024**2) + 100 * 1024**2
            # Every retained archive/export name is copied, including pending
            # files and locks. Keep256 additional inodes for the finite snapshot
            # directories, records, SQLite scratch/journals and bundle overhead.
            required_inodes = copied_files + 256
            if space.f_bavail * space.f_frsize < required or space.f_favail < required_inodes:
                raise ValueError
            snapshot = destination_root / identifier
            result = await create_stock_snapshot(
                loaded=loaded,
                code_hash=CodeHash(code_hash),
                database=data_root / "state/ledger.sqlite3",
                archive_dir=data_root / "archive",
                control_dir=data_root / "controls",
                export_dir=data_root / "exports",
                destination=snapshot,
                now=now,
                validation_policy=validation_policy,
            )
            descriptor = os.open(
                identifier + ".bundle",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "wb") as target:
                bundle = pack_snapshot(snapshot, target)
                target.flush()
                os.fsync(target.fileno())
            os.fsync(directory)
        return {
            "status": "snapshot_bundled",
            "identifier": identifier,
            "snapshot": asdict(result),
            "bundle": asdict(bundle),
        }
    except Exception:
        raise ValueError("stock_local_state_unavailable") from None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if (
            sys.platform != "linux"
            or os.geteuid() != 10001
            or len(args) not in {3, 4}
            or args[0] not in {"observe", "control-check", "snapshot", "snapshot-integrity"}
            or any(_HEX.fullmatch(value) is None for value in args[1:3])
            or ((args[0] in {"snapshot", "snapshot-integrity"}) != (len(args) == 4))
        ):
            raise ValueError
        from trading_bot.runtime.stock_research_worker import load_stock_worker_configuration

        loaded = load_stock_worker_configuration(Path(__file__).resolve().parents[3] / "configs")
        if str(loaded.config_hash) != args[1]:
            raise ValueError
        if args[0] in {"snapshot", "snapshot-integrity"}:
            result = asyncio.run(
                create_local_snapshot_bundle(
                    loaded=loaded,
                    code_hash=args[2],
                    data_root=_ROOT,
                    destination_root=_ROOT / "maintenance",
                    identifier=args[3],
                    now=datetime.now(UTC),
                    validation_policy=(
                        RECOVERY_INTEGRITY_V1 if args[0] == "snapshot-integrity" else FULL_REPLAY_V1
                    ),
                )
            )
        elif args[0] == "control-check":
            result = check_local_research_authority(
                loaded=loaded, code_hash=args[2], control_dir=_ROOT / "controls"
            )
        else:
            result = read_local_stock_state(
                loaded=loaded,
                control_dir=_ROOT / "controls",
                export_dir=_ROOT / "exports",
                now=datetime.now(UTC),
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    except Exception:
        print('{"status":"stock_local_state_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
