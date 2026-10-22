"""Bounded descriptive stock projections; no I/O, forecasts or execution authority."""

import re
from datetime import datetime
from decimal import Decimal, DecimalException
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from trading_bot.clock import require_utc
from trading_bot.config.models import StrictFalse
from trading_bot.domain.decimal_utils import canonical_decimal_text, require_bounded_decimal
from trading_bot.logging import contains_registered_secret

type Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
type Symbol = Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9.\-/]{0,14}$")]
type Gap = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z_]{0,79}$")]
type Status = Literal["never_run", "pending", "succeeded", "blocked", "failed", "cancelled"]
_REASONS = {
    "complete",
    "capture_partial",
    "runtime_failure",
    "auth_unavailable",
    "cancelled",
    "schema_mismatch",
    "screen_incomplete",
    "source_stale",
    "artifact_unavailable",
    "report_failed",
    "storage_full",
    "control_denied",
}
_UNAVAILABLE = {"export_unavailable", "stale_export", "future_export", "budget_day_changed"}


class _View(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True
    )


def _number(value: str | None) -> str | None:
    if value is not None:
        if (
            type(value) is not str
            or not 1 <= len(value) <= 128
            or re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value, flags=re.ASCII)
            is None
        ):
            raise ValueError("stock_dashboard_invalid")
        try:
            number = require_bounded_decimal(Decimal(value), "stock dashboard metric")
        except (DecimalException, ValueError):
            raise ValueError("stock_dashboard_invalid") from None
        if number.copy_abs() >= Decimal("1e30"):
            raise ValueError("stock_dashboard_invalid")
        value = canonical_decimal_text(number)
        if len(value) > 128:
            raise ValueError("stock_dashboard_invalid")
    return value


