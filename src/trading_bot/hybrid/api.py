"""Authenticated investor API. No broker writes or live-activation route exists."""

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.execution import mark_equity
from trading_bot.hybrid.models import Account
from trading_bot.hybrid.worker import Journal, worker_loop
from trading_bot.research.hybrid_service import research_snapshot
from trading_bot.research.stock_dashboard import (
    StockDashboardFeed,
    present_stock_dashboard,
    unavailable_stock_dashboard,
)
from trading_bot.research.stock_decision_dashboard import (
    StockDecisionFeed,
    present_stock_decisions,
    unavailable_stock_decisions,
)


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume_research", "kill"]


def snapshot(account: Account, policy: HybridSettings) -> dict[str, object]:
    from trading_bot.hybrid.inputs import ResearchInputs, present_research

    now = datetime.now(UTC)
    research = (
        present_research(ResearchInputs.model_validate_json(account.research_json), now)
        if account.research_json
        else research_snapshot()
    )
    if account.comparisons_json is not None:
        comparison = json.loads(account.comparisons_json)
        research["comparisons"] = [
            dict(
                model,
                name=model.get("model", "unknown"),
                status="illustrative_only",
                detail="Unqualified historical scenario; not actual performance",
            )
            for model in comparison.get("models", [])
        ]
    # Match the persisted valuation/exposure guards: a new response cannot refresh
    # old quotes or accept observations outside their recorded valuation checkpoint.
    valuation_at = account.valuation_at
    marks = (
        {
            quote.symbol: quote
            for quote in account.marks
            if 0 <= (now - quote.as_of).total_seconds() <= 5 and quote.as_of <= valuation_at
        }
        if valuation_at is not None and 0 <= (now - valuation_at).total_seconds() <= 5
        else {}
    )
    try:
        equity = mark_equity(account, marks)
    except ValueError:
        equity = None
    allocation_values = {
        sleeve: sum(
            (
                lot.quantity * marks[lot.symbol].bid
                for lot in account.lots
                if lot.sleeve == sleeve and lot.symbol in marks
            ),
            Decimal(0),
        )
        for sleeve in ("long_term", "tactical")
    }
    allocations: dict[str, str | None] = {
        "long_term": str(allocation_values["long_term"]) if equity is not None else None,
        "tactical": str(allocation_values["tactical"]) if equity is not None else None,
        "reserve": str(account.cash),
    }
    readiness = [
        {"name": name, "status": "blocked", "reason": reason}
        for name, reason in (
            ("Strategy evidence", "No qualified strategy; historical ETF study did not qualify"),
            ("Broker runtime", "Unattended authentication and complete order mapping unverified"),
            ("Live authorization", "Separate explicit authorization required"),
        )
    ]
    return {
        "generated_at": now.isoformat(),
        "mode": "paper",
        "live_enabled": False,
        "portfolio": {
            "starting_capital": str(account.starting_capital),
            "equity": None if equity is None else str(equity),
            "cash": str(account.cash),
            "buying_power": str(account.buying_power),
            "reserved_cash": str(account.reserved_cash),
            "tax_reserve": str(account.tax_reserve),
            "realized_gain": str(account.realized_gain),
            "unrealized_gain": (
                str(
                    sum(
                        (lot.quantity * marks[lot.symbol].bid - lot.basis for lot in account.lots),
                        Decimal(0),
                    )
                )
                if equity is not None
                else None
            ),
            "drawdown_pct": str(
                max(Decimal(0), (account.high_watermark - equity) / account.high_watermark * 100)
            )
            if equity is not None
            else None,
            "allocations": allocations,
            "positions": [
                {
                    "symbol": lot.symbol,
                    "quantity": str(lot.quantity),
                    "market_value": str(lot.quantity * marks[lot.symbol].bid)
                    if lot.symbol in marks
                    else None,
                    "unrealized_gain": str(lot.quantity * marks[lot.symbol].bid - lot.basis)
                    if lot.symbol in marks
                    else None,
                }
                for lot in account.lots
            ],
            "orders": [order.model_dump(mode="json") for order in account.orders],
            "lots": [
                {
                    "symbol": lot.symbol,
                    "quantity": str(lot.quantity),
                    "cost_basis": str(lot.basis),
                    "acquired_at": lot.acquired_at.isoformat(),
                }
                for lot in account.lots
            ],
            "valuation_status": ("cash_only" if not account.lots else "as_of_observation")
            if equity is not None
            else "marks_unavailable",
            "valuation_at": account.valuation_at.isoformat() if account.valuation_at else None,
            "tax_status": "assumed" if policy.tax_rate is not None else "unknown",
        },
        "research": research,
        "safety": {
            "paused": account.paused,
            "kill_switch": account.kill_switch,
            "live_enabled": False,
            "paper_period_required": False,
            "readiness": readiness,
            "authorization_status": "not_authorized",
            "tactical_suspended": account.tactical_suspended,
            "weekly_review_required": account.weekly_review_required,
        },
        "costs": {
            "monthly_usd": str(policy.monthly_operating_usd),
            "annual_pct_of_starting_capital": str(
                (policy.monthly_operating_usd * 12 / account.starting_capital * 100).normalize()
            ),
            "additional_budget_usd": 0,
        },
        "jobs": [job.model_dump(mode="json") for job in account.jobs],
        "reports": [report.model_dump(mode="json") for report in account.reports],
    }


