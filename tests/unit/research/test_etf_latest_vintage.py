"""Native price research remains distinct from original-vintage/execution evidence."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.unit.simulation.test_etf_history import study
from trading_bot.market_data.alpaca_native import AlpacaBarRecord, AlpacaStockRequest
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_latest_vintage")
    except ModuleNotFoundError:
        pytest.fail("Latest-vintage ETF research runner is missing")


def archive(count=760):
    start = datetime(2016, 1, 4, tzinfo=ZoneInfo("America/New_York"))
    rows = tuple(
        AlpacaBarRecord(
            content_hash(("body", i)),
            i // 1000,
            i % 1000,
            _ns((start + timedelta(days=i)).astimezone(UTC)),
            Decimal(100) + i,
            Decimal(102) + i,
            Decimal(99) + i,
            Decimal(101) + i,
            10000,
            1000,
            Decimal(101) + i,
        )
        for i in range(count)
    )
    return EtfNativeBarsArchive(
        "b" * 64,
        AlpacaStockRequest(
            "bars", _ns(datetime(2016, 1, 1, tzinfo=UTC)), _ns(datetime(2026, 1, 1, tzinfo=UTC))
        ),
        ("c" * 64,),
        rows,
        datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_fixed_signal_uses_only_completed_prior_bars_and_never_admits_orders():
    source = archive()
    frozen = replace(
        study(),
        policy=api()._policy(study()),
        source_plan_hash=api().latest_vintage_source_plan_hash(source),
    )
    result = api().run_latest_vintage_etf(api().EtfLatestVintageRequest(frozen, source))
    assert result.source_kind == "alpaca-sip-latest-vintage-v1"
    assert result.evaluated_observations == 10
    assert result.rebalance_candidates == 2
    assert result.positive_signal_observations == 10
    assert result.admitted_entries == 0
    assert not result.execution_enabled and not result.evidence_promotable
    assert "daily_bars_not_executable_quotes" in result.reasons
    assert result.decision_input_hashes[0] == content_hash(
        tuple(r.record_hash for r in source.bars[650:750])
    )


def test_future_price_changes_cannot_change_the_earlier_decision_prefix():
    source = archive()
    frozen = replace(
        study(),
        policy=api()._policy(study()),
        source_plan_hash=api().latest_vintage_source_plan_hash(source),
    )
    first = api().run_latest_vintage_etf(api().EtfLatestVintageRequest(frozen, source))
    row = source.bars[-1]
    changed = replace(
        source,
        bars=(
            *source.bars[:-1],
            replace(row, open=Decimal("1"), low=Decimal("1"), close=Decimal("1")),
        ),
    )
    other_study = replace(
        frozen,
        policy=api()._policy(frozen),
        source_plan_hash=api().latest_vintage_source_plan_hash(changed),
    )
    other = api().run_latest_vintage_etf(api().EtfLatestVintageRequest(other_study, changed))
    assert first.decision_input_hashes == other.decision_input_hashes


def test_source_identity_and_short_history_fail_closed():
    source = archive(100)
    with pytest.raises(ValueError, match="etf_latest_vintage_invalid"):
        api().EtfLatestVintageRequest(study(), source)
    frozen = replace(
        study(),
        policy=api()._policy(study()),
        source_plan_hash=api().latest_vintage_source_plan_hash(source),
    )
    result = api().run_latest_vintage_etf(api().EtfLatestVintageRequest(frozen, source))
    assert result.evaluated_observations == 0
    assert "study_warmup_incomplete" in result.reasons


def test_source_rejects_wrong_request_kind_and_rounded_midnight_identity():
    source = archive(760)
    altered = (
        replace(source, request=replace(source.request, kind="quotes")),
        replace(
            source,
            bars=(
                replace(source.bars[0], timestamp_ns=source.bars[0].timestamp_ns - 1),
                *source.bars[1:],
            ),
        ),
    )
    for bad in altered:
        frozen = replace(
            study(),
            policy=api()._policy(study()),
            source_plan_hash=api().latest_vintage_source_plan_hash(bad),
        )
        with pytest.raises(ValueError, match="etf_latest_vintage_invalid"):
            api().EtfLatestVintageRequest(frozen, bad)
