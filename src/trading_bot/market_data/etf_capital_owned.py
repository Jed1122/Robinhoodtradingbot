"""Private owned originals for later research preparation; never qualification."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import localcontext
from hashlib import sha256
from typing import cast

from trading_bot.market_data.etf_calendar import EtfCalendarArchive, EtfCalendarSession
from trading_bot.market_data.etf_capital_actions import (
    CapitalActionArchive,
    CapitalDistribution,
    CapitalSplit,
)
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_dataset import (
    CapitalResearchDataset,
    capital_dataset_features,
)
from trading_bot.market_data.etf_capital_observed import (
    CapitalObservedDataset,
    capital_observed_features,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _CONTEXT


@dataclass(frozen=True, slots=True, repr=False)
class _OwnedCapitalSource:
    """Internal snapshot, not a caller-supplied token or admitted market source."""

    dataset: CapitalResearchDataset
    source_hash: str


@dataclass(frozen=True, slots=True, repr=False)
class _OwnedCapitalObservedSource:
    """Distinct internal ownership of conditional observed-development inputs."""

    dataset: CapitalObservedDataset
    source_hash: str


def _owned_capital_source_kind_valid(
    owned: _OwnedCapitalSource | _OwnedCapitalObservedSource,
) -> bool:
    return (
        type(owned) is _OwnedCapitalSource and type(owned.dataset) is CapitalResearchDataset
    ) or (
        type(owned) is _OwnedCapitalObservedSource and type(owned.dataset) is CapitalObservedDataset
    )


def _immutable_clock(value: datetime) -> None:
    # Public readers keep their broader historical UTC contract. This NEW owned
    # boundary cannot retain arbitrary mutable timezone instances as aliases.
    if type(value) is not datetime or value.tzinfo is not UTC:
        raise ValueError("capital_owned_source_invalid")


def _validate_originals(dataset: CapitalResearchDataset) -> str:
    if type(dataset) is not CapitalResearchDataset:
        raise ValueError("capital_owned_source_invalid")
    return _validate_source_originals(dataset)


def _validate_source_originals(dataset: CapitalResearchDataset | CapitalObservedDataset) -> str:
    if type(dataset) not in (CapitalResearchDataset, CapitalObservedDataset):
        raise ValueError("capital_owned_source_invalid")
    if (
        type(dataset.archives) is not tuple
        or type(dataset.actions) is not tuple
        or type(dataset.calendar) is not EtfCalendarArchive
        or type(dataset.calendar.sessions) is not tuple
    ):
        raise ValueError("capital_owned_source_invalid")
    # Reject callable timezone leaves before existing public validators can
    # invoke them. This is a private ownership restriction, not new parsing.
    for archive in dataset.archives:
        if type(archive) is not CapitalDailyArchive or type(archive.received_at) is not tuple:
            raise ValueError("capital_owned_source_invalid")
        for instant in archive.received_at:
            _immutable_clock(instant)
    for action in dataset.actions:
        if type(action) is not CapitalActionArchive:
            raise ValueError("capital_owned_source_invalid")
        _immutable_clock(action.received_at)
    for session in dataset.calendar.sessions:
        if type(session) is not EtfCalendarSession:
            raise ValueError("capital_owned_source_invalid")
        _immutable_clock(session.opens_at)
        _immutable_clock(session.closes_at)
    dataset.__post_init__()
    for archive in dataset.archives:
        for page in archive.pages:
            for record in page.records:
                # Validate the ORIGINAL before replace() can reset its init=False
                # publication marker; do not launder forged chronology.
                record.bar.__post_init__()
    last = max(
        row.session_date
        for row in dataset.calendar.sessions
        if dataset.start <= row.session_date < dataset.end
    )
    # This existing consumer validates complete raw/action/calendar/basis
    # semantics, not only the recent signal window. Nothing is cached globally.
    if type(dataset) is CapitalObservedDataset:
        capital_observed_features(dataset, as_of_session=last)
    else:
        capital_dataset_features(cast(CapitalResearchDataset, dataset), as_of_session=last)
    return dataset.dataset_hash


def _own_capital_source(dataset: CapitalResearchDataset) -> _OwnedCapitalSource:
    """Copy validated originals, never adopt prepared signals or account state.

    Future public evaluators must create this snapshot internally. There is no
    public API that accepts an _OwnedCapitalSource as evidence or authority.
    Exact immutable leaves can be shared; every dataclass node is reconstructed.
    """
    if type(dataset) is not CapitalResearchDataset:
        raise ValueError("capital_owned_source_invalid")
    owned, source_hash = _copy_capital_source(dataset)
    return _OwnedCapitalSource(cast(CapitalResearchDataset, owned), source_hash)


def _own_capital_observed_source(dataset: CapitalObservedDataset) -> _OwnedCapitalObservedSource:
    """Own this variant explicitly; legacy admission is never widened."""
    if type(dataset) is not CapitalObservedDataset:
        raise ValueError("capital_owned_source_invalid")
    owned, source_hash = _copy_capital_source(dataset)
    return _OwnedCapitalObservedSource(cast(CapitalObservedDataset, owned), source_hash)


def _copy_capital_source(
    dataset: CapitalResearchDataset | CapitalObservedDataset,
) -> tuple[CapitalResearchDataset | CapitalObservedDataset, str]:
    def validate(value: CapitalResearchDataset | CapitalObservedDataset) -> str:
        # Preserve the established legacy validation seam for its callers and
        # instrumentation, while observed originals use their finite new branch.
        if type(value) is CapitalResearchDataset:
            return _validate_originals(value)
        return _validate_source_originals(value)

    try:
        with localcontext(_CONTEXT):
            original_hash = validate(dataset)
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
            owned: CapitalResearchDataset | CapitalObservedDataset
            if type(dataset) is CapitalObservedDataset:
                owned = replace(
                    dataset,
                    archives=tuple(archives),
                    actions=actions,
                    calendar=calendar,
                    action_model=replace(dataset.action_model),
                )
                namespace = "capital-owned-observed-source-v1"
            else:
                owned = replace(
                    dataset, archives=tuple(archives), actions=actions, calendar=calendar
                )
                namespace = "capital-owned-source-v1"
            if validate(owned) != original_hash or dataset.dataset_hash != original_hash:
                raise ValueError("capital_owned_source_invalid")
            return (
                owned,
                content_hash(
                    (
                        namespace,
                        sha256(owned.canonical_config).hexdigest(),
                        owned.config_hash,
                        original_hash,
                    )
                ),
            )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("capital_owned_source_invalid") from None
