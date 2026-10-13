"""Source regressions for admitted enum hooks at the preimage seam."""

import unittest
from datetime import timedelta, timezone, tzinfo
from enum import Enum
from types import MethodType
from unittest.mock import patch

from tests.unit.simulation.test_etf_capital_account import opening
from tests.unit.simulation.test_etf_capital_account_preimage import event_json
from trading_bot.domain import Side
from trading_bot.market_data.recording import canonical_json
from trading_bot.simulation import etf_capital_account as account


class HookRegression(unittest.TestCase):
    def test_optimized_enum_copies_occur_once_in_declaration_order(self):
        item = opening()
        order = item.request.order
        expected = canonical_json(item)
        with patch.object(account, "deepcopy", wraps=account.deepcopy) as copies:
            self.assertEqual(event_json(item, actions=True), expected)
        self.assertEqual(
            [call.args for call in copies.call_args_list],
            [
                (member,)
                for member in (
                    order.side,
                    order.purpose,
                    order.order_type,
                    order.time_in_force,
                    order.state,
                    item.request.position.asset_class,
                )
            ],
        )

    def test_genuine_bound_standard_hook_keeps_optimized_copy_path(self):
        hook = MethodType(Enum.__deepcopy__, Side.BUY)
        with patch.object(Side.BUY, "__deepcopy__", hook, create=True):
            expected = canonical_json(opening())
            with patch(
                "trading_bot.market_data.recording.dataclasses.asdict",
                side_effect=AssertionError("ordinary bound hook unexpectedly fell back"),
            ):
                self.assertEqual(event_json(opening(), actions=True), expected)

    def test_standard_hook_bound_to_another_member_falls_back_whole(self):
        hook = MethodType(Enum.__deepcopy__, Side.SELL)
        with patch.object(Side.BUY, "__deepcopy__", hook, create=True):
            expected = canonical_json(opening())
            with patch.object(
                account, "_original_event", side_effect=AssertionError("projected wrong self")
            ):
                self.assertEqual(event_json(opening(), actions=True), expected)

    def test_unknown_callable_metadata_is_not_observed(self):
        class Hook:
            @property
            def __func__(self):
                raise RuntimeError("metadata must not be probed")

            def __call__(self, memo):
                return Side.BUY

        with patch.object(Side.BUY, "__deepcopy__", Hook(), create=True):
            expected = canonical_json(opening())
            self.assertEqual(event_json(opening(), actions=True), expected)

    def test_descriptor_lookup_occurs_only_in_original_copy_order(self):
        def run(encode, failure):
            calls = []

            class HookDescriptor:
                def __get__(self, member, owner):
                    calls.append("lookup")
                    if failure is not None:
                        raise failure("literal missing or failed hook")

                    def perform(memo):
                        calls.append("copy")
                        return member

                    return perform

            item = opening()
            with patch.object(Side, "__deepcopy__", HookDescriptor()):
                try:
                    result = encode(item)
                except (AttributeError, RuntimeError) as error:
                    result = (type(error), str(error))
            return result, calls

        for failure in (None, AttributeError, RuntimeError):
            with self.subTest(failure=failure):
                self.assertEqual(
                    run(lambda event: event_json(event, actions=True), failure),
                    run(canonical_json, failure),
                )

    def test_callable_hook_cannot_forge_bound_method_identity(self):
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
                    return timezone(timedelta(hours=1))

            class CallableHook:
                def __init__(self):
                    self.__func__ = Enum.__deepcopy__
                    self.__self__ = Side.BUY

                def __call__(self, memo):
                    calls.append("side")
                    order = item.request.order
                    object.__setattr__(order, "updated_at", order.updated_at.replace(tzinfo=Zone()))
                    return Side.BUY

            with patch.object(Side.BUY, "__deepcopy__", CallableHook(), create=True):
                encoded = encode(item)
            return encoded, calls

        expected = run(canonical_json)
        self.assertEqual(expected[1], ["side", "zone"])
        self.assertEqual(run(lambda event: event_json(event, actions=True)), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
