"""Private synthetic manifests cannot qualify a genuine historical study."""

import hashlib
import json
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.market_data.etf_source import qualify_etf_source
from trading_bot.research.etf_study import freeze_etf_study

CONFIGS = Path(__file__).parents[3] / "configs"


@pytest.fixture
def study():
    return freeze_etf_study(
        load_config(
            CONFIGS / "base.yaml",
            CONFIGS / "backtest.yaml",
            CONFIGS / "safety-envelope.yaml",
            {"TRADING_BOT__EQUITY_STRATEGIES__ETF_PILOT__ENABLED": "true"},
        ),
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        holdout_previously_examined=False,
    )


def package(root, study, **changes):
    root.chmod(0o700)
    manifest = dict(
        schema="etf-synthetic-manifest-v1",
        study_hash=study.study_hash,
        source_plan_hash=study.source_plan_hash,
        origin="synthetic",
        feed="synthetic",
        starts_at="2016-01-01T00:00:00.000000Z",
        ends_at="2026-01-01T00:00:00.000000Z",
        pages=[],
    )
    manifest.update(changes)
    body = json.dumps(manifest).encode()
    path = root / (hashlib.sha256(body).hexdigest() + ".json")
    path.write_bytes(body)
    path.chmod(0o600)
    return path


def test_missing_and_empty_inputs_fail_closed(tmp_path, study):
    for path in (tmp_path / "missing.json", package(tmp_path, study)):
        result = qualify_etf_source(study, manifest_path=path, allowed_root=tmp_path)
        assert result.status == "BLOCKED_INPUTS" and result.dataset is None
        assert result.role_era_evidence_hashes == ()
        assert result.evidence_promotable is False
        assert "source_reference_unverified" in result.reasons


@pytest.mark.parametrize(
    "changes",
    [
        {"origin": "actual"},
        {"feed": "SIP"},
        {"feed": "IEX"},
        {"starts_at": "2018-05-01T00:00:00.000000Z"},
        {"verified": True},
        {"fractional_eligible": True},
        {"source_plan_hash": "d" * 64},
        {"study_hash": "e" * 64},
        {"pages": ["f" * 64]},
    ],
)
def test_claims_wrong_eras_missing_pages_never_qualify(tmp_path, study, changes):
    result = qualify_etf_source(
        study, manifest_path=package(tmp_path, study, **changes), allowed_root=tmp_path
    )
    assert result.dataset is None
    assert "source_input_invalid" in result.reasons


def test_manifest_substitution_symlink_escape_and_no_overwrite(tmp_path, study):
    path = package(tmp_path, study)
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    result = qualify_etf_source(study, manifest_path=path, allowed_root=tmp_path)
    assert "source_input_invalid" in result.reasons
    assert path.read_bytes() == original + b" "
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    for invalid in (link, tmp_path / ".." / tmp_path.name / path.name):
        assert (
            qualify_etf_source(study, manifest_path=invalid, allowed_root=tmp_path).dataset is None
        )


def page(root, index, next_page, rows):
    body = json.dumps(
        dict(
            schema="etf-synthetic-page-v1",
            feed="synthetic",
            page=index,
            next_page=next_page,
            records=rows,
        )
    ).encode()
    digest = hashlib.sha256(body).hexdigest()
    path = root / (digest + ".json")
    path.write_bytes(body)
    path.chmod(0o600)
    return digest


def bar(ordinal=0):
    return dict(
        kind="bar",
        ordinal=ordinal,
        instrument_id="SPY",
        event_at_ns=1478289600000000000,
        published_at_ns=1478289600000000001,
        received_at_ns=1478289600000000002,
        revision_of=None,
        payload=dict(
            instrument_id="SPY",
            interval="one_day",
            starts_at="2016-11-04T13:30:00.000000Z",
            ends_at="2016-11-04T20:00:00.000000Z",
            open="100",
            high="102",
            low="99",
            close="101",
            volume="123",
            source="synthetic",
            interpolated=False,
        ),
    )


def test_populated_fixed_window_fixture_still_has_no_actual_evidence(tmp_path, study):
    digest = page(tmp_path, 0, None, [bar()])
    path = package(tmp_path, study, pages=[digest])
    result = qualify_etf_source(study, manifest_path=path, allowed_root=tmp_path)
    assert result.parsed_event_count == 1
    assert "source_input_invalid" not in result.reasons
    assert set(result.reasons) == {
        "source_reference_unverified",
        "source_coverage_unverified",
        "fractional_terms_unverified",
        "synthetic_inputs_only",
        "historical_availability_unverified",
    }
    assert result.dataset is None and result.role_era_evidence_hashes == ()


def test_cross_page_revision_keeps_original_and_receipt_order(tmp_path, study):
    from trading_bot.market_data.recording import content_hash

    original = bar()
    revised = bar(1)
    revised.update(
        revision_of=content_hash(original),
        published_at_ns=1478289600000000010,
        received_at_ns=1478289600000000011,
    )
    revised["payload"]["close"] = "102"
    pages = [page(tmp_path, 0, 1, [original]), page(tmp_path, 1, None, [revised])]
    result = qualify_etf_source(
        study, manifest_path=package(tmp_path, study, pages=pages), allowed_root=tmp_path
    )
    assert result.parsed_event_count == 2
    assert "source_input_invalid" not in result.reasons
    assert result.dataset is None


@pytest.mark.parametrize("mode", ["truncated", "reversed", "repeated", "collision", "empty_tail"])
def test_pagination_and_source_order_denial(tmp_path, study, mode):
    first = page(tmp_path, 0, 1, [bar()])
    second = page(tmp_path, 1, None, [bar()])
    pages = {
        "truncated": [first],
        "reversed": [second, first],
        "repeated": [first, first],
        "collision": [first, second],
        "empty_tail": [first, page(tmp_path, 1, None, [])],
    }[mode]
    result = qualify_etf_source(
        study, manifest_path=package(tmp_path, study, pages=pages), allowed_root=tmp_path
    )
    assert result.dataset is None
    if mode != "empty_tail":
        assert "source_input_invalid" in result.reasons
    else:
        assert "source_coverage_unverified" in result.reasons


def test_page_substitution_and_directory_symlink_deny(tmp_path, study):
    digest = page(tmp_path, 0, None, [bar()])
    path = package(tmp_path, study, pages=[digest])
    raw = tmp_path / (digest + ".json")
    raw.write_bytes(raw.read_bytes() + b" ")
    assert (
        "source_input_invalid"
        in qualify_etf_source(study, manifest_path=path, allowed_root=tmp_path).reasons
    )
    alias = tmp_path / "linked-root"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert (
        "source_input_invalid"
        in qualify_etf_source(study, manifest_path=alias / path.name, allowed_root=alias).reasons
    )
