"""Owned copies of fabricated original inputs, never source qualification."""

from dataclasses import fields, is_dataclass, replace
from datetime import UTC, date, timedelta, tzinfo
from decimal import Decimal as D
from hashlib import sha256

import pytest

from tests.unit.market_data.test_etf_capital_dataset import dataset
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.market_data.etf_capital_dataset import capital_dataset_features
from trading_bot.market_data.recording import content_hash


def own(source):
    from trading_bot.market_data.etf_capital_owned import _own_capital_source

    return _own_capital_source(source)


def originals():
    source = dataset()
    actions = tuple(
        replace(
            row,
            splits=(CapitalSplit(date(2023, 1, 4), D(2), "d" * 64),),
            distributions=(
                CapitalDistribution(
                    date(2023, 1, 4), date(2023, 1, 5), date(2023, 2, 10), D(1), "e" * 64
                ),
            ),
        )
        for row in source.actions
    )
    return replace(source, actions=actions)


def dataclass_ids(value):
    if is_dataclass(value):
        return {id(value)} | set().union(
            *(dataclass_ids(getattr(value, field.name)) for field in fields(value))
        )
    if isinstance(value, tuple):
        return set().union(*(dataclass_ids(item) for item in value))
    return set()


def test_owned_source_retains_original_hash_and_literal_asof_split_basis():
    source = originals()
    result = own(source)
    assert result.dataset.dataset_hash == source.dataset_hash
    assert result.source_hash == content_hash(
        (
            "capital-owned-source-v1",
            sha256(source.canonical_config).hexdigest(),
            source.config_hash,
            source.dataset_hash,
        )
    )
    assert not (dataclass_ids(source) & dataclass_ids(result.dataset))
    prior = capital_dataset_features(result.dataset, as_of_session=date(2023, 1, 3))[0]
    after = capital_dataset_features(result.dataset, as_of_session=date(2023, 1, 4))[0]
    assert prior.raw_bars[0].close == prior.feature_bars[0].close == D(22)
    assert tuple(bar.close for bar in after.raw_bars) == (D(22), D(11))
    assert tuple(bar.close for bar in after.feature_bars) == (D(11), D(11))
    assert not result.dataset.source_qualified
    assert not result.dataset.execution_enabled and not result.dataset.evidence_promotable


@pytest.mark.parametrize(
    "target",
    ["dataset", "archive", "request", "page", "bar", "action", "split", "distribution", "session"],
)
def test_caller_mutation_after_intake_cannot_change_owned_inputs(target):
    source = originals()
    result = own(source)
    original_hash = result.dataset.dataset_hash
    rows = {
        "dataset": (source, "start", date(2023, 1, 2)),
        "archive": (source.archives[0], "manifest_hash", "f" * 64),
        "request": (source.archives[0].request, "limit", 500),
        "page": (source.archives[0].pages[0], "records", ()),
        "bar": (source.archives[0].pages[0].records[0].bar, "close", D(999)),
        "action": (source.actions[0], "source_hash", "f" * 64),
        "split": (source.actions[0].splits[0], "new_shares_per_old_share", D(3)),
        "distribution": (source.actions[0].distributions[0], "amount_per_share", D(9)),
        "session": (source.calendar.sessions[0], "opens_at", source.calendar.sessions[0].closes_at),
    }
    record, field, value = rows[target]
    object.__setattr__(record, field, value)
    assert result.dataset.dataset_hash == original_hash
    assert capital_dataset_features(result.dataset, as_of_session=date(2023, 1, 4))[0].feature_bars[
        0
    ].close == D(11)


def test_new_invocation_does_not_reuse_a_previous_source_snapshot():
    source = originals()
    before = own(source)
    object.__setattr__(source.archives[0], "manifest_hash", "f" * 64)
    after = own(source)
    assert before.source_hash != after.source_hash
    assert before.dataset.archives[0].manifest_hash == "a" * 64
    assert after.dataset.archives[0].manifest_hash == "f" * 64


@pytest.mark.parametrize("target", ["dataset", "archive", "page", "action", "calendar"])
def test_invalid_original_eligibility_is_not_normalized_away(target):
    source = originals()
    selected = {
        "dataset": source,
        "archive": source.archives[0],
        "page": source.archives[0].pages[0],
        "action": source.actions[0],
        "calendar": source.calendar,
    }[target]
    object.__setattr__(selected, "source_qualified", True)
    with pytest.raises(ValueError):
        own(source)


