"""Minimal decision projection tests use fictional owned plans only."""

import importlib
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from tests.unit.runtime.test_stock_investment_evidence import NOW
from tests.unit.runtime.test_stock_investment_plan import plan


def api():
    return importlib.import_module("trading_bot.runtime.stock_decision_export")


def test_current_projection_keeps_two_horizons_gaps_original_clocks_and_no_account_values():
    source = plan(allocation_context=None)
    exported = api().project_current_stock_decisions(source, "a" * 64)
    assert exported.report_evidence_hash == source.evidence_hash
    assert exported.generated_at == NOW
    assert [x.symbol for x in exported.long_term.decisions] == ["ALFA"]
    assert [x.symbol for x in exported.tactical.decisions] == ["ALFA"]
    assert exported.long_term.decisions[0].analytically_eligible
    assert "account_context_missing" in exported.needs
    assert exported.execution_authorized is exported.live_authorized is False
    assert "buying_power" not in exported.model_dump_json()


def test_expired_or_future_projection_never_advertises_current_eligibility():
    view = importlib.import_module("trading_bot.research.stock_decision_dashboard")
    exported = api().project_current_stock_decisions(plan(), "a" * 64)
    for at in (NOW - timedelta(seconds=1), NOW + timedelta(hours=3)):
        rendered = view.present_stock_decisions(exported, now=at, maximum_age_seconds=7200)
        assert rendered["status"] == "unavailable"
        assert rendered["long_term"]["decisions"] == []


def test_changed_authority_and_invalid_report_identity_fail_before_any_write():
    source = plan()
    object.__setattr__(source, "live_authorized", True)
    with pytest.raises(ValueError):
        api().project_current_stock_decisions(source, "a" * 64)
    with pytest.raises(ValueError):
        api().project_current_stock_decisions(plan(), "bad")


def test_projection_publish_reader_is_read_only_and_never_requires_archive(tmp_path, monkeypatch):
    from tests.unit.runtime.test_stock_current_worker import current_config

    loaded = current_config.__wrapped__(tmp_path)
    source = replace(plan(), source_config_hash=str(loaded.config_hash))
    exported = api().project_current_stock_decisions(source, "a" * 64)
    root = tmp_path / "view"
    root.mkdir(mode=0o700)
    receipt = api().publish_stock_decisions(root=root, export=exported)
    assert receipt["status"] == "published" and len(receipt["sha256"]) == 64
    reader = api().StockDecisionReader(root=root, loaded=loaded)

    def forbid(*a, **kw):
        raise AssertionError("reader attempted a write lease")

    monkeypatch.setattr(api(), "_write_projection", forbid)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    assert reader() == exported
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_exact_projection_numbers_ignore_ambient_capitalization():
    from decimal import Decimal, localcontext

    source = plan()
    row = source.rankings.assessments[0]
    row = replace(
        row, bullish_evidence=(replace(row.bullish_evidence[0], value=Decimal("1e-100")),)
    )
    source = replace(
        source,
        rankings=replace(source.rankings, assessments=(row, *source.rankings.assessments[1:])),
    )
    with localcontext() as ctx:
        ctx.capitals = 0
        lower = api().project_current_stock_decisions(source, "a" * 64)
    with localcontext() as ctx:
        ctx.capitals = 1
        upper = api().project_current_stock_decisions(source, "a" * 64)
    assert lower == upper


@pytest.mark.parametrize("kind", ["corrupt", "symlink", "fifo", "mode", "config"])
def test_reader_rejects_bad_private_projection_without_repair(tmp_path, kind):
    from tests.unit.runtime.test_stock_current_worker import current_config

    loaded = current_config.__wrapped__(tmp_path)
    root = tmp_path / "view"
    root.mkdir(mode=0o700)
    source = replace(plan(), source_config_hash=str(loaded.config_hash))
    api().publish_stock_decisions(
        root=root, export=api().project_current_stock_decisions(source, "a" * 64)
    )
    p = root / "stock-decisions.json"
    if kind == "corrupt":
        p.write_bytes(b"{}")
    elif kind == "symlink":
        original = root.parent / "elsewhere"
        p.rename(original)
        p.symlink_to(original)
    elif kind == "fifo":
        import os

        p.unlink()
        os.mkfifo(p, 0o600)
    elif kind == "mode":
        p.chmod(0o644)
    else:
        import json

        body = json.loads(p.read_bytes())
        body["source_config_hash"] = "f" * 64
        p.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError):
        api().StockDecisionReader(root=root, loaded=loaded)()
    assert p.lstat()


def test_reader_has_no_write_open_or_write_lease_on_read_only_mount(tmp_path, monkeypatch):
    import os

    from tests.unit.runtime.test_stock_current_worker import current_config

    loaded = current_config.__wrapped__(tmp_path)
    root = tmp_path / "view"
    root.mkdir(mode=0o700)
    api().publish_stock_decisions(
        root=root,
        export=api().project_current_stock_decisions(
            replace(plan(), source_config_hash=str(loaded.config_hash)), "a" * 64
        ),
    )
    original = os.open

    def readonly(path, flags, *args, **kwargs):
        assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT) == 0
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", readonly)
    assert api().StockDecisionReader(root=root, loaded=loaded)().report_body_sha256 == "a" * 64


