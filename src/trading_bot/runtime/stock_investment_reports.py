"""Exact current-plan JSON and bounded private report storage; no execution authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from trading_bot.clock import require_utc
from trading_bot.runtime.stock_archive import _read
from trading_bot.runtime.stock_archive_lease import LOCK_NAME, StockArchiveLease
from trading_bot.runtime.stock_capture import _private_directory, _publish
from trading_bot.runtime.stock_investment_plan import CurrentStockPlan

_MAX_FILES = 1024
_MAX_BYTES = 64 * 1024 * 1024
_MAX_BODY = 9_000_000
_SUFFIX = ".stock-investment.json"
_FILE = re.compile(r"[0-9a-f]{64}" + re.escape(_SUFFIX) + r"\Z")
_FLAGS = ("execution_authorized", "live_authorized", "orders_created", "reservations_created")


class StockInvestmentReportError(ValueError):
    """Fixed error text, without private paths or source contents."""


def _check(valid: bool) -> None:
    if not valid:
        raise StockInvestmentReportError("current_stock_report_invalid")


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _wire(value: object) -> Any:
    if type(value) is Decimal:
        _check(value.is_finite())
        exponent = value.as_tuple().exponent
        _check(isinstance(exponent, int) and -10000 <= exponent <= 10000)
        _check(len(value.as_tuple().digits) <= 10000)
        # Decimal.__str__ is exact; only its exponent-letter case uses context.
        # Do not call the portfolio money/display canonicalizer here.
        with localcontext() as context:
            context.capitals = 1
            return str(value)
    if type(value) is datetime:
        return require_utc(value).isoformat()
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, dict):
        _check(all(type(key) is str for key in value))
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        _check(type(value) in (tuple, list))
        return [_wire(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise StockInvestmentReportError("current_stock_report_invalid")


def _encode(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _scope(document: dict[str, Any]) -> None:
    _check(
        type(document) is dict
        and set(document)
        == {
            "schema_version",
            "report_kind",
            "status",
            "report_evidence_hash",
            "component_hashes",
            "plan",
            *_FLAGS,
        }
    )
    _check(type(document["schema_version"]) is int and document["schema_version"] in (1, 2))
    _check(document["report_kind"] == "current_stock_plan")
    _check(all(document[key] is False for key in _FLAGS))
    _check(_sha(document["report_evidence_hash"]))
    plan = document["plan"]
    hashes = document["component_hashes"]
    _check(type(plan) is dict and type(hashes) is dict)
    if document["schema_version"] == 1:
        _check("portfolio_proposals" not in plan)
    _check(all(plan[key] is False for key in _FLAGS))
    _check(plan["performance_evidence"] == "unproven_not_a_gate")
    expected = {
        "inputs": plan["inputs_hash"],
        "evidence_batch": plan["evidence_batch_hash"],
        "policy": plan["policy_hash"],
        "controls": plan["controls_hash"],
        "issuers": plan["issuer_hashes"],
        "analysis_code_hash": plan["analysis_code_hash"],
        "source_config_hash": plan["source_config_hash"],
        "acquisition_code_hashes": plan["acquisition_code_hashes"],
    }
    if document["schema_version"] == 2:
        expected["portfolio_proposals"] = None
        portfolio = plan["portfolio_proposals"]
        if portfolio is not None:
            _check(type(portfolio) is dict)
            _check(
                all(
                    portfolio[key] is False
                    for key in (*_FLAGS, "cash_credited", "global_concurrency_authority")
                )
            )
            _check(_sha(hashes["portfolio_proposals"]))
            expected["portfolio_proposals"] = hashes["portfolio_proposals"]
            holdings = portfolio["holding_reviews"]
            if holdings is not None:
                _check(
                    type(holdings) is dict
                    and holdings["execution_authorized"] is False
                    and holdings["live_authorized"] is False
                )
                for review in holdings["reviews"]:
                    _check(
                        type(review) is dict
                        and all(
                            review[key] is False
                            for key in (
                                "execution_authorized",
                                "live_authorized",
                                "order_created",
                                "performance_proven",
                                "first_eligible_session_verified",
                            )
                        )
                        and review["execute_not_before"] is None
                    )
            for profit in portfolio["profit_reductions"]:
                _check(type(profit) is dict and profit["indicative_estimates_only"] is True)
                _check(
                    all(
                        profit[key] is False
                        for key in (
                            "execution_authorized",
                            "live_authorized",
                            "order_created",
                            "cash_credited",
                            "completed_threshold_created",
                            "global_concurrency_authority",
                            "performance_proven",
                        )
                    )
                )
    _check(set(hashes) == {*expected, "rankings", "allocation", "decisions"})
    _check(all(hashes[key] == value for key, value in expected.items()))
    for key in ("inputs", "evidence_batch", "policy", "analysis_code_hash", "source_config_hash"):
        _check(_sha(hashes[key]))
    _check(hashes["controls"] is None or _sha(hashes["controls"]))
    for key in ("issuers", "acquisition_code_hashes"):
        _check(type(hashes[key]) is list and all(_sha(x) for x in hashes[key]))
    rankings, allocation = plan["rankings"], plan["allocation"]
    _check((hashes["rankings"] is None) == (rankings is None))
    _check((hashes["allocation"] is None) == (allocation is None))
    _check(type(hashes["decisions"]) is list)
    if rankings is not None:
        _check(type(rankings) is dict and _sha(hashes["rankings"]))
        _check(
            all(
                rankings[key] is False
                for key in (
                    "source_qualified",
                    "strategy_qualified",
                    "execution_authorized",
                    "live_authorized",
                )
            )
        )
        for key in ("assessments", "long_term", "tactical"):
            _check(type(rankings[key]) is list and len(rankings[key]) <= 10000)
            for decision in rankings[key]:
                _check(type(decision) is dict)
                _check(
                    all(
                        decision[name] is False
                        for name in (
                            "source_qualified",
                            "strategy_qualified",
                            "execution_authorized",
                            "trading_enabled",
                            "live_authorized",
                        )
                    )
                )
                _check(decision["performance_evidence"] == "unproven_not_a_gate")
        _check(len(hashes["decisions"]) == len(rankings["assessments"]))
        for identity, decision in zip(hashes["decisions"], rankings["assessments"], strict=True):
            _check(
                type(identity) is dict
                and set(identity)
                == {"symbol", "horizon", "decision_hash", "evidence_hash", "policy_hash"}
            )
            _check(
                identity["symbol"] == decision["symbol"]
                and identity["horizon"] == decision["horizon"]
            )
            _check(
                identity["evidence_hash"] == decision["evidence_hash"]
                and identity["policy_hash"] == decision["policy_hash"]
            )
            _check(
                all(_sha(identity[k]) for k in ("decision_hash", "evidence_hash", "policy_hash"))
            )
    else:
        _check(hashes["decisions"] == [])
    if allocation is not None:
        _check(type(allocation) is dict and _sha(hashes["allocation"]))
        _check(all(allocation[key] is False for key in (*_FLAGS, "global_concurrency_authority")))
    _check(
        document["status"] == ("research_only" if allocation is None else "portfolio_cash_ceilings")
    )


def current_stock_plan_document(plan: CurrentStockPlan) -> dict[str, Any]:
    """Render the typed owner's output exactly, without shared money rounding."""
    try:
        _check(type(plan) is CurrentStockPlan)
        evidence = plan.evidence_hash
        decisions = (
            []
            if plan.rankings is None
            else [
                {
                    "symbol": row.symbol,
                    "horizon": row.horizon,
                    "decision_hash": row.decision_hash,
                    "evidence_hash": row.evidence_hash,
                    "policy_hash": row.policy_hash,
                }
                for row in plan.rankings.assessments
            ]
        )
        document = {
            "schema_version": 2,
            "report_kind": "current_stock_plan",
            "status": "research_only" if plan.allocation is None else "portfolio_cash_ceilings",
            "report_evidence_hash": evidence,
            "component_hashes": {
                "inputs": plan.inputs_hash,
                "evidence_batch": plan.evidence_batch_hash,
                "policy": plan.policy_hash,
                "controls": plan.controls_hash,
                "issuers": list(plan.issuer_hashes),
                "analysis_code_hash": plan.analysis_code_hash,
                "source_config_hash": plan.source_config_hash,
                "acquisition_code_hashes": list(plan.acquisition_code_hashes),
                "rankings": None if plan.rankings is None else plan.rankings.report_hash,
                "allocation": None if plan.allocation is None else plan.allocation.evidence_hash,
                "portfolio_proposals": None
                if plan.portfolio_proposals is None
                else plan.portfolio_proposals.evidence_hash,
                "decisions": decisions,
            },
            "plan": _wire(asdict(plan)),
            **dict.fromkeys(_FLAGS, False),
        }
        _scope(document)
        _check(0 < len(_encode(document)) <= _MAX_BODY)
        return document
    except Exception:
        raise StockInvestmentReportError("current_stock_report_invalid") from None


