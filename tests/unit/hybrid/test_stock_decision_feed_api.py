"""Optional decision projection is authenticated and cannot enable execution."""

from types import SimpleNamespace

import httpx
import pytest

from tests.unit.hybrid.test_stock_feed_api import TOKEN, Owner
from tests.unit.runtime.test_stock_investment_evidence import NOW
from tests.unit.runtime.test_stock_investment_plan import plan
from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid import api
from trading_bot.runtime.stock_decision_export import project_current_stock_decisions


class Feed:
    maximum_age_seconds = 7200
    calls = 0

    def __init__(self, fail=False):
        self.fail = fail

    def __call__(self):
        self.calls += 1
        if self.fail:
            raise OSError("private-unavailable-path")
        return project_current_stock_decisions(plan(allocation_context=None), "a" * 64)


@pytest.mark.asyncio
async def test_optional_decision_view_is_not_read_by_guests_and_keeps_legacy_absence_exact(
    monkeypatch,
):
    monkeypatch.setattr(api, "datetime", SimpleNamespace(now=lambda _: NOW))
    owner = Owner()
    feed = Feed()
    app = api.build_hybrid_app(owner, HybridSettings(), TOKEN, stock_decision_reader=feed)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/api/hybrid/snapshot")).status_code == 401 and feed.calls == 0
        result = (
            await client.get("/api/hybrid/snapshot", headers={"Authorization": "Bearer " + TOKEN})
        ).json()
    current = result["research"].pop("current_decisions")
    assert (
        current["status"] == "available"
        and current["long_term"]["decisions"][0]["symbol"] == "ALFA"
    )
    assert current["execution_authorized"] is current["live_authorized"] is False
    assert result == api.snapshot(owner.state, HybridSettings())
    assert feed.calls == 1


@pytest.mark.asyncio
async def test_decision_feed_errors_have_no_private_text_or_eligible_fallback(monkeypatch):
    monkeypatch.setattr(api, "datetime", SimpleNamespace(now=lambda _: NOW))
    app = api.build_hybrid_app(
        Owner(), HybridSettings(), TOKEN, stock_decision_reader=Feed(fail=True)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/api/hybrid/snapshot", headers={"Authorization": "Bearer " + TOKEN}
        )
    assert "private-unavailable-path" not in response.text
    view = response.json()["research"]["current_decisions"]
    assert view["status"] == "unavailable" and view["long_term"]["decisions"] == []
