"""Closed native-staging manifest contracts; integrity is never economic eligibility."""

from datetime import date
from typing import cast

from trading_bot.market_data.bundle_codec import _array, _mapping, _string
from trading_bot.market_data.databento_batch import DefinitionRequest, _conditions, require
from trading_bot.market_data.recording import canonical_json

_FALSE_FLAGS = {
    "complete_chains_verified",
    "historical_availability_verified",
    "contract_enrichment_complete",
    "economic_evidence",
    "production_eligible",
}
_COUNTS = {
    "record_count",
    "unique_raw_symbols",
    "min_ts_recv",
    "max_ts_recv",
    "receive_timestamp_regressions",
    "outside_requested_receive_window_rows",
    "unknown_premium_multiplier_rows",
}
_HISTOGRAMS = {
    "receive_date_counts",
    "instrument_class_counts",
    "security_update_action_counts",
}


def _integer(value: object, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    require(type(value) is int and minimum <= value <= maximum)
    return cast(int, value)


def _hash(value: object) -> str:
    text = _string(value)
    require(len(text) == 64 and all(char in "0123456789abcdef" for char in text))
    return text


def validate_nested(manifest: dict[str, object]) -> dict[str, object]:
    profile = _mapping(
        manifest["validation"],
        _FALSE_FLAGS
        | _COUNTS
        | _HISTOGRAMS
        | {
            "schema",
            "dbn_version",
            "decoder",
            "compression_decoder",
            "raw_sha256",
            "metadata",
            "request",
            "record_bytes_sha256",
            "record_validation_complete",
        },
    )
    require(profile["schema"] == "databento-definitions-validation-v1")
    require(_integer(profile["dbn_version"], minimum=1, maximum=3) in (1, 2, 3))
    require(profile["decoder"] == "databento-dbn==0.69.0")
    require(profile["compression_decoder"] == "zstandard==0.25.0")
    require(profile["record_validation_complete"] is True)
    require(all(profile[key] is False for key in _FALSE_FLAGS))
    counts = {key: _integer(profile[key]) for key in _COUNTS}
    count = counts["record_count"]
    require(count > 0 and 0 < counts["unique_raw_symbols"] <= count)
    require(0 < counts["min_ts_recv"] <= counts["max_ts_recv"])
    require(counts["unknown_premium_multiplier_rows"] == count)
    require(counts["receive_timestamp_regressions"] < count)
    require(counts["outside_requested_receive_window_rows"] <= count)
    raw_hash = _hash(profile["raw_sha256"])
    _hash(profile["record_bytes_sha256"])
    query = _mapping(profile["request"], set(DefinitionRequest("SPY.OPT", 1, 2).query()))
    symbols = _array(query["symbols"])
    require(len(symbols) == 1)
    expected = DefinitionRequest(
        _string(symbols[0]), _integer(query["start"]), _integer(query["end"])
    )
    require(canonical_json(query) == canonical_json(expected.query()))
    metadata = _mapping(
        profile["metadata"],
        {
            "byte_count",
            "sha256",
            "mapping_count",
            "mapping_interval_count",
            "partial_symbol_count",
            "mapping_resolution_verified",
        },
    )
    require(metadata["mapping_resolution_verified"] is False)
    _hash(metadata["sha256"])
    _integer(metadata["byte_count"], minimum=128)
    for key in ("mapping_count", "mapping_interval_count", "partial_symbol_count"):
        _integer(metadata[key])
    for key in _HISTOGRAMS:
        histogram = profile[key]
        require(type(histogram) is dict and bool(histogram))
        total = 0
        for label, value in cast(dict[str, object], histogram).items():
            _string(label)
            if key == "receive_date_counts":
                require(date.fromisoformat(label).isoformat() == label)
            else:
                require(len(label) == 1 and label.isascii())
            total += _integer(value, minimum=1)
        require(total == count)
    files = _array(manifest["input_files"])
    require(len(files) == 4)
    names = set()
    for item in files:
        row = _mapping(item, {"name", "size", "sha256"})
        name = _string(row["name"])
        require(name not in names)
        names.add(name)
        _integer(row["size"], minimum=1)
        digest = _hash(row["sha256"])
        if name not in {"manifest.json", "metadata.json", "condition.json"}:
            require(
                name.endswith(".definition.dbn.zst")
                and "/" not in name
                and "\\" not in name
                and ".." not in name
                and digest == raw_hash
            )
    require({"manifest.json", "metadata.json", "condition.json"} < names)
    conditions = []
    for item in _array(manifest["conditions"]):
        pair = _array(item)
        require(len(pair) == 2)
        conditions.append({"date": pair[0], "condition": pair[1], "last_modified_date": None})
    _conditions(conditions, expected)
    return profile
