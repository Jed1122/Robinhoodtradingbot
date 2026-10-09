"""Canonical content addressing and JSONL market-data recording."""

import dataclasses
import hashlib
import inspect
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum, EnumType
from pathlib import Path
from types import MemberDescriptorType

from trading_bot.domain import DataHash, canonical_decimal_text


class _LegacyCanonicalRequired(Exception):
    """An unusual graph must retain the original asdict/deepcopy semantics."""


def _plain_record(value: object) -> object:
    """Flatten only proven plain immutable records, never arbitrary copy hooks.

    No canonical conversion/validation occurs until the complete attempt has
    succeeded. Unsupported graphs use the original asdict on the original
    object, preserving sorting, subclass reconstruction and deepcopy behavior.
    Class metadata is scoped to this one attempt; it is not retained evidence.
    """
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        raise TypeError("plain record requires a dataclass instance")
    fields: dict[type, tuple[str, ...]] = {}

    def flatten(item: object) -> object:
        cls = type(item)
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            if cls not in fields:
                if (
                    type(cls) is not type
                    or cls.__getattribute__ is not object.__getattribute__
                    or not inspect.getattr_static(cls, "__dataclass_params__").frozen
                ):
                    raise _LegacyCanonicalRequired
                names = tuple(field.name for field in dataclasses.fields(item))
                if any(
                    type(inspect.getattr_static(cls, name)) is not MemberDescriptorType
                    for name in names
                ):
                    raise _LegacyCanonicalRequired
                fields[cls] = names
            return {name: flatten(getattr(item, name)) for name in fields[cls]}
        if cls in (str, int, bool, type(None), Decimal, date, timedelta):
            return item
        if isinstance(item, datetime) and cls is datetime:
            if item.tzinfo is None or item.tzinfo is UTC:
                return item
            raise _LegacyCanonicalRequired
        if isinstance(item, Enum):
            if (
                type(cls) is EnumType
                and cls.__getattribute__ is object.__getattribute__
                and inspect.getattr_static(item, "__deepcopy__") is Enum.__deepcopy__
                and inspect.getattr_static(item, "value") is inspect.getattr_static(Enum, "value")
            ):
                return item
            raise _LegacyCanonicalRequired
        if isinstance(item, (tuple, list)) and cls in (tuple, list):
            return [flatten(element) for element in item]
        if isinstance(item, dict) and cls is dict and all(type(key) is str for key in item):
            return {key: flatten(element) for key, element in item.items()}
        raise _LegacyCanonicalRequired

    try:
        return flatten(value)
    except _LegacyCanonicalRequired:
        return dataclasses.asdict(value)


def _canonical(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _canonical(_plain_record(value))
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, timedelta):
        return {
            "days": value.days,
            "microseconds": value.microseconds,
            "seconds": value.seconds,
        }
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda p: str(p[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if type(value) in {str, int, bool} or value is None:
        return value
    raise TypeError("value cannot be encoded as canonical research data")


def canonical_json(value: object) -> str:
    return json.dumps(_canonical(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def content_hash(value: object) -> DataHash:
    return DataHash(hashlib.sha256(canonical_json(value).encode()).hexdigest())


@dataclasses.dataclass(frozen=True, slots=True)
class ResearchDataManifest:
    raw_hashes: tuple[DataHash, ...]
    cleaned_hashes: tuple[DataHash, ...]
    corporate_action_coverage: str
    point_in_time_universe: bool
    survivorship_limitations: tuple[str, ...]
    licensing_limitations: tuple[str, ...]
    known_gaps: tuple[str, ...]
    manifest_hash: DataHash

    @classmethod
    def create(
        cls,
        *,
        raw_hashes: tuple[DataHash, ...],
        cleaned_hashes: tuple[DataHash, ...],
        corporate_action_coverage: str,
        point_in_time_universe: bool,
        survivorship_limitations: tuple[str, ...] = (),
        licensing_limitations: tuple[str, ...] = (),
        known_gaps: tuple[str, ...] = (),
    ) -> "ResearchDataManifest":
        values = {
            "cleaned_hashes": cleaned_hashes,
            "corporate_action_coverage": corporate_action_coverage,
            "known_gaps": known_gaps,
            "licensing_limitations": licensing_limitations,
            "point_in_time_universe": point_in_time_universe,
            "raw_hashes": raw_hashes,
            "survivorship_limitations": survivorship_limitations,
        }
        return cls(
            raw_hashes=raw_hashes,
            cleaned_hashes=cleaned_hashes,
            corporate_action_coverage=corporate_action_coverage,
            point_in_time_universe=point_in_time_universe,
            survivorship_limitations=survivorship_limitations,
            licensing_limitations=licensing_limitations,
            known_gaps=known_gaps,
            manifest_hash=content_hash(values),
        )


def write_jsonl(path: str | Path, records: tuple[object, ...]) -> tuple[DataHash, ...]:
    encoded = tuple(canonical_json(record) for record in records)
    Path(path).write_text("".join(f"{line}\n" for line in encoded), encoding="utf-8")
    return tuple(content_hash(record) for record in records)


__all__ = ["ResearchDataManifest", "canonical_json", "content_hash", "write_jsonl"]
