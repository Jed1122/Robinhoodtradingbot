"""Small current-decision view contracts; no account, provider, ledger or I/O."""

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from trading_bot.clock import require_utc
from trading_bot.config.models import StrictFalse

Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[StrictStr, Field(min_length=1, max_length=512)]
Symbol = Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9.\-/]{0,14}$")]


class _View(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True
    )


class DecisionSource(_View):
    tool: Text
    observation_sha256: Digest
    record_ref: Text
    received_at: datetime
    _utc = field_validator("received_at")(require_utc)


class DecisionReason(_View):
    code: Text
    fact_name: Text | None
    value: Annotated[StrictStr, Field(max_length=128)] | None
    basis: Text | None


class DecisionRow(_View):
    symbol: Symbol
    horizon: Literal["long_term", "tactical"]
    action: Literal["enter", "hold", "reduce", "review", "avoid"]
    analytically_eligible: StrictBool
    ordinal_rank: Annotated[StrictInt, Field(ge=1, le=5000)] | None
    priority_score: Annotated[StrictStr, Field(max_length=128)] | None
    as_of: datetime
    source_received_at: datetime | None
    expires_at: datetime | None
    decision_hash: Digest
    bullish_evidence: Annotated[list[DecisionReason], Field(max_length=32)]
    bearish_evidence: Annotated[list[DecisionReason], Field(max_length=32)]
    missing_requirements: Annotated[list[Text], Field(max_length=128)]
    limitations: Annotated[list[Text], Field(max_length=32)]
    sources: Annotated[list[DecisionSource], Field(max_length=64)]

    @field_validator("as_of", "source_received_at", "expires_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if (self.source_received_at is not None and self.source_received_at > self.as_of) or any(
            x.received_at > self.as_of for x in self.sources
        ):
            raise ValueError("stock_decision_view_invalid")
        if self.analytically_eligible and (
            self.expires_at is None or self.expires_at <= self.as_of or self.ordinal_rank is None
        ):
            raise ValueError("stock_decision_view_invalid")
        return self


class DecisionTrack(_View):
    horizon: Literal["long_term", "tactical"]
    assessed_count: Annotated[StrictInt, Field(ge=0, le=5000)]
    eligible_count: Annotated[StrictInt, Field(ge=0, le=5000)]
    omitted_count: Annotated[StrictInt, Field(ge=0, le=5000)]
    earliest_eligible_expiry: datetime | None
    decisions: Annotated[list[DecisionRow], Field(max_length=40)]

    @field_validator("earliest_eligible_expiry")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def counts(self) -> Self:
        displayed_expiries = [
            row.expires_at
            for row in self.decisions
            if row.analytically_eligible and row.expires_at is not None
        ]
        if (
            self.assessed_count != len(self.decisions) + self.omitted_count
            or self.eligible_count > self.assessed_count
            or self.eligible_count < sum(row.analytically_eligible for row in self.decisions)
            or (
                self.omitted_count == 0
                and self.eligible_count != sum(row.analytically_eligible for row in self.decisions)
            )
            or any(x.horizon != self.horizon for x in self.decisions)
            or len({x.symbol for x in self.decisions}) != len(self.decisions)
            or (self.eligible_count == 0) != (self.earliest_eligible_expiry is None)
            or (
                self.earliest_eligible_expiry is not None
                and displayed_expiries
                and (
                    self.earliest_eligible_expiry > min(displayed_expiries)
                    or (
                        self.omitted_count == 0
                        and self.earliest_eligible_expiry != min(displayed_expiries)
                    )
                )
            )
        ):
            raise ValueError("stock_decision_view_invalid")
        return self


class StockDecisionExport(_View):
    schema_version: Literal[2] = 2
    worker_profile_id: Literal["stock-worker-current-provider-v1"] = (
        "stock-worker-current-provider-v1"
    )
    generated_at: datetime
    source_config_hash: Digest
    analysis_code_hash: Digest
    policy_hash: Digest
    report_body_sha256: Digest
    report_evidence_hash: Digest
    plan_status: Literal["research_only", "portfolio_cash_ceilings"]
    needs: Annotated[list[Text], Field(max_length=1024)]
    long_term: DecisionTrack
    tactical: DecisionTrack
    performance_evidence: Literal["unproven_not_a_gate"] = "unproven_not_a_gate"
    execution_authorized: StrictFalse = False
    live_authorized: StrictFalse = False
    orders_created: StrictFalse = False
    reservations_created: StrictFalse = False

    _utc = field_validator("generated_at")(require_utc)

    @field_validator("schema_version", mode="before")
    @classmethod
    def version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("stock_decision_view_invalid")
        return value

    @model_validator(mode="after")
    def tracks(self) -> Self:
        if (
            self.long_term.horizon != "long_term"
            or self.tactical.horizon != "tactical"
            or any(
                x.as_of != self.generated_at
                for track in (self.long_term, self.tactical)
                for x in track.decisions
            )
            or any(
                track.earliest_eligible_expiry is not None
                and track.earliest_eligible_expiry <= self.generated_at
                for track in (self.long_term, self.tactical)
            )
        ):
            raise ValueError("stock_decision_view_invalid")
        return self


class StockDecisionFeed(Protocol):
    @property
    def maximum_age_seconds(self) -> int: ...
    def __call__(self) -> StockDecisionExport: ...


def unavailable_stock_decisions(reason: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    if reason not in {"export_unavailable", "stale_export", "future_export", "expired_decision"}:
        raise ValueError("stock_decision_view_invalid")
    return {
        "status": "unavailable",
        "reason": reason,
        "as_of": None if as_of is None else require_utc(as_of).isoformat(),
        "long_term": {"decisions": []},
        "tactical": {"decisions": []},
        "execution_authorized": False,
        "live_authorized": False,
        "orders_created": False,
        "reservations_created": False,
        "performance_evidence": "unproven_not_a_gate",
    }


def present_stock_decisions(
    export: StockDecisionExport, *, now: datetime, maximum_age_seconds: int
) -> dict[str, Any]:
    if (
        type(export) is not StockDecisionExport
        or type(maximum_age_seconds) is not int
        or not 60 <= maximum_age_seconds <= 86400
    ):
        raise ValueError("stock_decision_view_invalid")
    export = StockDecisionExport.model_validate(export.model_dump())
    now = require_utc(now)
    age = (now - export.generated_at).total_seconds()
    source_deadline = export.generated_at + timedelta(seconds=maximum_age_seconds)
    # The aggregate includes eligible source rows omitted from the bounded view.
    # Displayed actions with a known earlier expiry are fenced as well.
    deadlines = [source_deadline]
    for track in (export.long_term, export.tactical):
        if track.earliest_eligible_expiry is not None:
            deadlines.append(track.earliest_eligible_expiry)
        deadlines.extend(row.expires_at for row in track.decisions if row.expires_at is not None)
    valid_until = min(deadlines)
    reason = (
        "future_export"
        if age < 0
        else "stale_export"
        if now >= source_deadline
        else "expired_decision"
        if now >= valid_until
        else None
    )
    if reason:
        return unavailable_stock_decisions(reason, as_of=export.generated_at)
    return export.model_dump(mode="json") | {
        "status": "available",
        "valid_until": valid_until.isoformat(),
    }
