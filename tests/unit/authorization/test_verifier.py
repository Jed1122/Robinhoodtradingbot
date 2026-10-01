from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.authorization import InvalidAuthorization, PreflightReport, validate_preflight
from trading_bot.config import load_config
from trading_bot.domain import AccountId, CodeHash, ConfigHash, ExecutionMode

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def valid_report() -> PreflightReport:
    return PreflightReport(
        AccountId("account-1"),
        ExecutionMode.MICRO_LIVE,
        Decimal("100"),
        ConfigHash("a" * 64),
        CodeHash("b" * 64),
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        NOW,
        True,
        False,
        True,
        True,
        True,
        False,
        True,
        True,
        0,
        Decimal("0.5"),
    )


def validate(report: PreflightReport) -> str:
    return validate_preflight(
        report, now=NOW, account_allowlist=("account-1",), equity_ceiling=Decimal("150")
    )


def test_ready_preflight_has_stable_hash() -> None:
    assert validate(valid_report()) == validate(valid_report())


@pytest.mark.parametrize(
    "report",
    [
        replace(valid_report(), equity=Decimal("150.01")),
        replace(valid_report(), observed_at=NOW - timedelta(seconds=301)),
        replace(valid_report(), kill_switch_active=True),
        replace(valid_report(), reconciliation_clean=False),
        replace(valid_report(), critical_alert_count=1),
        replace(valid_report(), clock_drift_seconds=Decimal("2.01")),
    ],
)
def test_preflight_gates_fail_closed(report: PreflightReport) -> None:
    with pytest.raises(InvalidAuthorization):
        validate(report)


@pytest.mark.parametrize(("equity", "allowed"), [("1000", True), ("1000.01", False)])
def test_authorization_preflight_enforces_canonical_account_ceiling(
    equity: str, allowed: bool
) -> None:
    configs = Path(__file__).parents[3] / "configs"
    loaded = load_config(
        base_path=configs / "base.yaml",
        mode_path=configs / "micro_live.yaml",
        safety_path=configs / "safety-envelope.yaml",
        environ={},
    )
    report = replace(valid_report(), equity=Decimal(equity), config_hash=loaded.config_hash)

    def check() -> str:
        return validate_preflight(
            report,
            now=NOW,
            account_allowlist=("account-1",),
            equity_ceiling=loaded.config.portfolio.live_account_equity_ceiling_usd,
        )

    if allowed:
        assert len(check()) == 64
    else:
        with pytest.raises(InvalidAuthorization, match="exceeds live ceiling"):
            check()
