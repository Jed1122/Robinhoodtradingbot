"""Synthetic, offline checks for descriptive observations and private source loading."""

import hashlib
import importlib
import json
from copy import deepcopy
from decimal import ROUND_UP, Decimal, Inexact, Overflow, Rounded, Underflow, localcontext
from pathlib import Path

import pytest

from trading_bot.market_data.recording import content_hash

D = Decimal
AT = "2020-06-03T12:00:00.000000Z"
BEFORE = "2020-06-03T11:59:59.000000Z"
AFTER = "2020-06-03T12:00:01.000000Z"
SOURCE_BODIES = {
    hashlib.sha256(body).hexdigest(): body
    for body in (
        b"synthetic terminal-order observations",
        b"synthetic terms snapshot",
        b"synthetic decision quote",
        b"synthetic arrival quote",
        b"synthetic charged-fee statement",
    )
}
ORDER_SOURCE, TERMS_SOURCE, DECISION_SOURCE, ARRIVAL_SOURCE, FEE_SOURCE = SOURCE_BODIES


def api():
    return importlib.import_module("trading_bot.research.etf_cost_calibration")


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def order(index=0, *, side="buy"):
    return {
        "order_hash": digest(f"synthetic order {index}"),
        "source_hash": ORDER_SOURCE,
        "terms_hash": TERMS_SOURCE,
        "side": side,
        "submitted_at": AT,
        "submitted_monotonic_ns": 1_000_000_000,
        "acknowledged_monotonic_ns": 1_100_000_000,
        "clock_session_hash": digest("synthetic local clock session"),
        "terminal_monotonic_ns": 2_500_000_000,
        "decision_quote": {
            "bid": "98",
            "ask": "100",
            "source_hash": DECISION_SOURCE,
            "observed_at": BEFORE,
            "received_monotonic_ns": 900_000_000,
        },
        "arrival_quote": {
            "bid": "100",
            "ask": "102",
            "source_hash": ARRIVAL_SOURCE,
            "observed_at": AFTER,
            "received_monotonic_ns": 1_200_000_000,
        },
        "fills": [
            {
                "fill_hash": digest(f"synthetic fill {index}"),
                "quantity": "1",
                "price": "103",
                "received_monotonic_ns": 1_250_000_000,
            }
        ],
        "charged_fees": {
            "commission": "0.03",
            "sec": "0.01",
            "taf": "0.002",
            "cat": "0.0001",
            "other": "0",
            "total": "0.0421",
            "source_hash": FEE_SOURCE,
        },
        "fee_grouping": "terminal-order-total",
    }


def wire(*orders, provenance="synthetic"):
    return {
        "schema": "etf-cost-observations-v1",
        "provenance": provenance,
        "execution_broker": "robinhood",
        "market_data_source": "alpaca-sip",
        "orders": list(orders),
    }


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


def measure(*orders, provenance="synthetic"):
    return api().measure_etf_cost_observations(encoded(wire(*orders, provenance=provenance)))


def stat(report, name, *, side=None, component=None):
    value = report[name]
    if side is not None:
        value = value[side]
    if component is not None:
        value = value[component]
    return value


def assert_invalid(body):
    with pytest.raises(api().EtfCalibrationError) as caught:
        api().measure_etf_cost_observations(body)
    assert str(caught.value) == "etf_cost_calibration_invalid"
    assert caught.value.__suppress_context__


