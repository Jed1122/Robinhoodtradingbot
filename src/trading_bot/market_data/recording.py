"""Canonical content addressing and JSONL market-data recording."""

import dataclasses
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from trading_bot.domain import DataHash, canonical_decimal_text


def _canonical(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _canonical(dataclasses.asdict(value))
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
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
