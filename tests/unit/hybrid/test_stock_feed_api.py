"""Stock feed is authenticated, descriptive and separate from account controls."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.api import build_hybrid_app
from trading_bot.hybrid.models import Account
from trading_bot.research.stock_dashboard import StockDashboardExport

TOKEN = "fictional-dashboard-token-with-more-than-32-characters"


class Owner:
    state = Account()

    async def read(self):
        return self.state

    async def change(self, key, kind, payload, transition):
        self.state = transition(self.state)
        return self.state


class Feed:
    maximum_age_seconds = 7200

    def __init__(self, change=None):
        self.calls = 0
        self.change = change

    def __call__(self):
        self.calls += 1
        if self.change == "fail":
            raise OSError("private-provider-error-token")
        export = StockDashboardExport.model_validate(
            {
                "schema_version": 1,
                "kind": "stock_research_dashboard",
                "generated_at": datetime.now(UTC)
                - timedelta(days=1 if self.change == "stale" else 0),
                "config_hash": "a" * 64,
                "code_hash": "b" * 64,
                "state_sha256": "c" * 64,
                "worker": {
                    "last_claim_at": None,
                    "last_result_at": None,
                    "phase": None,
                    "status": "never_run",
                    "reason": None,
                    "pending_claims": 0,
                    "reserved_today": 0,
                    "daily_limit": 512,
                    "remaining_calls": 512,
                    "next_eligible_at": None,
                },
                "discovery": None,
                "enrichment": None,
                "qualified": False,
                "investment_eligible": False,
                "live_enabled": False,
            }
        )
        return (
            export.model_copy(update={"live_enabled": True}) if self.change == "forged" else export
        )


@pytest.mark.asyncio
async def test_stock_feed_is_never_read_for_guests_or_health_and_controls_stay_separate():
    owner, feed = Owner(), Feed()
    app = build_hybrid_app(owner, HybridSettings(), TOKEN, stock_research_reader=feed)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/api/hybrid/snapshot")).status_code == 401
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/readyz")).status_code == 503
        assert feed.calls == 0
        headers = {"Authorization": f"Bearer {TOKEN}"}
        first = (await client.get("/api/hybrid/snapshot", headers=headers)).json()
        assert feed.calls == 1
        assert first["research"]["stock_worker"]["status"] == "never_run"
        assert first["research"]["stock_worker"]["control_scope"] == "separate"
        response = await client.post(
            "/api/hybrid/controls", headers=headers, json={"action": "resume_research"}
        )
        assert response.status_code == 200 and feed.calls == 2
        assert response.json()["safety"]["paused"] is False
        assert response.json()["research"]["stock_worker"]["status"] == "never_run"
        assert owner.state.cash == Account().cash and owner.state.orders == ()
        assert response.json()["live_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,reason",
    [("fail", "export_unavailable"), ("forged", "export_unavailable"), ("stale", "stale_export")],
)
async def test_bad_feed_becomes_unavailable_without_private_text_or_unsafe_fallback(change, reason):
    owner, feed = Owner(), Feed(change)
    app = build_hybrid_app(owner, HybridSettings(), TOKEN, stock_research_reader=feed)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/api/hybrid/snapshot", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200
        view = response.json()
        assert view["research"]["opportunities"] == []
        assert view["research"]["stock_worker"]["reason"] == reason
        assert view["research"]["stock_worker"]["reserved_today"] is None
        assert view["live_enabled"] is view["safety"]["live_enabled"] is False
        assert "private-provider-error-token" not in response.text
        assert owner.state.paused is True