@pytest.fixture
def private_input(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "observations.json"
    path.write_bytes(encoded(wire(order())))
    path.chmod(0o600)
    for sha, body in SOURCE_BODIES.items():
        source = private / (sha + ".source")
        source.write_bytes(body)
        source.chmod(0o600)
    return path, private, repository


def test_partial_fill_vwap_measures_terminal_order_and_charges_fees_once():
    row = order()
    row["fills"][0].update(quantity="1", price="100")
    row["fills"].append(
        {
            "fill_hash": digest("synthetic later partial fill"),
            "quantity": "3",
            "price": "102",
            "received_monotonic_ns": 2_000_000_000,
        }
    )
    report = measure(row)
    assert report["order_count"] == 1 and report["fill_count"] == 2
    assert report["executed_notional_usd"] == D("406")
    assert stat(report, "signed_adverse_slippage_bps_by_side", side="buy")["mean"] == D("150")
    assert stat(report, "charged_order_fee_usd", component="total") == {
        "count": 1,
        "mean": D("0.0421"),
        "p95_nearest_rank": D("0.0421"),
        "maximum": D("0.0421"),
        "minimum": D("0.0421"),
    }
    assert report["fee_observed_order_count"] == 1
    assert report["sampling_unit"] == "terminal-order"


def test_slippage_uses_whole_orders_as_sampling_unit_instead_of_share_weighting():
    small, large = order(1), order(2)
    small["fills"][0].update(quantity="1", price="101")
    large["fills"][0].update(quantity="100", price="103")
    report = measure(small, large)
    assert stat(report, "signed_adverse_slippage_bps_by_side", side="buy") == {
        "count": 2,
        "mean": D("200"),
        "p95_nearest_rank": D("300"),
        "maximum": D("300"),
        "minimum": D("100"),
    }
    assert report["executed_notional_usd"] == D("10401")


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_adverse_slippage_decomposes_market_movement_and_arrival_residual(side):
    row = order(side=side)
    if side == "sell":
        row["decision_quote"].update(bid="100", ask="102")
        row["arrival_quote"].update(bid="98", ask="100")
        row["fills"][0]["price"] = "97"
    report = measure(row)
    total = stat(report, "signed_adverse_slippage_bps_by_side", side=side)["mean"]
    movement = stat(report, "market_movement_bps_by_side", side=side)["mean"]
    residual = stat(report, "residual_beyond_arrival_quote_bps_by_side", side=side)["mean"]
    assert (total, movement, residual) == (D("300"), D("200"), D("100"))
    assert total == movement + residual
    assert stat(report, "decision_half_spread_bps_by_side", side=side)["mean"] > 0
    assert (
        stat(report, "signed_adverse_slippage_bps_by_side", side="sell" if side == "buy" else "buy")
        is None
    )


@pytest.mark.parametrize("side,fill_price", [("buy", "99"), ("sell", "101")])
def test_price_improvement_has_negative_signed_adverse_slippage(side, fill_price):
    row = order(side=side)
    row["decision_quote"].update(
        bid="100" if side == "sell" else "98", ask="102" if side == "sell" else "100"
    )
    row["fills"][0]["price"] = fill_price
    report = measure(row)
    assert stat(report, "signed_adverse_slippage_bps_by_side", side=side)["mean"] == D("-100")


def test_fill_at_decision_ask_does_not_charge_reported_spread_again():
    row = order()
    row["arrival_quote"].update(bid="98", ask="100")
    row["fills"][0]["price"] = "100"
    report = measure(row)
    assert stat(report, "signed_adverse_slippage_bps_by_side", side="buy")["mean"] == 0
    assert stat(report, "decision_half_spread_bps_by_side", side="buy")["mean"] > 0
    assert report["spread_in_fill_price"] is True
    assert report["executed_notional_usd"] == D("100")
    assert stat(report, "charged_order_fee_usd", component="total")["mean"] == D("0.0421")


def test_exact_observed_fee_components_are_not_recomputed_from_public_rules():
    row = order()
    row["charged_fees"].update(commission="0", sec="0", taf="0", cat="0", other="0", total="0")
    report = measure(row)
    assert report["missing_fee_order_count"] == 0
    for name in ("commission", "sec", "taf", "cat", "other", "total"):
        assert stat(report, "charged_order_fee_usd", component=name)["mean"] == 0
    assert "published_fee_rules_and_effective_dates_unverified" in report["reasons"]


def test_nearest_rank_fee_p95_is_computed_across_terminal_orders():
    rows = [order(index) for index in range(1, 21)]
    for index, row in enumerate(rows, 1):
        row["charged_fees"].update(
            commission=str(index), sec="0", taf="0", cat="0", total=str(index)
        )
    result = stat(measure(*rows), "charged_order_fee_usd", component="total")
    assert result["count"] == 20
    assert result["mean"] == D("10.5")
    assert result["p95_nearest_rank"] == D("19")
    assert result["minimum"] == D("1") and result["maximum"] == D("20")


def test_timing_is_same_session_local_receipt_difference_in_seconds():
    report = measure(order())
    assert report["local_acknowledgement_seconds"]["mean"] == D("0.1")
    assert report["local_first_fill_receipt_seconds"]["mean"] == D("0.25")
    assert report["local_terminal_receipt_seconds"]["mean"] == D("1.5")
    assert report["timing_scope"] == "same-clock-session-local-receipts-not-exchange-fill-latency"


def test_simultaneous_local_events_are_observed_zero_seconds_not_missing():
    row = order()
    for field in ("submitted_monotonic_ns", "acknowledged_monotonic_ns", "terminal_monotonic_ns"):
        row[field] = 2**63 - 1
    row["fills"][0]["received_monotonic_ns"] = 2**63 - 1
    row["arrival_quote"]["received_monotonic_ns"] = 2**63 - 1
    report = measure(row)
    for name in (
        "local_acknowledgement_seconds",
        "local_first_fill_receipt_seconds",
        "local_terminal_receipt_seconds",
    ):
        assert report[name]["count"] == 1 and report[name]["mean"] == 0
    assert "acknowledgement_observations_incomplete" not in report["reasons"]


def test_missing_fees_and_acknowledgement_remain_missing_instead_of_zero():
    row = order()
    row["charged_fees"] = None
    row["acknowledged_monotonic_ns"] = None
    report = measure(row)
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    assert report["fee_observed_order_count"] == 0 and report["missing_fee_order_count"] == 1
    assert all(value is None for value in report["charged_order_fee_usd"].values())
    assert report["local_acknowledgement_seconds"] is None
    assert report["local_first_fill_receipt_seconds"]["mean"] == D("0.25")
    assert "charged_fee_observations_incomplete" in report["reasons"]
    assert "acknowledgement_observations_incomplete" in report["reasons"]


def test_missing_fee_order_is_excluded_from_fee_summary_sample_count():
    complete, missing = order(1), order(2)
    missing["charged_fees"] = None
    report = measure(complete, missing)
    assert report["order_count"] == 2 and report["missing_fee_order_count"] == 1
    assert stat(report, "charged_order_fee_usd", component="total")["count"] == 1
    assert stat(report, "charged_order_fee_usd", component="total")["mean"] == D("0.0421")


def test_no_orders_returns_blocked_inputs_and_no_invented_measurements():
    report = measure()
    assert report["status"] == "BLOCKED_INPUTS"
    assert report["order_count"] == report["fill_count"] == report["executed_notional_usd"] == 0
    assert report["observed_submission_start"] is report["observed_submission_end"] is None
    assert report["local_acknowledgement_seconds"] is None
    assert report["signed_adverse_slippage_bps_by_side"] == {"buy": None, "sell": None}
    assert "execution_observations_missing" in report["reasons"]


@pytest.mark.parametrize("provenance", ["synthetic", "paper", "customer"])
def test_declared_provenance_never_qualifies_customer_costs_or_execution(provenance):
    report = measure(order(), provenance=provenance)
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    assert report["calibration_status"] == "unverified"
    assert report["economic_verdict"] == "ECONOMIC_NO_GO"
    for name in ("source_qualified", "evidence_promotable", "execution_enabled", "live_authorized"):
        assert report[name] is False
    assert "declared_records_not_authenticated_customer_evidence" in report["reasons"]
    assert "canonical_cost_calibration_unverified" in report["reasons"]
    if provenance != "customer":
        assert "paper_or_synthetic_is_not_customer_execution" in report["reasons"]


def test_input_sha_and_all_source_reference_identities_are_reported_deterministically():
    body = encoded(wire(order()))
    report = api().measure_etf_cost_observations(body)
    assert report == api().measure_etf_cost_observations(body)
    assert report["input_sha256"] == hashlib.sha256(body).hexdigest()
    assert report["source_hashes"] == tuple(sorted(SOURCE_BODIES))
    assert (
        report["execution_broker"] == "robinhood" and report["market_data_source"] == "alpaca-sip"
    )


def test_hostile_ambient_decimal_context_cannot_change_fee_or_receipt_measurements():
    expected = measure(order())
    with localcontext() as context:
        context.prec, context.rounding, context.Emin, context.Emax = 1, ROUND_UP, -1, 1
        for signal in (Inexact, Rounded, Overflow, Underflow):
            context.traps[signal] = True
        context.flags[Inexact] = True
        flags, traps = dict(context.flags), dict(context.traps)
        assert measure(order()) == expected
        assert (context.prec, context.rounding, context.Emin, context.Emax) == (1, ROUND_UP, -1, 1)
        assert dict(context.flags) == flags and dict(context.traps) == traps


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"\xff",
        b"[]",
        b"null",
        b"NaN",
        b"1.25",
        b" " * 1_048_577,
        "{}",
        bytearray(b"{}"),
        None,
    ],
)
def test_invalid_wire_is_bounded_and_reports_only_sanitized_error(body):
    assert_invalid(body)


