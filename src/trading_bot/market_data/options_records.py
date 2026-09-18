"""Versioned, provider-neutral options provenance; no acquisition or entitlement claim."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_nonempty,
    _require_sha256_hex,
)
from trading_bot.domain.market import CorporateAction, Quote
from trading_bot.domain.options import OptionContract, OptionQuote, OptionSession
from trading_bot.market_data.recording import content_hash

SCHEMA = "options-data-record-v1"


@dataclass(frozen=True, slots=True)
class ChainSnapshot:
    """Complete membership claimed by one source at the enclosing record's time."""

    underlying: str
    contract_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.underlying, "underlying")
        if type(self.contract_ids) is not tuple or not 1 <= len(self.contract_ids) <= 10000:
            raise DomainValidationError("chain requires bounded explicit membership")
        for item in self.contract_ids:
            _require_nonempty(item, "contract ID")
        if len(set(self.contract_ids)) != len(self.contract_ids):
            raise DomainValidationError("chain contains duplicate contracts")


type OptionsDataValue = (
    ChainSnapshot | OptionContract | OptionQuote | OptionSession | Quote | CorporateAction
)
type OptionsDataKind = Literal[
    "chain", "contract", "option_quote", "session", "underlying_quote", "corporate_action"
]


@dataclass(frozen=True, slots=True)
class OptionsDataRecord:
    source: str
    source_kind: Literal["synthetic", "imported"]
    raw_hash: str
    event_at: datetime
    available_at: datetime
    value: OptionsDataValue

    def __post_init__(self) -> None:
        _require_nonempty(self.source, "source")
        if type(self.source_kind) is not str or self.source_kind not in {"synthetic", "imported"}:
            raise DomainValidationError("unsupported options data origin")
        _require_sha256_hex(self.raw_hash, "raw source hash")
        require_utc(self.event_at)
        require_utc(self.available_at)
        if self.event_at > self.available_at:
            raise DomainValidationError("record available before event")
        value = self.value
        if type(value) not in (
            ChainSnapshot,
            OptionContract,
            OptionQuote,
            OptionSession,
            Quote,
            CorporateAction,
        ):
            raise DomainValidationError("unsupported options record value")
        if isinstance(value, OptionQuote) and (
            value.event_at != self.event_at
            or max(value.received_at, value.underlying_event_at) > self.available_at
        ):
            raise DomainValidationError("inconsistent option quote provenance")
        if isinstance(value, Quote) and value.observed_at != self.event_at:
            raise DomainValidationError("inconsistent underlying quote provenance")
        if isinstance(value, OptionContract) and value.available_at > self.available_at:
            raise DomainValidationError("contract definition is not available")
        if isinstance(value, CorporateAction) and value.announced_at > self.available_at:
            raise DomainValidationError("corporate action is not yet announced")

    @property
    def kind(self) -> OptionsDataKind:
        kinds: dict[type[object], OptionsDataKind] = {
            ChainSnapshot: "chain",
            OptionContract: "contract",
            OptionQuote: "option_quote",
            OptionSession: "session",
            Quote: "underlying_quote",
            CorporateAction: "corporate_action",
        }
        return kinds[type(self.value)]

    @property
    def entity_id(self) -> str:
        value = self.value
        if isinstance(value, ChainSnapshot):
            return value.underlying
        if isinstance(value, (OptionContract, OptionQuote)):
            return value.contract_id
        if isinstance(value, OptionSession):
            return value.session_id
        if isinstance(value, CorporateAction):
            return f"{value.instrument_id}:{value.action_type}:{value.effective_date.isoformat()}"
        return str(value.instrument_id)

    @property
    def record_hash(self) -> str:
        return str(content_hash({"schema": SCHEMA, "kind": self.kind, "record": self}))


def point_in_time(
    records: tuple[OptionsDataRecord, ...],
    *,
    as_of: datetime,
) -> tuple[OptionsDataRecord, ...]:
    """Select latest visible revisions independently per provider, kind and entity.

    Later availability breaks event-time ties. Conflicting simultaneous revisions are
    rejected, never resolved by file order. This does not certify source coverage/rights.
    """
    require_utc(as_of)
    if type(records) is not tuple or len(records) > 100000:
        raise DomainValidationError("options records require a bounded tuple")
    selected: dict[tuple[str, str, str], OptionsDataRecord] = {}
    revisions: dict[tuple[str, str, str, datetime, datetime], OptionsDataRecord] = {}
    for record in records:
        if type(record) is not OptionsDataRecord:
            raise DomainValidationError("invalid options record")
        if record.available_at > as_of or record.event_at > as_of:
            continue
        key = (record.source, record.kind, record.entity_id)
        previous = selected.get(key)
        stamp = (record.event_at, record.available_at)
        revision_key = (*key, *stamp)
        duplicate = revisions.get(revision_key)
        if duplicate is not None and record != duplicate:
            raise DomainValidationError("ambiguous point-in-time options revision")
        revisions[revision_key] = record
        if previous is not None:
            old_stamp = (previous.event_at, previous.available_at)
            if stamp <= old_stamp:
                continue
        selected[key] = record
    return tuple(selected[key] for key in sorted(selected))


def select_chain(
    records: tuple[OptionsDataRecord, ...],
    *,
    source: str,
    underlying: str,
    as_of: datetime,
) -> tuple[OptionContract, ...]:
    """Return only definitions explicitly present in a visible chain snapshot."""
    visible = tuple(item for item in point_in_time(records, as_of=as_of) if item.source == source)
    chains = [
        item.value
        for item in visible
        if isinstance(item.value, ChainSnapshot) and item.value.underlying == underlying
    ]
    if not chains:
        return ()
    definitions = {
        item.value.contract_id: item.value
        for item in visible
        if isinstance(item.value, OptionContract)
    }
    result = []
    for contract_id in chains[0].contract_ids:
        definition = definitions.get(contract_id)
        if definition is None or definition.available_at > as_of:
            raise DomainValidationError("incomplete point-in-time chain")
        if definition.underlying != underlying:
            raise DomainValidationError("inconsistent chain underlying")
        result.append(definition)
    return tuple(result)
