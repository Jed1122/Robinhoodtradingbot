"""Fictional stock observations exercise opt-in quality reporting without provider I/O."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.runtime.stock_dossier_report import compile_stock_dossier_report

AS_OF = datetime(2026, 10, 25, 20, tzinfo=UTC)


def _observation(symbol="ALFA", *, received_at=AS_OF):
    payload = {"data": {"results": [{"symbol": symbol, "market_cap": "2000000000"}]}}
    body = json.dumps(payload, sort_keys=True).encode()
    return {
        "tool": "get_equity_fundamentals",
        "arguments": {"symbols": [symbol]},
        "payload": payload,
        "observation_sha256": hashlib.sha256(body).hexdigest(),
        "received_at": received_at.isoformat(),
        "transport_authenticated": False,
    }


def test_default_report_preserves_existing_format_and_values():
    observations = (_observation(),)
    original = compile_stock_dossier_report(observations=observations, as_of=AS_OF)
    explicit = compile_stock_dossier_report(
        observations=observations, as_of=AS_OF, include_data_quality=False
    )
    assert original == explicit
    assert original["schema_version"] == 2
    assert "data_quality" not in original


def test_opt_in_quality_report_preserves_dossiers_and_never_promotes():
    observations = (_observation(),)
    original = compile_stock_dossier_report(observations=observations, as_of=AS_OF)
    report = compile_stock_dossier_report(
        observations=observations, as_of=AS_OF, include_data_quality=True
    )
    assert report["schema_version"] == 4
    assert report["dossiers"] == original["dossiers"]
    assert report["source_observation_hashes"] == original["source_observation_hashes"]
    assert len(report["data_quality"]) == 1
    quality = report["data_quality"][0]
    assert quality["symbol"] == "ALFA"
    assert len(quality["assessment_sha256"]) == 64
    for name in ("source_qualified", "strategy_qualified", "investment_eligible"):
        assert report[name] is quality[name] is False
    assert report["live_enabled"] is False
    assert report == compile_stock_dossier_report(
        observations=observations, as_of=AS_OF, include_data_quality=True
    )


def test_quality_report_does_not_introduce_future_company_membership():
    report = compile_stock_dossier_report(
        observations=(
            _observation(),
            _observation("BETA", received_at=AS_OF + timedelta(seconds=1)),
        ),
        as_of=AS_OF,
        include_data_quality=True,
    )
    assert report["future_observations_excluded"] == 1
    assert [row["symbol"] for row in report["data_quality"]] == ["ALFA"]


@pytest.mark.parametrize("value", [1, None, "true", [], {}])
def test_quality_option_rejects_non_boolean_values(value):
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        compile_stock_dossier_report(
            observations=(_observation(),), as_of=AS_OF, include_data_quality=value
        )


def test_private_publication_rehashes_sources_and_is_idempotent(tmp_path, monkeypatch):
    from trading_bot.runtime import stock_dossier_report as module

    root = tmp_path.resolve()
    root.chmod(0o700)
    reads = []

    def verified_read(actual_root, manifest_file, *, _directory_fd):
        reads.append((actual_root, manifest_file))
        return (_observation(),)

    monkeypatch.setattr(module, "read_stock_observations", verified_read)
    manifest = "a" * 64 + ".stock-capture.json"
    result = module.publish_stock_dossier_report(
        root=root, manifest_file=manifest, as_of=AS_OF, include_data_quality=True
    )
    path = root / result["report_file"]
    body = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(body).hexdigest() == result["report_sha256"]
    document = json.loads(body)
    assert document["schema_version"] == 4
    assert document["source_manifest_sha256"] == "a" * 64
    assert document["data_quality"][0]["source_qualified"] is False
    assert (
        module.publish_stock_dossier_report(
            root=root, manifest_file=manifest, as_of=AS_OF, include_data_quality=True
        )
        == result
    )
    assert reads == [(root, manifest)] * 2


def test_invalid_publication_flag_is_denied_before_opening_archive(monkeypatch):
    from pathlib import Path

    from trading_bot.runtime import stock_dossier_report as module

    def unexpected_open(*args, **kwargs):
        pytest.fail("invalid policy reached the source archive")

    monkeypatch.setattr(module, "_private_directory", unexpected_open)
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        module.publish_stock_dossier_report(
            root=Path("/fictional/private/archive"),
            manifest_file="a" * 64 + ".stock-capture.json",
            as_of=AS_OF,
            include_data_quality="true",
        )


def test_cli_explicitly_selects_quality_report(monkeypatch, capsys):
    from trading_bot.runtime import stock_dossier_report as module

    calls = []

    def publish(**kwargs):
        calls.append(kwargs)
        return {"status": "stock_dossier_report_published", "live_enabled": False}

    monkeypatch.setattr(module, "publish_stock_dossier_report", publish)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stock_dossier_report",
            "--archive-root",
            "/fictional/private/archive",
            "--manifest",
            "a" * 64 + ".stock-capture.json",
            "--as-of",
            AS_OF.isoformat(),
            "--data-quality",
        ],
    )
    assert module.main() == 0
    assert calls[0]["include_data_quality"] is True
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False