def test_duplicate_json_keys_and_injected_secret_like_fields_are_sanitized():
    marker = "Bearer synthetic-fixture-must-not-appear-in-errors"
    body = encoded(wire(order()))
    assert_invalid(body.replace(b'"schema":', b'"schema":"duplicate","schema":', 1))
    value = wire(order())
    value["Authorization"] = marker
    assert_invalid(encoded(value))
    value = wire(order())
    value["orders"][0]["side"] = marker
    assert_invalid(encoded(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "unknown"),
        ("provenance", "verified"),
        ("execution_broker", "alpaca"),
        ("market_data_source", "alpaca-iex"),
        ("orders", {}),
        ("orders", None),
    ],
)
def test_wrong_schema_provider_or_collection_cannot_be_treated_as_observations(field, value):
    document = wire(order())
    document[field] = value
    assert_invalid(encoded(document))


@pytest.mark.parametrize("field", ["order_hash", "source_hash", "terms_hash", "clock_session_hash"])
@pytest.mark.parametrize("value", [None, 1, "a" * 63, "g" * 64, "A" * 64])
def test_invalid_order_identity_and_clock_session_hash_are_rejected(field, value):
    row = order()
    row[field] = value
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("fee_grouping", "per-fill"),
        ("fills", []),
        ("side", "short"),
        ("submitted_at", "2020-06-03T12:00:00Z"),
        ("submitted_at", AFTER),
    ],
)
def test_invalid_grouping_empty_fills_side_and_submission_time_are_rejected(field, value):
    row = order()
    row[field] = value
    if field == "submitted_at" and value == AFTER:
        row["arrival_quote"]["observed_at"] = AT
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize(
    "field", ["submitted_monotonic_ns", "acknowledged_monotonic_ns", "terminal_monotonic_ns"]
)
@pytest.mark.parametrize("value", [True, False, "1", 1.5, -1, 2**63])
def test_monotonic_clocks_require_bounded_exact_nonnegative_integers(field, value):
    row = order()
    row[field] = value
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize(
    "case",
    [
        "terminal-before-submit",
        "ack-before-submit",
        "ack-after-terminal",
        "fill-before-submit",
        "fill-before-ack",
        "fill-after-terminal",
        "fill-reordered",
    ],
)
def test_inconsistent_local_receipt_ordering_is_rejected(case):
    row = order()
    if case == "terminal-before-submit":
        row["terminal_monotonic_ns"] = 0
    elif case == "ack-before-submit":
        row["acknowledged_monotonic_ns"] = 0
    elif case == "ack-after-terminal":
        row["acknowledged_monotonic_ns"] = 3_000_000_000
    elif case == "fill-before-submit":
        row["fills"][0]["received_monotonic_ns"] = 0
    elif case == "fill-before-ack":
        row["fills"][0]["received_monotonic_ns"] = 1_050_000_000
    elif case == "fill-after-terminal":
        row["fills"][0]["received_monotonic_ns"] = 3_000_000_000
    else:
        row["fills"].append(
            {
                **row["fills"][0],
                "fill_hash": digest("earlier synthetic fill"),
                "received_monotonic_ns": 1_200_000_000,
            }
        )
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize("case", ["order", "fill-in-order", "fill-across-orders"])
def test_duplicate_order_or_fill_identity_cannot_be_counted_twice(case):
    first, second = order(1), order(2)
    if case == "order":
        second["order_hash"] = first["order_hash"]
    elif case == "fill-in-order":
        first["fills"].append(deepcopy(first["fills"][0]))
    else:
        second["fills"][0]["fill_hash"] = first["fills"][0]["fill_hash"]
    assert_invalid(encoded(wire(first, second)))


