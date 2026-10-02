"""Descriptive private execution measurements, never canonical cost certification.

Whole orders are the sampling unit. Charged fee totals are supplied once per
terminal order, not charged again for each partial fill. Paper results and public
fee schedules cannot establish customer treatment. No transport or broker exists.
Bounded inputs whose derived report values exceed canonical Decimal bounds are
rejected before returning measurements.
"""

import hashlib
import os
from datetime import datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import cast

from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.bundle_codec import (
    _array,
    _decimal,
    _digest,
    _json,
    _mapping,
    _string,
    _time,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_costs import _fee_context

MAX_CALIBRATION_BYTES = 1_048_576
MAX_ORDERS = 1000
_FEE_NAMES = ("commission", "sec", "taf", "cat", "other")
_LIMITS = BundleLimits(1_048_576, 1_048_576, 8_388_608, 10000, 32)


class EtfCalibrationError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_cost_calibration_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EtfCalibrationError()


def _integer(value: object) -> int:
    _check(type(value) is int and 0 <= value <= 2**63 - 1)
    return cast(int, value)


def _positive(value: object) -> Decimal:
    result = _decimal(value)
    require_bounded_decimal(result, "measurement value", positive=True)
    return result


def _bounded_array(value: object, maximum: int) -> list[object]:
    result = _array(value)
    _check(len(result) <= maximum)
    return result


def _quote(value: object) -> tuple[Decimal, Decimal, str]:
    row = _mapping(value, {"bid", "ask", "source_hash", "observed_at", "received_monotonic_ns"})
    bid, ask = _positive(row["bid"]), _positive(row["ask"])
    _check(bid < ask)
    _time(row["observed_at"])
    return bid, ask, _digest(row["source_hash"])


def _summary(values: list[Decimal]) -> dict[str, object] | None:
    if not values:
        return None
    ordered = sorted(values)
    with localcontext(Context(prec=40)):
        # Descriptive means/ratios require rounding, unlike cash conservation.
        return {
            "count": len(values),
            "mean": sum(values, Decimal(0)) / Decimal(len(values)),
            "p95_nearest_rank": ordered[(95 * len(values) + 99) // 100 - 1],
            "maximum": ordered[-1],
            "minimum": ordered[0],
        }


def _measure(body: bytes) -> dict[str, object]:
    _check(type(body) is bytes and 0 < len(body) <= MAX_CALIBRATION_BYTES)
    wire = _mapping(
        _json(body, max_bytes=MAX_CALIBRATION_BYTES, limits=_LIMITS),
        {"schema", "provenance", "execution_broker", "market_data_source", "orders"},
    )
    _check(wire["schema"] == "etf-cost-observations-v1")
    provenance = _string(wire["provenance"])
    _check(provenance in ("synthetic", "paper", "customer"))
    _check(wire["execution_broker"] == "robinhood")
    _check(wire["market_data_source"] == "alpaca-sip")
    orders = _bounded_array(wire["orders"], MAX_ORDERS)
    seen_orders: set[str] = set()
    seen_fills: set[str] = set()
    source_hashes: set[str] = set()
    slippage: dict[str, list[Decimal]] = {"buy": [], "sell": []}
    extra: dict[str, list[Decimal]] = {"buy": [], "sell": []}
    movement: dict[str, list[Decimal]] = {"buy": [], "sell": []}
    spread: dict[str, list[Decimal]] = {"buy": [], "sell": []}
    acknowledgement: list[Decimal] = []
    first_fill: list[Decimal] = []
    completion: list[Decimal] = []
    fees: dict[str, list[Decimal]] = {name: [] for name in (*_FEE_NAMES, "total")}
    notional = Decimal(0)
    fill_count = 0
    incomplete_fee_count = 0
    incomplete_timing_count = 0
    observed_start: datetime | None = None
    observed_end: datetime | None = None
    with localcontext(Context(prec=40)):
        for value in orders:
            order = _mapping(
                value,
                {
                    "order_hash",
                    "source_hash",
                    "terms_hash",
                    "side",
                    "submitted_at",
                    "submitted_monotonic_ns",
                    "acknowledged_monotonic_ns",
                    "clock_session_hash",
                    "terminal_monotonic_ns",
                    "decision_quote",
                    "arrival_quote",
                    "fills",
                    "charged_fees",
                    "fee_grouping",
                },
            )
            order_hash = _digest(order["order_hash"])
            _check(order_hash not in seen_orders)
            seen_orders.add(order_hash)
            source_hashes.update((_digest(order["source_hash"]), _digest(order["terms_hash"])))
            _digest(order["clock_session_hash"])
            side = _string(order["side"])
            _check(side in ("buy", "sell"))
            _check(order["fee_grouping"] == "terminal-order-total")
            submitted_at = _time(order["submitted_at"])
            observed_start = min(observed_start or submitted_at, submitted_at)
            observed_end = max(observed_end or submitted_at, submitted_at)
            submitted = _integer(order["submitted_monotonic_ns"])
            terminal = _integer(order["terminal_monotonic_ns"])
            _check(submitted <= terminal)
            ack_value = order["acknowledged_monotonic_ns"]
            ack = None if ack_value is None else _integer(ack_value)
            if ack is not None:
                _check(submitted <= ack <= terminal)
                acknowledgement.append(Decimal(ack - submitted) / Decimal(10**9))
            else:
                incomplete_timing_count += 1
            decision_bid, decision_ask, decision_hash = _quote(order["decision_quote"])
            arrival_bid, arrival_ask, arrival_hash = _quote(order["arrival_quote"])
            decision_time = _time(cast(dict[str, object], order["decision_quote"])["observed_at"])
            arrival_time = _time(cast(dict[str, object], order["arrival_quote"])["observed_at"])
            _check(decision_time <= submitted_at <= arrival_time)
            decision_mono = _integer(
                cast(dict[str, object], order["decision_quote"])["received_monotonic_ns"]
            )
            arrival_mono = _integer(
                cast(dict[str, object], order["arrival_quote"])["received_monotonic_ns"]
            )
            _check(decision_mono <= submitted <= arrival_mono)
            source_hashes.update((decision_hash, arrival_hash))
            fills = _bounded_array(order["fills"], 1000)
            _check(bool(fills))
            quantity, order_notional = Decimal(0), Decimal(0)
            previous = submitted
            first: int | None = None
            for fill_value in fills:
                fill = _mapping(
                    fill_value, {"fill_hash", "quantity", "price", "received_monotonic_ns"}
                )
                fill_hash = _digest(fill["fill_hash"])
                _check(fill_hash not in seen_fills)
                seen_fills.add(fill_hash)
                received = _integer(fill["received_monotonic_ns"])
                _check(previous <= received <= terminal)
                _check(ack is None or ack <= received)
                previous = received
                if first is None:
                    first = received
                size, price = _positive(fill["quantity"]), _positive(fill["price"])
                with localcontext(_fee_context()):
                    quantity += size
                    order_notional += size * price
                fill_count += 1
                _check(fill_count <= 10000)
            _check(first is not None)
            _check(arrival_mono <= cast(int, first))
            first_fill.append(Decimal(cast(int, first) - submitted) / Decimal(10**9))
            completion.append(Decimal(terminal - submitted) / Decimal(10**9))
            vwap = order_notional / quantity
            sign = Decimal(1) if side == "buy" else Decimal(-1)
            decision_side = decision_ask if side == "buy" else decision_bid
            arrival_side = arrival_ask if side == "buy" else arrival_bid
            midpoint = (decision_bid + decision_ask) / 2
            # All components use the same decision-side denominator, so movement
            # plus residual equals total. Spread is reported, never debited twice.
            slippage[side].append(sign * (vwap - decision_side) / decision_side * 10000)
            movement[side].append(sign * (arrival_side - decision_side) / decision_side * 10000)
            extra[side].append(sign * (vwap - arrival_side) / decision_side * 10000)
            spread[side].append(sign * (decision_side - midpoint) / midpoint * 10000)
            with localcontext(_fee_context()):
                notional += order_notional
            fee_value = order["charged_fees"]
            if fee_value is None:
                incomplete_fee_count += 1
                continue
            components = _mapping(fee_value, set((*_FEE_NAMES, "total", "source_hash")))
            source_hashes.add(_digest(components["source_hash"]))
            amounts = {name: _decimal(components[name]) for name in (*_FEE_NAMES, "total")}
            for amount in amounts.values():
                require_bounded_decimal(amount, "charged fee", nonnegative=True)
            with localcontext(_fee_context()):
                _check(sum((amounts[name] for name in _FEE_NAMES), Decimal(0)) == amounts["total"])
            for name, amount in amounts.items():
                fees[name].append(amount)
    reasons = [
        "declared_records_not_authenticated_customer_evidence",
        "sampling_representativeness_unverified",
        "published_fee_rules_and_effective_dates_unverified",
        "cash_yield_evidence_missing",
        "operating_cost_evidence_missing",
        "canonical_cost_calibration_unverified",
        "historical_execution_controls_unqualified",
    ]
    if provenance != "customer":
        reasons.append("paper_or_synthetic_is_not_customer_execution")
    if not orders:
        reasons.append("execution_observations_missing")
    if incomplete_fee_count:
        reasons.append("charged_fee_observations_incomplete")
    if incomplete_timing_count:
        reasons.append("acknowledgement_observations_incomplete")
    report: dict[str, object] = {
        "schema": "etf-cost-calibration-report-v1",
        "status": "OBSERVED_UNQUALIFIED" if orders else "BLOCKED_INPUTS",
        "input_sha256": hashlib.sha256(body).hexdigest(),
        "provenance": provenance,
        "execution_broker": "robinhood",
        "market_data_source": "alpaca-sip",
        "order_count": len(orders),
        "fill_count": fill_count,
        "fee_observed_order_count": len(fees["total"]),
        "missing_fee_order_count": incomplete_fee_count,
        "observed_submission_start": observed_start,
        "observed_submission_end": observed_end,
        "source_hashes": tuple(sorted(source_hashes)),
        "executed_notional_usd": notional,
        "signed_adverse_slippage_bps_by_side": {s: _summary(v) for s, v in slippage.items()},
        "market_movement_bps_by_side": {s: _summary(v) for s, v in movement.items()},
        "residual_beyond_arrival_quote_bps_by_side": {s: _summary(v) for s, v in extra.items()},
        "decision_half_spread_bps_by_side": {s: _summary(v) for s, v in spread.items()},
        "local_acknowledgement_seconds": _summary(acknowledgement),
        "local_first_fill_receipt_seconds": _summary(first_fill),
        "local_terminal_receipt_seconds": _summary(completion),
        "charged_order_fee_usd": {name: _summary(v) for name, v in fees.items()},
        "spread_in_fill_price": True,
        "timing_scope": "same-clock-session-local-receipts-not-exchange-fill-latency",
        "sampling_unit": "terminal-order",
        "reasons": tuple(reasons),
        "descriptive_decimal_precision": 40,
        "calibration_status": "unverified",
        "economic_verdict": "ECONOMIC_NO_GO",
        "source_qualified": False,
        "evidence_promotable": False,
        "execution_enabled": False,
        "live_authorized": False,
    }
    # Exact products/sums and descriptive ratios can expand beyond input bounds.
    # Validate the entire unchanged report with the same encoder used by storage.
    canonical_json(report)
    return report


def measure_etf_cost_observations(body: bytes) -> dict[str, object]:
    try:
        return _measure(body)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
        raise EtfCalibrationError() from None


def load_etf_cost_observations(
    path: Path, allowed_root: Path, repository_root: Path
) -> dict[str, object]:
    """Recheck all referenced raw identities privately; hashes are not authenticity."""
    descriptor = -1
    try:
        _check(isinstance(path, Path) and isinstance(allowed_root, Path))
        _check(path.parent == allowed_root and path.is_absolute())
        descriptor = _open_root(allowed_root, repository_root)
        report = measure_etf_cost_observations(_read(descriptor, path.name, MAX_CALIBRATION_BYTES))
        total_bytes = 0
        for digest in cast(tuple[str, ...], report["source_hashes"]):
            source = _read(descriptor, digest + ".source", MAX_CALIBRATION_BYTES)
            total_bytes += len(source)
            _check(total_bytes <= 8_388_608 and hashlib.sha256(source).hexdigest() == digest)
        report["reference_bytes_reverified"] = True
        report["report_hash"] = content_hash(report)
        return report
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        raise EtfCalibrationError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
