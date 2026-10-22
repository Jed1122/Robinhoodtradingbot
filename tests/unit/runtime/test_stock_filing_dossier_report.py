"""Fictional native filing observations through the dossier compiler."""

import asyncio
import copy
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime.stock_dossier_report import compile_stock_dossier_report
from trading_bot.runtime.stock_dossier_report import publish_stock_dossier_report as publish

AS_OF = datetime(2026, 10, 21, 18, tzinfo=UTC)


def observation(tool, arguments, payload, *, received_at=AS_OF):
    return {
        "tool": tool,
        "arguments": arguments,
        "payload": payload,
        "observation_sha256": hashlib.sha256(
            canonical_json(payload).encode() + tool.encode()
        ).hexdigest(),
        "received_at": received_at.isoformat(),
        "transport_authenticated": False,
    }


def index(symbol="ALFA", filing_id="filing-a"):
    return observation(
        "get_sec_filing_index",
        {"symbol": symbol},
        {
            "data": {
                "symbol": symbol,
                "filings": [
                    {
                        "filing_id": filing_id,
                        "date_filed": "2026-08-01",
                        "form_type": "10-K",
                        "description": "Fictional annual filing",
                    }
                ],
                "next": "",
            }
        },
    )


def catalog():
    return observation(
        "get_sec_filing_facts_catalog",
        {"filing_id": "filing-a", "offset": 0},
        {
            "data": {
                "concepts": [
                    {
                        "concept": "Assets",
                        "is_text_block": False,
                        "axis_names": [],
                        "periods": [
                            {"period": period, "end_date": end}
                            for period, end in (("current", "2026-06-30"), ("prior", "2025-06-30"))
                        ],
                    }
                ],
                "count": 1,
            },
            "guide": "Untrusted reference text",
        },
    )


def filing_facts():
    return observation(
        "get_sec_filing_facts",
        {"filing_ids": ["filing-a"], "concepts": ["Assets"]},
        {
            "data": {
                "facts": [
                    {
                        "filing_id": "filing-a",
                        "concept": "Assets",
                        "entity": "Fictional entity",
                        "period": period,
                        "end_date": end,
                        "axises": [],
                        "char_value": "",
                        "value": value,
                        "unit": "USD",
                        "decimals": -6,
                    }
                    for period, end, value in (
                        ("current", "2026-06-30", "100"),
                        ("prior", "2025-06-30", "80"),
                    )
                ]
            },
            "guide": "Untrusted reference text",
        },
    )


def compile_rows(*rows):
    return compile_stock_dossier_report(observations=tuple(rows), as_of=AS_OF)


def test_exact_legacy_report_and_dossier_hashes_are_preserved():
    report = compile_rows(index())
    assert report["schema_version"] == 2
    assert "filing_evidence" not in report["dossiers"][0]
    assert "filing_evidence_denials" not in report
    assert report["dossier_hashes"] == [
        "0b8c031f7fb886db46c2eb1a8006a99c5375139a7beb02b4d0ea097a5dbc6e37"
    ]
    assert hashlib.sha256(canonical_json(report).encode()).hexdigest() == (
        "aa138c7306282bd9d7bc8505c5464e229d18df8614bbf38dae93e51f4d06dea7"
    )


def test_filing_facts_attach_only_to_the_matched_company_with_all_receipts():
    source_index, source_catalog, source_facts = index(), catalog(), filing_facts()
    report = compile_rows(source_index, index("BETA", "filing-b"), source_catalog, source_facts)
    assert report["schema_version"] == 3
    assert report["filing_evidence_denials"] == []
    assert report["unprojected_observations"] == []
    alfa, beta = report["dossiers"]
    assert beta["filing_evidence"] == []
    (evidence,) = alfa["filing_evidence"]
    assert evidence["filing"]["symbol"] == "ALFA"
    assert [r["numeric_value"] for r in evidence["facts"]["records"]] == ["100", "80"]
    assert evidence["available_at"] == "2026-10-21T18:00:00.000000Z"
    assert len(evidence["evidence_hash"]) == 64
    assert {
        evidence[name]["receipt"]["observation_sha256"] for name in ("index", "catalog", "facts")
    } == {r["observation_sha256"] for r in (source_index, source_catalog, source_facts)}
    assert "financial_currency_unknown" in alfa["gaps"]
    assert "filing_units_unqualified" in alfa["gaps"]
    assert "filing_entity_mapping_unknown" in alfa["gaps"]
    for record in (report, alfa, beta, evidence, evidence["facts"]):
        for flag in ("source_qualified", "strategy_qualified", "investment_eligible"):
            assert record[flag] is False
    assert report["live_enabled"] is False