@pytest.mark.parametrize("field", ["quantity", "price"])
@pytest.mark.parametrize(
    "value", ["0", "-1", "-0", "1.0", "01", "1e2", "NaN", "Infinity", "1" * 513, 1, True]
)
def test_fill_amounts_require_positive_finite_bounded_canonical_decimal_text(field, value):
    row = order()
    row["fills"][0][field] = value
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "unverified"),
        ("bid", "0"),
        ("ask", "0"),
        ("bid", "100"),
        ("bid", "101"),
        ("observed_at", AFTER),
    ],
)
def test_invalid_decision_quote_sources_amounts_or_future_observation_are_rejected(field, value):
    row = order()
    row["decision_quote"][field] = value
    assert_invalid(encoded(wire(row)))


def test_arrival_quote_cannot_precede_submission():
    row = order()
    row["arrival_quote"]["observed_at"] = BEFORE
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("commission", "-0.01"),
        ("sec", "NaN"),
        ("taf", "1e-3"),
        ("cat", 0),
        ("other", "0.00"),
        ("total", "0.0422"),
        ("source_hash", "not-a-digest"),
    ],
)
def test_fees_reject_bad_amounts_source_identity_and_total_mismatch(field, value):
    row = order()
    row["charged_fees"][field] = value
    assert_invalid(encoded(wire(row)))


