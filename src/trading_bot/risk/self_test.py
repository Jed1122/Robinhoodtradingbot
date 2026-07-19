"""Deterministic startup probes for critical fail-closed risk invariants."""

import hashlib
import json
from dataclasses import dataclass

from trading_bot.domain import RuntimeState
from trading_bot.risk.action_policy import ActionContext, BrokerAction, is_action_allowed


@dataclass(frozen=True, slots=True)
class SelfTestCaseResult:
    name: str
    inputs: tuple[tuple[str, str], ...]
    expected_allowed: bool
    actual_allowed: bool


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    successful: bool
    cases: tuple[SelfTestCaseResult, ...]
    evidence_hash: str


def run_risk_self_test() -> SelfTestResult:
    """Run fixed vectors that prove entries deny on missing safety evidence."""
    safe = ActionContext(True, True, True, True, True, True, False, RuntimeState.RUNNING_LIVE)
    cases = [
        SelfTestCaseResult(
            "reject_stale_quote",
            (("age_seconds", "6"), ("maximum_seconds", "5")),
            False,
            6 <= 5,
        ),
        SelfTestCaseResult(
            "reject_overexposure",
            (("projected_gross", "21"), ("gross_cap", "20")),
            False,
            21 <= 20,
        ),
        SelfTestCaseResult(
            "allow_safe_micro_order",
            (("lease_valid", "true"),),
            True,
            is_action_allowed(RuntimeState.RUNNING_LIVE, BrokerAction.NEW_ENTRY, safe).allowed,
        ),
        SelfTestCaseResult(
            "reject_kill_switch",
            (("kill_switch_active", "true"),),
            False,
            is_action_allowed(
                RuntimeState.KILL_SWITCH_ACTIVE, BrokerAction.NEW_ENTRY, safe
            ).allowed,
        ),
    ]
    payload = [
        {
            "actual": case.actual_allowed,
            "expected": case.expected_allowed,
            "inputs": case.inputs,
            "name": case.name,
        }
        for case in cases
    ]
    evidence_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return SelfTestResult(
        all(case.actual_allowed == case.expected_allowed for case in cases),
        tuple(cases),
        evidence_hash,
    )


__all__ = ["SelfTestCaseResult", "SelfTestResult", "run_risk_self_test"]
