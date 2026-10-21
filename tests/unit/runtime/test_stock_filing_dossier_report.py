"""Fictional native filing observations through the dossier compiler."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime.stock_dossier_report import compile_stock_dossier_report

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


@pytest.mark.parametrize(
    "kind", ["missing_index", "wrong_index", "duplicate_evidence", "forged_flag", "future_cutoff"]
)
def test_direct_dossier_boundary_revalidates_filing_evidence(kind):
    from trading_bot.market_data.stock_filing_facts import (
        bind_filing_evidence,
        normalize_filing_catalog,
        normalize_filing_facts,
    )

    from trading_bot.market_data.stock_events import normalize_filing_index
    from trading_bot.research.stock_dossiers import build_stock_dossiers

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
                **common,
                observation_sha256=other["observation_sha256"],
                requested_symbol="BETA",
            ),
        )
    elif kind == "duplicate_evidence":
        supplied = (evidence, evidence)
    elif kind == "forged_flag":
        object.__setattr__(evidence, "investment_eligible", True)
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
