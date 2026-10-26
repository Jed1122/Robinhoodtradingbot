"""Fictional quality diagnostics preserve unknowns and never promote a data source."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from trading_bot.market_data.stock_events import normalize_filing_index
from trading_bot.market_data.stock_facts import normalize_financials, normalize_fundamentals
from trading_bot.market_data.stock_filing_facts import (
    bind_filing_evidence,
    normalize_filing_catalog,
    normalize_filing_facts,
)
from trading_bot.market_data.stock_history_projection import normalize_history_by_symbol
from trading_bot.research.stock_dossiers import StockDossier, build_stock_dossiers

NOW = datetime(2026, 10, 25, 18, tzinfo=UTC)
RECEIVED = NOW - timedelta(hours=1)


def api():
    try:
        return importlib.import_module("trading_bot.research.stock_data_quality")
    except ModuleNotFoundError:
        pytest.fail("stock data quality assessment is missing")


def dossier(
    *,
    received=RECEIVED,
    bar_date="2026-10-23",
    period_end="2026-06-30",
    interpolated=False,
    bad=False,
    null_bar=False,
    empty=False,
):
    fundamentals = normalize_fundamentals(
        {"data": {"results": [{"symbol": "ALFA", "market_cap": "0"}]}},
        received_at=received,
        observation_sha256="a" * 64,
        requested_symbols=("ALFA",),
    )
    financials = normalize_financials(
        {
            "data": {
                "results": [
                    {
                        "symbol": "ALFA",
                        "period": "annual",
                        "financials": [
                            {
                                "fiscal_year": 2026,
                                "period_end_date": period_end,
                                "revenue": "0",
                                "gross_profit": None,
                                "net_income": "-2",
                                "net_margin": None,
                            }
                        ],
                    }
                ]
            }
        },
        received_at=received,
        observation_sha256="b" * 64,
        requested_symbols=("ALFA",),
    )
    bar = {
        "begins_at": bar_date + "T04:00:00Z",
        "open_price": "20",
        "high_price": "22",
        "low_price": "19",
        "close_price": "99" if bad else "21",
        "volume": 0,
        "session": "reg",
    }
    if interpolated is not None:
        bar["interpolated"] = interpolated
    history = normalize_history_by_symbol(
        {
            "data": {
                "results": [
                    {
                        "symbol": "ALFA",
                        "interval": "day",
                        "bounds": "regular",
                        "bars": [] if empty else [bar, *([None] if null_bar else [])],
                    }
                ]
            }
        },
        received_at=received,
        observation_sha256="c" * 64,
        requested_symbols=("ALFA",),
        request_adjustment_type="none",
        completed_before=received.replace(hour=0),
    )
    return build_stock_dossiers(
        as_of=NOW, facts=(fundamentals, financials), history=(history,), earnings=(), filings=()
    )[0]


def reasons(report, use):
    return next(item.reason_codes for item in report.blocked_uses if item.use == use)


def test_receipt_ages_are_per_source_and_do_not_relabel_old_financial_periods():
    report = api().assess_stock_data_quality(dossier(period_end="2020-06-30"), as_of=NOW)
    assert {item.receipt_age_seconds for item in report.sources} == {Decimal(3600)}
    period = report.financial_periods[0]
    assert period.period_end == date(2020, 6, 30) and period.period_age_days == 2308
    assert period.receipt_age_seconds == Decimal(3600)
    assert "financial_period_stale" in period.reason_codes
    assert report.descriptive_observations_present
    assert "financial_currency_unknown" in reasons(report, "financial_comparison")


def test_fresh_receipt_does_not_hide_old_bars_and_history_unknowns_are_counted():
    report = api().assess_stock_data_quality(
        dossier(bar_date="2026-09-01", interpolated=None, null_bar=True),
        as_of=NOW,
    )
    assert report.history.latest_bar_lag_days == 54
    assert report.history.bar_count == 1 and report.history.null_bar_count == 1
    assert report.history.interpolation_unknown_count == 1
    assert report.history.session_unknown_count == 0
    assert {
        "latest_bar_stale",
        "interpolation_unknown",
        "history_null_bars",
        "insufficient_history_bars",
    } <= set(report.history.reason_codes)
    assert "calendar_coverage_unknown" in reasons(report, "daily_price_features")
    assert "corporate_action_coverage_unknown" in reasons(report, "historical_strategy")


def test_null_financial_metrics_are_missing_while_actual_zero_is_present():
    original = dossier()
    report = api().assess_stock_data_quality(original, as_of=NOW)
    assert report.financial_periods[0].missing_metrics == ("gross_profit", "net_margin")
    assert report.financial_periods[0].missing_metric_count == 2
    assert original.financial_periods[0].metrics[0].value == Decimal(0)
    assert report.financial_currency_unknown_count == 1
    assert report.fundamentals_missing_metrics == original.fundamentals.missing_metrics
    assert report.filing_fact_count == 0
    assert "filing_evidence_absent" in report.reason_codes
    assert "entity_mapping_unknown" in report.reason_codes
    assert "point_in_time_availability_unknown" in report.reason_codes


@pytest.mark.parametrize(
    "options,status,count",
    [
        ({"bad": True}, "quarantined", None),
        ({"empty": True}, "unavailable", 0),
        ({"interpolated": True}, "unavailable", 0),
    ],
)
def test_unusable_history_keeps_unknown_counts_and_omission_provenance(options, status, count):
    report = api().assess_stock_data_quality(dossier(**options), as_of=NOW)
    assert report.history.status == status and report.history.bar_count == count
    if status == "quarantined":
        assert report.history.null_bar_count is None
        assert report.history.interpolation_unknown_count is None
    if options.get("interpolated"):
        assert report.history.omitted_interpolated_count == 1
    assert "history_" + status in report.history.reason_codes


def test_absent_data_is_unknown_not_zero_and_no_descriptive_observations_are_claimed():
    empty = StockDossier("ALFA", NOW, None, (), None, (), (), (), ())
    report = api().assess_stock_data_quality(empty, as_of=NOW)
    assert report.history.status == "absent" and report.history.bar_count is None
    assert report.fundamentals_missing_metrics is None
    assert not report.descriptive_observations_present
    assert "observations_absent_or_stale" in reasons(report, "current_descriptive_research")


def test_one_old_source_does_not_make_all_sources_stale_and_exact_limit_is_inclusive():
    current = dossier()
    old_receipt = replace(current.sources[0].receipt, received_at=NOW - timedelta(days=2))
    changed = replace(
        current, sources=(replace(current.sources[0], receipt=old_receipt), *current.sources[1:])
    )
    report = api().assess_stock_data_quality(changed, as_of=NOW)
    assert report.sources[0].receipt_age_seconds == Decimal(172800)
    assert report.sources[0].reason_codes == ("receipt_stale",)
    assert all("receipt_stale" not in source.reason_codes for source in report.sources[1:])
    boundary = api().assess_stock_data_quality(dossier(received=NOW - timedelta(days=1)), as_of=NOW)
    assert all("receipt_stale" not in source.reason_codes for source in boundary.sources)


@pytest.mark.parametrize("mutation", ["dossier", "source", "record", "history"])
def test_future_information_in_a_supplied_dossier_is_rejected_without_reporting_values(mutation):
    original = dossier()
    future = NOW + timedelta(microseconds=1)
    if mutation == "dossier":
        original = replace(original, as_of=future)
    elif mutation == "source":
        source = original.sources[0]
        original = replace(
            original,
            sources=(
                replace(source, receipt=replace(source.receipt, received_at=future)),
                *original.sources[1:],
            ),
        )
    elif mutation == "record":
        record = original.financial_periods[0]
        original = replace(
            original,
            financial_periods=(
                replace(record, receipt=replace(record.receipt, received_at=future)),
            ),
        )
    else:
        history = original.history
        normalized = history.outcome.normalized
        original = replace(
            original,
            history=replace(
                history,
                outcome=replace(
                    history.outcome,
                    normalized=replace(
                        normalized, receipt=replace(normalized.receipt, received_at=future)
                    ),
                ),
            ),
        )
    with pytest.raises(ValueError, match=r"^stock_data_quality_invalid$"):
        api().assess_stock_data_quality(original, as_of=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_receipt_age_seconds", True),
        ("max_receipt_age_seconds", 0),
        ("max_receipt_age_seconds", 31536001),
        ("max_latest_bar_lag_days", -1),
        ("max_latest_bar_lag_days", 3651),
        ("max_financial_period_age_days", 36501),
        ("minimum_history_bars", 0),
        ("minimum_history_bars", 100001),
        ("minimum_history_bars", 201.0),
    ],
)
def test_policy_rejects_boolean_noninteger_and_unbounded_thresholds(field, value):
    with pytest.raises(ValueError, match=r"^stock_data_quality_invalid$"):
        api().StockDataQualityPolicy(**{field: value})


@pytest.mark.parametrize(
    "clock", [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=1)))]
)
def test_non_utc_assessment_clocks_are_rejected(clock):
    with pytest.raises(ValueError, match=r"^stock_data_quality_invalid$"):
        api().assess_stock_data_quality(dossier(), as_of=clock)


def test_complete_dossier_policy_and_assessment_clock_are_hash_bound_without_promotion():
    original = dossier()
    module = api()
    first = module.assess_stock_data_quality(original, as_of=NOW)
    same = module.assess_stock_data_quality(original, as_of=NOW)
    provenance = replace(original.sources[0], collection_observation_hash="f" * 64)
    changed = replace(original, sources=(provenance, *original.sources[1:]))
    hashes = {
        first.assessment_hash,
        module.assess_stock_data_quality(changed, as_of=NOW).assessment_hash,
        module.assess_stock_data_quality(
            original, as_of=NOW + timedelta(seconds=1)
        ).assessment_hash,
        module.assess_stock_data_quality(
            original, as_of=NOW, policy=module.StockDataQualityPolicy(minimum_history_bars=200)
        ).assessment_hash,
    }
    assert first == same and len(hashes) == 4
    assert first.dossier_hash == original.dossier_hash
    for name in (
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
    ):
        assert getattr(first, name) is False
        with pytest.raises(TypeError):
            replace(first, **{name: True})
    with pytest.raises(FrozenInstanceError):
        first.reason_codes = ()


def filing_evidence():
    index = normalize_filing_index(
        {
            "data": {
                "symbol": "ALFA",
                "filings": [
                    {
                        "filing_id": "fictional",
                        "date_filed": "2026-06-30",
                        "form_type": "10-Q",
                        "description": "fictional",
                    }
                ],
            }
        },
        received_at=RECEIVED,
        observation_sha256="d" * 64,
        requested_symbol="ALFA",
    )
    catalog = normalize_filing_catalog(
        {
            "data": {
                "concepts": [
                    {
                        "concept": "fictional:Amount",
                        "is_text_block": False,
                        "periods": [{"period": "current", "end_date": "2026-06-30"}],
                        "axis_names": [],
                    }
                ],
                "count": 1,
            },
            "guide": "untrusted",
        },
        received_at=RECEIVED,
        observation_sha256="e" * 64,
        requested_filing_id="fictional",
        requested_offset=0,
    )
    facts = normalize_filing_facts(
        {
            "data": {
                "facts": [
                    {
                        "filing_id": "fictional",
                        "concept": "fictional:Amount",
                        "entity": "opaque-entity",
                        "period": "current",
                        "axises": [],
                        "char_value": "unparsed",
                        "end_date": "2026-06-30",
                        "value": None,
                        "unit": None,
                    }
                ]
            },
            "guide": "untrusted",
        },
        received_at=RECEIVED,
        observation_sha256="f" * 64,
        requested_filing_ids=("fictional",),
        requested_concepts=("fictional:Amount",),
    )
    return bind_filing_evidence(index, catalog, facts, as_of=NOW)


def test_filing_counts_keep_native_unknown_values_and_opaque_entity_unverified():
    original = replace(dossier(), filing_evidence=(filing_evidence(),))
    report = api().assess_stock_data_quality(original, as_of=NOW)
    assert report.filing_fact_count == 1 and report.filing_numeric_missing_count == 1
    assert report.filing_unit_unknown_count == 1
    assert report.filing_period_start_unknown_count == 1
    assert report.filing_entity_unverified_count == 1
    assert "filing_units_unqualified" in report.reason_codes
    assert "filing_evidence_absent" not in report.reason_codes
    assert {source.tool for source in report.sources} >= {
        "get_sec_filing_facts",
        "get_sec_filing_facts_catalog",
        "get_sec_filing_index",
    }


def test_filing_receipt_future_cutoff_rejects_even_when_top_level_sources_are_visible():
    original = replace(
        dossier(received=RECEIVED - timedelta(days=2)), filing_evidence=(filing_evidence(),)
    )
    # All normal binders reject future data; an assessment also fails closed on a
    # manually supplied dossier whose decision clock precedes retained evidence.
    original = replace(original, as_of=RECEIVED - timedelta(seconds=1))
    with pytest.raises(ValueError, match=r"^stock_data_quality_invalid$"):
        api().assess_stock_data_quality(original, as_of=RECEIVED - timedelta(seconds=1))


def test_stale_history_is_explicit_even_when_another_source_has_a_fresh_receipt():
    original = dossier(received=NOW - timedelta(days=2))
    current = dossier()
    mixed = replace(original, fundamentals=current.fundamentals)
    report = api().assess_stock_data_quality(mixed, as_of=NOW)
    assert report.descriptive_observations_present
    assert "receipt_stale" in report.history.reason_codes
    assert "receipt_stale" in reasons(report, "daily_price_features")


def test_fractional_receipt_ages_preserve_microseconds_at_freshness_boundary():
    policy = api().StockDataQualityPolicy(max_receipt_age_seconds=3600)
    first = api().assess_stock_data_quality(dossier(), as_of=NOW, policy=policy)
    later = api().assess_stock_data_quality(
        dossier(), as_of=NOW + timedelta(microseconds=1), policy=policy
    )
    assert first.sources[0].receipt_age_seconds == Decimal("3600")
    assert later.sources[0].receipt_age_seconds == Decimal("3600.000001")
    assert "receipt_stale" not in first.sources[0].reason_codes
    assert "receipt_stale" in later.sources[0].reason_codes


def test_decimal_context_cannot_round_stale_receipts_back_inside_policy():
    original = dossier(received=NOW - timedelta(days=1, microseconds=1))
    with localcontext() as context:
        context.prec = 6
        report = api().assess_stock_data_quality(original, as_of=NOW)
    assert all(item.receipt_age_seconds == Decimal("86400.000001") for item in report.sources)
    assert not report.descriptive_observations_present
    assert all("receipt_stale" in item.reason_codes for item in report.sources)


def test_policy_age_and_bar_count_boundaries_do_not_imply_qualification():
    module = api()
    policy = module.StockDataQualityPolicy(minimum_history_bars=1)
    exact_period = (NOW.date() - timedelta(days=550)).isoformat()
    exact_bar = (NOW.date() - timedelta(days=7)).isoformat()
    at_limit = module.assess_stock_data_quality(
        dossier(period_end=exact_period, bar_date=exact_bar),
        as_of=NOW,
        policy=policy,
    )
    beyond = module.assess_stock_data_quality(
        dossier(
            period_end=(NOW.date() - timedelta(days=551)).isoformat(),
            bar_date=(NOW.date() - timedelta(days=8)).isoformat(),
        ),
        as_of=NOW,
        policy=policy,
    )
    assert "financial_period_stale" not in at_limit.financial_periods[0].reason_codes
    assert "latest_bar_stale" not in at_limit.history.reason_codes
    assert "insufficient_history_bars" not in at_limit.history.reason_codes
    assert "financial_period_stale" in beyond.financial_periods[0].reason_codes
    assert "latest_bar_stale" in beyond.history.reason_codes
    assert "calendar_coverage_unknown" in reasons(at_limit, "daily_price_features")
    assert not at_limit.source_qualified and not at_limit.strategy_qualified


def test_source_scope_missing_results_and_unknown_session_remain_explicit():
    original = dossier()
    history = original.history
    normalized = history.outcome.normalized
    changed_bar = replace(normalized.records[0], session=None)
    changed_source = replace(
        original.sources[0],
        scope_verified=False,
        results_missing=True,
        null_row_count=3,
        unavailable_symbols=("ALFA",),
    )
    changed = replace(
        original,
        sources=(changed_source, *original.sources[1:]),
        history=replace(
            history,
            outcome=replace(
                history.outcome, normalized=replace(normalized, records=(changed_bar,))
            ),
        ),
    )
    report = api().assess_stock_data_quality(changed, as_of=NOW)
    assert report.sources[0].collection_null_row_count == 3
    assert {"request_scope_unknown", "source_results_missing", "symbol_unavailable"} <= set(
        report.sources[0].reason_codes
    )
    assert report.history.session_unknown_count == 1
    assert "session_unknown" in report.history.reason_codes


def test_projected_receipt_is_linked_to_original_history_without_becoming_another_source():
    original = dossier()
    original_history_source = next(
        row for row in original.sources if row.tool == "get_equity_historicals"
    )
    projected_receipt = original.history.outcome.normalized.receipt
    assert (
        projected_receipt.observation_sha256 != original_history_source.receipt.observation_sha256
    )
    report = api().assess_stock_data_quality(original, as_of=NOW)
    projection = next(
        row
        for row in report.sources
        if row.observation_sha256 == projected_receipt.observation_sha256
    )
    assert projection.receipt_origin == "linked_local_projection"
    assert projection.original_source_observation_sha256 == "c" * 64
    assert projection.observation_sha256 == projected_receipt.observation_sha256
    assert sum(row.receipt_origin == "dossier_source" for row in report.sources) == 3
    for source in report.sources:
        if source.receipt_origin == "dossier_source":
            assert source.original_source_observation_sha256 == source.observation_sha256


def test_receipt_without_matching_original_projection_context_stays_unverified():
    original = dossier()
    history = original.history
    unlinked = replace(
        original,
        history=replace(
            history,
            outcome=replace(
                history.outcome,
                context=replace(history.outcome.context, original_source_sha256="f" * 64),
            ),
        ),
    )
    report = api().assess_stock_data_quality(unlinked, as_of=NOW)
    extra = next(
        row
        for row in report.sources
        if row.observation_sha256 == history.outcome.normalized.receipt.observation_sha256
    )
    assert extra.receipt_origin == "unverified_additional_receipt"
    assert extra.original_source_observation_sha256 is None
    assert extra.observation_sha256 == history.outcome.normalized.receipt.observation_sha256
    assert (
        report.assessment_hash
        != api().assess_stock_data_quality(original, as_of=NOW).assessment_hash
    )