def test_order_and_per_order_fill_limits_are_enforced_before_arithmetic():
    assert_invalid(encoded(wire(*[order(index) for index in range(1001)])))
    row = order()
    row["fills"] = [deepcopy(row["fills"][0]) for _ in range(1001)]
    assert_invalid(encoded(wire(row)))


def test_private_loader_rechecks_every_reference_and_hashes_repeatable_report(private_input):
    path, private, repository = private_input
    report = api().load_etf_cost_observations(path, private, repository)
    assert report["reference_bytes_reverified"] is True
    assert report["source_hashes"] == tuple(sorted(SOURCE_BODIES))
    report_hash = report.pop("report_hash")
    assert report_hash == content_hash(report)
    assert report_hash == api().load_etf_cost_observations(path, private, repository)["report_hash"]
    assert report["source_qualified"] is False and report["evidence_promotable"] is False


@pytest.mark.parametrize("source", list(SOURCE_BODIES))
@pytest.mark.parametrize("case", ["missing", "changed", "symlink", "public-permissions"])
def test_every_private_source_reference_must_be_present_unmodified_and_private(
    private_input, source, case
):
    path, private, repository = private_input
    source_path = private / (source + ".source")
    if case == "missing":
        source_path.unlink()
    elif case == "changed":
        source_path.write_bytes(b"altered synthetic source bytes")
    elif case == "symlink":
        source_path.unlink()
        source_path.symlink_to(
            private / (next(sha for sha in SOURCE_BODIES if sha != source) + ".source")
        )
    else:
        source_path.chmod(0o644)
    with pytest.raises(api().EtfCalibrationError, match=r"^etf_cost_calibration_invalid$"):
        api().load_etf_cost_observations(path, private, repository)


