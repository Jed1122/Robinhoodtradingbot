"""Cost-evidence contracts only; source labels and hashes do not certify calibration."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from trading_bot.clock import DomainValidationError, require_utc
from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash

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
