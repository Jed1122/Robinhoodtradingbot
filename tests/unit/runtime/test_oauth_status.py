"""Status may decrypt lifecycle metadata but never performs provider I/O."""

import json
from datetime import UTC, datetime

import pytest

from trading_bot.runtime import oauth_status


@pytest.mark.asyncio
async def test_status_selects_only_safe_metadata(tmp_path, monkeypatch):
    from tests.unit.brokers.test_robinhood_oauth_provider import provider

    _p, storage = await provider(tmp_path)
    monkeypatch.setattr(oauth_status, "EncryptedFileTokenStorage", lambda _root: storage)
    result = await oauth_status.read_oauth_status(tmp_path, now=datetime(2026, 10, 22, tzinfo=UTC))
    assert set(result) == {
        "version",
        "state",
        "flow",
        "generation",
        "expires_at",
        "last_observed_at",
        "expired",
        "natural_expiry_not_before",
    }
    assert result["expired"] is True
    assert result["state"] == "active"
    assert result["natural_expiry_not_before"] == "2026-10-21T16:15:00+00:00"
    assert "fixture" not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_lifecycle_cannot_claim_active(tmp_path, monkeypatch):
    from tests.unit.brokers.test_robinhood_oauth_provider import provider

    _p, storage = await provider(tmp_path, legacy=True)
    monkeypatch.setattr(oauth_status, "EncryptedFileTokenStorage", lambda _root: storage)
    with pytest.raises(ValueError, match="oauth_status_unavailable"):
        await oauth_status.read_oauth_status(tmp_path, now=datetime(2026, 10, 22, tzinfo=UTC))


@pytest.mark.asyncio
async def test_bad_clock_does_not_claim_status(tmp_path, monkeypatch):
    from tests.unit.brokers.test_robinhood_oauth_provider import provider

    _p, storage = await provider(tmp_path)
    monkeypatch.setattr(oauth_status, "EncryptedFileTokenStorage", lambda _root: storage)
    with pytest.raises(ValueError, match="oauth_status_unavailable"):
        await oauth_status.read_oauth_status(tmp_path, now=datetime(2026, 10, 20, tzinfo=UTC))


@pytest.mark.asyncio
async def test_status_requires_private_store_owner_and_no_lease_overlap(tmp_path):
    from trading_bot.brokers.robinhood_oauth_lifecycle import PrivateOAuthStoreLease

    tmp_path.chmod(0o700)
    with (
        PrivateOAuthStoreLease(tmp_path),
        pytest.raises(ValueError, match="oauth_status_unavailable"),
    ):
        await oauth_status.read_oauth_status(tmp_path, now=datetime.now(UTC))


def test_cli_sanitizes_failure_and_does_not_print_path(tmp_path, capsys):
    assert oauth_status.main(["--oauth-store", str(tmp_path / "private-fixture")]) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "oauth_status_unavailable"}
