"""Lazy merge must preserve native identity, duplicates and stable tie order."""

from dataclasses import replace

import pytest

from tests.unit.market_data.test_etf_replay_adapter import api, quote
from tests.unit.market_data.test_etf_replay_adapter import inputs as inputs
from trading_bot.market_data.etf_quote_catalog_models import (
    CatalogQuoteOccurrence,
    QuoteCaptureLocation,
)


def merge(baseline, records):
    function = getattr(api(), "iter_native_etf_events", None)
    assert function is not None, "lazy native projection is missing"
    occurrences = (
        CatalogQuoteOccurrence(QuoteCaptureLocation("capture", "b" * 64), "c" * 64, record)
        for record in records
    )
    return function(baseline, occurrences)


def baseline(inputs):
    function = getattr(api(), "native_etf_baseline", None)
    assert function is not None, "quote-free incremental baseline is missing"
    return function(
        inputs["bars"], inputs["calendar"], inputs["distributions"],
        catalog_hash=inputs["quote_provenance_hash"],
    )


def test_lazy_merge_matches_legacy_including_equal_time_duplicates(inputs):
    records = (quote(), quote(), quote(row_index=1))
    base = baseline(inputs)
    legacy = api().native_etf_dataset(**(inputs | {"quotes": records}))
    actual = tuple(merge(base, records))
    assert actual == legacy.events
    assert len([item for item in actual if item.kind == "quote"]) == 3


def test_projection_is_lazy_and_source_failure_preserved(inputs):
    base = baseline(inputs)

    def records():
        yield quote()
        raise OSError("not a complete input stream")

    projected = merge(base, records())
    first = next(projected)
    assert first.kind != "quote"
    with pytest.raises(ValueError, match="etf_replay_adapter_invalid"):
        tuple(projected)


def test_regressing_quotes_deny(inputs):
    base = baseline(inputs)
    with pytest.raises(ValueError):
        tuple(merge(base, (quote(), quote("2016-03-18T13:30:00Z"))))


def test_already_projected_quote_baseline_denies(inputs):
    baseline = api().native_etf_dataset(**(inputs | {"quotes": (quote(),)}))
    with pytest.raises(ValueError):
        tuple(merge(replace(baseline), (quote(),)))


def test_null_quote_delivery_is_not_normal_exhaustion(inputs):
    base = baseline(inputs)
    function = api().iter_native_etf_events
    with pytest.raises(ValueError):
        tuple(function(base, iter((None,))))