@dataclass(frozen=True, slots=True)
class StockInvestmentReportArtifact:
    file: str
    body_sha256: str
    report_evidence_hash: str


def _roots(output_dir: Path, archive_dir: Path) -> None:
    _check(isinstance(output_dir, Path) and isinstance(archive_dir, Path))
    _check(output_dir.is_absolute() and archive_dir.is_absolute())
    _check(
        output_dir.resolve(strict=True) == output_dir
        and archive_dir.resolve(strict=True) == archive_dir
    )
    _check(
        not output_dir.is_relative_to(archive_dir) and not archive_dir.is_relative_to(output_dir)
    )


def _root_identity(path: Path, descriptor: int) -> None:
    fresh = _private_directory(path)
    try:
        current, owned = os.fstat(fresh), os.fstat(descriptor)
        _check((current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino))
    finally:
        os.close(fresh)


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verified(directory: int, name: str) -> dict[str, Any]:
    document = _read(directory, name, _SUFFIX)
    _scope(document)
    body = _encode(document)
    _check(0 < len(body) <= _MAX_BODY and hashlib.sha256(body).hexdigest() == name[:64])
    return document


def _inventory(directory: int) -> tuple[int, int, set[str]]:
    count = size = 0
    names = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            count += 1
            _check(count <= _MAX_FILES)
            info = entry.stat(follow_symlinks=False)
            _check(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1
            )
            size += info.st_size
            _check(size <= _MAX_BYTES)
            if entry.name == LOCK_NAME:
                _check(info.st_size == 0)
            else:
                _check(_FILE.fullmatch(entry.name) is not None)
                _verified(directory, entry.name)
            _check(
                _stamp(info) == _stamp(os.stat(entry.name, dir_fd=directory, follow_symlinks=False))
            )
            names.add(entry.name)
    return count, size, names