def test_missing_evidence_review_decisions_remain_visible_in_their_horizon():
    from tests.unit.runtime.test_stock_investment_evidence import inputs

    source = plan(inputs(columns={"P/FCF": ""}))
    assert all(row.action == "review" for row in source.rankings.assessments)
    exported = api().project_current_stock_decisions(source, "a" * 64)
    assert exported.long_term.decisions[0].action == "review"
    assert exported.tactical.decisions[0].missing_requirements
    assert exported.long_term.eligible_count == 0


def test_projection_counts_cannot_hide_displayed_eligible_companies():
    from trading_bot.research.stock_decision_dashboard import StockDecisionExport

    exported = api().project_current_stock_decisions(plan(), "a" * 64)
    body = exported.model_dump()
    body["long_term"]["eligible_count"] = 0
    with pytest.raises(ValueError):
        StockDecisionExport.model_validate(body)


def test_projection_keeps_current_provider_method_and_unknown_date_disclosures():
    source = plan()
    exported = api().project_current_stock_decisions(source, "a" * 64)
    row = exported.long_term.decisions[0]
    assert row.limitations == list(source.rankings.long_term[0].limitations)
    assert "balance_sheet_effective_date_unknown_unless_supplied" in row.limitations
    assert "provider_price_signals_not_completed_close" in row.limitations


def test_omitted_eligible_decision_expiry_still_expires_the_bounded_projection():
    from tests.unit.research.test_stock_investment_decisions import AS_OF, provider_evidence
    from trading_bot.research.stock_decision_dashboard import present_stock_decisions
    from trading_bot.research.stock_investment_decisions import (
        CurrentInvestmentPolicy,
        rank_current_stocks,
    )

    stocks = []
    shift = NOW - AS_OF
    for index in range(21):
        stock = provider_evidence(f"E{index:02d}")

        def reference(ref, index=index):
            ref = replace(
                ref, received_at=ref.received_at + shift, expires_at=ref.expires_at + shift
            )
            if index == 20 and ref.tool == "preview_scan":
                ref = replace(
                    ref,
                    received_at=NOW - timedelta(minutes=119),
                    expires_at=NOW + timedelta(minutes=1),
                )
            return ref

        stocks.append(
            replace(
                stock,
                identity_refs=tuple(reference(ref) for ref in stock.identity_refs),
                sector_refs=tuple(reference(ref) for ref in stock.sector_refs),
                metrics=tuple(
                    replace(metric, refs=tuple(reference(ref) for ref in metric.refs))
                    for metric in stock.metrics
                ),
            )
        )
    ranks = rank_current_stocks(
        tuple(stocks),
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
        as_of=NOW,
    )
    source = replace(plan(allocation_context=None), rankings=ranks)
    exported = api().project_current_stock_decisions(source, "a" * 64)
    assert exported.long_term.eligible_count == 21 and exported.long_term.omitted_count == 1
    assert "E20" not in {row.symbol for row in exported.long_term.decisions}
    assert all(row.expires_at > NOW + timedelta(minutes=2) for row in exported.long_term.decisions)
    rendered = present_stock_decisions(
        exported, now=NOW + timedelta(minutes=2), maximum_age_seconds=7200
    )
    assert rendered["status"] == "unavailable" and rendered["reason"] == "expired_decision"
    assert rendered["long_term"]["decisions"] == []


def test_projection_requires_an_explicit_all_eligible_expiry_commitment():
    from trading_bot.research.stock_decision_dashboard import StockDecisionExport

    exported = api().project_current_stock_decisions(plan(), "a" * 64)
    body = exported.model_dump()
    body["long_term"].pop("earliest_eligible_expiry", None)
    with pytest.raises(ValueError):
        StockDecisionExport.model_validate(body)


@pytest.mark.parametrize("kind", ["old_version", "null", "later", "naive", "before_source", "bool"])
def test_projection_rejects_unbound_or_invalid_aggregate_expiry(kind):
    from trading_bot.research.stock_decision_dashboard import StockDecisionExport

    exported = api().project_current_stock_decisions(plan(), "a" * 64)
    body = exported.model_dump()
    if kind == "old_version":
        body["schema_version"] = 1
    else:
        body["long_term"]["earliest_eligible_expiry"] = {
            "null": None,
            "later": exported.long_term.decisions[0].expires_at + timedelta(seconds=1),
            "naive": NOW.replace(tzinfo=None),
            "before_source": NOW,
            "bool": True,
        }[kind]
    with pytest.raises(ValueError):
        StockDecisionExport.model_validate(body)


def test_presenter_deadline_has_exclusive_source_age_and_original_generation():
    from trading_bot.research.stock_decision_dashboard import present_stock_decisions

    exported = api().project_current_stock_decisions(plan(), "a" * 64)
    active = present_stock_decisions(
        exported, now=NOW + timedelta(seconds=59), maximum_age_seconds=60
    )
    assert active["status"] == "available" and datetime.fromisoformat(active["generated_at"]) == NOW
    assert active["valid_until"] == (NOW + timedelta(seconds=60)).isoformat()
    expired = present_stock_decisions(
        exported, now=NOW + timedelta(seconds=60), maximum_age_seconds=60
    )
    assert expired["status"] == "unavailable" and expired["reason"] == "stale_export"


def test_no_eligible_decisions_keep_explicit_null_expiry_and_no_eligibility_claim():
    from tests.unit.runtime.test_stock_investment_evidence import inputs

    exported = api().project_current_stock_decisions(plan(inputs(columns={"P/FCF": ""})), "a" * 64)
    for track in (exported.long_term, exported.tactical):
        assert track.eligible_count == 0 and track.earliest_eligible_expiry is None