@pytest.mark.parametrize(
    "case",
    [
        "root-permissions",
        "file-permissions",
        "file-symlink",
        "root-symlink",
        "ancestor-symlink",
        "inside-repository",
        "different-parent",
        "relative-file",
        "relative-root",
        "parent-traversal",
        "missing-file",
    ],
)
def test_private_loader_rejects_unsafe_paths_and_permissions(private_input, case):
    path, private, repository = private_input
    if case == "root-permissions":
        private.chmod(0o755)
    elif case == "file-permissions":
        path.chmod(0o644)
    elif case == "file-symlink":
        target = private / "copy.json"
        target.write_bytes(path.read_bytes())
        target.chmod(0o600)
        path.unlink()
        path.symlink_to(target)
    elif case in ("root-symlink", "ancestor-symlink"):
        link = private.parent / "private-link"
        link.symlink_to(private, target_is_directory=True)
        if case == "ancestor-symlink":
            private = link / "nested"
            (link / "nested").mkdir(mode=0o700)
        else:
            private = link
        path = private / "observations.json"
    elif case == "inside-repository":
        repository = private.parent
    elif case == "different-parent":
        path = private.parent / "observations.json"
    elif case == "relative-file":
        path = Path("observations.json")
    elif case == "relative-root":
        private = Path("private")
        path = private / "observations.json"
    elif case == "parent-traversal":
        private = private / ".." / private.name
        path = private / "observations.json"
    else:
        path.unlink()
    with pytest.raises(api().EtfCalibrationError, match=r"^etf_cost_calibration_invalid$"):
        api().load_etf_cost_observations(path, private, repository)


@pytest.mark.parametrize("field", ["path", "allowed_root", "repository_root"])
@pytest.mark.parametrize("value", [None, "synthetic-invalid-path", 1])
def test_invalid_private_path_argument_types_are_sanitized(private_input, field, value):
    path, private, repository = private_input
    arguments = {"path": path, "allowed_root": private, "repository_root": repository}
    arguments[field] = value
    with pytest.raises(api().EtfCalibrationError, match=r"^etf_cost_calibration_invalid$"):
        api().load_etf_cost_observations(**arguments)


@pytest.mark.parametrize("quote_name", ["decision_quote", "arrival_quote"])
@pytest.mark.parametrize("value", [None, True, "100", -1, 2**63])
def test_quote_receipt_clock_requires_same_bounded_integer_shape(quote_name, value):
    row = order()
    row[quote_name]["received_monotonic_ns"] = value
    assert_invalid(encoded(wire(row)))


@pytest.mark.parametrize(
    "case", ["decision-after-submit", "arrival-before-submit", "arrival-after-first-fill"]
)
def test_quote_receipts_cannot_use_future_quotes_after_decision_or_fill(case):
    row = order()
    if case == "decision-after-submit":
        row["decision_quote"]["received_monotonic_ns"] = 1_000_000_001
    elif case == "arrival-before-submit":
        row["arrival_quote"]["received_monotonic_ns"] = 999_999_999
    else:
        row["arrival_quote"]["received_monotonic_ns"] = 1_250_000_001
    assert_invalid(encoded(wire(row)))


def test_quote_receipts_at_submit_and_first_fill_are_causally_allowed():
    row = order()
    row["decision_quote"]["received_monotonic_ns"] = row["submitted_monotonic_ns"]
    row["arrival_quote"]["received_monotonic_ns"] = row["fills"][0]["received_monotonic_ns"]
    assert measure(row)["status"] == "OBSERVED_UNQUALIFIED"