@pytest.mark.parametrize("state", ["absent", "null", "empty", "exponent"])
def test_missing_values_and_extreme_exact_values_never_become_zero_or_scaled(state):
    row = filing_facts()
    fact = row["payload"]["data"]["facts"][0]
    fact.pop("unit")
    if state == "absent":
        fact.pop("value")
    else:
        fact["value"] = {"null": None, "empty": "", "exponent": "1e1000"}[state]
    report = compile_rows(index(), catalog(), row)
    normalized = report["dossiers"][0]["filing_evidence"][0]["facts"]["records"][0]
    assert normalized["numeric_value"] == ("1E+1000" if state == "exponent" else None)
    assert normalized["unit_present"] is False and normalized["unit_raw"] is None
    assert normalized["value_present"] is (state != "absent")
    assert normalized["decimals_raw"] == -6


@pytest.mark.parametrize(
    "kind",
    [
        "missing_index",
        "missing_catalog",
        "missing_facts",
        "ambiguous_index",
        "ambiguous_catalog",
        "ambiguous_facts",
        "period_mismatch",
        "scope_mismatch",
        "malformed",
    ],
)
def test_incomplete_ambiguous_or_contradictory_evidence_is_explicitly_denied(kind):
    i, c, f = index(), catalog(), filing_facts()
    rows = [i, c, f]
    if kind.startswith("missing_"):
        rows.remove({"missing_index": i, "missing_catalog": c, "missing_facts": f}[kind])
    elif kind.startswith("ambiguous_"):
        duplicate = copy.deepcopy(
            {"ambiguous_index": i, "ambiguous_catalog": c, "ambiguous_facts": f}[kind]
        )
        duplicate["observation_sha256"] = "e" * 64
        rows.append(duplicate)
    elif kind == "period_mismatch":
        f["payload"]["data"]["facts"][0]["end_date"] = "2026-06-29"
    elif kind == "scope_mismatch":
        f["payload"]["data"]["facts"][0]["filing_id"] = "unrequested-private-id"
    else:
        c["payload"]["data"]["concepts"][0]["axis_names"] = "invalid-private-axis"
    report = compile_rows(*rows)
    assert report["filing_evidence_denials"]
    assert all(not d["filing_evidence"] for d in report["dossiers"])
    safe = json.dumps(report["filing_evidence_denials"] + report["normalization_denials"])
    assert "unrequested-private-id" not in safe and "invalid-private-axis" not in safe
    assert "Fictional" not in safe and "filing-a" not in safe


def test_future_filing_sources_do_not_change_legacy_dossier_hashes():
    c, f = catalog(), filing_facts()
    c["received_at"] = f["received_at"] = (AS_OF + timedelta(seconds=1)).isoformat()
    expected = compile_rows(index())
    actual = compile_rows(index(), c, f)
    assert actual["schema_version"] == 2
    assert actual["future_observations_excluded"] == 2
    assert actual["dossiers"] == expected["dossiers"]
    assert actual["dossier_hashes"] == expected["dossier_hashes"]


def test_earlier_filing_date_does_not_backdate_combined_receipt_availability():
    i, c, f = index(), catalog(), filing_facts()
    i["received_at"] = (AS_OF - timedelta(hours=2)).isoformat()
    c["received_at"] = (AS_OF - timedelta(hours=1)).isoformat()
    report = compile_rows(i, c, f)
    evidence = report["dossiers"][0]["filing_evidence"][0]
    assert evidence["filing"]["date_filed"] == "2026-08-01"
    assert evidence["available_at"] == "2026-10-21T18:00:00.000000Z"
    earlier = compile_stock_dossier_report(
        observations=(i, c, f), as_of=AS_OF - timedelta(minutes=30)
    )
    assert earlier["future_observations_excluded"] == 1
    assert earlier["dossiers"][0]["filing_evidence"] == []
    assert earlier["filing_evidence_denials"][0]["reason"] == "stock_filing_evidence_incomplete"


