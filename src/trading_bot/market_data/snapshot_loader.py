"""Conservative offline synthetic snapshots using existing application value contracts."""

from datetime import datetime
from typing import cast

from trading_bot.app import ValidatedMarketSnapshot
from trading_bot.domain import Bar, CorporateAction, DataHash, InstrumentId
from trading_bot.market_data.bundle_models import (
    BundleError,
    CoverageDeclaration,
    MembershipBaseline,
    NormalizedRecord,
    SnapshotSettings,
    _check,
    _instant,
)
from trading_bot.market_data.bundle_normalize import _limitations
from trading_bot.market_data.bundle_verify import VerifiedBundle
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.universe import PointInTimeUniverse, UniverseMembership
from trading_bot.strategies import HistoricalSlice


class BundleSnapshotLoader:
    def __init__(self, bundle: VerifiedBundle, *, settings: SnapshotSettings) -> None:
        _check(
            type(bundle) is VerifiedBundle and type(settings) is SnapshotSettings,
            "snapshot_query_invalid",
        )
        self._bundle, self._settings = bundle, settings

    @property
    def bundle_hash(self) -> DataHash:
        return self._bundle.envelope.bundle_hash

    @property
    def limitation_codes(self) -> tuple[str, ...]:
        return self._bundle.limitation_codes

    async def load(
        self, universe: tuple[InstrumentId, ...], as_of: datetime
    ) -> ValidatedMarketSnapshot:
        try:
            _instant(as_of)
        except BundleError:
            pass
        else:
            _check(type(universe) is tuple and bool(universe), "snapshot_query_invalid")
            known = {mapping.instrument_id for mapping in self._bundle.envelope.instruments}
            _check(
                all(type(item) is str and item in known for item in universe),
                "snapshot_query_invalid",
            )
            _check(
                len(set(universe)) == len(universe) and self._settings.history_start < as_of,
                "snapshot_query_invalid",
            )
            histories = tuple(self._history(instrument, as_of) for instrument in universe)
            digest = content_hash(
                {
                    "domain": "bundle-snapshot-v1",
                    "as_of": as_of,
                    "settings": self._settings,
                    "universe": universe,
                    "histories": tuple(history.data_hash for history in histories),
                }
            )
            return ValidatedMarketSnapshot(as_of, histories, str(digest))
        raise BundleError("snapshot_query_invalid")

    def _visible_coverage(
        self,
        records: tuple[NormalizedRecord, ...],
        as_of: datetime,
    ) -> tuple[NormalizedRecord, ...]:
        start = self._settings.history_start
        selected: list[NormalizedRecord] = []
        for kind in ("bar", "corporate_action", "membership"):
            segments = tuple(
                sorted(
                    (
                        row
                        for row in records
                        if isinstance(row.value, CoverageDeclaration)
                        and row.value.record_kind == kind
                        and (kind != "bar" or row.value.interval == self._settings.interval)
                        and row.value.starts_at < as_of
                        and row.value.ends_at > start
                    ),
                    key=lambda row: (
                        cast(CoverageDeclaration, row.value).starts_at,
                        cast(CoverageDeclaration, row.value).ends_at,
                        row.source_hash,
                        row.locator,
                    ),
                )
            )
            cursor = start
            for row in segments:
                segment = cast(CoverageDeclaration, row.value)
                _check(
                    row.available_at <= as_of
                    and segment.state == "complete"
                    and segment.starts_at <= cursor,
                    "snapshot_coverage_missing",
                )
                cursor = max(cursor, segment.ends_at)
            _check(cursor >= as_of, "snapshot_coverage_missing")
            selected.extend(segments)
        return tuple(selected)

    def _membership(
        self,
        records: tuple[NormalizedRecord, ...],
        instrument: InstrumentId,
        as_of: datetime,
    ) -> tuple[NormalizedRecord, ...]:
        baselines = tuple(
            row
            for row in records
            if isinstance(row.value, MembershipBaseline)
            and row.value.coverage_start <= self._settings.history_start
            and row.available_at <= as_of
            and row.value.announced_at <= as_of
        )
        _check(bool(baselines), "snapshot_membership_missing")
        baseline = max(
            baselines, key=lambda row: cast(MembershipBaseline, row.value).coverage_start
        )
        assertion = cast(MembershipBaseline, baseline.value)
        events = tuple(
            sorted(
                (
                    row
                    for row in records
                    if isinstance(row.value, UniverseMembership)
                    and assertion.coverage_start <= row.value.effective_at <= as_of
                    and row.available_at <= as_of
                    and row.value.announced_at <= as_of
                ),
                key=lambda row: (
                    cast(UniverseMembership, row.value).effective_at,
                    cast(UniverseMembership, row.value).announced_at,
                    row.source_hash,
                    row.locator,
                ),
            )
        )
        # The source baseline is a state assertion, never a fabricated membership event.
        included = assertion.included
        if events:
            universe = PointInTimeUniverse(
                tuple(cast(UniverseMembership, row.value) for row in events), history_complete=False
            )
            included = instrument in universe.members_at(as_of)
        _check(included, "snapshot_not_member")
        return (baseline, *events)

    def _history(self, instrument: InstrumentId, as_of: datetime) -> HistoricalSlice:
        records = tuple(
            row for row in self._bundle.envelope.records if row.value.instrument_id == instrument
        )
        coverage = self._visible_coverage(records, as_of)
        membership = self._membership(records, instrument, as_of)
        start = self._settings.history_start
        bars = tuple(
            sorted(
                (
                    row
                    for row in records
                    if isinstance(row.value, Bar)
                    and row.value.interval == self._settings.interval
                    and start <= row.value.starts_at < row.value.ends_at <= as_of
                ),
                key=lambda row: (cast(Bar, row.value).starts_at, cast(Bar, row.value).ends_at),
            )
        )
        expected = tuple(
            sorted(
                (slot.starts_at, slot.ends_at)
                for row in coverage
                if isinstance(row.value, CoverageDeclaration) and row.value.record_kind == "bar"
                for slot in row.value.expected_slots
                if start <= slot.starts_at and slot.ends_at <= as_of
            )
        )
        actual = tuple(
            (cast(Bar, row.value).starts_at, cast(Bar, row.value).ends_at) for row in bars
        )
        _check(
            actual == expected and all(row.available_at <= as_of for row in bars),
            "snapshot_records_unavailable",
        )
        _check(len(bars) >= self._settings.minimum_bars, "snapshot_history_insufficient")
        _check(all(not cast(Bar, row.value).interpolated for row in bars), "snapshot_interpolated")
        _check(
            all(row.price_basis == "unadjusted" for row in bars), "snapshot_price_basis_unsupported"
        )
        earliest = cast(Bar, bars[0].value).starts_at.date()
        # Future publication can deny unsupported history, but can never adjust past prices.
        _check(
            not any(
                isinstance(row.value, CorporateAction)
                and earliest <= row.value.effective_date <= as_of.date()
                for row in records
            ),
            "snapshot_action_unsupported",
        )
        selected = (*bars, *membership, *coverage)
        source_hashes = {row.source_hash for row in selected}
        sources = tuple(
            source
            for source in self._bundle.envelope.sources
            if source.descriptor_hash in source_hashes
        )
        digest = content_hash(
            {
                "domain": "bundle-history-v1",
                "instrument_id": instrument,
                "as_of": as_of,
                "settings": self._settings,
                "bars": tuple(row.record_hash for row in bars),
                "membership": tuple(row.record_hash for row in membership),
                "coverage": tuple(row.record_hash for row in coverage),
                "classification": "synthetic",
                "limitations": _limitations(sources, selected),
            }
        )
        return HistoricalSlice(
            instrument, tuple(cast(Bar, row.value) for row in bars), None, digest
        )