def test_execution_notional_conserves_exact_high_precision_partial_fill_cash():
    row = order()
    row["fills"][0].update(quantity="1", price="100.00000000000000000000000000000000000000001")
    row["fills"].append(
        {
            "fill_hash": digest("synthetic precision-sensitive fill"),
            "quantity": "1",
            "price": "0.00000000000000000000000000000000000000001",
            "received_monotonic_ns": 2_000_000_000,
        }
    )
    assert measure(row)["executed_notional_usd"] == D(
        "100.00000000000000000000000000000000000000002"
    )


def test_fee_reconciliation_does_not_round_away_a_small_component():
    row = order()
    row["charged_fees"].update(
        commission="1",
        sec="0.00000000000000000000000000000000000000001",
        taf="0",
        cat="0",
        other="0",
        total="1",
    )
    assert_invalid(encoded(wire(row)))
    row["charged_fees"]["total"] = "1.00000000000000000000000000000000000000001"
    report = measure(row)
    assert stat(report, "charged_order_fee_usd", component="total")["maximum"] == D(
        row["charged_fees"]["total"]
    )
    assert stat(report, "charged_order_fee_usd", component="sec")["minimum"] == D(
        row["charged_fees"]["sec"]
    )


@pytest.mark.parametrize(
    "location", ["order", "decision_quote", "arrival_quote", "fill", "charged_fees"]
)
@pytest.mark.parametrize("case", ["extra-field", "missing-field", "wrong-collection"])
def test_nested_observation_schema_rejects_partial_or_unrecognized_records(location, case):
    row = order()
    if location == "order":
        target = row
    elif location == "fill":
        target = row["fills"][0]
    else:
        target = row[location]
    if case == "extra-field":
        target["synthetic-unknown-field"] = "fixture-value"
    elif case == "missing-field":
        target.pop(next(iter(target)))
    elif location == "order":
        row = []
    elif location == "fill":
        row["fills"][0] = []
    else:
        row[location] = []
    assert_invalid(encoded(wire(row)))


def test_private_loader_bounds_total_referenced_source_bytes(private_input):
    path, private, repository = private_input
    rows = [order(1), order(2)]
    refs = (
        [(row, "source_hash") for row in rows]
        + [(row, "terms_hash") for row in rows]
        + [
            (row[quote], "source_hash")
            for row in rows
            for quote in ("decision_quote", "arrival_quote")
        ]
        + [(row["charged_fees"], "source_hash") for row in rows]
    )
    for index, (target, key) in enumerate(refs):
        body = bytes([65 + index]) * 1_048_576
        sha = hashlib.sha256(body).hexdigest()
        target[key] = sha
        source = private / (sha + ".source")
        source.write_bytes(body)
        source.chmod(0o600)
    path.write_bytes(encoded(wire(*rows)))
    with pytest.raises(api().EtfCalibrationError, match=r"^etf_cost_calibration_invalid$"):
        api().load_etf_cost_observations(path, private, repository)


def test_private_loader_does_not_read_nonregular_input_or_source(private_input):
    path, private, repository = private_input
    path.unlink()
    path.mkdir(mode=0o600)
    with pytest.raises(api().EtfCalibrationError, match=r"^etf_cost_calibration_invalid$"):
        api().load_etf_cost_observations(path, private, repository)
    path.rmdir()
    path.write_bytes(encoded(wire(order())))
    path.chmod(0o600)
    source = private / (ORDER_SOURCE + ".source")
    source.unlink()
    source.mkdir(mode=0o600)
    with pytest.raises(api().EtfCalibrationError, match=r"^etf_cost_calibration_invalid$"):
        api().load_etf_cost_observations(path, private, repository)


@pytest.mark.parametrize(
    "quantity,price",
    [
        ("9" * 512, "9" * 512),
        ("9" * 512, "103"),
        ("0." + "0" * 509 + "1", "0." + "0" * 509 + "1"),
    ],
    ids=["1024-digit-product", "large-product-with-bounded-ratios", "tiny-product"],
)
def test_measure_denies_exact_products_that_cannot_enter_canonical_reports(quantity, price):
    row = order()
    row["fills"][0].update(quantity=quantity, price=price)
    assert_invalid(encoded(wire(row)))


