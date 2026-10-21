from datetime import UTC, datetime
from decimal import Decimal

import httpx

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.api import build_hybrid_app
from trading_bot.hybrid.models import Account
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
