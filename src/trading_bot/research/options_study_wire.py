"""Closed study-v1 serialization. Unknown fields and changed hash preimages deny."""

from dataclasses import asdict, fields
from decimal import Decimal

from trading_bot.config import LoadedConfig
from trading_bot.domain import ConfigHash
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping, _string, _time
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.options_data_codec import _contract, _session
from trading_bot.market_data.options_source_models import SourceEvidenceError, check
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.options_acquisition_models import CoverageSemantics
from trading_bot.research.options_study_models import OptionsStudySpec, StudyFold


def encode_study_spec(spec: OptionsStudySpec) -> bytes:
    check(type(spec) is OptionsStudySpec)
    return canonical_json({**asdict(spec), "study_hash": spec.study_hash}).encode()


def decode_study_spec(body: bytes, *, loaded: LoadedConfig) -> OptionsStudySpec:
    try:
        row = _mapping(
            _json(
                body,
                max_bytes=loaded.config.options.research_shortlist.max_input_bytes,
                limits=bounds(loaded),
            ),
            {*(f.name for f in fields(OptionsStudySpec)), "study_hash"},
        )
        check(row.pop("schema") == "options-study-v1")
        digest = _digest(row.pop("study_hash"))
        for name in ("registered_at", "selection_frozen_at"):
            row[name] = _time(row[name])
        if row["outcome_access_started_at"] is not None:
            row["outcome_access_started_at"] = _time(row["outcome_access_started_at"])
        row["decision_sessions"] = tuple(_session(s) for s in _array(row["decision_sessions"]))
        row["initialization_sessions"] = tuple(
            _session(s) for s in _array(row["initialization_sessions"])
        )
        row["contracts"] = tuple(_contract(c) for c in _array(row["contracts"]))
        row["coverage_semantics"] = tuple(
            CoverageSemantics(**_mapping(s, {f.name for f in fields(CoverageSemantics)}))  # type: ignore[arg-type]
            for s in _array(row["coverage_semantics"])
        )
        row["source_hashes"] = tuple(_digest(v) for v in _array(row["source_hashes"]))
        row["config_hash"] = ConfigHash(_digest(row["config_hash"]))
        row["scenario_hashes"] = tuple(
            tuple(_string(v) for v in _array(p)) for p in _array(row["scenario_hashes"])
        )
        row["capital_tiers"] = tuple(Decimal(_string(v)) for v in _array(row["capital_tiers"]))
        for name in ("final_session_ids", "rejection_criteria"):
            row[name] = tuple(_string(v) for v in _array(row[name]))
        row["block_lengths_ns"] = tuple(_array(row["block_lengths_ns"]))
        folds = []
        for item in _array(row["folds"]):
            fold = _mapping(item, {f.name for f in fields(StudyFold)})
            for name in ("train_session_ids", "test_session_ids"):
                fold[name] = tuple(_string(v) for v in _array(fold[name]))
            folds.append(StudyFold(**fold))  # type: ignore[arg-type]
        row["folds"] = tuple(folds)
        result = OptionsStudySpec(**row)  # type: ignore[arg-type]
        check(result.study_hash == digest)
        return result
    except Exception:
        raise SourceEvidenceError() from None
