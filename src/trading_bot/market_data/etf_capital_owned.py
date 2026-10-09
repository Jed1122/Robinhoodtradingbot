"""Private owned originals for later research preparation; never qualification."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import localcontext
from hashlib import sha256
from typing import cast

from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.market_data.etf_capital_dataset import (
    CapitalResearchDataset,
    capital_dataset_features,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _CONTEXT


@dataclass(frozen=True, slots=True, repr=False)
class _OwnedCapitalSource:
    """Internal snapshot, not a caller-supplied token or admitted market source."""

    dataset: CapitalResearchDataset
    source_hash: str


def _immutable_clock(value: datetime) -> None:
    # Public readers keep their broader historical UTC contract. This NEW owned
    # boundary cannot retain arbitrary mutable timezone instances as aliases.
    if type(value) is not datetime or value.tzinfo is not UTC:
        raise ValueError("capital_owned_source_invalid")


def _validate_originals(dataset: CapitalResearchDataset) -> str:
    if type(dataset) is not CapitalResearchDataset:
        raise ValueError("capital_owned_source_invalid")
    dataset.__post_init__()
    for archive in dataset.archives:
        for instant in archive.received_at:
            _immutable_clock(instant)
        for page in archive.pages:
            for record in page.records:
                # Validate the ORIGINAL before replace() can reset its init=False
                # publication marker; do not launder forged chronology.
                record.bar.__post_init__()
    for action in dataset.actions:
        _immutable_clock(action.received_at)
    for session in dataset.calendar.sessions:
        _immutable_clock(session.opens_at)
        _immutable_clock(session.closes_at)
    last = max(
        row.session_date
        for row in dataset.calendar.sessions
        if dataset.start <= row.session_date < dataset.end
    )
    # This existing consumer validates complete raw/action/calendar/basis
    # semantics, not only the recent signal window. Nothing is cached globally.
    capital_dataset_features(dataset, as_of_session=last)
    return dataset.dataset_hash


def _own_capital_source(dataset: CapitalResearchDataset) -> _OwnedCapitalSource:
    """Copy validated originals, never adopt prepared signals or account state.

    Future public evaluators must create this snapshot internally. There is no
    public API that accepts an _OwnedCapitalSource as evidence or authority.
    Exact immutable leaves can be shared; every dataclass node is reconstructed.
    """
    try:
        with localcontext(_CONTEXT):
            original_hash = _validate_originals(dataset)
            archives = []
            for archive in dataset.archives:
                request = replace(archive.request)
                pages = tuple(
                    replace(
                        page,
                        request=request,
                        records=tuple(
                            replace(record, bar=replace(record.bar)) for record in page.records
                        ),
                    )
                    for page in archive.pages
                )
                archives.append(replace(archive, request=request, pages=pages))
            actions = tuple(
                replace(
                    action,
                    splits=tuple(
                        replace(row) for row in cast(tuple[CapitalSplit, ...], action.splits)
                    ),
                    distributions=tuple(
                        replace(row)
                        for row in cast(tuple[CapitalDistribution, ...], action.distributions)
                    ),
                )
                for action in dataset.actions
            )
            calendar = replace(
                dataset.calendar,
                sessions=tuple(replace(row) for row in dataset.calendar.sessions),
            )
            owned = replace(dataset, archives=tuple(archives), actions=actions, calendar=calendar)
            if _validate_originals(owned) != original_hash or dataset.dataset_hash != original_hash:
                raise ValueError("capital_owned_source_invalid")
            return _OwnedCapitalSource(
                owned,
                content_hash(
                    (
                        "capital-owned-source-v1",
                        sha256(owned.canonical_config).hexdigest(),
                        owned.config_hash,
                        original_hash,
                    )
                ),
            )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("capital_owned_source_invalid") from None
