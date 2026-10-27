"""Project verified archive inputs into source-bound current stock assessments.

This is a pure projection, not source authentication or broker authorization.
Production callers obtain inputs from load_current_stock_research_inputs. Native
financials do not provide report IDs, duration starts or currency; none is inferred
from a different scanner snapshot. Receipt clocks remain the original clocks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, DecimalException
from typing import Any, Literal

from trading_bot.clock import require_utc
from trading_bot.market_data.recording import content_hash
from trading_bot.research.stock_investment_decisions import (
    CurrentEvidenceRef,
    CurrentMetric,
    CurrentStockEvidence,
)
from trading_bot.runtime.stock_investment_inputs import CurrentStockResearchInputs

PROFILE = "stock-worker-current-provider-v1"
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-/]{0,14}\Z")
_COLUMNS = (
    ("roe", "Return on equity", "provider_feature"),
    ("net_margin", "Net profit margin", "provider_feature"),
    ("annual_eps_growth", "Annual EPS growth", "provider_feature"),
    ("quarterly_revenue_growth", "Quarterly revenue growth", "provider_feature"),
    ("pe_ratio", "P/E", "multiple"),
    ("fcf_per_share", "FCF/share", "per_share"),
    ("scanner_price", "Last", "price_per_share"),
    ("price_to_fcf", "P/FCF", "multiple"),
    ("total_stockholders_equity", "Total stockholders equity", "monetary"),
    ("assets_to_equity", "Assets/equity", "ratio"),
    ("provider_close_20", "Provider close 20", "price_per_share"),
    ("provider_sma_50", "Provider SMA 50", "price_per_share"),
)


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("current_stock_evidence_invalid")


def _number(raw: object) -> Decimal | None:
    if type(raw) is not str or not 0 < len(raw) <= 80:
        return None
    try:
        value = Decimal(raw)
        exponent = value.as_tuple().exponent
        if (
            value.is_finite()
            and value.copy_abs() < Decimal("1e30")
            and len(value.as_tuple().digits) <= 80
            and isinstance(exponent, int)
            and -30 <= exponent <= 30
        ):
            return value
    except (DecimalException, ValueError):
        pass
    return None


@dataclass(frozen=True, slots=True)
class CurrentStockEvidenceBatch:
    input_hash: str
    worker_profile_id: str
    stocks: tuple[CurrentStockEvidence, ...]
    needs: tuple[str, ...]
    as_of: datetime
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        _check(self.execution_authorized is self.live_authorized is False)
        return str(
            content_hash(
                (
                    "current-stock-evidence-projection-v1",
                    self.input_hash,
                    self.worker_profile_id,
                    tuple(x.evidence_hash for x in self.stocks),
                    self.needs,
                    self.as_of,
                )
            )
        )


def _financials(
    dossier: dict[str, Any] | None,
    dossier_index: int,
    dossier_hash: str | None,
    symbol: str,
) -> tuple[CurrentMetric, ...]:
    if dossier is None:
        return ()
    periods = dossier["financial_periods"]
    _check(type(periods) is list and len(periods) <= 80)
    seen = set()
    for row in periods:
        key = (row["period"], row["period_end"])
        _check(key not in seen and row["symbol"] == symbol)
        seen.add(key)
    if not periods:
        return ()
    # Use the latest economic period, preferring its quarterly duration on a
    # year-end tie. Never skip an unfavorable or incomplete latest report.
    index, period = max(
        enumerate(periods),
        key=lambda x: (date.fromisoformat(x[1]["period_end"]), x[1]["period"] == "quarterly"),
    )
    receipt = period["receipt"]
    _check(receipt["tool"] == "get_financials")
    stamp = require_utc(datetime.fromisoformat(receipt["received_at"]))
    ref = CurrentEvidenceRef(
        tool="get_financials",
        observation_sha256=receipt["observation_sha256"],
        record_ref=f"dossiers/{dossier_index}/financial_periods/{index}",
        received_at=stamp,
        expires_at=stamp + timedelta(days=7),
        effective_date=date.fromisoformat(period["period_end"]),
        normalized_sha256=dossier_hash,
        symbol=symbol,
    )
    values: dict[str, object] = {}
    for metric in period["metrics"]:
        _check(metric["name"] not in values)
        values[metric["name"]] = metric["value"]
    return tuple(
        CurrentMetric(
            name=name,
            value=_number(values.get(name)),
            unit="monetary",
            period_basis=period["period"],
            refs=(ref,),
            period_end=date.fromisoformat(period["period_end"]),
            # These unknown native fields are deliberately not supplied.
            currency=None,
            period_start=None,
            original_report_id=None,
        )
        for name in ("net_income", "revenue")
    )


def build_current_stock_evidence(
    inputs: CurrentStockResearchInputs,
    *,
    worker_profile_id: str,
    held_sleeves: tuple[tuple[str, Literal["long_term", "tactical"]], ...] = (),
) -> CurrentStockEvidenceBatch:
    """Project only the current discovery cohort and explicitly owned companies."""
    try:
        _check(type(inputs) is CurrentStockResearchInputs and worker_profile_id == PROFILE)
        now = require_utc(inputs.as_of)
        input_hash = inputs.evidence_hash
        _check(type(held_sleeves) is tuple and len(held_sleeves) <= 256)
        owned: dict[str, Literal["long_term", "tactical"]] = {}
        for row in held_sleeves:
            _check(type(row) is tuple and len(row) == 2)
            symbol, sleeve = row
            _check(type(symbol) is str and _SYMBOL.fullmatch(symbol) is not None)
            _check(sleeve in ("long_term", "tactical") and symbol not in owned)
            owned[symbol] = sleeve
        _check(set(owned) <= set(inputs.held_symbols))
        wanted = set(inputs.held_symbols)
        if inputs.discovery_json is not None:
            discovery = json.loads(inputs.discovery_json)
            wanted.update(x["symbol"] for x in discovery["screen"]["opportunities"])
        _check(len(wanted) <= 512)
        _check(all(type(s) is str and _SYMBOL.fullmatch(s) for s in wanted))
        dossiers: dict[str, tuple[int, dict[str, Any], str]] = {}
        if inputs.enrichment_json is not None:
            report = json.loads(inputs.enrichment_json)
            for index, (dossier, digest) in enumerate(
                zip(report["dossiers"], report["dossier_hashes"], strict=True)
            ):
                symbol = dossier["symbol"]
                _check(symbol not in dossiers)
                dossiers[symbol] = (index, dossier, digest)
        scans = {}
        for item in inputs.scanner_rows:
            _check(item.symbol not in scans)
            _check(type(item.record_index) is int and item.record_index >= 0)
            _check(require_utc(item.received_at) <= now)
            raw = json.loads(item.native_row_json)
            _check(raw["ticker"] == item.symbol and raw["instrument_id"] == item.instrument_id)
            _check(raw["instrument_type"] == "EQUITY" and raw["columns"]["Asset type"] == "STOCK")
            scans[item.symbol] = (item, raw)
        needs = set(inputs.needs)
        stocks = []
        for symbol in sorted(wanted):
            held = symbol in inputs.held_symbols
            if held and symbol not in owned:
                needs.add("held_sleeve_missing:" + symbol)
                continue
            if symbol not in dossiers:
                needs.add("company_financial_dossier_missing:" + symbol)
            index, dossier, digest = dossiers.get(symbol, (-1, None, None))
            financials = _financials(dossier, index, digest, symbol)
            identity: tuple[CurrentEvidenceRef, ...] = ()
            metrics = list(financials)
            sector = instrument = None
            if symbol in scans:
                item, raw = scans[symbol]
                instrument = item.instrument_id
                cells = raw["columns"]
                ref = CurrentEvidenceRef(
                    tool="preview_scan",
                    observation_sha256=item.observation_hash,
                    record_ref=f"results/{item.record_index}",
                    received_at=item.received_at,
                    expires_at=item.received_at + timedelta(minutes=120),
                    symbol=symbol,
                    instrument_id=instrument,
                )
                identity = (ref,)
                sector = cells.get("Sector") or None
                report_currency = cells.get("Reporting currency")
                if type(report_currency) is not str or not re.fullmatch(
                    "[A-Z]{3}", report_currency
                ):
                    report_currency = None
                quote_currency = cells.get("Quotation currency")
                if type(quote_currency) is not str or not re.fullmatch("[A-Z]{3}", quote_currency):
                    quote_currency = None
                for name, display, unit in _COLUMNS:
                    currency = (
                        report_currency
                        if name == "total_stockholders_equity"
                        else (
                            quote_currency
                            if name in ("scanner_price", "provider_close_20", "provider_sma_50")
                            else None
                        )
                    )
                    metrics.append(
                        CurrentMetric(
                            name=name,
                            value=_number(cells.get(display)),
                            unit=unit,
                            period_basis="provider_current",
                            refs=identity,
                            currency=currency,
                        )
                    )
            else:
                needs.add(
                    ("held_scanner_missing:" if held else "candidate_scanner_missing:") + symbol
                )
            horizons: tuple[Literal["long_term", "tactical"], ...] = (
                (owned[symbol],) if held else ("long_term", "tactical")
            )
            for horizon in horizons:
                stocks.append(
                    CurrentStockEvidence(
                        symbol=symbol,
                        instrument_id=instrument,
                        instrument_type="stock",
                        horizon=horizon,
                        metrics=tuple(metrics),
                        identity_refs=identity,
                        sector=sector,
                        sector_refs=identity,
                        held=held,
                        dossier_hash=digest,
                    )
                )
        return CurrentStockEvidenceBatch(
            input_hash,
            PROFILE,
            tuple(stocks),
            tuple(sorted(needs)),
            now,
        )
    except Exception:
        raise ValueError("current_stock_evidence_invalid") from None
