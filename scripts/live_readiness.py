"""Fail-closed local readiness audit for operator-controlled live activation."""

from __future__ import annotations

import argparse
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from trading_bot.config import ConfigLoadError, load_config
from trading_bot.domain import ExecutionMode

REQUIRED_CRYPTO_SECRET_FILES: Final[tuple[str, ...]] = (
    "ROBINHOOD_CRYPTO_API_KEY_FILE",
    "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE",
)
REQUIRED_OPERATOR_FILES: Final[tuple[str, ...]] = (
    "TRADING_BOT_AUTH_VERIFY_KEY_FILE",
    "TRADING_BOT_ACCOUNT_ALLOWLIST_FILE",
)
OPTIONAL_SECURE_DIRECTORIES: Final[tuple[str, ...]] = ("ROBINHOOD_MCP_OAUTH_STORE_DIR",)
FORBIDDEN_RUNTIME_SECRET_PATHS: Final[tuple[str, ...]] = ("TRADING_BOT_AUTH_SIGNING_KEY_FILE",)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"detail": self.detail, "name": self.name, "ok": self.ok}


def _mode_bits(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _path_check(name: str, *, required: bool, max_mode: int) -> Check:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return Check(
            name, not required, "unset" if not required else "required environment path is unset"
        )
    path = Path(raw)
    if not path.is_file():
        return Check(name, False, "path is not a regular file")
    mode = _mode_bits(path)
    if mode & ~max_mode:
        return Check(name, False, f"file mode {mode:04o} is more permissive than {max_mode:04o}")
    if path.stat().st_size <= 0:
        return Check(name, False, "file is empty")
    return Check(name, True, f"present with mode {mode:04o}")


def _directory_check(name: str, *, max_mode: int) -> Check:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return Check(name, True, "unset; browser Agentic connection is not a runtime credential")
    path = Path(raw)
    if not path.is_dir():
        return Check(name, False, "path is not a directory")
    mode = _mode_bits(path)
    if mode & ~max_mode:
        return Check(
            name, False, f"directory mode {mode:04o} is more permissive than {max_mode:04o}"
        )
    if path.stat().st_uid != os.geteuid():
        return Check(name, False, "directory is not owned by the runtime user")
    return Check(name, True, f"present with mode {mode:04o}")


def _forbidden_path_check(name: str) -> Check:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return Check(name, True, "unset")
    return Check(name, False, "runtime must not receive operator signing-key path")


def _config_check(config: Path, mode: str) -> Check:
    try:
        loaded = load_config(
            Path("configs/base.yaml"), config, Path("configs/safety-envelope.yaml"), os.environ
        )
    except ConfigLoadError as exc:
        return Check("configuration", False, str(exc))
    expected = ExecutionMode(mode)
    if loaded.config.mode is not expected:
        return Check("configuration", False, f"resolved mode is {loaded.config.mode.value}")
    if not loaded.config.live_trading_enabled:
        return Check("configuration", False, "live_trading_enabled is false")
    if loaded.config.runtime.start_paused is not True:
        return Check("configuration", False, "live runtime must start paused")
    return Check("configuration", True, f"{mode} config hash {loaded.config_hash}")


def evaluate(config: Path, mode: str) -> tuple[bool, tuple[Check, ...]]:
    checks: list[Check] = [_config_check(config, mode)]
    checks.extend(
        _path_check(name, required=True, max_mode=0o600) for name in REQUIRED_CRYPTO_SECRET_FILES
    )
    checks.extend(
        _path_check(name, required=True, max_mode=0o644) for name in REQUIRED_OPERATOR_FILES
    )
    checks.extend(_directory_check(name, max_mode=0o700) for name in OPTIONAL_SECURE_DIRECTORIES)
    checks.extend(_forbidden_path_check(name) for name in FORBIDDEN_RUNTIME_SECRET_PATHS)
    return all(check.ok for check in checks), tuple(checks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/micro_live.yaml"))
    parser.add_argument("--mode", choices=("micro_live", "normal_live"), default="micro_live")
    args = parser.parse_args()
    ready, checks = evaluate(args.config, args.mode)
    print(
        json.dumps(
            {
                "checks": [check.as_dict() for check in checks],
                "ready": ready,
                "status": "ready_for_operator_activation" if ready else "blocked_fail_closed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    raise SystemExit(0 if ready else 2)


if __name__ == "__main__":
    main()
