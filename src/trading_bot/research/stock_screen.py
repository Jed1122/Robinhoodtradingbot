"""Numerical stock research priorities; no forecasts, qualification or order authority."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, DecimalException
from typing import Any

from trading_bot.clock import require_utc
from trading_bot.config.stock_research import StockResearchSettings
from trading_bot.domain.decimal_utils import require_bounded_decimal

TURNOVER_COLUMN = 'turnoverAvg(candleCount={sessions}, candlePeriod="1d", session="regular")'
LEGACY_WORKER_PROFILE = "stock-worker-v1"
CURRENT_PROVIDER_WORKER_PROFILE = "stock-worker-current-provider-v1"
_COLUMNS = {
    "roe": ("Return on equity", "fundamental.returnOnEquity"),
    "net_margin": ("Net profit margin", "fundamental.netProfitMargin"),
    "annual_eps_growth": ("Annual EPS growth", "fundamental.annualEpsGrowth"),
    "quarterly_revenue_growth": ("Quarterly revenue growth", "fundamental.quarterlyRevenueGrowth"),
    "pe": ("P/E", "fundamental.peRatio"),
    "fcf_per_share": ("FCF/share", "fundamental.cashFlowFreePerShare"),
}
_CURRENT_COLUMNS = {
    "price_to_fcf": ("P/FCF", "fundamental.pfcfRatio"),
    "total_stockholders_equity": ("Total stockholders equity", "fundamental.totalStockEquity"),
    "assets_to_equity": ("Assets/equity", "fundamental.totalAssetsEquityRatio"),
    "report_currency": ("Reporting currency", "fundamental.reportCurrency"),
    "provider_close_20": (
        "Provider close 20",
        'close(candleCount=20, candlePeriod="1d", session="regular")',
    ),
    "provider_sma_50": (
        "Provider SMA 50",
        'closeAvg(candleCount=50, candlePeriod="1d", session="regular")',
    ),
    "quotation_currency": ("Quotation currency", "currency"),
}


def _current_profile(worker_profile_id: str) -> bool:
    if type(worker_profile_id) is not str or worker_profile_id not in (
        LEGACY_WORKER_PROFILE,
        CURRENT_PROVIDER_WORKER_PROFILE,
    ):
        raise ValueError("stock_screen_invalid")
    return worker_profile_id == CURRENT_PROVIDER_WORKER_PROFILE


def discovery_requests(
    policy: StockResearchSettings, *, worker_profile_id: str = LEGACY_WORKER_PROFILE
) -> list[dict[str, Any]]:
    """Non-overlapping market-cap partitions; completeness must be verified afterward."""
    current = _current_profile(worker_profile_id)
    requests: list[dict[str, Any]] = [{"tool": "get_scanner_filter_specs", "arguments": {}}]
    columns = [
        {"display_name": title, "expression": expression} for title, expression in _COLUMNS.values()
    ]
    columns.append({"display_name": "Sector", "expression": "fundamental.morningstarSectorLabel"})
    if current:
        columns.extend(
            {"display_name": title, "expression": expression}
            for title, expression in _CURRENT_COLUMNS.values()
        )
    for index, lower in enumerate(policy.market_cap_boundaries_usd):
        filters: list[dict[str, Any]] = [
            {"filter_type": "FILTER_TYPE_INSTRUMENT_TYPE", "predicate": "=", "values": ["STOCK"]},
            {
                "filter_type": "FILTER_TYPE_LAST",
                "predicate": ">=",
                "values": [str(policy.minimum_price_usd)],
            },
            {
                "expression": TURNOVER_COLUMN.format(sessions=policy.turnover_sessions),
                "predicate": ">=",
                "values": [str(policy.minimum_scanner_turnover_usd)],
            },
            {"filter_type": "FILTER_TYPE_MARKET_CAP", "predicate": ">=", "values": [str(lower)]},
        ]
        if index + 1 < len(policy.market_cap_boundaries_usd):
            filters.append(
                {
                    "filter_type": "FILTER_TYPE_MARKET_CAP",
                    "predicate": "<",
                    "values": [str(policy.market_cap_boundaries_usd[index + 1])],
                }
            )
        requests.append(
            {"tool": "preview_scan", "arguments": {"filters": filters, "columns": columns}}
        )
    return requests


def _key(item: Mapping[str, Any], *, echoed: bool) -> tuple[object, ...]:
    kind = (
        item.get("filter_type_enum", item.get("filter_type")) if echoed else item.get("filter_type")
    )
    if kind == "FILTER_TYPE_CUSTOM":
        kind = None
    predicate = item.get("predicate")
    if kind == "FILTER_TYPE_INSTRUMENT_TYPE" and predicate == "ANY_OF":
        predicate = "="
    return (
        kind,
        item.get("expression") if kind is None else None,
        predicate,
        tuple(item.get("values") or []),
    )


def _decimal(value: object) -> Decimal | None:
    if type(value) is not str or not value or len(value) > 80:
        return None
    try:
        result = require_bounded_decimal(Decimal(value), "stock factor")
        return result if result.copy_abs() < Decimal("1e30") else None
    except (DecimalException, ValueError):
        return None


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    try:
        result = require_bounded_decimal(numerator / denominator, "derived stock factor")
        return result if result.copy_abs() < Decimal("1e30") else None
    except (DecimalException, ValueError):
        return None


def _percentile(value: Decimal, peers: Sequence[Decimal]) -> Decimal:
    if len(peers) == 1:
        return Decimal("0.5")
    below = sum(item < value for item in peers)
    tied = sum(item == value for item in peers)
    return (Decimal(below) + Decimal(tied - 1) / 2) / Decimal(len(peers) - 1)


def screen_stocks(
    observations: Sequence[Mapping[str, Any]],
    *,
    policy: StockResearchSettings,
    as_of: datetime,
    worker_profile_id: str = LEGACY_WORKER_PROFILE,
) -> dict[str, object]:
    """Rank only complete, current partition coverage; missing facts are never zero-filled.

    Scores order research effort, with fixed experimental weights. Sequential scans
    are not atomic snapshots. Turnover is the broker's scanner feature until actual
    completed raw OHLCV observations independently establish dollar-volume eligibility.
    """
    try:
        current = _current_profile(worker_profile_id)
        now = require_utc(as_of)
        if not 0 <= len(observations) <= 24:
            raise ValueError("observation count invalid")
        expected = {
            tuple(_key(f, echoed=False) for f in request["arguments"]["filters"]): request
            for request in discovery_requests(policy, worker_profile_id=worker_profile_id)[1:]
        }
        seen: set[tuple[tuple[object, ...], ...]] = set()
        symbols: set[str] = set()
        instruments: set[str] = set()
        candidates: list[dict[str, Any]] = []
        issues: set[str] = set()
        for observation in observations:
            if observation["tool"] != "preview_scan":
                raise ValueError("stock scan required")
            stamp = require_utc(datetime.fromisoformat(observation["received_at"]))
            if stamp > now:
                raise ValueError("future stock observation")
            if (now - stamp).total_seconds() > policy.maximum_source_age_minutes * 60:
                issues.add("stale_partition")
            digest = observation["observation_sha256"]
            if type(digest) is not str or re.fullmatch("[0-9a-f]{64}", digest) is None:
                raise ValueError("stock observation identity invalid")
            filters = observation["arguments"]["filters"]
            key = tuple(_key(item, echoed=False) for item in filters)
            if key in seen:
                raise ValueError("repeated stock partition")
            if key not in expected:
                issues.add("unexpected_partition")
                continue
            if observation["arguments"] != expected[key]["arguments"]:
                raise ValueError("stock factor column identity mismatch")
            seen.add(key)
            result = observation["payload"]["data"]["result"]
            if Counter(_key(item, echoed=True) for item in result["filters_applied"]) != Counter(
                key
            ):
                raise ValueError("stock filter echo mismatch")
            rows = result["results"]
            total = result["total_items"]
            if (
                type(rows) is not list
                or not len(rows) <= 200
                or type(total) is not int
                or total < len(rows)
            ):
                raise ValueError("stock scan count invalid")
            if total != len(rows):
                issues.add("truncated_partition")
            lower = next(
                Decimal(item["values"][0])
                for item in filters
                if item.get("filter_type") == "FILTER_TYPE_MARKET_CAP" and item["predicate"] == ">="
            )
            upper = next(
                (
                    Decimal(item["values"][0])
                    for item in filters
                    if item.get("filter_type") == "FILTER_TYPE_MARKET_CAP"
                    and item["predicate"] == "<"
                ),
                None,
            )
            for row in rows:
                symbol, instrument = row["ticker"], row["instrument_id"]
                if (
                    type(symbol) is not str
                    or re.fullmatch(r"[A-Z][A-Z0-9.\-/]{0,14}", symbol) is None
                ):
                    raise ValueError("stock symbol invalid")
                if type(instrument) is not str or not 1 <= len(instrument) <= 128:
                    raise ValueError("stock instrument identity invalid")
                if symbol in symbols or instrument in instruments:
                    issues.add("overlapping_partition_membership")
                    continue
                symbols.add(symbol)
                instruments.add(instrument)
                cells = row["columns"]
                price, cap = _decimal(cells.get("Last")), _decimal(cells.get("Market cap"))
                turnover = _decimal(
                    cells.get(TURNOVER_COLUMN.format(sessions=policy.turnover_sessions))
                )
                if (
                    row["instrument_type"] != "EQUITY"
                    or cells.get("Asset type") != "STOCK"
                    or price is None
                    or price < policy.minimum_price_usd
                    or cap is None
                    or cap < lower
                    or (upper is not None and cap >= upper)
                    or turnover is None
                    or turnover < policy.minimum_scanner_turnover_usd
                ):
                    raise ValueError("stock row violates screening scope")
                metrics = {
                    name: _decimal(cells.get(column)) for name, (column, _) in _COLUMNS.items()
                }
                metrics["earnings_yield"] = _ratio(Decimal(1), metrics["pe"])
                if current:
                    metrics.update(
                        {
                            name: _decimal(cells.get(column))
                            for name, (column, _) in _CURRENT_COLUMNS.items()
                            if name not in ("report_currency", "quotation_currency")
                        }
                    )
                    metrics["fcf_yield"] = _ratio(Decimal(1), metrics["price_to_fcf"])
                else:
                    metrics["fcf_yield"] = _ratio(metrics["fcf_per_share"], price)
                sector = cells.get("Sector", "")
                if type(sector) is not str or len(sector) > 128:
                    raise ValueError("stock sector invalid")
                candidate: dict[str, Any] = {
                    "symbol": symbol,
                    "sector": sector,
                    "metrics": metrics,
                    "source_observation_sha256": digest,
                    "available_at": stamp.isoformat(),
                }
                if current:
                    for name, column in (
                        ("report_currency", "Reporting currency"),
                        ("quotation_currency", "Quotation currency"),
                    ):
                        currency = cells.get(column)
                        candidate["metrics"][name] = (
                            currency
                            if type(currency) is str and re.fullmatch(r"[A-Z]{3}", currency)
                            else None
                        )
                candidates.append(candidate)
        if len(seen) != len(expected):
            issues.add("missing_partition")
        complete = not issues
        factors = (
            "roe",
            "net_margin",
            "annual_eps_growth",
            "quarterly_revenue_growth",
            "earnings_yield",
            "fcf_yield",
        )
        excluded = [
            {
                "symbol": row["symbol"],
                "reason": "missing_or_unusable_factors",
                "missing": [factor for factor in factors if row["metrics"][factor] is None],
            }
            for row in candidates
            if any(row["metrics"][factor] is None for factor in factors)
        ]
        usable = [
            row
            for row in candidates
            if all(row["metrics"][factor] is not None for factor in factors)
        ]
        ranked: list[dict[str, Any]] = []
        if complete:
            for row in usable:
                sector_peers = [item for item in usable if item["sector"] == row["sector"]]
                sector_based = (
                    bool(row["sector"]) and len(sector_peers) >= policy.minimum_sector_peers
                )
                peers = sector_peers if sector_based else usable
                ranks = {
                    factor: _percentile(
                        row["metrics"][factor], [item["metrics"][factor] for item in peers]
                    )
                    for factor in factors
                }
                quality = (ranks["roe"] + ranks["net_margin"]) / 2
                growth = (ranks["annual_eps_growth"] + ranks["quarterly_revenue_growth"]) / 2
                value = (ranks["earnings_yield"] + ranks["fcf_yield"]) / 2
                score = (
                    quality * policy.quality_weight_pct
                    + growth * policy.growth_weight_pct
                    + value * policy.valuation_weight_pct
                )
                ranked.append(
                    row
                    | {
                        "research_priority_score": str(score.quantize(Decimal("0.01"))),
                        "peer_basis": "sector" if sector_based else "all_observed_companies",
                        "peer_count": len(peers),
                        "metrics": {
                            name: None if item is None else str(item)
                            for name, item in row["metrics"].items()
                        },
                        "investment_eligible": False,
                        "risk_flags": [
                            "balance_sheet_unverified",
                            "filing_review_pending",
                            "completed_raw_dollar_volume_unverified",
                            "strategy_unqualified",
                        ],
                    }
                )
            ranked.sort(key=lambda row: (-Decimal(row["research_priority_score"]), row["symbol"]))
        report = {
            "as_of": now.isoformat(),
            "policy_id": policy.policy_id,
            "qualified": False,
            "live_enabled": False,
            "coverage_complete": complete,
            "snapshot_atomic": False,
            "coverage_issues": sorted(issues),
            "expected_partitions": len(expected),
            "observed_partitions": len(seen),
            "candidate_count": len(candidates),
            "scorable_count": len(usable),
            "excluded": excluded,
            "opportunities": ranked[: policy.shortlist_count],
            "score_meaning": (
                "Relative research priority; no calibrated relationship to future returns."
            ),
        }
        if current:
            report.update(
                {
                    "worker_profile_id": worker_profile_id,
                    "provider_price_basis": "current_provider_snapshot_not_completed_close",
                    "balance_sheet_date": None,
                }
            )
        return report
    except (KeyError, TypeError, ValueError, DecimalException, OverflowError):
        raise ValueError("stock_screen_invalid") from None
