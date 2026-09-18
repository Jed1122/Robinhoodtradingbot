"""Point-in-time options provenance, using only synthetic records."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.domain.test_options import NOW, contract, quote
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.market_data.options_records import (
    ChainSnapshot,
    OptionsDataRecord,
    point_in_time,
    select_chain,
)


def record(original: object, **changes: object) -> OptionsDataRecord:
    return replace(
        OptionsDataRecord("fixture", "synthetic", "f" * 64, NOW, NOW, original), **changes
    )  # type: ignore[arg-type]


def test_available_time_not_event_time_controls_visibility() -> None:
    early = record(quote())
    late = replace(early, available_at=NOW + timedelta(seconds=10))
    assert point_in_time((late,), as_of=NOW) == ()
    assert point_in_time((early,), as_of=NOW) == (early,)
    assert point_in_time((late,), as_of=late.available_at) == (late,)


def test_later_event_revision_and_conflicts_do_not_depend_on_input_order() -> None:
    first = record(quote())
    revision = replace(first, raw_hash="e" * 64, available_at=NOW + timedelta(seconds=1))
    assert point_in_time((revision, first), as_of=revision.available_at) == (revision,)
    assert point_in_time((first, revision), as_of=revision.available_at) == (revision,)
    conflicting = replace(first, raw_hash="b" * 64)
    with pytest.raises(DomainValidationError, match="ambiguous"):
        point_in_time((first, conflicting), as_of=NOW)
    assert point_in_time((first, first), as_of=NOW) == (first,)


def test_sources_are_not_silently_blended() -> None:
    first = record(quote())
    second = replace(first, source="another-provider")
    assert len(point_in_time((first, second), as_of=NOW)) == 2


def test_chain_requires_known_members_and_cannot_look_forward() -> None:
    c = contract(available_at=NOW)
    chain = record(ChainSnapshot("SYN", (c.contract_id,)))
    definition = record(c)
    assert select_chain((chain, definition), source="fixture", underlying="SYN", as_of=NOW) == (c,)
    future = replace(definition, available_at=NOW + timedelta(seconds=1))
    with pytest.raises(DomainValidationError, match="incomplete"):
        select_chain((chain, future), source="fixture", underlying="SYN", as_of=NOW)
    wrong = record(contract(underlying="OTHER", deliverable_symbol="OTHER", available_at=NOW))
    with pytest.raises(DomainValidationError, match="inconsistent"):
        select_chain((chain, wrong), source="fixture", underlying="SYN", as_of=NOW)
    assert select_chain((definition,), source="fixture", underlying="SYN", as_of=NOW) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"raw_hash": "bad"},
        {"source_kind": "historical_verified"},
        {"source": ""},
        {"available_at": NOW - timedelta(seconds=1)},
        {"event_at": NOW + timedelta(seconds=1)},
        {"value": {}},
        {"event_at": NOW - timedelta(seconds=1)},
    ],
)
def test_invalid_or_inconsistent_provenance_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises((DomainValidationError, ValueError)):
        record(quote(), **changes)


@pytest.mark.parametrize("ids", [(), ("one", "one"), ("",), ["one"]])
def test_chain_members_are_explicit_distinct_bounded_tuples(ids: object) -> None:
    with pytest.raises(DomainValidationError):
        ChainSnapshot("SYN", ids)  # type: ignore[arg-type]


def test_identity_is_content_addressed_without_claiming_authenticity() -> None:
    value = record(quote())
    assert value.record_hash == record(quote()).record_hash
    assert value.record_hash != replace(value, source_kind="imported").record_hash
    assert value.kind == "option_quote"
    assert value.entity_id == value.value.contract_id  # type: ignore[union-attr]
