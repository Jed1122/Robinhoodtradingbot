"""Reopen current research evidence without acquiring data or touching an account.

The factory checks manifest-committed retained bytes and recomputes the existing
reports. That establishes local integrity, not independent native-wire provenance
or investment/execution approval. Original source clocks and false flags survive.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, localcontext
from pathlib import Path
from typing import Any, Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.domain import CodeHash
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.persistence.stock_research_jobs import SqlStockResearchJobs
from trading_bot.runtime.stock_archive import read_stock_observations
from trading_bot.runtime.stock_archive_lease import StockArchiveLease
from trading_bot.runtime.stock_dashboard_export import _policy
from trading_bot.runtime.stock_research_worker import _cached

# Legacy screen reports stringify reciprocal factors under the worker's standard
# Decimal context. Reproduce that version, rather than changing retained results.
_SCREEN_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-/]{0,14}\Z")


@dataclass(frozen=True, slots=True)
class CurrentScannerSourceRow:
    symbol: str
    instrument_id: str
    received_at: datetime
    observation_hash: str
    native_row_json: str = field(repr=False)
    record_index: int


@dataclass(frozen=True, slots=True)
class CurrentStockResearchInputs:
    status: Literal["available", "needs_research"]
    needs: tuple[str, ...]
    as_of: datetime
    source_state_hash: str
    source_config_hash: str
    acquisition_code_hashes: tuple[str, ...]
    discovery_manifest_hash: str | None
    enrichment_manifest_hash: str | None
    discovery_report_hash: str | None
    enrichment_report_hash: str | None
    discovery_json: str | None = field(repr=False)
    enrichment_json: str | None = field(repr=False)
    scanner_rows: tuple[CurrentScannerSourceRow, ...]
    held_symbols: tuple[str, ...]
    pending_acquisition_claims: int
    native_http_wire_receipt: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        if not (
            self.native_http_wire_receipt
            is self.investment_eligible
            is self.execution_authorized
            is self.live_authorized
            is False
        ):
            raise ValueError("current_stock_research_scope_changed")
        return str(content_hash(("current-stock-research-inputs-v1", self)))


def _current_scanner_rows(
    observations: tuple[dict[str, Any], ...], *, wanted: set[str], cutoff: datetime
) -> tuple[CurrentScannerSourceRow, ...]:
    """Merge already archive-verified rows without repairing identity or clocks."""
    require_utc(cutoff)
    selected: dict[tuple[str, str], CurrentScannerSourceRow] = {}
    instruments: dict[str, str] = {}
    symbols: dict[str, str] = {}
    at_clock: dict[tuple[str, str, datetime], str] = {}
    for observation in observations:
        if observation["tool"] != "preview_scan":
            continue
        received = require_utc(datetime.fromisoformat(observation["received_at"]))
        digest = _require_sha256_hex(observation["observation_sha256"], "scanner_observation")
        if received > cutoff:
            raise ValueError("current_stock_scanner_source_invalid")
        for index, row in enumerate(observation["payload"]["data"]["result"]["results"]):
            symbol = row["ticker"]
            if symbol not in wanted:
                continue
            instrument = row["instrument_id"]
            if (
                type(symbol) is not str
                or _SYMBOL.fullmatch(symbol) is None
                or type(instrument) is not str
                or not 0 < len(instrument) <= 128
                or not instrument.isprintable()
                or (symbol in symbols and symbols[symbol] != instrument)
                or (instrument in instruments and instruments[instrument] != symbol)
            ):
                raise ValueError("current_stock_scanner_source_invalid")
            symbols[symbol], instruments[instrument] = instrument, symbol
            native = canonical_json(row)
            clock_key = symbol, instrument, received
            if clock_key in at_clock and at_clock[clock_key] != native:
                raise ValueError("current_stock_scanner_source_invalid")
            at_clock[clock_key] = native
            candidate = CurrentScannerSourceRow(symbol, instrument, received, digest, native, index)
            key = symbol, instrument
            previous = selected.get(key)
            if (
                previous is None
                or received > previous.received_at
                or (
                    received == previous.received_at
                    and (digest, index) < (previous.observation_hash, previous.record_index)
                )
            ):
                selected[key] = candidate
    return tuple(selected[key] for key in sorted(selected))


async def load_current_stock_research_inputs(
    *,
    loaded: LoadedConfig,
    acquisition_code_hash: CodeHash,
    factory: object,
    archive_dir: Path,
    held_symbols: tuple[str, ...] = (),
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CurrentStockResearchInputs:
    """Read/recompute only; missing or stale heads request research, never a trade."""
    try:
        _require_sha256_hex(acquisition_code_hash, "acquisition_code_hash")
        if (
            type(held_symbols) is not tuple
            or len(held_symbols) > 256
            or len(set(held_symbols)) != len(held_symbols)
            or any(type(s) is not str or _SYMBOL.fullmatch(s) is None for s in held_symbols)
        ):
            raise ValueError
        policy = _policy(loaded)
        jobs = SqlStockResearchJobs(
            factory, loaded=loaded, code_hash=acquisition_code_hash, clock=clock
        )
        with StockArchiveLease(archive_dir) as archive:
            state = await jobs.snapshot()
            observed = require_utc(state.observed_at)
            with localcontext(_SCREEN_CONTEXT):
                discovery, enrichment = _cached(
                    state=state, archive=archive, root=archive_dir, policy=policy, now=observed
                )
            wanted = set(held_symbols)
            discovery_symbols: set[str] = set()
            if discovery is not None:
                discovery_symbols.update(
                    row["symbol"] for row in discovery["screen"]["opportunities"]
                )
                wanted.update(discovery_symbols)
            enriched_symbols: set[str] = set()
            if enrichment is not None:
                enriched_symbols.update(row["symbol"] for row in enrichment["dossiers"])
                wanted.update(enriched_symbols)
            observations: list[dict[str, Any]] = []
            for head in (state.discovery_head, state.enrichment_head):
                if head is None:
                    continue
                manifest = head.manifest_sha256
                if manifest is None:
                    raise ValueError
                observations.extend(
                    read_stock_observations(
                        archive_dir,
                        str(manifest) + ".stock-capture.json",
                        _directory_fd=archive.directory_fd,
                    )
                )
            rows = _current_scanner_rows(tuple(observations), wanted=wanted, cutoff=observed)
            finished = require_utc(clock())
            if finished < observed:
                raise ValueError
            needs: list[str] = []
            claims = {claim.claim_id: claim for claim in state.claims}
            codes: set[str] = set()
            for phase, head in (
                ("discovery", state.discovery_head),
                ("enrichment", state.enrichment_head),
            ):
                if head is None:
                    needs.append(phase + "_missing")
                    continue
                claim = claims[head.claim_id]
                codes.add(str(claim.code_hash))
                age = (finished - claim.claimed_at).total_seconds()
                if age < 0:
                    raise ValueError
                if age >= policy.stock_research.maximum_source_age_minutes * 60:
                    needs.append(phase + "_stale")
            needs.extend(
                "discovery_dossier_missing:" + symbol
                for symbol in sorted(discovery_symbols - enriched_symbols)
            )
            needs.extend(
                "held_evidence_missing:" + symbol
                for symbol in sorted(set(held_symbols) - enriched_symbols)
            )
            needs.extend(
                "held_scanner_identity_missing:" + symbol
                for symbol in sorted(set(held_symbols) - {row.symbol for row in rows})
            )
            a, b = state.discovery_head, state.enrichment_head
            return CurrentStockResearchInputs(
                status="needs_research" if needs else "available",
                needs=tuple(needs),
                as_of=finished,
                source_state_hash=state.state_hash,
                source_config_hash=str(loaded.config_hash),
                acquisition_code_hashes=tuple(sorted(codes)),
                discovery_manifest_hash=None if a is None else a.manifest_sha256,
                enrichment_manifest_hash=None if b is None else b.manifest_sha256,
                discovery_report_hash=None if a is None else a.report_sha256,
                enrichment_report_hash=None if b is None else b.report_sha256,
                discovery_json=None if discovery is None else canonical_json(discovery),
                enrichment_json=None if enrichment is None else canonical_json(enrichment),
                scanner_rows=rows,
                held_symbols=tuple(sorted(held_symbols)),
                pending_acquisition_claims=state.pending_count,
            )
    except Exception:
        raise ValueError("current_stock_research_unavailable") from None
