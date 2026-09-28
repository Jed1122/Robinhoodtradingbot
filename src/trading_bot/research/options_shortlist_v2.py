"""Reverified imported-data shortlist. No saved verification result grants authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Context, localcontext
from pathlib import Path
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import ConfigHash, DataHash
from trading_bot.domain.decimal_utils import MAX_CANONICAL_DECIMAL_TEXT_LENGTH
from trading_bot.domain.options import OptionKind
from trading_bot.market_data import options_source_rules
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.databento_bar_store import verify_bar_stage
from trading_bot.market_data.options_definition_inputs import (
    REASONS as DEFINITION_REASONS,
)
from trading_bot.market_data.options_definition_inputs import (
    ContractReferenceInput,
    assemble_definition_inputs,
)
from trading_bot.market_data.options_records import select_chain
from trading_bot.market_data.options_session_inputs import (
    REASONS as SESSION_REASONS,
)
from trading_bot.market_data.options_session_inputs import (
    SessionReferenceInput,
    _ns,
    assemble_session_inputs,
)
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceEvidenceBundle,
    SourceVerification,
    VerificationContext,
    check,
    hashes,
)
from trading_bot.market_data.options_source_verify import verify_source_bundle
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_shortlist import _contract_identities, _eligible, _rank
from trading_bot.research.options_shortlist_models import (
    REASONS as POLICY_REASONS,
)
from trading_bot.research.options_shortlist_models import (
    VERSION,
    OptionsShortlistCandidate,
)

REASONS = POLICY_REASONS | SESSION_REASONS | DEFINITION_REASONS
_CODE_FILES = (
    "clock.py",
    "domain/decimal_utils.py",
    "domain/market.py",
    "market_data/databento_batch.py",
    "market_data/options_parquet.py",
    "market_data/options_source_models.py",
    "market_data/options_source_rules.py",
    "market_data/options_source_wire.py",
    "market_data/options_source_verify.py",
    "market_data/databento_native_io.py",
    "market_data/databento_metadata.py",
    "market_data/databento_bars.py",
    "market_data/databento_bar_models.py",
    "market_data/databento_bar_store.py",
    "market_data/databento_bar_wire.py",
    "market_data/databento_native_rows.py",
    "market_data/databento_definitions.py",
    "market_data/databento_stage.py",
    "market_data/databento_stage_schema.py",
    "market_data/options_session_inputs.py",
    "market_data/options_definition_inputs.py",
    "market_data/options_records.py",
    "market_data/options_data_codec.py",
    "research/options_shortlist.py",
    "research/options_shortlist_models.py",
    "research/options_shortlist_wire.py",
    "research/options_shortlist_v2.py",
    "research/options_shortlist_v2_wire.py",
    "domain/options.py",
    "domain/options_serialization.py",
)


def verified_shortlist_code_hash() -> DataHash:
    root = Path(__file__).resolve().parents[1]
    return content_hash(
        {
            "source_verifier": options_source_rules.source_code_hash(),
            "files": tuple(
                (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
                for name in _CODE_FILES
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class VerifiedShortlistInput:
    bundle: SourceEvidenceBundle
    bars: PrivateArtifactRef
    definitions: PrivateArtifactRef
    session: SessionReferenceInput
    contracts: ContractReferenceInput
    config_hash: ConfigHash

    def __post_init__(self) -> None:
        for value, kind in (
            (self.bundle, SourceEvidenceBundle),
            (self.bars, PrivateArtifactRef),
            (self.definitions, PrivateArtifactRef),
            (self.session, SessionReferenceInput),
            (self.contracts, ContractReferenceInput),
        ):
            check(type(value) is kind)
        hashes((DataHash(self.config_hash),))

    @property
    def record_count(self) -> int:
        return (
            len(self.bundle.claims)
            + len(self.bundle.references)
            + len(self.bundle.manifests)
            + len(self.contracts.references)
            + len(self.session.calendar_days)
            + len(self.session.actions)
        )


@dataclass(frozen=True, slots=True)
class VerifiedShortlistResult:
    status: Literal["selected", "no_candidate"]
    candidates: tuple[OptionsShortlistCandidate, ...]
    reasons: tuple[str, ...]
    decision_hash: DataHash
    input_hash: DataHash
    verification: SourceVerification
    session_id: str
    as_of: datetime
    config_hash: ConfigHash
    code_hash: DataHash
    input_record_count: int
    schema: Literal["options-shortlist-result-v2"] = field(
        default="options-shortlist-result-v2", init=False
    )
    version: Literal["spy-prior-close-atm-30d-v1"] = field(
        default="spy-prior-close-atm-30d-v1", init=False
    )
    source_kind: Literal["imported"] = field(default="imported", init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        check(type(self.status) is str and self.status in {"selected", "no_candidate"})
        check(type(self.session_id) is str and 0 < len(self.session_id) <= 1024)
        require_utc(self.as_of)
        for digest in (
            self.decision_hash,
            self.input_hash,
            DataHash(self.config_hash),
            self.code_hash,
        ):
            hashes((digest,))
        check(type(self.verification) is SourceVerification)
        check(type(self.input_record_count) is int and self.input_record_count >= 0)
        check(
            type(self.candidates) is tuple
            and all(type(c) is OptionsShortlistCandidate for c in self.candidates)
        )
        check(
            type(self.reasons) is tuple
            and all(type(r) is str and r in REASONS for r in self.reasons)
        )
        check(self.reasons == tuple(sorted(set(self.reasons))))
        if self.status == "selected":
            check(
                not self.reasons
                and tuple(c.kind for c in self.candidates) == (OptionKind.CALL, OptionKind.PUT)
            )
            check(len({c.expiration for c in self.candidates}) == 1)
            check(
                all(
                    c.session_id == self.session_id and c.as_of == self.as_of
                    for c in self.candidates
                )
            )
        else:
            check(not self.candidates and bool(self.reasons))


def _without_paths(value: object) -> object:
    if type(value) is dict:
        return {key: _without_paths(item) for key, item in value.items() if key != "path"}
    if type(value) is list:
        return [_without_paths(item) for item in value]
    return value


def select_verified_shortlist(
    request: VerifiedShortlistInput, *, loaded: LoadedConfig, repository_root: Path
) -> VerifiedShortlistResult:
    from trading_bot.research.options_shortlist_v2_wire import encode_verified_shortlist_input

    check(type(request) is VerifiedShortlistInput)
    native_limits(loaded)
    canonical, config_hash = hash_loaded_config(loaded.config, loaded.safety_envelope)
    check(
        canonical == loaded.canonical_json
        and config_hash == loaded.config_hash == request.config_hash
    )
    settings = loaded.config.options.research_shortlist
    check(request.record_count <= settings.max_input_records)
    encoded = encode_verified_shortlist_input(request)
    check(
        len(encoded)
        + sum(item.byte_count for item in request.bundle.references + request.bundle.manifests)
        <= settings.max_input_bytes
    )
    as_of = request.session.current.opens_at
    prior = request.session.prior
    context = VerificationContext(
        _ns(as_of),
        _ns(prior.opens_at) if prior else _ns(as_of) - 1,
        _ns(as_of),
        config_hash,
        options_source_rules.source_code_hash(),
        options_source_rules.reviewed_rulebook_hash(),
    )
    verification = verify_source_bundle(
        request.bundle, context=context, loaded=loaded, repository_root=repository_root
    )
    code_hash = verified_shortlist_code_hash()
    input_hash = content_hash(_without_paths(json.loads(encoded)))
    count = request.record_count
    candidates: tuple[OptionsShortlistCandidate, ...] = ()
    reasons: set[str] = set()
    evidence: dict[str, object] = {
        "current": request.session.current,
        "prior": prior,
        "calendar": request.session.calendar_days,
        "actions": request.session.actions,
        "source_code": context.code_hash,
        "rulebook": context.rulebook_hash,
    }
    if not settings.enabled:
        reasons.add("shortlist_disabled")
    elif not {"calendar", "bar_publication", "actions", "definition_state", "contract_terms"} <= {
        finding.role for finding in verification.findings if finding.status == "verified"
    }:
        reasons.add("source_evidence_unverified")
    else:
        try:
            check(
                request.bars in request.bundle.manifests
                and request.definitions in request.bundle.manifests
            )
            check(
                request.bars.path.stem == request.bars.sha256
                and request.definitions.path.stem == request.definitions.sha256
            )
            check(
                all(
                    ref in request.bundle.manifests or ref in request.bundle.references
                    for ref in request.contracts.references
                )
            )
            dataset = verify_bar_stage(
                request.bars.path, loaded=loaded, repository_root=repository_root
            )
            session = assemble_session_inputs(
                dataset,
                request.session,
                verification=verification,
                loaded=loaded,
                repository_root=repository_root,
            )
            definitions = assemble_definition_inputs(
                request.definitions.path,
                request.contracts,
                verification=verification,
                as_of=as_of,
                loaded=loaded,
                repository_root=repository_root,
            )
            reasons.update(session.reasons + definitions.reasons)
            count += (
                session.included_count
                + session.excluded_count
                + session.rejected_count
                + session.duplicate_count
                + len(definitions.records)
            )
            if count > settings.max_input_records:
                reasons.add("source_limit_exceeded")
            if not reasons:
                if session.bar is None:
                    raise ValueError("source_integrity_invalid")
                check(
                    session.bar is not None
                    and session.available_at is not None
                    and session.available_at <= as_of
                )
                check(definitions.visible_hash == content_hash(definitions.records))
                check(
                    all(
                        r.source == "OPRA.PILLAR"
                        and r.source_kind == "imported"
                        and r.available_at <= as_of
                        for r in definitions.records
                    )
                )
                with localcontext(Context(prec=MAX_CANONICAL_DECIMAL_TEXT_LENGTH * 2)):
                    contracts = select_chain(
                        definitions.records, source="OPRA.PILLAR", underlying="SPY", as_of=as_of
                    )
                    _contract_identities(contracts)
                    selected = _rank(
                        tuple(c for c in contracts if _eligible(c, as_of)),
                        session.bar.close,
                        request.session.current.trading_date,
                        settings,
                    )
                evidence["close"] = session.bar
                evidence["definitions"] = definitions.visible_hash
                if not selected:
                    reasons.add("no_common_eligible_expiry")
                else:
                    close_hash = content_hash(session.bar)
                    role_hashes = {
                        "prior_close": close_hash,
                        "chain": definitions.visible_hash,
                        "calendar": content_hash(request.session.calendar_days),
                        "actions": content_hash(request.session.actions),
                    }
                    candidates = tuple(
                        OptionsShortlistCandidate(
                            request.session.current.session_id,
                            as_of,
                            c.kind,
                            c.contract_id,
                            c.standardized_id,
                            c.expiration,
                            c.strike,
                            close_hash,
                            tuple(sorted({**role_hashes, "contract": content_hash(c)}.items())),
                        )
                        for c in selected
                    )
        except Exception:
            candidates = ()
            reasons = {"source_integrity_invalid"}
    reason_tuple = tuple(sorted(reasons))
    decision_hash = content_hash(
        {
            "schema": "options-shortlist-result-v2",
            "version": VERSION,
            "config_hash": config_hash,
            "code_hash": code_hash,
            "policy": settings.model_dump(),
            "evidence": evidence,
            "candidates": candidates,
            "reasons": reason_tuple,
        }
    )
    return VerifiedShortlistResult(
        "selected" if candidates else "no_candidate",
        candidates,
        reason_tuple,
        decision_hash,
        input_hash,
        verification,
        request.session.current.session_id,
        as_of,
        config_hash,
        code_hash,
        count,
    )