@pytest.mark.parametrize(
    "target",
    ["publication", "calendar_kind", "calendar_limit", "missing_action", "config", "late_bar"],
)
def test_invalid_original_facts_deny_before_snapshot_construction(target):
    source = originals()
    rows = {
        "publication": (source.archives[0].pages[0].records[0].bar, "publication_at_ns", 42),
        "calendar_kind": (source.calendar, "source_kind", "qualified"),
        "calendar_limit": (source.calendar, "limitations", ()),
        "missing_action": (source.actions[0], "splits", None),
        "config": (source, "config_hash", "f" * 64),
        "late_bar": (source.archives[0].pages[0].records[-1].bar, "close", D(999)),
    }
    record, field, value = rows[target]
    object.__setattr__(record, field, value)
    with pytest.raises(ValueError):
        own(source)


class MutableUtc(tzinfo):
    def utcoffset(self, value):
        return timedelta(0)

    def dst(self, value):
        return timedelta(0)


class ForbiddenOffset(tzinfo):
    def utcoffset(self, value):
        raise AssertionError("custom timezone hook must not be invoked")


@pytest.mark.parametrize("target", ["receipt", "action", "session"])
def test_owned_clock_rejection_precedes_public_validation_timezone_hooks(target):
    source = originals()
    if target == "receipt":
        original = source.archives[0].received_at[0]
        object.__setattr__(
            source.archives[0], "received_at", (original.replace(tzinfo=ForbiddenOffset()),)
        )
    elif target == "action":
        original = source.actions[0].received_at
        object.__setattr__(
            source.actions[0], "received_at", original.replace(tzinfo=ForbiddenOffset())
        )
    else:
        original = source.calendar.sessions[0].opens_at
        object.__setattr__(
            source.calendar.sessions[0], "opens_at", original.replace(tzinfo=ForbiddenOffset())
        )
    with pytest.raises(ValueError, match="capital_owned_source_invalid"):
        own(source)


@pytest.mark.parametrize("target", ["receipt", "action", "session"])
def test_owned_boundary_rejects_custom_mutable_timezone_without_changing_public_api(target):
    source = originals()
    if target == "receipt":
        original = source.archives[0].received_at[0]
        object.__setattr__(
            source.archives[0], "received_at", (original.replace(tzinfo=MutableUtc()),)
        )
    elif target == "action":
        object.__setattr__(
            source.actions[0],
            "received_at",
            source.actions[0].received_at.replace(tzinfo=MutableUtc()),
        )
    else:
        original = source.calendar.sessions[0].opens_at
        object.__setattr__(
            source.calendar.sessions[0], "opens_at", original.replace(tzinfo=MutableUtc())
        )
    source.__post_init__()  # Existing public UTC validation still accepts it.
    with pytest.raises(ValueError, match="capital_owned_source_invalid"):
        own(source)


def test_exact_utc_clocks_remain_immutable_declared_inputs():
    result = own(originals())
    assert result.dataset.archives[0].received_at[0].tzinfo is UTC
    assert result.dataset.actions[0].received_at.tzinfo is UTC
    assert result.dataset.calendar.sessions[0].opens_at.tzinfo is UTC


@pytest.mark.parametrize("value", [None, (), True, "a" * 64])
def test_owned_boundary_rejects_non_original_input_types(value):
    with pytest.raises(ValueError, match="capital_owned_source_invalid"):
        own(value)


@pytest.mark.parametrize("during", ["request", "dataset"])
def test_copy_time_source_change_denies_instead_of_binding_mixed_originals(monkeypatch, during):
    from trading_bot.market_data import etf_capital_owned as module

    source = originals()
    target = source.archives[0].request if during == "request" else source
    actual_replace = module.replace
    changed = False

    def replace_while_source_changes(record, **values):
        nonlocal changed
        if record is target and not changed:
            object.__setattr__(source.archives[0], "manifest_hash", "f" * 64)
            changed = True
        return actual_replace(record, **values)

    monkeypatch.setattr(module, "replace", replace_while_source_changes)
    with pytest.raises(ValueError, match="capital_owned_source_invalid"):
        own(source)
    assert changed


@pytest.mark.parametrize(
    "target",
    ["archives", "actions", "calendar", "sessions", "archive", "receipts", "action", "session"],
)
def test_malformed_clock_containers_deny_before_nested_access(target):
    source = originals()
    rows = {
        "archives": (source, "archives", []),
        "actions": (source, "actions", []),
        "calendar": (source, "calendar", None),
        "sessions": (source.calendar, "sessions", []),
        "archive": (source, "archives", (None,)),
        "receipts": (source.archives[0], "received_at", []),
        "action": (source, "actions", (None,)),
        "session": (source.calendar, "sessions", (None,)),
    }
    record, field, value = rows[target]
    object.__setattr__(record, field, value)
    with pytest.raises(ValueError, match="capital_owned_source_invalid"):
        own(source)