def test_measure_denies_aggregate_cash_sum_that_outgrows_canonical_decimal_bounds():
    first, second = order(1), order(2)
    for row in (first, second):
        row["fills"][0].update(quantity="5" + "0" * 511, price="1")
    # Each 512-character order notional is representable; their exact sum is not.
    assert_invalid(encoded(wire(first, second)))


def test_measure_denies_ratio_expansion_even_when_executed_cash_is_representable():
    row = order()
    for quote in (row["decision_quote"], row["arrival_quote"]):
        quote.update(bid="0." + "0" * 508 + "1", ask="0." + "0" * 508 + "2")
    row["fills"][0].update(quantity="1", price="1")
    # Both quote inputs fit 511 characters, but adverse bps expand to 513.
    assert_invalid(encoded(wire(row)))


def test_exact_notional_at_canonical_length_boundary_is_accepted_and_hashable(private_input):
    row = order()
    row["fills"][0].update(quantity="9" * 510, price="100")
    body = encoded(wire(row))
    report = api().measure_etf_cost_observations(body)
    expected_cash = "9" * 510 + "00"
    assert report["executed_notional_usd"] == D(expected_cash)
    assert len(expected_cash) == 512
    assert len(content_hash(report)) == 64
    path, private, repository = private_input
    path.write_bytes(body)
    loaded_report = api().load_etf_cost_observations(path, private, repository)
    assert loaded_report["executed_notional_usd"] == report["executed_notional_usd"]
    assert loaded_report["report_hash"] == content_hash(
        {**report, "reference_bytes_reverified": True}
    )


def test_ratio_at_canonical_length_boundary_is_accepted_and_hashable():
    row = order()
    for quote in (row["decision_quote"], row["arrival_quote"]):
        quote.update(bid="0." + "0" * 507 + "1", ask="0." + "0" * 507 + "2")
    row["fills"][0].update(quantity="1", price="1")
    report = measure(row)
    assert report["executed_notional_usd"] == 1
    assert stat(report, "signed_adverse_slippage_bps_by_side", side="buy")["maximum"] == D(
        "5" + "0" * 511
    )
    assert len(content_hash(report)) == 64


def test_canonical_closure_acceptance_and_denial_are_independent_of_caller_decimal_context():
    valid, invalid = order(1), order(2)
    valid["fills"][0].update(quantity="9" * 510, price="100")
    invalid["fills"][0].update(quantity="9" * 512, price="103")
    expected = measure(valid)
    with localcontext() as context:
        context.prec, context.rounding, context.Emin, context.Emax = 1, ROUND_UP, -1, 1
        for signal in (Inexact, Rounded, Overflow, Underflow):
            context.traps[signal] = True
        context.flags[Inexact] = True
        flags, traps = dict(context.flags), dict(context.traps)
        assert measure(valid) == expected
        assert_invalid(encoded(wire(invalid)))
        assert (context.prec, context.rounding, context.Emin, context.Emax) == (1, ROUND_UP, -1, 1)
        assert dict(context.flags) == flags and dict(context.traps) == traps


def test_measure_denies_fee_mean_rounding_that_expands_past_canonical_bounds():
    row = order()
    row["charged_fees"].update(
        commission="9" * 512, sec="0", taf="0", cat="0", other="0", total="9" * 512
    )
    # Exact component reconciliation fits, but the 40-digit mean rounds upward
    # to a 513-character value. Every reported Decimal must remain encodable.
    assert_invalid(encoded(wire(row)))


def test_private_loader_and_pure_measure_deny_same_unrepresentable_cash_report(private_input):
    row = order()
    row["fills"][0].update(quantity="9" * 512, price="103")
    body = encoded(wire(row))
    assert_invalid(body)
    path, private, repository = private_input
    path.write_bytes(body)
    with pytest.raises(api().EtfCalibrationError) as caught:
        api().load_etf_cost_observations(path, private, repository)
    assert str(caught.value) == "etf_cost_calibration_invalid"
    assert caught.value.__suppress_context__
