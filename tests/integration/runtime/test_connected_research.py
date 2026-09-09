from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from trading_bot.brokers.robinhood_equity_mapping import account_fingerprint
from trading_bot.code_identity import DeployedImageAttestation
from trading_bot.config import load_config
from trading_bot.domain import AccountId, Bar, BarInterval, DataHash, InstrumentId
from trading_bot.market_data import content_hash
from trading_bot.market_data.robinhood_equity_mcp import EquityHistoricalRead
from trading_bot.runtime import connected_research

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"


def _connected_research_environment() -> dict[str, str]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["connected-research"]["environment"]
    allowed_aliases = {"LIVE_TRADING_ENABLED", "PREDICTION_LIVE_ENABLED"}
    return {
        name: value
        for name, value in environment.items()
        if name.startswith("TRADING_BOT__") or name in allowed_aliases
    }


class FakeSession:
    async def list_tools(self) -> tuple[object, ...]:
        return ()


class FakeConnection:
    def __init__(self, **_: object) -> None:
        self.session = FakeSession()

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeBroker:
    def __init__(self, account_id: AccountId) -> None:
        self._account_id = account_id

    async def health_check(self) -> object:
        return SimpleNamespace(healthy=True)

    async def get_accounts(self) -> tuple[object, ...]:
        return (SimpleNamespace(account_id=self._account_id, restricted=False),)


class FakeMarket:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def get_tradability(self, *_: object, **__: object) -> object:
        return SimpleNamespace(tradeable=True)

    async def get_research_bars(
        self,
        instrument_id: InstrumentId,
        interval: BarInterval,
        start: datetime,
        end: datetime,
    ) -> EquityHistoricalRead:
        del start
        starts_at = end - timedelta(days=2)
        raw_hash = str(content_hash({"instrument": instrument_id}))
        return EquityHistoricalRead(
            bars=(
                Bar(
                    instrument_id,
                    interval,
                    starts_at,
                    starts_at + timedelta(days=1),
                    Decimal("100"),
                    Decimal("101"),
                    Decimal("99"),
                    Decimal("100"),
                    Decimal("1000"),
                    "fixture",
                    DataHash(raw_hash),
                    interpolated=True,
                ),
            ),
            raw_response_hash=raw_hash,
            interpolation_status="unknown",
        )


def test_connected_research_persists_rejected_report_without_writes(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    account_id = AccountId("synthetic-agentic-account")
    oauth = tmp_path / "oauth"
    oauth.mkdir(mode=0o700)
    oauth.chmod(0o700)
    fingerprint = oauth / "account-fingerprint"
    fingerprint.write_text(f"{account_fingerprint(account_id)}\n", encoding="ascii")
    fingerprint.chmod(0o600)
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    evidence.chmod(0o700)

    monkeypatch.setattr(
        connected_research,
        "RobinhoodMcpSdkConnection",
        FakeConnection,
    )
    monkeypatch.setattr(
        connected_research,
        "validate_read_tool_declarations",
        lambda _: DataHash("a" * 64),
    )
    monkeypatch.setattr(
        connected_research,
        "build_equity_read_adapter",
        lambda *_, **__: FakeBroker(account_id),
    )
    monkeypatch.setattr(
        connected_research,
        "RobinhoodEquityMarketData",
        FakeMarket,
    )
    loaded = load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "shadow.yaml",
        CONFIGS / "safety-envelope.yaml",
        _connected_research_environment(),
    )
    image_digest = f"sha256:{'b' * 64}"
    compose_sha256 = "c" * 64
    verified = DeployedImageAttestation(
        image_digest=image_digest,
        deployment_config_hash=str(loaded.config_hash),
        compose_sha256=compose_sha256,
        release_key=(
            f"{'b' * 64}-{loaded.config_hash}-{compose_sha256}"
        ),
    )
    monkeypatch.setattr(
        connected_research,
        "verify_deployed_image_attestation",
        lambda *_, **__: verified,
        raising=False,
    )

    output = connected_research.run_connected_equity_research_once(
        loaded=loaded,
        repository_root=ROOT,
        oauth_store=oauth,
        account_fingerprint_file=fingerprint,
        ledger=evidence / "ledger.db",
        artifact_dir=evidence / "research",
        image_digest=image_digest,
        image_attestation=tmp_path / "runtime-image-attestation.json",
    )

    assert output["status"] == "connected_research_recorded"
    assert output["promotion_eligible"] is False
    assert output["code_identity_verified"] is True
    assert output["write_capabilities_present"] is False
    assert "research_promotion_disabled" in output["ineligible_reasons"]
    artifact = Path(str(output["artifact"]))
    assert artifact.is_file() and artifact.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(evidence / "ledger.db") as connection:
        stored = connection.execute(
            "SELECT eligible, reason_codes_json FROM research_acceptance_evidence"
        ).fetchall()
    assert len(stored) == 1
    assert stored[0][0] == 0
    assert stored[0][1] != "[]"


def test_connected_research_rejects_environment_altered_candidate_scope(
    tmp_path: Path,
) -> None:
    loaded = load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "shadow.yaml",
        CONFIGS / "safety-envelope.yaml",
        {
            "TRADING_BOT__EQUITY_STRATEGIES__RESEARCH_CANDIDATE_STRATEGY_IDS": (
                "[equity_momentum]"
            )
        },
    )

    with pytest.raises(
        connected_research.ConnectedResearchNotReady,
        match="approved release scope",
    ):
        connected_research.run_connected_equity_research_once(
            loaded=loaded,
            repository_root=ROOT,
            oauth_store=tmp_path / "oauth",
            account_fingerprint_file=tmp_path / "fingerprint",
            ledger=tmp_path / "ledger.db",
            artifact_dir=tmp_path / "research",
            image_digest=f"sha256:{'b' * 64}",
            image_attestation=tmp_path / "missing-attestation.json",
        )


def test_connected_research_rejects_read_allowlist_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        connected_research,
        "READ_ONLY_EQUITY_MCP_TOOLS",
        connected_research.READ_ONLY_EQUITY_MCP_TOOLS
        | frozenset({"place_equity_order"}),
    )

    with pytest.raises(
        connected_research.ConnectedResearchNotReady,
        match="capability contract changed",
    ):
        connected_research._validate_connected_read_scope()
