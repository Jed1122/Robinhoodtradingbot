import hashlib
import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest

AS_OF = datetime(2026, 10, 21, 18, tzinfo=UTC)


def observation(tool, arguments, payload, *, future=False):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "tool": tool,
        "arguments": arguments,
        "payload": payload,
        "observation_sha256": hashlib.sha256(body + tool.encode()).hexdigest(),
        "received_at": (AS_OF + timedelta(days=1) if future else AS_OF).isoformat(),
        "transport_authenticated": False,
    }


def facts(symbol="ALFA", **kwargs):
    return observation(
        "get_equity_fundamentals",
        {"symbols": [symbol]},
        {"data": {"results": [{"symbol": symbol, "market_cap": "2000000000"}]}},
        **kwargs,
    )


def history():
    return observation(
        "get_equity_historicals",
        {"symbols": ["ALFA", "BETA"], "adjustment_type": "none"},
        {
            "data": {
                "results": [
                    {
                        "symbol": symbol,
                        "interval": "day",
                        "bounds": "regular",
                        "bars": [
                            {
                                "begins_at": "2026-10-19T04:00:00Z",
                                "open_price": "20",
                                "high_price": "22",
                                "low_price": "19",
                                "close_price": "21" if symbol == "ALFA" else "23",
                                "volume": 1000,
                                "session": "reg",
                                "interpolated": False,
                            }
                        ],
                    }
                    for symbol in ("ALFA", "BETA")
                ]
            }
        },
    )


def test_report_retains_quarantine_absence_sources_and_never_promotes():
    module = importlib.import_module("trading_bot.runtime.stock_dossier_report")
    report = module.compile_stock_dossier_report(
        observations=(
            facts(),
            history(),
            observation("get_financials", {"symbols": ["BETA"]}, {"data": {"results": [None]}}),
            observation(
                "get_earnings_results", {"symbol": "ALFA"}, {"data": {"results": []}}
            ),
            observation(
                "get_sec_filing_index",
                {"symbol": "ALFA"},
                {"data": {"symbol": "ALFA", "filings": [], "next": ""}},
            ),
        ),
        as_of=AS_OF,
    )
    assert report["company_count"] == 2
    assert report["normalization_denials"] == []
    alfa, beta = report["dossiers"]
    assert alfa["symbol"] == "ALFA" and alfa["history"]["bar_count"] == 1
    assert beta["history"]["outcome"]["status"] == "quarantined"
    assert beta["history"]["bar_count"] is None
    assert "financials_absent" in beta["gaps"]
    assert len(alfa["sources"]) == 4
    assert all(not row["investment_eligible"] for row in report["dossiers"])
    assert report["source_transport_authenticated"] is False
    assert report["strategy_qualified"] is report["live_enabled"] is False
    alfa_features, beta_features = report["technical_features"]
    assert alfa_features["symbol"] == "ALFA"
    assert alfa_features["supported_bar_count"] == 1
    assert alfa_features["metrics"]["price_return_20"] is None
    assert beta_features["calculation_status"] == "quarantined"
    assert all(value is None for value in beta_features["metrics"].values())
    assert "outcome" not in alfa_features
    assert alfa_features["projection_context"]["original_source_sha256"]


def test_future_receipt_excluded_and_invalid_collection_explicitly_denied():
    module = importlib.import_module("trading_bot.runtime.stock_dossier_report")
    bad = facts("BETA")
    bad["payload"]["data"]["results"][0]["market_cap"] = "not-a-number"
    report = module.compile_stock_dossier_report(
        observations=(facts(), facts("FUTURE", future=True), bad), as_of=AS_OF
    )
    assert report["company_count"] == 1
    assert report["future_observations_excluded"] == 1
    assert report["normalization_denials"] == [
        {
            "tool": "get_equity_fundamentals",
            "observation_sha256": bad["observation_sha256"],
            "reason": "stock_observation_normalization_denied",
        }
    ]
    assert "not-a-number" not in json.dumps(report)


def test_duplicate_archive_rows_fail_instead_of_selecting_one_version():
    module = importlib.import_module("trading_bot.runtime.stock_dossier_report")
    row = facts()
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        module.compile_stock_dossier_report(observations=(row, row), as_of=AS_OF)


def test_omitted_interpolation_flag_stays_unknown_and_blocks_technical_metrics():
    module = importlib.import_module("trading_bot.runtime.stock_dossier_report")
    row = history()
    row["payload"]["data"]["results"][0]["bars"][0].pop("interpolated")
    report = module.compile_stock_dossier_report(observations=(row,), as_of=AS_OF)
    alfa = report["dossiers"][0]
    assert "history_interpolation_unknown" in alfa["gaps"]
    assert alfa["history"]["outcome"]["normalized"]["records"][0]["interpolated"] is None
    features = report["technical_features"][0]
    assert features["calculation_status"] == "ineligible"
    assert all(value is None for value in features["metrics"].values())


def test_publish_uses_rehashed_archive_and_private_content_addressing(tmp_path, monkeypatch):
    module = importlib.import_module("trading_bot.runtime.stock_dossier_report")
    root = tmp_path.resolve()
    root.chmod(0o700)
    calls = []

    def read(actual_root, manifest_file):
        calls.append((actual_root, manifest_file))
        return (facts(),)

    monkeypatch.setattr(module, "read_stock_observations", read)
    manifest = "a" * 64 + ".stock-capture.json"
    result = module.publish_stock_dossier_report(root=root, manifest_file=manifest, as_of=AS_OF)
    output = root / result["report_file"]
    data = output.read_bytes()
    assert output.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(data).hexdigest() == result["report_sha256"]
    assert json.loads(data)["source_manifest_sha256"] == "a" * 64
    repeated = module.publish_stock_dossier_report(root=root, manifest_file=manifest, as_of=AS_OF)
    assert repeated == result
    assert calls == [(root, manifest)] * 2


def test_report_size_boundary_denies_before_publication(tmp_path, monkeypatch):
    module = importlib.import_module("trading_bot.runtime.stock_dossier_report")
    root = tmp_path.resolve()
    root.chmod(0o700)
    monkeypatch.setattr(module, "read_stock_observations", lambda *args: (facts(),))
    manifest = "a" * 64 + ".stock-capture.json"
    result = module.publish_stock_dossier_report(root=root, manifest_file=manifest, as_of=AS_OF)
    size = (root / result["report_file"]).stat().st_size
    monkeypatch.setattr(module, "_MAX_REPORT_BYTES", size)
    assert module.publish_stock_dossier_report(
        root=root, manifest_file=manifest, as_of=AS_OF
    ) == result

    def unexpected_publish(*args):
        pytest.fail("oversized report reached publication")

    monkeypatch.setattr(module, "_MAX_REPORT_BYTES", size - 1)
    monkeypatch.setattr(module, "_publish", unexpected_publish)
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        module.publish_stock_dossier_report(root=root, manifest_file=manifest, as_of=AS_OF)
