"""Literal legacy preimages and unusual deepcopy/denial boundaries."""

from collections import namedtuple
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal
from enum import Enum

import pytest

from trading_bot.market_data.recording import canonical_json, content_hash


@dataclass(frozen=True, slots=True)
class Record:
    value: object


class Label(Enum):
    ONE = "one"


def test_literal_nested_preimage_and_hash_are_unchanged():
    record = Record((Record(Decimal("1.200")), [None, True, 7, "café"]))
    assert canonical_json(record) == '{"value":[{"value":"1.2"},[null,true,7,"caf\\u00e9"]]}'
    assert (
        content_hash(record) == "f6bd7603599180c82aa9c4ebaa60064a2eb7e773dea3b1060ae9cb1694b2668f"
    )


def test_literal_time_enum_and_decimal_preimages_are_unchanged():
    value = Record(
        {
            "z": Label.ONE,
            "a": (
                date(2020, 1, 2),
                datetime(2020, 1, 2, tzinfo=UTC),
                timedelta(days=-1, seconds=2),
                Decimal("-0"),
            ),
        }
    )
    assert canonical_json(value) == (
        '{"value":{"a":["2020-01-02","2020-01-02T00:00:00.000000Z",'
        '{"days":-1,"microseconds":0,"seconds":2},"0"],"z":"one"}}'
    )


@pytest.mark.parametrize("key", (Record(1), (Record(1),), namedtuple("Key", "part")(Record(1))))
def test_nested_dataclass_mapping_keys_keep_legacy_unhashable_denial(key):
    with pytest.raises(TypeError, match="unhashable"):
        canonical_json(Record({key: 2}))


class Converted:
    def __deepcopy__(self, memo):
        return 7


class Refusing:
    def __deepcopy__(self, memo):
        raise RuntimeError("copy-refused")


def test_external_deepcopy_conversion_and_refusal_are_preserved():
    assert canonical_json(Record(Converted())) == '{"value":7}'
    with pytest.raises(RuntimeError, match="copy-refused"):
        canonical_json(Record(Refusing()))


class TrimmingList(list):
    def __init__(self, values):
        super().__init__(tuple(values)[:1])


def test_container_subclass_reconstruction_is_not_bypassed():
    value = TrimmingList([1, 2])
    value.append(3)
    assert canonical_json(Record(value)) == '{"value":[1]}'


class ConvertedDecimal(Decimal):
    def __deepcopy__(self, memo):
        return Decimal("2.5")


def test_decimal_subclass_copy_conversion_keeps_legacy_acceptance():
    assert canonical_json(Record(ConvertedDecimal("1.5"))) == '{"value":"2.5"}'


class ChangingZone(tzinfo):
    def utcoffset(self, value):
        return timedelta(hours=1)

    def dst(self, value):
        return timedelta(0)

    def __deepcopy__(self, memo):
        from datetime import timezone

        return timezone(timedelta(hours=2))


def test_exact_datetime_with_custom_zone_keeps_deepcopy_offset():
    value = Record(datetime(2020, 1, 2, tzinfo=ChangingZone()))
    assert canonical_json(value) == '{"value":"2020-01-02T00:00:00.000000+02:00"}'


def test_enum_member_deepcopy_override_keeps_legacy_value(monkeypatch):
    monkeypatch.setattr(Label.ONE, "__deepcopy__", lambda memo: "copied", raising=False)
    assert canonical_json(Record(Label.ONE)) == '{"value":"copied"}'


def test_sorted_field_validation_precedence_is_preserved():
    @dataclass(frozen=True, slots=True)
    class TwoFields:
        z: object
        a: object

    with pytest.raises(TypeError):
        canonical_json(TwoFields(Decimal("NaN"), 1.5))


@pytest.mark.parametrize("metadata", ["missing", "none", "custom"])
def test_dataclass_metadata_does_not_change_legacy_encoding(metadata):
    @dataclass(frozen=True, slots=True)
    class LocalRecord:
        value: object

    class RefusingMetadata:
        @property
        def frozen(self):
            raise RuntimeError("metadata-read")

    if metadata == "missing":
        delattr(LocalRecord, "__dataclass_params__")
    else:
        LocalRecord.__dataclass_params__ = None if metadata == "none" else RefusingMetadata()
    assert canonical_json(LocalRecord(7)) == '{"value":7}'


def test_dynamic_dataclass_field_is_read_once_even_with_deepcopy_leaf():
    reads = []

    class Copied:
        def __deepcopy__(self, memo):
            return "copied"

    @dataclass(frozen=True, slots=True)
    class DynamicRecord:
        first: object = field(init=False)
        second: object

        def __getattr__(self, name):
            if name == "first":
                reads.append(name)
                return len(reads)
            raise AttributeError(name)

    assert canonical_json(DynamicRecord(Copied())) == '{"first":1,"second":"copied"}'
    assert reads == ["first"]