def direct_evidence():
    from trading_bot.market_data.stock_events import normalize_filing_index
    from trading_bot.market_data.stock_filing_facts import (
        bind_filing_evidence,
        normalize_filing_catalog,
        normalize_filing_facts,
    )

    i, c, f = index(), catalog(), filing_facts()
    common = {"received_at": AS_OF}
    normalized_index = normalize_filing_index(
        i["payload"],
        **common,
        observation_sha256=i["observation_sha256"],
        requested_symbol="ALFA",
    )
    normalized_catalog = normalize_filing_catalog(
        c["payload"],
        **common,
        observation_sha256=c["observation_sha256"],
        requested_filing_id="filing-a",
    )
    normalized_facts = normalize_filing_facts(
        f["payload"],
        **common,
        observation_sha256=f["observation_sha256"],
        requested_filing_ids=("filing-a",),
        requested_concepts=("Assets",),
    )
    evidence = bind_filing_evidence(
        normalized_index, normalized_catalog, normalized_facts, as_of=AS_OF
    )
    return normalized_index, evidence


@pytest.mark.parametrize(
    "kind",
    [
        "missing_index",
        "wrong_index",
        "duplicate_evidence",
        "forged_flag",
        "forged_false_scalar",
        "future_cutoff",
    ],
)
def test_direct_dossier_boundary_revalidates_filing_evidence(kind):
    from trading_bot.market_data.stock_events import normalize_filing_index
    from trading_bot.research.stock_dossiers import build_stock_dossiers

    normalized_index, evidence = direct_evidence()
    indexes = (normalized_index,)
    supplied = (evidence,)
    cutoff = AS_OF
    if kind == "missing_index":
        indexes = ()
    elif kind == "wrong_index":
        other = index("BETA", "filing-a")
        indexes = (
            normalize_filing_index(
                other["payload"],
                received_at=AS_OF,
                observation_sha256=other["observation_sha256"],
                requested_symbol="BETA",
            ),
        )
    elif kind == "duplicate_evidence":
        supplied = (evidence, evidence)
    elif kind == "forged_flag":
        object.__setattr__(evidence, "investment_eligible", True)
    elif kind == "forged_false_scalar":
        object.__setattr__(evidence, "investment_eligible", 0)
    else:
        cutoff -= timedelta(seconds=1)
    with pytest.raises(ValueError, match="stock_dossiers_invalid"):
        build_stock_dossiers(
            as_of=cutoff,
            facts=(),
            history=(),
            earnings=(),
            filings=indexes,
            filing_evidence=supplied,
        )


def test_valid_earlier_evidence_is_revalidated_and_attached_at_the_current_cutoff():
    from trading_bot.research.stock_dossiers import build_stock_dossiers

    normalized_index, evidence = direct_evidence()
    cutoff = AS_OF + timedelta(seconds=1)
    (dossier,) = build_stock_dossiers(
        as_of=cutoff,
        facts=(),
        history=(),
        earnings=(),
        filings=(normalized_index,),
        filing_evidence=(evidence,),
    )
    (attached,) = dossier.filing_evidence
    assert attached.as_of == cutoff
    assert evidence.as_of == AS_OF
    assert attached.available_at == evidence.available_at == AS_OF
    assert attached.evidence_hash != evidence.evidence_hash
    assert attached.filing == evidence.filing
    assert attached.investment_eligible is False


