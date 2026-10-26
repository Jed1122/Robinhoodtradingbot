"""Invented annual statements only; no retained provider amounts or calls."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal, DefaultContext, localcontext

import pytest

from trading_bot.market_data.stock_events import normalize_filing_index
from trading_bot.market_data.stock_filing_facts import StockFilingFacts, normalize_filing_facts
from trading_bot.research.stock_annual_quality import (
    AnnualQualityError,
    AnnualQualityPeriods,
    AnnualQualityRequest,
    DefinedAnnualQuality,
    UnavailableAnnualQuality,
    build_annual_quality,
    revalidate_annual_quality,
)

RECEIVED = datetime(2026, 10, 26, tzinfo=UTC)
PUBLIC = datetime(2024, 2, 11, tzinfo=UTC)
FID = "fictional-original-filing"
ENTITY = "0000999999"
CONCEPTS = (
    "NetIncomeLoss",
    "RevenuesNetOfInterestExpense",
    "StockholdersEquity",
    "LongTermDebt",
    "ShortTermBorrowings",
)


def _filing(**changes):
    row = {
        "filing_id": FID,
        "date_filed": "2024-02-09",
        "form_type": "10-K",
        "description": "Invented annual source",
        **changes,
    }
    return normalize_filing_index(
        {"data": {"symbol": "AXP", "filings": [row]}, "guide": "fictional"},
        received_at=RECEIVED,
        observation_sha256="a" * 64,
        requested_symbol="AXP",
    ).records[0]


def _row(concept, value, end="2023-12-31", start=None, **changes):
    row = {
        "filing_id": FID,
        "concept": concept,
        "entity": ENTITY,
        "period": f"{start}T00:00:00/{end}T00:00:00" if start else f"{end}T00:00:00",
        "axises": [],
        "char_value": "",
        "end_date": end,
        "unit": "iso4217:USD",
        "decimals": -6,
        "value": value,
    }
    if start is not None:
        row["start_date"] = start
    return row | changes


def _rows():
    return [
        _row("NetIncomeLoss", "20000000", start="2023-01-01"),
        _row("RevenuesNetOfInterestExpense", "150000000", start="2023-01-01"),
        _row("RevenuesNetOfInterestExpense", "100000000", end="2022-12-31", start="2022-01-01"),
        _row("StockholdersEquity", "80000000", end="2022-12-31"),
        _row("StockholdersEquity", "120000000"),
        _row("LongTermDebt", "30000000"),
        _row("ShortTermBorrowings", "10000000"),
    ]


def _facts(rows=None, *, filing_ids=(FID,), observation="b" * 64, concepts=CONCEPTS):
    return normalize_filing_facts(
        {"data": {"facts": _rows() if rows is None else rows}, "guide": "fictional source"},
        received_at=RECEIVED,
        observation_sha256=observation,
        requested_filing_ids=filing_ids,
        requested_concepts=concepts,
    )


def _periods(**changes):
    values = {
        "current_start": date(2023, 1, 1),
        "current_end": date(2023, 12, 31),
        "prior_start": date(2022, 1, 1),
        "prior_end": date(2022, 12, 31),
        **changes,
    }
    return AnnualQualityPeriods(**values)


def _request(rows=None, **changes):
    values = {
        "filing": _filing(),
        "facts": (_facts(rows),),
        "entity": ENTITY,
        "periods": _periods(),
        "information_at": PUBLIC,
        **changes,
    }
    return AnnualQualityRequest(**values)


def test_defined_bundle_uses_base_usd_and_keeps_duration_and_instant_sources() -> None:
    request = _request()
    result = build_annual_quality(request)
    assert isinstance(result, DefinedAnnualQuality)
    assert result.roe == Decimal("0.2")
    assert result.revenue_growth == Decimal("0.5")
    assert result.debt_to_equity == Decimal("0.33333333333333333333333333333333333333333333333333")
    assert result.method_id == "axp-annual-as-reported-financing-to-reported-equity-v1"
    assert result.availability_proxy_at == PUBLIC
    assert result.debt_measurement_kind == "instant"
    assert result.debt_measurement_at == date(2023, 12, 31)
    assert result.request.filing.receipt.received_at == RECEIVED
    assert result.request.facts[0].receipt.received_at == RECEIVED
    assert len(result.references) == 7
    debt = next(ref for ref in result.references if ref.role == "long_term_debt")
    assert debt.fact.start_date_present is False and debt.fact.start_date is None
    assert debt.fact.value_raw == "30000000" and debt.fact.decimals_raw == -6
    assert debt.fact.period == "2023-12-31T00:00:00"
    assert debt.observation_sha256 == "b" * 64
    assert debt.source_facts_hash == request.facts[0].facts_hash
    assert debt.fact is request.facts[0].records[5]
    assert revalidate_annual_quality(result) is result
    assert len(result.evidence_hash) == 64


def test_actual_receipt_does_not_become_historical_publication_clock() -> None:
    result = build_annual_quality(_request(information_at=PUBLIC.replace(hour=1)))
    assert isinstance(result, DefinedAnnualQuality)
    assert result.availability_proxy_at < result.request.filing.receipt.received_at
    unavailable = build_annual_quality(_request(information_at=PUBLIC.replace(day=10, hour=23)))
    assert isinstance(unavailable, UnavailableAnnualQuality)
    assert "filing_not_available_at_proxy" in unavailable.reason_codes
    assert unavailable.roe is unavailable.revenue_growth is unavailable.debt_to_equity is None


def test_53_week_fiscal_year_uses_native_adjacent_periods_and_opening_equity() -> None:
    periods = _periods(
        current_start=date(2022, 12, 25),
        current_end=date(2023, 12, 30),
        prior_start=date(2021, 12, 26),
        prior_end=date(2022, 12, 24),
    )
    rows = [
        _row("NetIncomeLoss", "20000000", end="2023-12-30", start="2022-12-25"),
        _row("RevenuesNetOfInterestExpense", "150000000", end="2023-12-30", start="2022-12-25"),
        _row("RevenuesNetOfInterestExpense", "100000000", end="2022-12-24", start="2021-12-26"),
        _row("StockholdersEquity", "80000000", end="2022-12-24"),
        _row("StockholdersEquity", "120000000", end="2023-12-30"),
        _row("LongTermDebt", "30000000", end="2023-12-30"),
        _row("ShortTermBorrowings", "10000000", end="2023-12-30"),
    ]
    result = build_annual_quality(_request(rows, periods=periods))
    assert isinstance(result, DefinedAnnualQuality)
    assert result.roe == Decimal("0.2") and result.revenue_growth == Decimal("0.5")
    assert result.request.periods.current_start == date(2022, 12, 25)
    assert result.debt_measurement_at == date(2023, 12, 30)


@pytest.mark.parametrize(
    "periods",
    [
        _periods(current_start=date(2023, 10, 1)),
        _periods(prior_end=date(2022, 12, 30)),
    ],
)
def test_partial_year_or_nonadjacent_comparison_is_unavailable(periods) -> None:
    assert isinstance(build_annual_quality(_request(periods=periods)), UnavailableAnnualQuality)


@pytest.mark.parametrize("role_index", range(7))
def test_missing_component_is_unavailable_with_no_partial_values(role_index) -> None:
    rows = _rows()
    del rows[role_index]
    result = build_annual_quality(_request(rows))
    assert isinstance(result, UnavailableAnnualQuality)
    assert result.reason_codes
    assert result.roe is result.revenue_growth is result.debt_to_equity is None


@pytest.mark.parametrize(
    "index,value",
    [(2, "0"), (2, "-1"), (4, "0"), (4, "-1"), (3, "-120000000"), (5, "-1"), (6, "-1")],
)
def test_invalid_denominators_or_negative_financing_fail_closed(index, value) -> None:
    rows = _rows()
    rows[index]["value"] = value
    assert isinstance(build_annual_quality(_request(rows)), UnavailableAnnualQuality)


def test_observed_zero_short_borrowing_is_distinct_from_missing() -> None:
    rows = _rows()
    rows[6]["value"] = "0"
    result = build_annual_quality(_request(rows))
    assert isinstance(result, DefinedAnnualQuality)
    assert result.debt_to_equity == Decimal("0.25")


@pytest.mark.parametrize(
    "changes",
    [
        {"entity": "0000000001"},
        {"unit": "iso4217:EUR"},
        {"unit": None},
        {"axises": ["ConsolidatedEntitiesAxis: ParentCompanyMember"]},
        {"axises": None},
        {"period": "2023-01-01/2023-12-31"},
        {"start_date": "2023-01-01"},
    ],
)
def test_debt_requires_matching_entity_native_usd_empty_axes_and_true_instant(changes) -> None:
    rows = _rows()
    rows[5] |= changes
    assert isinstance(build_annual_quality(_request(rows)), UnavailableAnnualQuality)


def test_fee_revenue_or_profit_loss_cannot_replace_frozen_scopes() -> None:
    rows = _rows()
    rows[0]["concept"] = "ProfitLoss"
    rows[1]["concept"] = "RevenueFromContractWithCustomerExcludingAssessedTax"
    facts = _facts(
        rows,
        concepts=(*CONCEPTS, "ProfitLoss", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    )
    result = build_annual_quality(_request(facts=(facts,)))
    assert isinstance(result, UnavailableAnnualQuality)


def test_equivalent_period_strings_keep_every_matching_reference_when_values_agree() -> None:
    rows = _rows()
    rows.append(rows[0] | {"period": "2023-01-01/2023-12-31", "value": "20000000.00"})
    result = build_annual_quality(_request(rows))
    assert isinstance(result, DefinedAnnualQuality)
    refs = [ref for ref in result.references if ref.role == "net_income"]
    assert len(refs) == 2
    assert {ref.fact.row_index for ref in refs} == {0, 7}
    assert {ref.fact.period for ref in refs} == {
        "2023-01-01T00:00:00/2023-12-31T00:00:00",
        "2023-01-01/2023-12-31",
    }


@pytest.mark.parametrize("native_count", [16, 64, 128])
def test_agreeing_contexts_have_linear_full_batch_hash_work(native_count, monkeypatch) -> None:
    rows = _rows()
    rows.extend(rows[0].copy() for _ in range(native_count - len(rows)))
    request = _request(rows)
    source = request.facts[0]
    original_hash = StockFilingFacts.facts_hash.fget
    expected_digest = original_hash(source)
    counters = {"calls": 0, "row_visits": 0}

    def counted_hash(value):
        counters["calls"] += 1
        counters["row_visits"] += len(value.records)
        return original_hash(value)

    with monkeypatch.context() as context:
        context.setattr(StockFilingFacts, "facts_hash", property(counted_hash))
        result = build_annual_quality(request)
        assert isinstance(result, DefinedAnnualQuality)
        assert len(result.references) == native_count
        assert all(ref.source_facts_hash == expected_digest for ref in result.references)
        # At most one complete hash in each of the factory/constructor assessments,
        # rather than a complete batch traversal for each agreeing context.
        assert counters["calls"] <= 2
        assert counters["row_visits"] <= 2 * native_count
        previous_calls = counters["calls"]
        assert revalidate_annual_quality(result) is result
        assert previous_calls < counters["calls"] <= previous_calls + 2


def test_revalidation_rehashes_even_an_unused_mutated_native_context() -> None:
    rows = _rows()
    rows.append(_row("NetIncomeLoss", "5000000", end="2020-12-31", start="2020-01-01"))
    request = _request(rows)
    result = build_annual_quality(request)
    unused = request.facts[0].records[-1]
    # Keep the normalized fact internally consistent so only a fresh full-source
    # digest exposes this alteration; no selected measurement value changes.
    object.__setattr__(unused, "value_raw", "6000000")
    object.__setattr__(unused, "numeric_value", Decimal("6000000"))
    with pytest.raises(AnnualQualityError):
        revalidate_annual_quality(result)


def test_conflicting_duplicate_values_are_unavailable_instead_of_arbitrary_selection() -> None:
    rows = _rows()
    rows.append(rows[0] | {"period": "2023-01-01/2023-12-31", "value": "21000000"})
    result = build_annual_quality(_request(rows))
    assert isinstance(result, UnavailableAnnualQuality)
    assert "conflicting_values:net_income" in result.reason_codes


def test_multiple_collections_preserve_each_full_receipt_and_do_not_relabel_rows() -> None:
    rows = _rows()
    first, second = _facts(rows[:4]), _facts(rows[4:], observation="c" * 64)
    result = build_annual_quality(_request(facts=(first, second)))
    assert isinstance(result, DefinedAnnualQuality)
    assert {ref.observation_sha256 for ref in result.references} == {"b" * 64, "c" * 64}
    assert {ref.source_collection_index for ref in result.references} == {0, 1}
    assert result.request.facts == (first, second)


def test_later_original_vintage_cannot_fill_missing_earlier_component() -> None:
    rows = _rows()
    del rows[0]
    rows.append(_rows()[0] | {"filing_id": "later-original", "value": "999000000"})
    facts = _facts(rows, filing_ids=(FID, "later-original"))
    assert isinstance(build_annual_quality(_request(facts=(facts,))), UnavailableAnnualQuality)


def test_future_vintage_mutation_cannot_change_target_original_features() -> None:
    rows = [*_rows(), _rows()[0] | {"filing_id": "later-original", "value": "999000000"}]
    first = build_annual_quality(
        _request(facts=(_facts(rows, filing_ids=(FID, "later-original")),))
    )
    rows[-1]["value"] = "1"
    second = build_annual_quality(
        _request(facts=(_facts(rows, filing_ids=(FID, "later-original")),))
    )
    assert isinstance(first, DefinedAnnualQuality) and isinstance(second, DefinedAnnualQuality)
    assert (first.roe, first.revenue_growth, first.debt_to_equity) == (
        second.roe,
        second.revenue_growth,
        second.debt_to_equity,
    )


@pytest.mark.parametrize("changes", [{"form_type": "10-K/A"}, {"filing_id": "different-original"}])
def test_amendment_or_unrequested_filing_is_not_silently_used(changes) -> None:
    assert isinstance(
        build_annual_quality(_request(filing=_filing(**changes))), UnavailableAnnualQuality
    )


def test_method_cannot_be_generalized_to_another_issuer() -> None:
    filing = replace(_filing(), symbol="OTHER")
    assert isinstance(build_annual_quality(_request(filing=filing)), UnavailableAnnualQuality)


def test_public_constructors_replace_and_revalidation_cannot_promote_authority() -> None:
    result = build_annual_quality(_request())
    assert isinstance(result, DefinedAnnualQuality)
    for flag in (
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
    ):
        assert getattr(result, flag) is False
        with pytest.raises((TypeError, ValueError)):
            replace(result, **{flag: True})
    with pytest.raises((TypeError, ValueError)):
        replace(result, roe=Decimal("999"))
    with pytest.raises(FrozenInstanceError):
        result.roe = Decimal("999")
    with pytest.raises(AnnualQualityError):
        DefinedAnnualQuality(_request(rows=[]))
    with pytest.raises(AnnualQualityError):
        UnavailableAnnualQuality(_request())
    object.__setattr__(result, "qualified", True)
    with pytest.raises(AnnualQualityError):
        revalidate_annual_quality(result)


def test_revalidation_rejects_forged_numeric_fields_and_source_derived_values() -> None:
    result = build_annual_quality(_request())
    object.__setattr__(result, "roe", Decimal("999"))
    with pytest.raises(AnnualQualityError):
        revalidate_annual_quality(result)
    request = _request()
    object.__setattr__(request.facts[0].records[0], "numeric_value", Decimal("999"))
    with pytest.raises(AnnualQualityError):
        build_annual_quality(request)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_collection_index": True},
        {"source_facts_hash": "0" * 64},
        {"observation_sha256": "0" * 64},
        {"received_at": RECEIVED.replace(tzinfo=None)},
    ],
)
def test_revalidation_rejects_forged_row_provenance(changes) -> None:
    result = build_annual_quality(_request())
    altered = replace(result.references[0], **changes)
    object.__setattr__(result, "references", (altered, *result.references[1:]))
    with pytest.raises(AnnualQualityError):
        revalidate_annual_quality(result)


def test_unavailable_result_remains_typed_revalidatable_and_unqualified() -> None:
    result = build_annual_quality(_request(rows=[]))
    assert isinstance(result, UnavailableAnnualQuality)
    assert result.qualified is result.source_qualified is result.investment_eligible is False
    assert result.live_authorized is result.trading_enabled is False
    assert revalidate_annual_quality(result) is result
    assert len(result.evidence_hash) == 64


def test_negative_income_and_growth_are_observed_measurements_not_missing_or_authority() -> None:
    rows = _rows()
    rows[0]["value"] = "-20000000"
    rows[1]["value"] = "50000000"
    result = build_annual_quality(_request(rows))
    assert isinstance(result, DefinedAnnualQuality)
    assert result.roe == Decimal("-0.2") and result.revenue_growth == Decimal("-0.5")
    assert result.qualified is result.investment_eligible is result.live_authorized is False


def test_source_authority_tampering_is_rejected() -> None:
    request = _request()
    object.__setattr__(request.facts[0], "qualified", True)
    with pytest.raises(AnnualQualityError):
        build_annual_quality(request)


def test_bounds_are_checked_before_unbounded_source_work() -> None:
    with pytest.raises(AnnualQualityError):
        _request(facts=(_facts(),) * 9)
    with pytest.raises(AnnualQualityError):
        _request(facts=())
    many = _facts(_rows() * 1429)
    with pytest.raises(AnnualQualityError):
        _request(facts=(many, many))


def test_null_native_rows_count_toward_the_total_source_bound() -> None:
    null_source = _facts([None] * 10001)
    with pytest.raises(AnnualQualityError):
        _request(facts=(null_source, null_source))


def test_receipt_before_original_filing_is_unavailable_without_clock_repair() -> None:
    source = normalize_filing_facts(
        {"data": {"facts": _rows()}, "guide": "fictional impossible clock"},
        received_at=datetime(2024, 2, 8, tzinfo=UTC),
        observation_sha256="d" * 64,
        requested_filing_ids=(FID,),
        requested_concepts=CONCEPTS,
    )
    result = build_annual_quality(_request(facts=(source,)))
    assert isinstance(result, UnavailableAnnualQuality)
    assert "receipt_before_filing" in result.reason_codes
    assert result.request.facts[0].receipt.received_at == datetime(2024, 2, 8, tzinfo=UTC)


def test_nonadjacent_extreme_period_is_unavailable_without_calendar_overflow() -> None:
    periods = _periods(prior_end=date.max)
    assert isinstance(build_annual_quality(_request(periods=periods)), UnavailableAnnualQuality)


def test_filing_outside_availability_proxy_calendar_bound_is_rejected() -> None:
    filing = _filing()
    filing = replace(
        filing,
        date_filed=date.max,
        receipt=replace(filing.receipt, received_at=datetime.max.replace(tzinfo=UTC)),
    )
    with pytest.raises(AnnualQualityError):
        build_annual_quality(_request(filing=filing))


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_explicit_decimal_context_ignores_mutable_default_and_ambient_settings(rounding) -> None:
    request = _request()
    baseline_digest = build_annual_quality(request).evidence_hash
    original = DefaultContext.copy()
    try:
        DefaultContext.prec = 2
        DefaultContext.rounding = rounding
        DefaultContext.Emin = -2
        DefaultContext.Emax = 2
        DefaultContext.capitals = 0
        DefaultContext.clamp = 1
        for signal in DefaultContext.traps:
            DefaultContext.traps[signal] = True
            DefaultContext.flags[signal] = True
        with localcontext() as ambient:
            ambient.prec = 3
            ambient.rounding = rounding
            value = build_annual_quality(request)
            digest = value.evidence_hash
            assert ambient.prec == 3 and ambient.rounding == rounding
        assert isinstance(value, DefinedAnnualQuality)
        assert value.roe == Decimal("0.2")
        assert value.debt_to_equity == Decimal(
            "0.33333333333333333333333333333333333333333333333333"
        )
        assert len(digest) == 64 and digest == baseline_digest
    finally:
        for key in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(DefaultContext, key, getattr(original, key))
        DefaultContext.flags = original.flags.copy()
        DefaultContext.traps = original.traps.copy()