def _secret_leaf(value: object) -> bool:
    if type(value) is str:
        return contains_registered_secret(value)
    if type(value) is dict:
        return any(_secret_leaf(key) or _secret_leaf(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_secret_leaf(item) for item in value)
    return False


class StockDashboardMetrics(_View):
    roe: StrictStr | None
    net_margin: StrictStr | None
    annual_eps_growth: StrictStr | None
    quarterly_revenue_growth: StrictStr | None
    earnings_yield: StrictStr | None
    fcf_yield: StrictStr | None

    _numbers = field_validator("*")(_number)


class StockDashboardOpportunity(_View):
    symbol: Symbol
    research_priority_score: StrictStr
    available_at: datetime
    source_observation_sha256: Digest
    metrics: StockDashboardMetrics

    _utc = field_validator("available_at")(require_utc)

    @field_validator("research_priority_score")
    @classmethod
    def score(cls, value: str) -> str:
        checked = _number(value)
        if not 0 <= Decimal(value) <= 100:
            raise ValueError("stock_dashboard_invalid")
        if checked is None:
            raise ValueError("stock_dashboard_invalid")
        return checked


class StockDashboardWorker(_View):
    last_claim_at: datetime | None
    last_result_at: datetime | None
    phase: Literal["discovery", "enrichment"] | None
    status: Status
    reason: StrictStr | None
    pending_claims: Annotated[StrictInt, Field(ge=0, le=50000)]
    reserved_today: Annotated[StrictInt, Field(ge=0, le=1024)]
    daily_limit: Annotated[StrictInt, Field(ge=1, le=1024)]
    remaining_calls: Annotated[StrictInt, Field(ge=0, le=1024)]
    next_eligible_at: datetime | None

    @field_validator("last_claim_at", "last_result_at", "next_eligible_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.reason is not None and self.reason not in _REASONS:
            raise ValueError("stock_dashboard_invalid")
        if self.remaining_calls != max(0, self.daily_limit - self.reserved_today):
            raise ValueError("stock_dashboard_invalid")
        if self.status == "never_run":
            if any(
                (
                    self.last_claim_at,
                    self.last_result_at,
                    self.phase,
                    self.reason,
                    self.pending_claims,
                    self.reserved_today,
                    self.next_eligible_at,
                )
            ):
                raise ValueError("stock_dashboard_invalid")
        elif self.last_claim_at is None or self.phase is None or self.next_eligible_at is None:
            raise ValueError("stock_dashboard_invalid")
        if self.status == "pending" and (not self.pending_claims or self.reason is not None):
            raise ValueError("stock_dashboard_invalid")
        if self.status not in {"never_run", "pending"} and (
            self.last_result_at is None
            or self.last_claim_at is None
            or self.last_result_at < self.last_claim_at
            or self.reason is None
            or (self.status == "succeeded") != (self.reason == "complete")
        ):
            raise ValueError("stock_dashboard_invalid")
        if (
            self.next_eligible_at
            and self.last_claim_at
            and self.next_eligible_at < self.last_claim_at
        ):
            raise ValueError("stock_dashboard_invalid")
        return self


class StockDashboardDiscovery(_View):
    claimed_at: datetime
    as_of: datetime
    report_sha256: Digest
    manifest_sha256: Digest
    candidate_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    scorable_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    opportunities: Annotated[list[StockDashboardOpportunity], Field(max_length=20)]

    _utc = field_validator("claimed_at", "as_of")(require_utc)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        symbols = [row.symbol for row in self.opportunities]
        if (
            self.claimed_at > self.as_of
            or len(symbols) != len(set(symbols))
            or len(symbols) > self.scorable_count
            or self.scorable_count > self.candidate_count
            or any(
                not self.claimed_at <= row.available_at <= self.as_of for row in self.opportunities
            )
        ):
            raise ValueError("stock_dashboard_invalid")
        return self


class StockDashboardDossier(_View):
    symbol: Symbol
    gaps: Annotated[list[Gap], Field(max_length=64)]

    @field_validator("gaps")
    @classmethod
    def unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("stock_dashboard_invalid")
        return value


class StockDashboardEnrichment(_View):
    claimed_at: datetime
    as_of: datetime
    report_sha256: Digest
    manifest_sha256: Digest
    dossiers: Annotated[list[StockDashboardDossier], Field(max_length=20)]

    _utc = field_validator("claimed_at", "as_of")(require_utc)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.claimed_at > self.as_of or len({row.symbol for row in self.dossiers}) != len(
            self.dossiers
        ):
            raise ValueError("stock_dashboard_invalid")
        return self


class StockDashboardExport(_View):
    schema_version: Literal[1]
    kind: Literal["stock_research_dashboard"]
    generated_at: datetime
    config_hash: Digest
    code_hash: Digest
    state_sha256: Digest
    worker: StockDashboardWorker
    discovery: StockDashboardDiscovery | None
    enrichment: StockDashboardEnrichment | None
    qualified: StrictFalse
    investment_eligible: StrictFalse
    live_enabled: StrictFalse

    _utc = field_validator("generated_at")(require_utc)

    @field_validator("schema_version", mode="before")
    @classmethod
    def version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("stock_dashboard_invalid")
        return value

    @model_validator(mode="after")
    def visible(self) -> Self:
        times = [self.worker.last_claim_at, self.worker.last_result_at]
        times.extend(row.as_of for row in (self.discovery, self.enrichment) if row)
        if any(value is not None and value > self.generated_at for value in times):
            raise ValueError("stock_dashboard_invalid")
        if self.worker.status == "never_run" and (
            self.discovery is not None or self.enrichment is not None
        ):
            raise ValueError("stock_dashboard_invalid")
        if _secret_leaf(self.model_dump()):
            raise ValueError("stock_dashboard_invalid")
        return self


class StockDashboardFeed(Protocol):
    @property
    def maximum_age_seconds(self) -> int: ...

    def __call__(self) -> StockDashboardExport: ...


def unavailable_stock_dashboard(reason: str) -> dict[str, Any]:
    if reason not in _UNAVAILABLE:
        raise ValueError("stock_dashboard_invalid")
    return {
        "regime": "unknown",
        "opportunities": [],
        "sources": [],
        "comparisons": [],
        "strategy_status": [
            {"name": "Individual stock selection", "status": "unavailable", "reason": reason}
        ],
        "limitations": [
            "Stock research is unavailable; no investment conclusion is supported.",
            "Portfolio research controls do not govern the separate stock collector.",
        ],
        "stock_worker": {
            **dict.fromkeys(
                (
                    "exported_at",
                    "last_claim_at",
                    "last_result_at",
                    "phase",
                    "pending_claims",
                    "reserved_today",
                    "daily_limit",
                    "remaining_calls",
                    "next_eligible_at",
                    "discovery_as_of",
                    "enrichment_as_of",
                )
            ),
            "status": "unavailable",
            "reason": reason,
            "control_scope": "separate",
            "qualified": False,
            "live_enabled": False,
        },
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
    }


def present_stock_dashboard(
    export: StockDashboardExport, *, now: datetime, maximum_age_seconds: int
) -> dict[str, Any]:
    if (
        type(export) is not StockDashboardExport
        or type(maximum_age_seconds) is not int
        or not 60 <= maximum_age_seconds <= 86400
    ):
        raise ValueError("stock_dashboard_invalid")
    export = StockDashboardExport.model_validate(export.model_dump())
    now = require_utc(now)
    age = (now - export.generated_at).total_seconds()
    reason = (
        "future_export"
        if age < 0
        else "stale_export"
        if age > maximum_age_seconds
        else "budget_day_changed"
        if now.date() != export.generated_at.date()
        else None
    )
    if reason:
        view = unavailable_stock_dashboard(reason)
        view["stock_worker"]["exported_at"] = export.generated_at.isoformat()
        return view
    discovery, enrichment = export.discovery, export.enrichment
    fresh = (
        discovery is not None
        and (now - discovery.claimed_at).total_seconds() <= maximum_age_seconds
    )
    deeper = (
        enrichment is not None
        and (now - enrichment.claimed_at).total_seconds() <= maximum_age_seconds
    )
    dossiers = {row.symbol: row for row in enrichment.dossiers} if deeper and enrichment else {}
    rows = []
    for row in discovery.opportunities if fresh and discovery else ():
        dossier = dossiers.get(row.symbol)
        rows.append(
            {
                "symbol": row.symbol,
                "strategy": "fundamental_screen",
                "status": "unqualified_research",
                "reason": (
                    "Financial quality, growth and valuation screen; deeper verification pending."
                ),
                "research_priority_score": row.research_priority_score,
                "available_at": row.available_at.isoformat(),
                "metrics": row.metrics.model_dump(),
                "gaps": dossier.gaps if dossier else ["deeper_research_pending"],
                "dossier_as_of": enrichment.as_of.isoformat() if dossier and enrichment else None,
            }
        )
    worker = export.worker.model_dump(mode="json")
    worker.update(
        {
            "exported_at": export.generated_at.isoformat(),
            "discovery_as_of": discovery.as_of.isoformat() if discovery else None,
            "enrichment_as_of": enrichment.as_of.isoformat() if enrichment else None,
            "control_scope": "separate",
            "qualified": False,
            "live_enabled": False,
        }
    )
    extra_limitations = (
        ["Discovery evidence is stale; research priorities are suppressed."]
        if discovery and not fresh
        else []
    )
    return {
        "regime": "unknown",
        "opportunities": rows,
        "sources": [
            {
                "name": "Robinhood stock discovery"
                if label == "discovery"
                else "Robinhood company dossiers",
                "status": "unqualified" if (fresh if label == "discovery" else deeper) else "stale",
                "as_of": item.as_of.isoformat(),
                "report_sha256": item.report_sha256,
                "manifest_sha256": item.manifest_sha256,
            }
            for label, item in (("discovery", discovery), ("enrichment", enrichment))
            if item
        ],
        "strategy_status": [
            {
                "name": "Individual stock selection",
                "status": "unqualified",
                "reason": "No validated relationship between research priority and future returns.",
            }
        ],
        "comparisons": [],
        "stock_worker": worker,
        "limitations": [
            "Research priorities are descriptive scores; investment performance is unvalidated.",
            "Source authenticity, corporate actions and historical coverage remain unqualified.",
            "Missing or unknown observations remain unknown; no expected returns are supplied.",
            "A pending claim is unresolved; it does not establish a running process.",
            "Portfolio research controls do not govern the separate stock collector.",
            *extra_limitations,
        ],
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
    }
