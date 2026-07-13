"""Runtime contract tests for least-privilege broker capabilities."""

import inspect
from datetime import datetime
from decimal import Decimal
from typing import Generic, Protocol, get_type_hints

import pytest

import trading_bot.brokers as broker_exports
import trading_bot.brokers.errors as broker_errors
import trading_bot.brokers.protocols as broker_protocols
from trading_bot.brokers import (
    BrokerCancelOnly,
    BrokerPlace,
    BrokerRead,
    BrokerReview,
    BrokerSubmissionAmbiguous,
    BrokerUnavailable,
    SchemaDriftError,
    UnsupportedCapabilityError,
)
from trading_bot.capabilities import UnsupportedCapabilityError as CapabilityExportedError
from trading_bot.capabilities.models import UnsupportedCapabilityError as CapabilityModelError
from trading_bot.capabilities.registry import UnsupportedCapabilityError as RegistryError
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetClass,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderId,
    BrokerOrderReview,
    CancelReceipt,
    Fill,
    OrderIntent,
    PersistedReviewedOrder,
    Position,
)

EXPECTED_PROTOCOL_METHODS = {
    BrokerRead: {
        "get_accounts": ((), tuple[AccountSnapshot, ...]),
        "get_account_state": ((AccountId,), AccountSnapshot),
        "get_positions": ((AccountId,), tuple[Position, ...]),
        "get_open_orders": ((AccountId,), tuple[BrokerOrder, ...]),
        "get_recent_orders": ((AccountId, datetime), tuple[BrokerOrder, ...]),
        "get_fills": ((AccountId, datetime), tuple[Fill, ...]),
        "get_buying_power": ((AccountId, AssetClass), Decimal),
        "health_check": ((), BrokerHealth),
    },
    BrokerReview: {
        "review_order": ((OrderIntent,), BrokerOrderReview),
    },
    BrokerPlace: {
        "place_order": ((PersistedReviewedOrder,), BrokerOrder),
    },
    BrokerCancelOnly: {
        "cancel_known_order": ((AccountId, BrokerOrderId), CancelReceipt),
    },
}

EXPECTED_PARAMETER_NAMES = {
    "get_accounts": (),
    "get_account_state": ("account_id",),
    "get_positions": ("account_id",),
    "get_open_orders": ("account_id",),
    "get_recent_orders": ("account_id", "since"),
    "get_fills": ("account_id", "since"),
    "get_buying_power": ("account_id", "asset_class"),
    "health_check": (),
    "review_order": ("intent",),
    "place_order": ("submission",),
    "cancel_known_order": ("account_id", "order_id"),
}

EXPECTED_SAFE_ERROR_MESSAGES = {
    BrokerUnavailable: "broker capability is unavailable",
    BrokerSubmissionAmbiguous: "broker submission outcome is ambiguous",
    SchemaDriftError: "broker schema does not match the reviewed contract",
}


def _public_callables(protocol: type[object]) -> set[str]:
    return {
        name
        for name, value in protocol.__dict__.items()
        if not name.startswith("_") and callable(value)
    }


def test_protocols_have_exact_async_methods_and_type_hints() -> None:
    for protocol, expected_methods in EXPECTED_PROTOCOL_METHODS.items():
        assert _public_callables(protocol) == set(expected_methods)
        for method_name, (parameter_types, return_type) in expected_methods.items():
            method = protocol.__dict__[method_name]
            assert inspect.iscoroutinefunction(method)

            method_signature = inspect.signature(method)
            expected_names = ("self", *EXPECTED_PARAMETER_NAMES[method_name])
            assert tuple(method_signature.parameters) == expected_names
            assert all(
                parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                and parameter.default is inspect.Parameter.empty
                for parameter in method_signature.parameters.values()
            )

            expected_hints = dict(
                zip(EXPECTED_PARAMETER_NAMES[method_name], parameter_types, strict=True)
            )
            expected_hints["return"] = return_type
            assert get_type_hints(method) == expected_hints


def test_protocols_are_four_independent_non_runtime_protocols() -> None:
    for protocol in EXPECTED_PROTOCOL_METHODS:
        assert protocol.__bases__ == (Protocol,)
        assert protocol.__mro__ == (protocol, Protocol, Generic, object)
        assert getattr(protocol, "_is_runtime_protocol", False) is False


def test_cancel_only_surface_cannot_place_orders() -> None:
    assert _public_callables(BrokerCancelOnly) == {"cancel_known_order"}
    assert "cancel_known_order" in BrokerCancelOnly.__dict__
    assert "place_order" not in BrokerCancelOnly.__dict__
    assert not hasattr(BrokerCancelOnly, "place_order")


def test_modules_export_only_the_reviewed_public_contract() -> None:
    expected_protocols = {"BrokerRead", "BrokerReview", "BrokerPlace", "BrokerCancelOnly"}
    expected_errors = {
        "UnsupportedCapabilityError",
        "BrokerUnavailable",
        "BrokerSubmissionAmbiguous",
        "SchemaDriftError",
    }
    assert set(broker_protocols.__all__) == expected_protocols
    assert set(broker_errors.__all__) == expected_errors
    assert set(broker_exports.__all__) == expected_protocols | expected_errors

    for name in expected_protocols:
        assert getattr(broker_exports, name) is getattr(broker_protocols, name)
    for name in expected_errors:
        assert getattr(broker_exports, name) is getattr(broker_errors, name)


def test_unsupported_capability_error_is_reexported_without_redefinition() -> None:
    assert UnsupportedCapabilityError is CapabilityModelError
    assert UnsupportedCapabilityError is CapabilityExportedError
    assert UnsupportedCapabilityError is RegistryError
    assert UnsupportedCapabilityError is broker_errors.UnsupportedCapabilityError
    assert UnsupportedCapabilityError is broker_exports.UnsupportedCapabilityError


def test_broker_local_errors_are_only_the_three_safe_runtime_errors() -> None:
    expected = {BrokerUnavailable, BrokerSubmissionAmbiguous, SchemaDriftError}
    local_error_types = {
        value
        for value in vars(broker_errors).values()
        if inspect.isclass(value)
        and value.__module__ == broker_errors.__name__
        and issubclass(value, RuntimeError)
    }
    assert local_error_types == expected
    for error_type in expected:
        assert error_type.__bases__ == (RuntimeError,)


@pytest.mark.parametrize(
    ("error_type", "expected_message"),
    tuple(EXPECTED_SAFE_ERROR_MESSAGES.items()),
)
def test_broker_local_errors_have_fixed_generic_messages(
    error_type: type[RuntimeError],
    expected_message: str,
) -> None:
    error = error_type()
    assert error.args == (expected_message,)
    assert str(error) == expected_message


@pytest.mark.parametrize("error_type", tuple(EXPECTED_SAFE_ERROR_MESSAGES))
@pytest.mark.parametrize(
    ("args", "kwargs"),
    (
        (("secret-provider-payload",), {}),
        ((), {"payload": "secret-provider-payload"}),
        ((), {"context": "secret-provider-payload"}),
    ),
)
def test_broker_local_errors_reject_secret_bearing_context(
    error_type: type[RuntimeError],
    args: tuple[str, ...],
    kwargs: dict[str, str],
) -> None:
    sentinel = "secret-provider-payload"
    with pytest.raises(TypeError) as raised:
        error_type(*args, **kwargs)
    assert sentinel not in repr(raised.value.args)
