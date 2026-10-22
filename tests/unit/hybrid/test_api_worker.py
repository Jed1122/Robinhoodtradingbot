from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid import api
from trading_bot.hybrid.api import build_hybrid_app
from trading_bot.hybrid.models import Account, Lot, Quote, Settlement
from trading_bot.hybrid.worker import run_due_jobs

TOKEN = "fictional-test-token-with-at-least-32-characters"
NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)


class MemoryJournal:
    def __init__(self):
        self.state = Account()
        self.keys = set()

    async def read(self):
        return self.state

    async def change(self, key, kind, payload, transition):
        if key not in self.keys:
            self.state = transition(self.state)
            self.keys.add(key)
        return self.state


@pytest.fixture
def snapshot_clock(monkeypatch):
    current = [NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz == UTC
            return current[0]

    monkeypatch.setattr(api, "datetime", Clock)
    return current


def marked_account(*, quote_at=NOW, valuation_at=NOW):
    return Account(
        cash=Decimal(100),
        realized_gain=Decimal(25),
        tax_reserve=Decimal(10),
        high_watermark=Decimal(1500),
        lots=(
            Lot(
                id="holding",
                symbol="AAA",
                sleeve="long_term",
                quantity=Decimal(10),
                basis=Decimal(1000),
                acquired_at=NOW - timedelta(days=100),
            ),
        ),
        marks=(Quote(symbol="AAA", bid=Decimal(110), ask=Decimal(111), as_of=quote_at),),
        valuation_at=valuation_at,
    )


@pytest.mark.parametrize(
    ("quote_at", "valuation_at", "available"),
    [
        (NOW, NOW, True),
        (NOW - timedelta(seconds=5), NOW, True),
        (NOW - timedelta(seconds=5, microseconds=1), NOW, False),
        (NOW + timedelta(microseconds=1), NOW, False),
        (NOW, None, False),
        (NOW, NOW - timedelta(seconds=6), False),
        (NOW, NOW + timedelta(microseconds=1), False),
        (NOW, NOW - timedelta(seconds=1), False),
    ],
)
def test_portfolio_values_require_fresh_marks_bound_to_a_valid_valuation(
    snapshot_clock, quote_at, valuation_at, available
):
    account = marked_account(quote_at=quote_at, valuation_at=valuation_at)
    view = api.snapshot(account, HybridSettings())
    portfolio = view["portfolio"]
    assert view["generated_at"] == NOW.isoformat()
    assert portfolio["valuation_at"] == (
        valuation_at.isoformat() if valuation_at is not None else None
    )
    assert portfolio["cash"] == "100"
    assert portfolio["buying_power"] == "90"
    assert portfolio["realized_gain"] == "25"
    assert portfolio["tax_reserve"] == "10"
    assert portfolio["equity"] == ("1200" if available else None)
    assert portfolio["unrealized_gain"] == ("100" if available else None)
    assert portfolio["drawdown_pct"] == ("20.0" if available else None)
    assert portfolio["allocations"] == {
        "long_term": "1100" if available else None,
        "tactical": "0" if available else None,
        "reserve": "100",
    }
    assert portfolio["positions"] == [
        {
            "symbol": "AAA",
            "quantity": "10",
            "market_value": "1100" if available else None,
            "unrealized_gain": "100" if available else None,
        }
    ]
    assert portfolio["valuation_status"] == (
        "as_of_observation" if available else "marks_unavailable"
    )


def test_never_marked_holdings_are_unknown_while_cash_only_is_ledger_valued(snapshot_clock):
    holdings = marked_account().model_copy(update={"marks": (), "valuation_at": None})
    unmarked = api.snapshot(holdings, HybridSettings())["portfolio"]
    assert unmarked["equity"] is unmarked["positions"][0]["market_value"] is None
    assert unmarked["valuation_status"] == "marks_unavailable"
    cash_only = Account(
        cash=Decimal(100),
        settlements=(
            Settlement(id="settling", amount=Decimal(50), due_at=NOW + timedelta(days=1)),
        ),
    )
    cash = api.snapshot(cash_only, HybridSettings())["portfolio"]
    assert cash["equity"] == "150"
    assert cash["unrealized_gain"] == "0"
    assert cash["valuation_status"] == "cash_only"
    assert cash["valuation_at"] is None
    assert cash["allocations"] == {"long_term": "0", "tactical": "0", "reserve": "100"}


async def test_new_responses_cannot_refresh_persisted_portfolio_marks(snapshot_clock):
    owner = MemoryJournal()
    owner.state = marked_account()
    app = build_hybrid_app(owner, HybridSettings(), TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        first = (await client.get("/api/hybrid/snapshot", headers=headers)).json()
        assert first["portfolio"]["equity"] == "1200"
        snapshot_clock[0] = NOW + timedelta(seconds=6)
        second = (await client.get("/api/hybrid/snapshot", headers=headers)).json()
        assert second["generated_at"] == snapshot_clock[0].isoformat()
        assert second["portfolio"]["equity"] is None
        assert second["portfolio"]["valuation_status"] == "marks_unavailable"
        assert second["portfolio"]["valuation_at"] == first["portfolio"]["valuation_at"]
        paused = (
            await client.post("/api/hybrid/controls", headers=headers, json={"action": "pause"})
        ).json()
        assert paused["portfolio"]["equity"] is None
        assert paused["portfolio"]["positions"][0]["market_value"] is None
        assert owner.state.marks == marked_account().marks
        assert owner.state.valuation_at == NOW


async def test_authentication_controls_and_no_live_endpoint():
    owner = MemoryJournal()
    app = build_hybrid_app(owner, HybridSettings(), TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/api/hybrid/snapshot")).status_code == 401
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = await client.get("/api/hybrid/snapshot", headers=headers)
        assert response.status_code == 200
        state = response.json()
        assert state["portfolio"]["equity"] == "1000"
        assert state["costs"]["annual_pct_of_starting_capital"] == "14.4"
        assert state["safety"]["paper_period_required"] is False
        response = await client.post(
            "/api/hybrid/controls", headers=headers, json={"action": "resume_research"}
        )
        assert response.json()["safety"]["paused"] is False
        await client.post("/api/hybrid/controls", headers=headers, json={"action": "kill"})
        assert owner.state.kill_switch is True
        assert (
            await client.post(
                "/api/hybrid/controls", headers=headers, json={"action": "enable_live"}
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/hybrid/controls", headers=headers, json={"action": "resume_research"}
            )
        ).status_code == 409
        assert (await client.post("/api/hybrid/live", headers=headers)).status_code == 404
        assert (
            await client.post(
                "/api/hybrid/controls",
                headers=headers | {"Origin": "https://evil.test"},
                json={"action": "pause"},
            )
        ).status_code == 403


async def test_scheduler_durable_deduplication_and_paused_behavior():
    owner = MemoryJournal()
    assert await run_due_jobs(owner, HybridSettings(), NOW) == 0
    owner.state = owner.state.model_copy(update={"paused": False})
    assert await run_due_jobs(owner, HybridSettings(), NOW) > 0
    count = len(owner.keys)
    await run_due_jobs(owner, HybridSettings(), NOW)
    assert len(owner.keys) == count
    assert owner.state.reports[0].status == "insufficient_evidence"
    assert owner.state.cash == Decimal(1000)
