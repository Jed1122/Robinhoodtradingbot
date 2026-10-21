"""Fictional completed raw observations support descriptions, never investment scores."""

import hashlib
import importlib
import json
import math
import statistics
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from trading_bot.market_data.stock_history_projection import normalize_history_by_symbol

AS_OF = datetime(2026, 10, 21, 18, tzinfo=UTC)
RECEIVED = AS_OF - timedelta(hours=1)
CUTOFF = datetime(2026, 10, 21, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.research.stock_technicals")
    except ModuleNotFoundError:
        pytest.fail("stock descriptive technical features are missing")


def history(
    prices,
    *,
    symbol="ALFA",
    volume=100,
    raw=True,
    complete=True,
    marker=True,
    interpolated_at=None,
    bad=False,
    received_at=RECEIVED,
    cutoff=CUTOFF,
):
    bars = []
    for index, price in enumerate(prices):
        item = {
            "begins_at": (datetime(2026, 1, 1, 4, tzinfo=UTC) + timedelta(days=index)).isoformat(),
            "open_price": str(price),
            "high_price": str(price),
            "low_price": str(price),
            "close_price": str(price),
            "volume": volume,
            "session": "reg",
        }
        if marker:
            item["interpolated"] = index == interpolated_at
        bars.append(item)
    if bad and bars:
        bars[-1]["close_price"] = "999999"
    payload = {
        "data": {
            "results": [{"symbol": symbol, "interval": "day", "bounds": "regular", "bars": bars}]
        }
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return normalize_history_by_symbol(
        payload,
        received_at=received_at,
        observation_sha256=digest,
        requested_symbols=(symbol,),
        request_adjustment_type="none" if raw else None,
        completed_before=cutoff if complete else None,
    )


def compute(*batches, as_of=AS_OF):
    return api().compute_stock_technicals(as_of=as_of, history=batches)


def test_known_price_volume_windows_preserve_provenance_and_remain_unqualified():
    source = history(range(1, 202))
    (features,) = compute(source)
    assert features.symbol == "ALFA" and features.as_of == AS_OF
    assert features.total_bar_count == features.supported_bar_count == 201
    assert features.source_bar_slot_count == 201 and features.omitted_interpolated_count == 0
    assert features.calculation_status == "calculated"
    metrics = features.metrics
    assert abs(metrics.price_return_20 - Decimal(20) / Decimal(181)) < Decimal("1e-26")
    assert abs(metrics.price_return_60 - Decimal(60) / Decimal(141)) < Decimal("1e-26")
    assert abs(metrics.price_return_120 - Decimal(120) / Decimal(81)) < Decimal("1e-26")
    assert metrics.sma_50 == Decimal("176.5") and metrics.sma_200 == Decimal("101.5")
    assert metrics.average_volume_20 == metrics.average_volume_30 == Decimal(100)
    assert metrics.average_dollar_volume_20 == Decimal(19150)
    assert metrics.average_dollar_volume_30 == Decimal(18650)
    assert metrics.series_max_drawdown == Decimal(0)
    daily_returns = [float(Decimal(index + 1) / Decimal(index) - 1) for index in range(181, 201)]
    reference = statistics.stdev(daily_returns) * math.sqrt(252)
    assert abs(metrics.realized_volatility_20 - Decimal(str(reference))) < Decimal("1e-14")
    assert features.receipt == source.receipt
    assert features.projection_batch_hash == source.observation_hash
    assert features.outcome == source.outcomes[0]
    assert features.normalized_observation_hash == source.outcomes[0].normalized.observation_hash
    assert features.window_basis == "retained_completed_daily_observations"
    assert features.volatility_annualization_sessions == 252
    assert (
        not features.qualified and not features.investment_eligible and not features.live_authorized
    )
    assert not hasattr(metrics, "relative_strength") and not hasattr(features, "score")
    with pytest.raises(AttributeError):
        features.total_bar_count = 0


def test_insufficient_windows_are_null_while_true_zero_volume_and_volatility_remain_zero():
    (features,) = compute(history([10] * 20, volume=0))
    values = features.metrics
    assert values.price_return_20 is None and values.realized_volatility_20 is None
    assert values.price_return_60 is None and values.price_return_120 is None
    assert values.sma_50 is None and values.sma_200 is None
    assert values.average_volume_20 == values.average_dollar_volume_20 == Decimal(0)
    assert values.average_volume_30 is None and values.series_max_drawdown == Decimal(0)
    assert any(
        item.metric == "price_return_20" and item.reason == "insufficient_observations"
        for item in features.missing_metrics
    )
    (enough,) = compute(history([10] * 21))
    assert enough.metrics.price_return_20 == enough.metrics.realized_volatility_20 == Decimal(0)


def test_max_drawdown_uses_running_peak_over_all_retained_raw_closes():
    (features,) = compute(history([100, 120, 90, 110, 80, 120]))
    assert abs(features.metrics.series_max_drawdown - Decimal(1) / Decimal(3)) < Decimal("1e-27")
    assert features.metrics.average_volume_20 is None
    assert "raw_corporate_actions_unknown_not_total_returns" in features.limitations


@pytest.mark.parametrize(
    "kwargs",
    [
        {"raw": False},
        {"complete": False},
        {"marker": False},
    ],
)
def test_unverified_input_prerequisites_produce_null_metrics_without_selecting_a_partial_prefix(
    kwargs,
):
    (features,) = compute(history(range(1, 202), **kwargs))
    assert features.calculation_status == "ineligible"
    assert features.total_bar_count == 201
    assert features.metrics.sma_50 is None and features.metrics.series_max_drawdown is None
    assert all(item.reason == "ineligible_history" for item in features.missing_metrics)


def test_quarantined_company_has_unknown_counts_and_no_technical_values():
    (features,) = compute(history([100, 110], bad=True))
    assert features.calculation_status == "quarantined"
    assert features.total_bar_count is None and features.source_bar_slot_count is None
    assert features.outcome.normalized is None
    assert features.metrics.series_max_drawdown is None and features.metrics.price_return_20 is None
    (empty,) = compute(history([]))
    assert empty.calculation_status == "unavailable" and empty.total_bar_count == 0


def test_one_incomplete_tail_does_not_silently_select_an_earlier_completed_prefix():
    (features,) = compute(history(range(1, 202), cutoff=datetime(2026, 7, 20, tzinfo=UTC)))
    assert features.total_bar_count == 201 and features.supported_bar_count == 200
    assert features.calculation_status == "ineligible"
    assert features.metrics.sma_50 is None and features.metrics.series_max_drawdown is None


@pytest.mark.parametrize("count", [49, 50, 199, 200])
def test_moving_average_window_boundaries(count):
    (features,) = compute(history(range(1, count + 1)))
    assert (features.metrics.sma_50 is not None) == (count >= 50)
    assert (features.metrics.sma_200 is not None) == (count >= 200)


def test_interpolated_omissions_are_retained_without_calendar_or_gap_filling_claims():
    source = history(range(1, 23), interpolated_at=20)
    (features,) = compute(source)
    assert features.total_bar_count == 21 and features.source_bar_slot_count == 22
    assert features.omitted_interpolated_count == 1
    assert features.outcome.normalized.omitted_interpolated_bars[0].symbol == "ALFA"
    assert features.metrics.price_return_20 == Decimal(21)
    assert features.window_basis == "retained_completed_daily_observations"
    assert "calendar_session_coverage_unverified" in features.limitations


def test_decimal_calculations_are_reproducible_despite_callers_arithmetic_context():
    source = history(range(1, 202))
    original = compute(source)[0]
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        changed = compute(source)[0]
    assert original.metrics == changed.metrics and original.feature_hash == changed.feature_hash


def test_unsafe_derived_magnitude_is_null_for_affected_fields_without_zero_fill():
    (features,) = compute(history(["1e-300"] * 20 + ["1e300"]))
    assert features.metrics.price_return_20 is None
    assert features.metrics.realized_volatility_20 is None
    assert features.metrics.average_volume_20 == Decimal(100)
    assert any(
        item.metric == "price_return_20" and item.reason == "arithmetic_invalid"
        for item in features.missing_metrics
    )


def test_future_receipts_do_not_create_company_membership_and_duplicate_sources_deny():
    source = history([10, 11])
    future = history([10, 11], symbol="BETA", received_at=AS_OF + timedelta(seconds=1))
    assert tuple(item.symbol for item in compute(source, future)) == ("ALFA",)
    with pytest.raises(ValueError, match=r"^stock_technicals_invalid$"):
        compute(source, source)


def test_wrong_projection_provenance_is_not_accepted_as_company_evidence():
    source = history([10, 11])
    wrong = replace(
        source,
        outcomes=(
            replace(
                source.outcomes[0],
                context=replace(source.outcomes[0].context, original_source_sha256="f" * 64),
            ),
        ),
    )
    with pytest.raises(ValueError, match=r"^stock_technicals_invalid$"):
        compute(wrong)


@pytest.mark.parametrize("as_of", [AS_OF.replace(tzinfo=None), None])
def test_invalid_cutoff_denies(as_of):
    with pytest.raises(ValueError, match=r"^stock_technicals_invalid$"):
        compute(history([10, 11]), as_of=as_of)


def test_collection_bounds_and_mutable_input_deny_but_empty_tuple_is_valid():
    source = history([10, 11])
    for collections in ([source], (source,) * 257):
        with pytest.raises(ValueError, match=r"^stock_technicals_invalid$"):
            api().compute_stock_technicals(as_of=AS_OF, history=collections)
    assert compute() == ()