def build_hybrid_app(
    owner: Journal,
    policy: HybridSettings,
    token: str,
    *,
    static_dir: Path | None = None,
    run_worker: bool = False,
    stock_research_reader: StockDashboardFeed | None = None,
    stock_decision_reader: StockDecisionFeed | None = None,
) -> FastAPI:
    if len(token) < 32 or any(char.isspace() for char in token):
        raise ValueError("a private high-entropy dashboard token is required")
    expected = hashlib.sha256(token.encode()).digest()

    def current_snapshot(account: Account) -> dict[str, object]:
        result = snapshot(account, policy)
        if stock_research_reader is not None:
            try:
                view = present_stock_dashboard(
                    stock_research_reader(),
                    now=datetime.now(UTC),
                    maximum_age_seconds=stock_research_reader.maximum_age_seconds,
                )
            except Exception:
                view = unavailable_stock_dashboard("export_unavailable")
            original = result["research"]
            if isinstance(original, dict):
                view["comparisons"] = original.get("comparisons", [])
            result["research"] = view
        if stock_decision_reader is not None:
            try:
                decisions = present_stock_decisions(
                    stock_decision_reader(),
                    now=datetime.now(UTC),
                    maximum_age_seconds=stock_decision_reader.maximum_age_seconds,
                )
            except Exception:
                decisions = unavailable_stock_decisions("export_unavailable")
            research = result["research"]
            if isinstance(research, dict):
                research["current_decisions"] = decisions
        return result

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        task = asyncio.create_task(worker_loop(owner, policy)) if run_worker else None
        app.state.worker = task
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    async def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        supplied = (
            credentials.credentials
            if credentials and credentials.scheme.lower() == "bearer"
            else ""
        )
        if not hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(), expected):
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
            )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        origin = request.headers.get("origin")
        if request.method != "GET" and origin and origin != str(request.base_url).rstrip("/"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Cross-origin control denied"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        await owner.read()
        task = getattr(app.state, "worker", None)
        if task is not None and task.done():
            raise HTTPException(503, "Research worker unavailable")
        return {"healthy": True, "live_enabled": False}

    @app.get("/readyz")
    async def readyz() -> None:
        raise HTTPException(503, "Live readiness denied; no live authorization")

    @app.get("/api/hybrid/snapshot", dependencies=[Depends(authenticate)])
    async def get_snapshot() -> dict[str, object]:
        return current_snapshot(await owner.read())

    @app.post("/api/hybrid/controls", dependencies=[Depends(authenticate)])
    async def control(body: Control) -> dict[str, object]:
        def change(account: Account) -> Account:
            if body.action == "resume_research" and account.kill_switch:
                raise ValueError("Kill switch requires an offline operator review")
            return Account.model_validate(
                account.model_dump()
                | {
                    "paused": body.action != "resume_research",
                    "kill_switch": account.kill_switch or body.action == "kill",
                }
            )

        try:
            account = await owner.change(str(uuid4()), "control", {"action": body.action}, change)
        except ValueError:
            raise HTTPException(409, "Control denied; operator review required") from None
        return current_snapshot(account)

    if static_dir is not None:
        if not (static_dir / "index.html").is_file():
            raise ValueError("built dashboard assets unavailable")
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app
