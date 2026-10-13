"""Exact source controls for account-local original-event identity serialization."""

import copy
import dataclasses
import hashlib
import unittest
from datetime import UTC, timedelta, tzinfo
from decimal import Decimal as D
from decimal import localcontext
from unittest.mock import patch

from tests.unit.simulation.test_etf_capital_account import opening, script
from tests.unit.simulation.test_etf_capital_action_account import action
from trading_bot.domain import AssetClass, OrderEvent, Side
from trading_bot.market_data.recording import canonical_json
from trading_bot.simulation import etf_capital_account as account


def event_json(event, *, actions):
    account._admit_event(event, legacy=False, actions=actions)
    return account._original_event_json(event)


def fixtures():
    return (*script(), action("split"), action(), action("payment", 6))


class SourcePreimageControls(unittest.TestCase):
    def test_literal_all_eight_shapes(self):
        # Literal goldens are independently specified, not reflected from event fields.
        cursor = '{"occurred_at":"2026-09-17T00:00:08.000000Z","sequence":8}'
        self.assertEqual(
            event_json(script()[8], actions=True),
            '{"cursor":' + cursor + ',"event_id":"settle-sale","fill_id":"sell-fill"}',
        )
        expected = {
            "symbol": "SPY",
            "episode_fee_bound": "0.1",
            "execution_enabled": False,
            "request": {
                "cash": "100",
                "events": [],
                "submitted": {"sequence": 0, "occurred_at": "2026-09-17T00:00:00.000000Z"},
                "order": {
                    "id": "order-0",
                    "broker_order_id": "broker-0",
                    "account_id": "synthetic-account",
                    "intent_id": None,
                    "client_order_id": None,
                    "instrument_id": "capital-research:SPY",
                    "side": "buy",
                    "purpose": "entry",
                    "order_type": "limit",
                    "time_in_force": "good_til_canceled",
                    "requested_quantity": "0.2",
                    "filled_quantity": "0",
                    "limit_price": "100",
                    "stop_price": None,
                    "state": "submission_pending",
                    "created_at": "2026-09-17T00:00:00.000000Z",
                    "updated_at": "2026-09-17T00:00:00.000000Z",
                    "data_hash": "a" * 64,
                },
                "position": {
                    "account_id": "synthetic-account",
                    "instrument_id": "capital-research:SPY",
                    "asset_class": "equity",
                    "quantity": "0",
                    "average_price": None,
                    "market_value": "0",
                    "observed_at": "2026-09-17T00:00:00.000000Z",
                    "data_hash": "b" * 64,
                },
            },
        }
        self.assertEqual(event_json(opening(), actions=True), canonical_json(expected))
        self.assertEqual(
            event_json(script()[1], actions=True),
            canonical_json(
                {
                    "event_id": "accepted-buy",
                    "cursor": {"sequence": 1, "occurred_at": "2026-09-17T00:00:01.000000Z"},
                    "account_id": "synthetic-account",
                    "instrument_id": "capital-research:SPY",
                    "broker_order_id": "broker-0",
                    "event": "broker_accepted",
                }
            ),
        )
        self.assertEqual(
            event_json(script()[2], actions=True),
            canonical_json(
                {
                    "event_id": "buy-fill",
                    "cursor": {"sequence": 2, "occurred_at": "2026-09-17T00:00:02.000000Z"},
                    "fill": {
                        "id": "buy-fill",
                        "broker_order_id": "broker-0",
                        "account_id": "synthetic-account",
                        "instrument_id": "capital-research:SPY",
                        "side": "buy",
                        "quantity": "0.1",
                        "price": "99",
                        "fee": "0.04",
                        "occurred_at": "2026-09-17T00:00:02.000000Z",
                        "data_hash": "c" * 64,
                    },
                }
            ),
        )
        self.assertEqual(
            event_json(script()[9], actions=True),
            canonical_json(
                {
                    "event_id": "final-fees",
                    "cursor": {"sequence": 9, "occurred_at": "2026-09-17T00:00:09.000000Z"},
                    "total_fees": "0.09",
                    "account_id": "synthetic-account",
                    "opening_order_id": "order-0",
                }
            ),
        )
        common = {
            "event_id": "action-5",
            "cursor": {"sequence": 5, "occurred_at": "2026-09-17T00:00:05.000000Z"},
            "account_id": "synthetic-account",
            "opening_order_id": "order-0",
            "symbol": "SPY",
            "execution_enabled": False,
            "source_qualified": False,
            "evidence_promotable": False,
        }
        self.assertEqual(
            event_json(action("split"), actions=True),
            canonical_json(
                {
                    **common,
                    "action_id": "split-1",
                    "record_hash": "a" * 64,
                    "ratio": "2",
                    "post_action_mark": "49.5",
                }
            ),
        )
        self.assertEqual(
            event_json(action(), actions=True),
            canonical_json(
                {
                    **common,
                    "action_id": "distribution-1",
                    "record_hash": "b" * 64,
                    "amount_per_share": "1",
                    "ex_mark": "98",
                    "pay_date": "2026-09-17",
                }
            ),
        )
        self.assertEqual(
            event_json(action("payment"), actions=True),
            canonical_json({**common, "entitlement_id": "distribution-1", "amount": "0.1"}),
        )

    def test_bytes_variants_decimal_context_escaping_optional(self):
        cases = list(fixtures())
        for amount in ("0", "-0.000", "0E+9", "0.0400", "4E-2", "0." + "0" * 110 + "1"):
            cases.append(
                dataclasses.replace(
                    script()[2], fill=dataclasses.replace(script()[2].fill, fee=D(amount))
                )
            )
        item = opening()
        order = dataclasses.replace(
            item.request.order, intent_id='say"hi\\雪', client_order_id="literal\nvalue"
        )
        cases.append(
            dataclasses.replace(item, request=dataclasses.replace(item.request, order=order))
        )
        for precision in (2, 28, 100):
            with localcontext() as ctx:
                ctx.prec = precision
                for item in cases:
                    with self.subTest(precision=precision, kind=type(item).__name__):
                        expected = canonical_json(item).encode()
                        got = event_json(item, actions=True).encode()
                        self.assertEqual(got, expected)
                        self.assertEqual(
                            hashlib.sha256(got).digest(), hashlib.sha256(expected).digest()
                        )

    def test_invalid_original_denied_before_encoder_or_copy(self):
        cases = []
        for field, value in (
            ("execution_enabled", 0),
            ("episode_fee_bound", True),
            ("symbol", "BAD"),
        ):
            item = opening()
            object.__setattr__(item, field, value)
            cases.append(item)
        item = opening()
        object.__setattr__(item.request.order, "intent_id", " ")
        cases.append(item)
        for item in cases:
            with (
                patch(
                    "trading_bot.market_data.recording.dataclasses.asdict",
                    side_effect=AssertionError("copied before admission"),
                ),
                self.assertRaises(ValueError),
            ):
                event_json(item, actions=True)
        with self.assertRaises(ValueError):
            event_json(action(), actions=False)

    def test_fresh_admission_every_original_in_real_owner(self):
        tape = script()
        progress = None
        with patch.object(account, "_admit_event", wraps=account._admit_event) as admit:
            for end in range(1, len(tape) + 1):
                progress, _ = account._account_prefixes_owned(
                    progress, initial_cash=D("100"), events=tape[:end], actions=False
                )
            # 55 original admissions plus the ten new suffix events in the reducer.
            self.assertEqual(admit.call_count, 65)
            object.__setattr__(tape[0], "execution_enabled", 0)
            with (
                patch.object(
                    account, "_original_event_json", side_effect=AssertionError("too early")
                ),
                self.assertRaises(ValueError),
            ):
                account._account_prefixes_owned(
                    progress, initial_cash=D("100"), events=tape, actions=False
                )

    def test_fast_path_does_not_expand_dataclass(self):
        expected = tuple(canonical_json(item) for item in fixtures())
        with patch(
            "trading_bot.market_data.recording.dataclasses.asdict",
            side_effect=AssertionError("generic expansion"),
        ):
            actual = tuple(event_json(item, actions=True) for item in fixtures())
        self.assertEqual(actual, expected)

    def test_enum_mutates_later_timestamp_whole_fallback_once_in_order(self):
        # Mutation after preflight must not enter a partially projected mapping.
        def run(encode):
            item = opening()
            calls = []

            class Zone(tzinfo):
                def utcoffset(self, dt):
                    return timedelta(0)

                def dst(self, dt):
                    return timedelta(0)

                def __deepcopy__(self, memo):
                    calls.append("zone")
                    return UTC

            def hook(member, memo):
                calls.append("side")
                object.__setattr__(
                    item.request.order,
                    "updated_at",
                    item.request.order.updated_at.replace(tzinfo=Zone()),
                )
                return member

            with patch.object(Side, "__deepcopy__", hook):
                value = encode(item)
            return value, calls

        self.assertEqual(run(lambda x: event_json(x, actions=True)), run(canonical_json))
        self.assertEqual(run(canonical_json)[1], ["side", "zone"])

    def test_enum_mutates_later_nested_dataclass_and_raises_preserved(self):
        def run(encode, fail=False):
            item = opening()
            calls = []

            def hook(member, memo):
                calls.append("side")
                if fail:
                    raise RuntimeError("literal enum copy failure")
                object.__setattr__(item.request.position, "market_value", D("12.3400"))
                return member

            with patch.object(Side, "__deepcopy__", hook):
                try:
                    result = encode(item)
                except RuntimeError as error:
                    result = (type(error), str(error))
            return result, calls

        for fail in (False, True):
            self.assertEqual(
                run(lambda x: event_json(x, actions=True), fail),
                run(canonical_json, fail),
            )

    def test_per_occurrence_enum_copy_order_and_instance_hook(self):
        for enum_type in (Side, AssetClass, OrderEvent):
            observed = []
            original = enum_type.__deepcopy__

            def hook(member, memo, observed=observed, original=original):
                observed.append(member.value)
                return original(member, memo)

            with patch.object(enum_type, "__deepcopy__", hook):
                expected = [canonical_json(item) for item in fixtures()]
                calls = list(observed)
                observed.clear()
                actual = [event_json(item, actions=True) for item in fixtures()]
                self.assertEqual(actual, expected)
                self.assertEqual(observed, calls)
        with patch.object(Side.BUY, "__deepcopy__", lambda memo: Side.SELL, create=True):
            self.assertEqual(event_json(opening(), actions=True), canonical_json(opening()))

    def test_custom_clock_whole_fallback_no_extra_copy(self):
        calls = []

        class Zone(tzinfo):
            def utcoffset(self, dt):
                return timedelta(0)

            def dst(self, dt):
                return timedelta(0)

            def __deepcopy__(self, memo):
                calls.append("copy")
                return UTC

        item = opening()
        object.__setattr__(
            item.request.order, "created_at", item.request.order.created_at.replace(tzinfo=Zone())
        )
        expected = canonical_json(item)
        self.assertEqual(calls, ["copy"])
        calls.clear()
        self.assertEqual(event_json(item, actions=True), expected)
        self.assertEqual(calls, ["copy"])

    def test_projection_changes_original_identity_and_has_no_alias(self):
        item = opening()
        old = event_json(item, actions=True)
        object.__setattr__(item.request.order, "limit_price", D("99"))
        new = event_json(item, actions=True)
        self.assertNotEqual(new, old)
        self.assertEqual(new, canonical_json(item))

    def test_schema_drift_falls_back_before_copy(self):
        import sys
        from importlib.util import module_from_spec, spec_from_file_location

        original_fields = dataclasses.fields

        def changed_fields(cls):
            result = original_fields(cls)
            return result[:-1] if cls.__name__ == "CapitalAccountSubmission" else result

        name = "_source_account_schema_drift"
        spec = spec_from_file_location(name, account.__file__)
        module = module_from_spec(spec)
        with (
            patch.dict(sys.modules, {name: module}),
            patch.object(dataclasses, "fields", changed_fields),
        ):
            spec.loader.exec_module(module)
        self.assertFalse(module._ORIGINAL_SCHEMA_OK)
        with patch.object(module, "_original_event", side_effect=AssertionError("projected drift")):
            for item in fixtures():
                self.assertEqual(module._original_event_json(item), canonical_json(item))

    def test_original_subclass_nested_cursor_and_decimal_rejected(self):
        class Amount(D):
            pass

        cases = []
        item = opening()
        object.__setattr__(item, "episode_fee_bound", Amount("0.1"))
        cases.append(item)
        item = opening()
        object.__setattr__(item.request.submitted, "sequence", False)
        cases.append(item)

        class Submission(account.CapitalAccountSubmission):
            pass

        cases.append(Submission("SPY", opening().request, D("0.1")))
        for item in cases:
            with (
                patch.object(
                    account,
                    "_original_event_json",
                    side_effect=AssertionError("encoded invalid original"),
                ),
                self.assertRaises(ValueError),
            ):
                event_json(item, actions=True)

    def test_custom_clock_copy_exception_unchanged(self):
        class Zone(tzinfo):
            def utcoffset(self, dt):
                return timedelta(0)

            def dst(self, dt):
                return timedelta(0)

            def __deepcopy__(self, memo):
                raise RuntimeError("literal zone copy failure")

        item = opening()
        object.__setattr__(
            item.request.order, "created_at", item.request.order.created_at.replace(tzinfo=Zone())
        )
        for encode in (canonical_json, lambda x: event_json(x, actions=True)):
            with self.assertRaisesRegex(RuntimeError, "^literal zone copy failure$"):
                encode(item)

    def test_source_late_failure_matrix_leaves_progress_unchanged(self):
        cases = (
            (
                script()[:3],
                dataclasses.replace(
                    script()[2],
                    event_id="conflicting-fill",
                    fill=dataclasses.replace(script()[2].fill, fee=D("0.03")),
                ),
            ),
            (
                (*script()[:5], action("split")),
                dataclasses.replace(action("split", 6), ratio=D("3")),
            ),
            ((*script()[:5], action()), action("payment", 6, amount=D("0.09"))),
            (script()[:8], dataclasses.replace(script()[8], fill_id="unknown-fill")),
            (script()[:9], dataclasses.replace(script()[9], total_fees=D("0.08"))),
        )
        for tape, bad in cases:
            progress, values = account._account_prefixes_owned(
                None, initial_cash=D("100"), events=tape, actions=True
            )
            saved = copy.deepcopy(progress)
            with self.assertRaises(ValueError):
                account._account_prefixes_owned(
                    progress, initial_cash=D("100"), events=(*tape, bad), actions=True
                )
            self.assertEqual(progress, saved)
            self.assertEqual(
                account._account_prefixes_owned(
                    progress, initial_cash=D("100"), events=tape, actions=True
                ),
                (saved, values),
            )

    def test_source_duplicate_alignment_matches_original_encoder(self):
        tape = (*script()[:3], script()[2], *script()[3:])
        with patch.object(account, "_original_event_json", canonical_json):
            expected = account._account_prefixes_owned(
                None, initial_cash=D("100"), events=tape, actions=False
            )
        progress = None
        for end in range(len(tape) + 1):
            progress, values = account._account_prefixes_owned(
                progress, initial_cash=D("100"), events=tape[:end], actions=False
            )
        self.assertEqual((progress, values), expected)

    def test_source_prefixes_bindings_and_detached_results_match_original(self):
        for actions, tape in (
            (False, script()),
            (True, (*script()[:5], action(), action("payment", 6))),
        ):
            with patch.object(account, "_original_event_json", canonical_json):
                expected = account._account_prefixes_owned(
                    None, initial_cash=D("100"), events=tape, actions=actions
                )
            progress = None
            for end in range(len(tape) + 1):
                progress, values = account._account_prefixes_owned(
                    progress, initial_cash=D("100"), events=tape[:end], actions=actions
                )
            self.assertEqual((progress, values), expected)
            saved = copy.deepcopy(progress)
            other = account._account_prefixes_owned(
                progress, initial_cash=D("100.0"), events=tape, actions=actions
            )
            self.assertNotEqual(other[0].binding, progress.binding)
            object.__setattr__(values[-1], "cash", D("999"))
            self.assertEqual(progress, saved)


def test_original_identity_seam_avoids_generic_dataclass_expansion():
    """Generic event serialization must not recur during original-prefix scanning."""
    tape = script()
    expected = account._account_prefixes_owned(
        None, initial_cash=D("100"), events=tape, actions=False
    )
    original = account.canonical_json

    def only_scalar_graph(value):
        if dataclasses.is_dataclass(value):
            raise AssertionError("original event still uses generic dataclass expansion")
        return original(value)

    with patch.object(account, "canonical_json", only_scalar_graph):
        progress = None
        for end in range(len(tape) + 1):
            progress, values = account._account_prefixes_owned(
                progress, initial_cash=D("100"), events=tape[:end], actions=False
            )
        assert (progress, values) == expected