def test_unrelated_ambiguous_indexes_are_withheld_with_explicit_safe_receipt_denial():
    beta_a, beta_b = index("BETA", "filing-b"), index("BETA", "filing-c")
    report = compile_rows(index(), catalog(), filing_facts(), beta_a, beta_b)
    assert [row["symbol"] for row in report["dossiers"]] == ["ALFA"]
    assert len(report["dossiers"][0]["filing_evidence"]) == 1
    assert any(
        denial["reason"] == "stock_filing_evidence_ambiguous"
        and set(denial["observation_sha256s"])
        == {beta_a["observation_sha256"], beta_b["observation_sha256"]}
        for denial in report["filing_evidence_denials"]
    )
    assert "BETA" not in json.dumps(report["filing_evidence_denials"])


@pytest.fixture
def committed_captures(tmp_path):
    from trading_bot.brokers.robinhood_mcp_transport import McpToolResult
    from trading_bot.runtime.stock_capture import StockCaptureRequest, capture_stock_observations

    class Transport:
        def __init__(self, row):
            self.row = row

        async def call_tool(self, tool, arguments):
            assert tool == self.row["tool"] and arguments == self.row["arguments"]
            return McpToolResult((), False, self.row["payload"])

    result = []
    for name, row in (("index", index()), ("catalog", catalog()), ("facts", filing_facts())):
        root = tmp_path.resolve() / name
        root.mkdir(mode=0o700)

        ticks = iter(AS_OF - timedelta(minutes=10) + timedelta(seconds=i) for i in range(20))
        captured = asyncio.run(
            capture_stock_observations(
                transport=Transport(row),
                output_dir=root,
                requests=(StockCaptureRequest(row["tool"], row["arguments"]),),
                clock=ticks.__next__,
                transport_authenticated=False,
            )
        )
        assert captured["status"] == "complete"
        result.append((root, captured["manifest_file"]))
    return tuple(result)


@pytest.mark.parametrize("borrowed", [False, True])
def test_three_real_fictional_archives_are_rehashed_bound_and_privately_published(
    committed_captures, borrowed
):
    from contextlib import nullcontext

    from trading_bot.runtime.stock_archive_lease import StockArchiveLease

    (root, manifest), *extra = committed_captures
    context = StockArchiveLease(root) if borrowed else nullcontext()
    with context as lease:
        kwargs = {"_directory_fd": lease.directory_fd} if borrowed else {}
        result = publish(
            root=root,
            manifest_file=manifest,
            as_of=AS_OF,
            additional_captures=tuple(extra),
            **kwargs,
        )
        assert (
            publish(
                root=root,
                manifest_file=manifest,
                as_of=AS_OF,
                additional_captures=tuple(extra),
                **kwargs,
            )
            == result
        )
    data = (root / result["report_file"]).read_bytes()
    report = json.loads(data)
    assert hashlib.sha256(data).hexdigest() == result["report_sha256"]
    assert (root / result["report_file"]).stat().st_mode & 0o777 == 0o600
    assert report["source_manifest_sha256"] == manifest[:64]
    assert report["source_manifest_sha256s"] == [m[:64] for _, m in committed_captures]
    assert report["filing_evidence_denials"] == []
    assert len(report["dossiers"][0]["filing_evidence"][0]["facts"]["records"]) == 2
    assert report["source_transport_authenticated"] is False
    assert report["live_enabled"] is result["live_enabled"] is False
    assert str(root) not in json.dumps(result) and "Fictional" not in json.dumps(result)


