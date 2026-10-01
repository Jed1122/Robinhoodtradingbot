"""Cost-evidence contracts only; source labels and hashes do not certify calibration."""

import hashlib
import os
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from decimal import Context, Decimal, localcontext
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

from trading_bot.clock import DomainValidationError, require_utc
from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    _require_sha256_hex,
    require_bounded_decimal,
)
from trading_bot.market_data.bundle_codec import (
    _array,
    _decimal,
    _digest,
    _json,
    _mapping,
    _string,
    _time,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.lifecycle_accounting import _context

_UNITS = {
    "commission_per_share": "USD/share",
    "minimum_commission": "USD/order",
    "regulatory_per_notional": "USD/USD",
    "extra_slippage": "bps",
    "latency": "seconds",
    "cash_rate": "whole_percent/year",
    "operating_cost": "USD/day",
}


@dataclass(frozen=True, slots=True)
class EtfCostInterval:
    role: str
    unit: str
    value: Decimal
    currency: Literal["USD"]
    starts_at: datetime
    ends_at: datetime
    known_at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        if type(self.role) is not str or self.role not in _UNITS:
            raise DomainValidationError("unsupported cost role")
        if type(self.unit) is not str or self.unit != _UNITS[self.role]:
            raise DomainValidationError("cost unit does not match role")
        if type(self.currency) is not str or self.currency != "USD":
            raise DomainValidationError("unsupported cost currency")
        require_bounded_decimal(self.value, "cost value", nonnegative=True)
        for value in (self.starts_at, self.ends_at, self.known_at):
            require_utc(value)
        if self.starts_at >= self.ends_at:
            raise DomainValidationError("empty or reversed cost interval")
        _require_sha256_hex(self.source_hash, "cost source")


@dataclass(frozen=True, slots=True)
class EtfCostEvidence:
    intervals: tuple[EtfCostInterval, ...]
    source_kind: Literal["synthetic", "recorded"]
    calibration_hashes: tuple[str, ...]
    calibration_status: Literal["unverified"] = field(default="unverified", init=False)
    spread_in_fill_price: Literal[True] = field(default=True, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.intervals) is not tuple or not 1 <= len(self.intervals) <= 10000:
            raise DomainValidationError("cost intervals must be a bounded immutable tuple")
        if any(type(i) is not EtfCostInterval for i in self.intervals):
            raise DomainValidationError("invalid cost interval record")
        for item in self.intervals:
            replace(item)
        if {i.role for i in self.intervals} != set(_UNITS):
            raise DomainValidationError("missing cost role is not a zero-cost assumption")
        for role in _UNITS:
            windows = sorted(
                (i for i in self.intervals if i.role == role), key=lambda i: i.starts_at
            )
            if any(a.ends_at > b.starts_at for a, b in pairwise(windows)):
                raise DomainValidationError("overlapping or duplicate cost intervals")
        if type(self.source_kind) is not str or self.source_kind not in ("synthetic", "recorded"):
            raise DomainValidationError("unsupported cost provenance")
        if type(self.calibration_hashes) is not tuple or len(self.calibration_hashes) > 10000:
            raise DomainValidationError("calibration identities must be a bounded tuple")
        for digest in self.calibration_hashes:
            _require_sha256_hex(digest, "cost calibration")
        if len(set(self.calibration_hashes)) != len(self.calibration_hashes):
            raise DomainValidationError("duplicate calibration identity")

    @property
    def cost_hash(self) -> DataHash:
        return content_hash({"schema": "etf-cost-evidence-v1", "costs": self})


class EtfCostSourceError(ValueError):
    """Sanitized failure: no filenames, arbitrary fields or provider text escape."""

    def __init__(self) -> None:
        super().__init__("etf_cost_source_invalid")


def _fee_context() -> Context:
    context = _context(exact=True)
    # Three bounded factors plus an incremental minimum require exact arithmetic,
    # independent of the caller's precision, rounding, flags and exponent limits.
    context.prec = 4 * MAX_CANONICAL_DECIMAL_TEXT_LENGTH
    return context


@dataclass(frozen=True, slots=True)
class EtfExecutionCharges:
    """Incremental fixture charges; neither calibrated fees nor execution authority."""

    commission_usd: Decimal
    regulatory_fee_usd: Decimal
    total_fee_usd: Decimal
    cost_hash: str
    fee_schedule_hash: str
    observed_at: datetime
    regulatory_side_assumption: Literal["both-sides-unverified-upper-bound"] = field(
        default="both-sides-unverified-upper-bound", init=False
    )
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for value in (self.commission_usd, self.regulatory_fee_usd, self.total_fee_usd):
            require_bounded_decimal(value, "execution fee", nonnegative=True)
        _require_sha256_hex(self.cost_hash, "cost identity")
        _require_sha256_hex(self.fee_schedule_hash, "active fee schedule")
        require_utc(self.observed_at)
        with localcontext(_fee_context()):
            if self.commission_usd + self.regulatory_fee_usd != self.total_fee_usd:
                raise DomainValidationError("execution fee total is inconsistent")


def etf_execution_charges(
    costs: EtfCostEvidence,
    *,
    at: datetime,
    prior_quantity: Decimal,
    quantity: Decimal,
    price: Decimal,
    prior_schedule_hash: str | None = None,
) -> EtfExecutionCharges:
    """Charge a positive fill once, preserving a per-order minimum across partials.

    All seven active roles must be present and known before their interval starts.
    Continuations bind that complete active schedule rather than repricing earlier
    fills under a new epoch. Regulatory charges are a conservative, unverified
    both-sides assumption, not a claim about any broker's fee policy. Spread and
    additional slippage belong in the execution price, not a second fee debit.
    """
    try:
        _require(type(costs) is EtfCostEvidence)
        checked = replace(costs)
        _require(
            costs.calibration_status == "unverified"
            and type(costs.calibration_status) is str
            and costs.spread_in_fill_price is True
            and costs.execution_enabled is False
            and costs.evidence_promotable is False
            and checked == costs
        )
        require_utc(at)
        require_bounded_decimal(prior_quantity, "prior fill quantity", nonnegative=True)
        require_bounded_decimal(quantity, "fill quantity", positive=True)
        require_bounded_decimal(price, "fill price", positive=True)
        active = tuple(
            sorted(
                (item for item in checked.intervals if item.starts_at <= at < item.ends_at),
                key=lambda item: item.role,
            )
        )
        _require(len(active) == len(_UNITS) and {i.role for i in active} == set(_UNITS))
        _require(all(item.known_at <= item.starts_at for item in active))
        rates = {item.role: item.value for item in active}
        _require(rates["latency"] > 0)
        schedule_hash = content_hash(active)
        if prior_quantity == 0:
            _require(prior_schedule_hash is None)
        else:
            _require(type(prior_schedule_hash) is str)
            _require_sha256_hex(cast(str, prior_schedule_hash), "prior fee schedule")
            _require(prior_schedule_hash == schedule_hash)
        with localcontext(_fee_context()):
            previous = (
                max(rates["minimum_commission"], prior_quantity * rates["commission_per_share"])
                if prior_quantity > 0
                else Decimal(0)
            )
            commission = (
                max(
                    rates["minimum_commission"],
                    (prior_quantity + quantity) * rates["commission_per_share"],
                )
                - previous
            )
            regulatory = quantity * price * rates["regulatory_per_notional"]
            return EtfExecutionCharges(
                commission,
                regulatory,
                commission + regulatory,
                checked.cost_hash,
                schedule_hash,
                at,
            )
    except (ValueError, TypeError, ArithmeticError, RecursionError, AttributeError):
        raise EtfCostSourceError() from None


_MAX_MANIFEST_BYTES = 1048576
_MAX_SOURCE_BYTES = 1048576
_MAX_TOTAL_BYTES = 8388608
_MAX_REFERENCES = 256


def _require(ok: bool) -> None:
    if not ok:
        raise EtfCostSourceError()


def _cost_interval(value: object) -> EtfCostInterval:
    row = _mapping(value, {item.name for item in fields(EtfCostInterval)})
    _require(row["currency"] == "USD")
    return EtfCostInterval(
        role=_string(row["role"]),
        unit=_string(row["unit"]),
        value=_decimal(row["value"]),
        currency="USD",
        starts_at=_time(row["starts_at"]),
        ends_at=_time(row["ends_at"]),
        known_at=_time(row["known_at"]),
        source_hash=_digest(row["source_hash"]),
    )


def _full_coverage(costs: EtfCostEvidence, study: EtfStudy) -> None:
    for role in _UNITS:
        cursor = study.requested_start
        for item in sorted(
            (i for i in costs.intervals if i.role == role), key=lambda i: i.starts_at
        ):
            _require(item.starts_at == cursor and item.ends_at <= study.requested_end)
            _require(item.known_at <= item.starts_at)
            _require(role != "latency" or item.value > 0)
            cursor = item.ends_at
        _require(cursor == study.requested_end)


def load_etf_cost_evidence(
    manifest_path: Path, allowed_root: Path, study: EtfStudy
) -> EtfCostEvidence:
    """Load bounded private inputs, not verified costs or live permissions.

    The SHA256-named manifest binds the frozen study and cost plan. Every required
    role must cover the full requested window without a gap, overlap or future-
    known rate. Referenced source/calibration bytes must exist and match their
    SHA256.raw names. These integrity checks cannot certify source semantics,
    historical availability, fractional pricing or empirical fill calibration.
    No network, writes, fee calculation or execution owner is introduced here.
    """
    try:
        _require(type(study) is EtfStudy)
        _require(isinstance(manifest_path, Path) and isinstance(allowed_root, Path))
        _require(manifest_path.is_absolute() and ".." not in manifest_path.parts)
        _require(manifest_path.parent == allowed_root and manifest_path.suffix == ".json")
        _require_sha256_hex(manifest_path.stem, "cost manifest")
        root = _open_root(allowed_root, Path(__file__).resolve().parents[3])
        try:
            encoded = _read(root, manifest_path.name, _MAX_MANIFEST_BYTES)
            _require(hashlib.sha256(encoded).hexdigest() == manifest_path.stem)
            manifest = _mapping(
                _json(
                    encoded,
                    max_bytes=_MAX_MANIFEST_BYTES,
                    limits=BundleLimits(
                        _MAX_MANIFEST_BYTES, _MAX_SOURCE_BYTES, _MAX_TOTAL_BYTES, 10000, 16
                    ),
                ),
                {
                    "schema",
                    "study_hash",
                    "cost_plan_hash",
                    "source_kind",
                    "starts_at",
                    "ends_at",
                    "intervals",
                    "calibration_hashes",
                },
            )
            _require(manifest["schema"] == "etf-cost-manifest-v1")
            _require(manifest["study_hash"] == study.study_hash)
            _require(manifest["cost_plan_hash"] == study.cost_plan_hash)
            _require(_time(manifest["starts_at"]) == study.requested_start)
            _require(_time(manifest["ends_at"]) == study.requested_end)
            rows = _array(manifest["intervals"])
            calibrations = _array(manifest["calibration_hashes"])
            _require(len(rows) <= 10000 and len(calibrations) <= _MAX_REFERENCES)
            costs = EtfCostEvidence(
                intervals=tuple(_cost_interval(item) for item in rows),
                source_kind=cast(
                    Literal["synthetic", "recorded"], _string(manifest["source_kind"])
                ),
                calibration_hashes=tuple(_digest(item) for item in calibrations),
            )
            _full_coverage(costs, study)
            references = {i.source_hash for i in costs.intervals} | set(costs.calibration_hashes)
            _require(len(references) <= _MAX_REFERENCES)
            total = len(encoded)
            for digest in sorted(references):
                _require(total < _MAX_TOTAL_BYTES)
                body = _read(
                    root, digest + ".raw", min(_MAX_SOURCE_BYTES, _MAX_TOTAL_BYTES - total)
                )
                _require(bool(body) and hashlib.sha256(body).hexdigest() == digest)
                total += len(body)
            return costs
        finally:
            os.close(root)
    except (OSError, ValueError, TypeError, ArithmeticError, RecursionError, AttributeError):
        raise EtfCostSourceError() from None