def _opened(output_dir: Path, archive_dir: Path, stack: ExitStack) -> tuple[StockArchiveLease, int]:
    _roots(output_dir, archive_dir)
    source = _private_directory(archive_dir)
    stack.callback(os.close, source)
    target = _private_directory(output_dir)
    stack.callback(os.close, target)
    _check(
        (os.fstat(source).st_dev, os.fstat(source).st_ino)
        != (os.fstat(target).st_dev, os.fstat(target).st_ino)
    )
    lease = stack.enter_context(StockArchiveLease(output_dir, _directory_fd=target))
    _root_identity(archive_dir, source)
    _root_identity(output_dir, lease.directory_fd)
    return lease, source


def publish_current_stock_plan(
    plan: CurrentStockPlan, *, output_dir: Path, archive_dir: Path
) -> StockInvestmentReportArtifact:
    """Publish without overwrite, acquisition-side effects, or execution approval."""
    try:
        document = current_stock_plan_document(plan)
        body = _encode(document)
        digest = hashlib.sha256(body).hexdigest()
        name = digest + _SUFFIX
        with ExitStack() as stack:
            lease, source = _opened(output_dir, archive_dir, stack)
            directory = lease.directory_fd
            count, size, names = _inventory(directory)
            if name in names:
                _check(_verified(directory, name) == document)
                os.fsync(directory)
            else:
                _check(count + 2 <= _MAX_FILES and size + 2 * len(body) <= _MAX_BYTES)
                space = os.fstatvfs(directory)
                _check(
                    space.f_bavail * space.f_frsize >= len(body) + 2 * max(4096, space.f_frsize)
                    and space.f_favail >= 2
                )
                _root_identity(archive_dir, source)
                _root_identity(output_dir, lease.directory_fd)
                published, actual = _publish(directory, body, _SUFFIX)
                _check((published, actual) == (name, digest))
            _inventory(lease.directory_fd)
            _check(_verified(lease.directory_fd, name) == document)
            _root_identity(archive_dir, source)
            _root_identity(output_dir, lease.directory_fd)
            return StockInvestmentReportArtifact(name, digest, document["report_evidence_hash"])
    except Exception:
        raise StockInvestmentReportError("current_stock_report_invalid") from None


def read_current_stock_plan_report(
    *, output_dir: Path, archive_dir: Path, artifact_file: str
) -> dict[str, Any]:
    """Verify private immutable artifact bytes, not upstream source authenticity."""
    try:
        _check(type(artifact_file) is str and _FILE.fullmatch(artifact_file) is not None)
        with ExitStack() as stack:
            lease, source = _opened(output_dir, archive_dir, stack)
            _inventory(lease.directory_fd)
            result = _verified(lease.directory_fd, artifact_file)
            _root_identity(archive_dir, source)
            _root_identity(output_dir, lease.directory_fd)
            return result
    except Exception:
        raise StockInvestmentReportError("current_stock_report_invalid") from None