@pytest.mark.parametrize("target", ["manifest", "observation", "missing"])
def test_altered_or_missing_additional_capture_cannot_publish(committed_captures, target):
    (root, manifest), *extra = committed_captures
    other, other_manifest = extra[-1]
    artifact = other / other_manifest
    if target == "observation":
        artifact = other / json.loads(artifact.read_bytes())["observations"][0]["file"]
    if target == "missing":
        artifact.unlink()
    else:
        artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        publish(root=root, manifest_file=manifest, as_of=AS_OF, additional_captures=tuple(extra))
    assert not list(root.glob("*.stock-dossiers.json"))


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "three", "list", "bad_manifest", "relative", "mode", "symlink", "missing_root"],
)
def test_whole_additional_input_denied_before_read_or_publish(
    committed_captures, monkeypatch, kind
):
    from trading_bot.runtime import stock_dossier_report as module

    (root, manifest), *extra = committed_captures
    if kind == "duplicate":
        extra = [(root, manifest)]
    elif kind == "three":
        extra.append(extra[0])
    elif kind == "bad_manifest":
        extra[-1] = (extra[-1][0], "not-a-manifest")
    elif kind == "relative":
        extra[-1] = (Path("relative"), extra[-1][1])
    elif kind == "mode":
        extra[-1][0].chmod(0o755)
    elif kind == "symlink":
        alias = root.parent / "alias"
        alias.symlink_to(extra[-1][0], target_is_directory=True)
        extra[-1] = (alias, extra[-1][1])
    elif kind == "missing_root":
        extra[-1] = (root.parent / "missing-root", extra[-1][1])
    monkeypatch.setattr(
        module,
        "read_stock_observations",
        lambda *args, **kwargs: pytest.fail("unsafe inputs reached source read"),
    )
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        publish(
            root=root,
            manifest_file=manifest,
            as_of=AS_OF,
            additional_captures=extra if kind == "list" else tuple(extra),
        )
    assert not list(root.glob("*.stock-dossiers.json"))


def test_owned_additional_archive_prevents_report_without_relocking_primary(committed_captures):
    from trading_bot.runtime.stock_archive_lease import StockArchiveLease

    (root, manifest), *extra = committed_captures
    with (
        StockArchiveLease(extra[-1][0]),
        pytest.raises(ValueError, match="stock_dossier_report_invalid"),
    ):
        publish(root=root, manifest_file=manifest, as_of=AS_OF, additional_captures=tuple(extra))
    assert not list(root.glob("*.stock-dossiers.json"))


@pytest.mark.parametrize("kind", ["duplicate_receipt", "too_many"])
def test_combined_observation_bounds_and_duplicates_fail_before_publication(
    committed_captures, monkeypatch, kind
):
    from trading_bot.runtime import stock_dossier_report as module

    (root, manifest), *extra = committed_captures
    if kind == "duplicate_receipt":
        observations = (index(),)
    else:
        observations = tuple(index(f"S{i}", f"filing-{i}") for i in range(12))
    monkeypatch.setattr(module, "read_stock_observations", lambda *a, **kw: observations)
    with pytest.raises(ValueError, match="stock_dossier_report_invalid"):
        publish(root=root, manifest_file=manifest, as_of=AS_OF, additional_captures=tuple(extra))
    assert not list(root.glob("*.stock-dossiers.json"))


def test_cleanup_error_cannot_claim_success_and_all_opened_leases_are_closed(
    committed_captures, monkeypatch
):
    from trading_bot.runtime.stock_archive_lease import StockArchiveLease

    (root, manifest), *extra = committed_captures
    original = StockArchiveLease.__exit__
    closed = []

    def failing_close(self, *args):
        descriptor = self.directory_fd
        original(self, *args)
        closed.append(descriptor)
        raise OSError("private close detail")

    monkeypatch.setattr(StockArchiveLease, "__exit__", failing_close)
    with pytest.raises(ValueError, match=r"^stock_dossier_report_invalid$"):
        publish(root=root, manifest_file=manifest, as_of=AS_OF, additional_captures=tuple(extra))
    assert len(closed) == 3
    for descriptor in closed:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_cli_preserves_ordered_additional_capture_references(monkeypatch, capsys):
    from trading_bot.runtime import stock_dossier_report as module

    calls = []
    monkeypatch.setattr(
        module,
        "publish_stock_dossier_report",
        lambda **kwargs: calls.append(kwargs) or {"live_enabled": False},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "report",
            "--archive-root",
            "/private/primary",
            "--manifest",
            "a" * 64 + ".stock-capture.json",
            "--additional-capture",
            "/private/catalog",
            "b" * 64 + ".stock-capture.json",
            "--additional-capture",
            "/private/facts",
            "c" * 64 + ".stock-capture.json",
        ],
    )
    assert module.main() == 0
    assert calls[0]["additional_captures"] == (
        (Path("/private/catalog"), "b" * 64 + ".stock-capture.json"),
        (Path("/private/facts"), "c" * 64 + ".stock-capture.json"),
    )
    assert json.loads(capsys.readouterr().out) == {"live_enabled": False}
