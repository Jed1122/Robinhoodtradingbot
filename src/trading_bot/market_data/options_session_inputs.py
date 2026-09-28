"""Evidence-bound regular-session aggregation; no calendar inference or adjusted prices."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import Bar, BarInterval, CorporateAction, DataHash, InstrumentId
from trading_bot.domain.options import OptionSession
from trading_bot.market_data.databento_bar_models import (
    MINUTE_NS,
    NativeBarDataset,
    NativeBarRow,
    native_limits,
)
from trading_bot.market_data.databento_native_rows import read_bar_rows
from trading_bot.market_data.options_source_models import SourceVerification, hashes
from trading_bot.market_data.options_source_rules import source_code_hash
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_shortlist_models import ShortlistAction, ShortlistCalendarDay

REASONS = frozenset(
    {
        "source_scope_mismatch",
        "calendar_unverified",
        "prior_close_unavailable",
        "action_coverage_unverified",
        "reference_discontinuity",
        "source_coverage_degraded",
        "source_data_unusable",
        "bar_publication_unverified",
        "source_close_coverage_unverified",
        "source_limit_exceeded",
    }
)


def _check(value: bool) -> None:
    if not value:
        raise ValueError("options_session_inputs_invalid")


def _ns(value: datetime) -> int:
    require_utc(value)
    elapsed = value - datetime(1970, 1, 1, tzinfo=UTC)
    return (elapsed.days * 86400 + elapsed.seconds) * 10**9 + elapsed.microseconds * 1000


@dataclass(frozen=True, slots=True)
class SessionReferenceInput:
    current: OptionSession
    prior: OptionSession | None
    calendar_days: tuple[ShortlistCalendarDay, ...]
    actions: tuple[ShortlistAction, ...]
    claim_hashes: tuple[DataHash, ...]

    def __post_init__(self) -> None:
        _check(type(self.current) is OptionSession)
        _check(self.prior is None or type(self.prior) is OptionSession)
        for values, kind in (
            (self.calendar_days, ShortlistCalendarDay),
            (self.actions, ShortlistAction),
        ):
            _check(type(values) is tuple and len(values) <= 25000)
            _check(all(type(value) is kind for value in values))
        hashes(self.claim_hashes)


@dataclass(frozen=True, slots=True)
class SessionInputs:
    reference: SessionReferenceInput
    bar: Bar | None
    available_at: datetime | None
    selected_native_hashes: tuple[DataHash, ...]
    included_count: int
    excluded_count: int
    rejected_count: int
    duplicate_count: int
    reasons: tuple[str, ...]
    price_basis: Literal["unadjusted"] = field(default="unadjusted", init=False)
    coverage_label: Literal["source_last_trade"] = field(default="source_last_trade", init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.reference) is SessionReferenceInput)
        _check(self.bar is None or type(self.bar) is Bar)
        _check((self.bar is None) == (self.available_at is None))
        if self.available_at is not None:
            require_utc(self.available_at)
        hashes(self.selected_native_hashes)
        for value in (
            self.included_count,
            self.excluded_count,
            self.rejected_count,
            self.duplicate_count,
        ):
            _check(type(value) is int and 0 <= value <= 25000)
        _check(
            type(self.reasons) is tuple
            and all(type(reason) is str and reason in REASONS for reason in self.reasons)
        )
        _check(self.reasons == tuple(sorted(set(self.reasons))))
        _check((self.bar is None) == bool(self.reasons))


def _fact(verification: SourceVerification, role: str, value: object) -> bool:
    digest = content_hash(value)
    return digest in verification.record_hashes and any(
        finding.role == role and finding.status == "verified" and digest in finding.visible_hashes
        for finding in verification.findings
    )


def _calendar(reference: SessionReferenceInput) -> bool:
    prior, current = reference.prior, reference.current
    if (
        prior is None
        or not prior.closes_at <= current.opens_at
        or prior.trading_date >= current.trading_date
    ):
        return False
    count = (current.trading_date - prior.trading_date).days + 1
    if count > 25000 or len(reference.calendar_days) != count:
        return False
    for index, item in enumerate(reference.calendar_days):
        if item.trading_date != prior.trading_date + timedelta(days=index):
            return False
    sessions = tuple(
        item.regular_session for item in reference.calendar_days if item.regular_session is not None
    )
    return sessions == (prior, current)


def assemble_session_inputs(
    dataset: NativeBarDataset,
    reference: SessionReferenceInput,
    *,
    verification: SourceVerification,
    loaded: LoadedConfig,
    repository_root: Path,
) -> SessionInputs:
    _check(type(dataset) is NativeBarDataset and type(reference) is SessionReferenceInput)
    _check(type(verification) is SourceVerification)
    native_limits(loaded)
    denied: set[str] = set()
    selected: list[NativeBarRow] = []
    regular_hashes: set[DataHash] = set()
    included = excluded = rejected = duplicates = 0

    def result(bar: Bar | None = None) -> SessionInputs:
        return SessionInputs(
            reference,
            bar,
            ceil_available_at(verification.context.as_of_ns) if bar is not None else None,
            tuple(sorted({row.record_hash for row in selected})),
            included,
            excluded,
            rejected,
            duplicates,
            tuple(sorted(denied)),
        )

    prior, current = reference.prior, reference.current
    if prior is None:
        denied.add("prior_close_unavailable")
        return result()
    canonical, config_hash = hash_loaded_config(loaded.config, loaded.safety_envelope)
    context = verification.context
    if (
        context.config_hash != config_hash
        or loaded.config_hash != config_hash
        or canonical != loaded.canonical_json
        or context.code_hash != source_code_hash()
        or dataset.config_hash != config_hash
        or context.start_ns != _ns(prior.opens_at)
        or context.end_ns != _ns(current.opens_at)
        or context.as_of_ns != _ns(current.opens_at)
        or dataset.manifest_hash not in verification.source_hashes
        or not reference.claim_hashes
        or not set(reference.claim_hashes) <= set(verification.visible_claim_hashes)
    ):
        denied.add("source_scope_mismatch")
        return result()
    if not _calendar(reference) or not _fact(
        verification,
        "calendar",
        {"kind": "calendar", "current": current, "prior": prior, "days": reference.calendar_days},
    ):
        denied.add("calendar_unverified")
    if not _fact(
        verification,
        "actions",
        {
            "kind": "actions",
            "start_ns": _ns(prior.opens_at),
            "end_ns": _ns(current.opens_at),
            "actions": reference.actions,
        },
    ):
        denied.add("action_coverage_unverified")
    for item in reference.actions:
        action = item.action
        if action.instrument_id != "SPY" or item.available_at > current.opens_at:
            denied.add("action_coverage_unverified")
        if prior.trading_date <= action.effective_date <= current.trading_date and (
            type(action) is not CorporateAction or action.action_type != "dividend"
        ):
            denied.add("reference_discontinuity")
    conditions = tuple(
        item for item in dataset.conditions if item.trading_date == prior.trading_date
    )
    if len(conditions) != 1 or conditions[0].state != "available":
        denied.add("source_coverage_degraded")
    day_start = _ns(datetime.combine(prior.trading_date, time(), UTC))
    day_end = day_start + 86400 * 10**9
    if not dataset.request.start_ns <= day_start < day_end <= dataset.request.end_ns:
        denied.add("source_scope_mismatch")
        return result()
    try:
        for count, row in enumerate(
            read_bar_rows(
                dataset,
                start_ns=day_start,
                end_ns=day_end,
                loaded=loaded,
                repository_root=repository_root,
            ),
            1,
        ):
            if count > loaded.config.options.research_shortlist.max_input_records:
                denied.add("source_limit_exceeded")
                return result()
            in_session = _ns(
                prior.opens_at
            ) <= row.interval_start_ns and row.interval_start_ns + MINUTE_NS <= _ns(prior.closes_at)
            if in_session:
                regular_hashes.add(row.record_hash)
            if row.disposition == "duplicate":
                duplicates += 1
            elif row.disposition == "rejected":
                rejected += 1
                if in_session:
                    denied.add("source_data_unusable")
            elif in_session:
                selected.append(row)
                included += 1
            else:
                excluded += 1
    except Exception:
        denied.add("source_data_unusable")
        return result()
    if not _fact(
        verification,
        "bar_publication",
        {
            "kind": "bar_publication",
            "start_ns": _ns(prior.opens_at),
            "end_ns": _ns(prior.closes_at),
            "as_of_ns": context.as_of_ns,
            "coverage": "complete_trade_intervals",
            "native_hashes": tuple(sorted(regular_hashes)),
        },
    ):
        denied.add("bar_publication_unverified")
    if not selected:
        denied.add("prior_close_unavailable")
        return result()
    if len({(row.publisher_id, row.instrument_id) for row in selected}) != 1:
        denied.add("source_data_unusable")
    last_end = selected[-1].interval_start_ns + MINUTE_NS
    if last_end != _ns(prior.closes_at) and not _fact(
        verification,
        "bar_publication",
        {
            "kind": "no_trade",
            "start_ns": last_end,
            "end_ns": _ns(prior.closes_at),
            "as_of_ns": context.as_of_ns,
        },
    ):
        denied.add("source_close_coverage_unverified")
    if denied:
        return result()
    first, last = selected[0], selected[-1]
    _check(first.open_nanos is not None and last.close_nanos is not None)
    bar = Bar(
        InstrumentId("SPY"),
        BarInterval.ONE_DAY,
        prior.opens_at,
        prior.closes_at,
        Decimal(str(first.open_nanos)) / Decimal(10**9),
        Decimal(max(row.high_nanos for row in selected if row.high_nanos is not None))
        / Decimal(10**9),
        Decimal(min(row.low_nanos for row in selected if row.low_nanos is not None))
        / Decimal(10**9),
        Decimal(str(last.close_nanos)) / Decimal(10**9),
        Decimal(sum(row.volume for row in selected)),
        "XNAS.ITCH",
        content_hash(
            {"session": prior, "native_hashes": tuple(row.record_hash for row in selected)}
        ),
        False,
    )
    return result(bar)
