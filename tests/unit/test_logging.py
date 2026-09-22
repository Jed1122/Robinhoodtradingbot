"""Tests for fail-closed, pre-serialization structured-log redaction."""

from __future__ import annotations

import gc
import json
import logging as stdlib_logging
import threading
import types
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
import structlog

import trading_bot.logging as logging_module
from trading_bot.config import LoggingSettings
from trading_bot.logging import (
    SecretRegistry,
    configure_logging,
    contains_registered_secret,
    redact_secrets,
)

_OWN_HANDLER_MARKER = "_trading_bot_json_handler"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_logging_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )
    logging_module._install_logging_settings(
        LoggingSettings(max_event_bytes=65536),
        LoggingSettings(max_event_bytes=65536),
    )
    root = stdlib_logging.getLogger()
    manager = root.manager
    logger_dict = manager.loggerDict
    original_logger_registry = dict(logger_dict)
    original_logger_states: dict[stdlib_logging.Logger, dict[str, object]] = {}
    original_logger_mutable_contents: dict[stdlib_logging.Logger, dict[str, object]] = {}
    for logger in (*original_logger_registry.values(), root):
        if not isinstance(logger, stdlib_logging.Logger):
            continue
        state = dict(logging_module._FILTERER_DICT_DESCRIPTOR.__get__(logger, type(logger)))
        mutable_contents: dict[str, object] = {}
        cache = state.get("_cache")
        if type(cache) is dict:
            mutable_contents["_cache"] = dict(cache)
        for field_name in ("handlers", "filters"):
            field_value = state.get(field_name)
            if type(field_value) is list:
                mutable_contents[field_name] = list(field_value)
        original_logger_states[logger] = state
        original_logger_mutable_contents[logger] = mutable_contents
    original_manager_disable = manager.disable
    original_manager_disable_descriptor = stdlib_logging.Manager.__dict__["disable"]
    original_manager_logger_class = manager.loggerClass
    original_logger_class = stdlib_logging.getLoggerClass()
    original_record_factory = stdlib_logging.getLogRecordFactory()
    original_last_resort = stdlib_logging.lastResort
    original_base_log = stdlib_logging.Logger.__dict__["_log"]
    original_base_make_record = stdlib_logging.Logger.__dict__["makeRecord"]
    original_base_find_caller = stdlib_logging.Logger.__dict__["findCaller"]
    original_structlog_was_configured = structlog.is_configured()
    original_structlog_config = dict(structlog.get_config())
    yield
    type.__setattr__(stdlib_logging.Logger, "_log", original_base_log)
    type.__setattr__(stdlib_logging.Logger, "makeRecord", original_base_make_record)
    type.__setattr__(stdlib_logging.Logger, "findCaller", original_base_find_caller)
    type.__setattr__(
        stdlib_logging.Manager,
        "disable",
        original_manager_disable_descriptor,
    )
    stdlib_logging.setLoggerClass(original_logger_class)
    stdlib_logging.setLogRecordFactory(original_record_factory)
    stdlib_logging.lastResort = original_last_resort
    manager.loggerClass = original_manager_logger_class
    dict.clear(logger_dict)
    dict.update(logger_dict, original_logger_registry)
    for logger, original_state in original_logger_states.items():
        for field_name, contents in original_logger_mutable_contents[logger].items():
            original_value = original_state.get(field_name)
            if type(original_value) is list and type(contents) is list:
                list.clear(original_value)
                list.extend(original_value, contents)
            elif type(original_value) is dict and type(contents) is dict:
                dict.clear(original_value)
                dict.update(original_value, contents)
        state = logging_module._FILTERER_DICT_DESCRIPTOR.__get__(logger, type(logger))
        dict.clear(state)
        dict.update(state, original_state)
    manager_state = logging_module._MANAGER_DICT_DESCRIPTOR.__get__(manager, type(manager))
    manager_state["_disable"] = original_manager_disable
    if original_structlog_was_configured:
        structlog.configure(**original_structlog_config)
    else:
        structlog.reset_defaults()


@pytest.fixture
def secret_registry() -> SecretRegistry:
    return SecretRegistry()


def _serialized(event: dict[str, object]) -> str:
    return json.dumps(event, sort_keys=True, allow_nan=False)


def test_module_exports_exact_public_api() -> None:
    assert logging_module.__all__ == [
        "SecretRegistry",
        "configure_logging",
        "contains_registered_secret",
        "redact_secrets",
    ]


def test_registered_secret_identifier_screen_is_exact_registry_only() -> None:
    SecretRegistry().register("ordinary-registered-value")

    assert contains_registered_secret("prefix-ordinary-registered-value-suffix")
    assert not contains_registered_secret("4b8be287-49b5-4d14-bf47-f02dddc0d98c")


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "private_key",
        "x-signature",
        "authorization",
        "cookie",
        "live_authorization",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    event = redact_secrets(None, "info", {key: "secret", "safe": "visible"})

    assert event[key] == "[REDACTED]"
    assert event["safe"] == "visible"


@pytest.mark.parametrize(
    ("value", "sentinel"),
    [
        ("https://host/path?account_number=RHC123456789&safe=true", "RHC123456789"),
        ("https://host/path?account%255Fid%253DRHC123456789", "RHC123456789"),
        ("Authorization: Bearer fixture-bearer-value", "fixture-bearer-value"),
        ("x-api-key%253Dfixture-api-key-value", "fixture-api-key-value"),
        ("first line\nsignature=fixture-signature\nlast line", "fixture-signature"),
    ],
)
def test_sensitive_text_forms_are_removed(value: str, sentinel: str) -> None:
    event = redact_secrets(None, "error", {"error": value})

    assert sentinel not in _serialized(event)


def test_sensitive_text_is_classified_before_registered_substring_replacement() -> None:
    SecretRegistry().register("auth")

    event = redact_secrets(None, "error", {"error": "authorization: tiny"})

    assert "tiny" not in _serialized(event)


def test_registry_is_process_wide_and_replaces_longest_overlapping_values_first() -> None:
    first = SecretRegistry()
    second = SecretRegistry()
    first.register("alpha")
    second.register("alpha-bravo")

    event = redact_secrets(
        None,
        "info",
        {"event": "alpha-bravo then alpha", "alpha-bravo-key": "visible"},
    )
    serialized = _serialized(event)

    assert "alpha-bravo" not in serialized
    assert "alpha" not in serialized
    assert "visible" in serialized


def test_registry_accepts_text_and_bytes_without_exposing_registered_state() -> None:
    registry = SecretRegistry()
    registry.register("fixture-text-secret")
    registry.register(b"fixture-bytes-secret")

    event = redact_secrets(
        None,
        "info",
        {"event": "fixture-text-secret / fixture-bytes-secret"},
    )
    serialized = _serialized(event)

    assert "fixture-text-secret" not in serialized
    assert "fixture-bytes-secret" not in serialized
    assert "fixture-text-secret" not in repr(registry)
    assert "fixture-bytes-secret" not in repr(registry)
    with pytest.raises(TypeError):
        vars(registry)


def test_registry_registration_is_thread_safe_across_instances() -> None:
    values = tuple(f"concurrent-fixture-value-{index}" for index in range(20))

    with ThreadPoolExecutor(max_workers=4) as pool:
        tuple(pool.map(SecretRegistry().register, values))

    serialized = _serialized(redact_secrets(None, "info", {"event": " / ".join(values)}))
    assert all(value not in serialized for value in values)


def test_registered_value_overlapping_redaction_markers_never_survives_serialization() -> None:
    SecretRegistry().register("DACT")

    event = redact_secrets(
        None,
        "error",
        {
            "authorization": "fixture-value",
            "message": "prefix DACT suffix",
            "payload": b"fixture-bytes",
        },
    )
    serialized = _serialized(event)

    assert "DACT" not in serialized
    assert event["authorization"] == ""


def test_registered_key_material_is_not_reintroduced_by_collision_suffixes() -> None:
    registry = SecretRegistry()
    registry.register("DACT")
    registry.register("#2")

    event = redact_secrets(None, "info", {"safe": "first", "safe#2": "second"})
    serialized = _serialized(event)

    assert "DACT" not in serialized
    assert "#2" not in serialized
    assert event == {"safe": ""}


@pytest.mark.parametrize("value", ["", b""])
def test_registry_rejects_empty_secrets_with_generic_errors(value: str | bytes) -> None:
    with pytest.raises(ValueError, match="secret must not be empty") as raised:
        SecretRegistry().register(value)

    assert value not in raised.value.args


@pytest.mark.parametrize("value", [None, True, 1, bytearray(b"value"), object()])
def test_registry_rejects_non_exact_types_without_rendering_them(value: object) -> None:
    with pytest.raises(TypeError, match="secret must be exact text or bytes"):
        SecretRegistry().register(value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class _FrozenEnvelope:
    safe: str
    authorization: str
    nested: tuple[object, ...]


@dataclass(frozen=True)
class _FrozenDictEnvelope:
    safe: str


class _HostileDataclassKey:
    def __hash__(self) -> int:
        return hash("safe")

    def __eq__(self, value: object) -> bool:
        raise AssertionError("custom dataclass key equality must not run")


class _HostileObject:
    @property
    def payload(self) -> str:
        raise AssertionError("property must not be read")

    def __iter__(self) -> Any:
        raise AssertionError("custom iterator must not run")

    def __repr__(self) -> str:
        raise AssertionError("repr must not run")

    def __str__(self) -> str:
        raise AssertionError("str must not run")


class _HostileClassProperty:
    @property  # type: ignore[misc]
    def __class__(self) -> type[RuntimeError]:  # type: ignore[override]
        raise AssertionError("instance __class__ property must not run")


class _HostileMetadata(type):
    metadata_calls: ClassVar[list[str]] = []

    @property  # type: ignore[misc]
    def __dict__(cls) -> object:  # type: ignore[override]
        cls.metadata_calls.append("dict")
        raise AssertionError("metaclass __dict__ property must not run")


class _HostileMetadataObject(metaclass=_HostileMetadata):
    pass


class _HostileList(list[object]):
    def __iter__(self) -> Any:
        raise AssertionError("custom list iterator must not run")

    def __repr__(self) -> str:
        raise AssertionError("custom list repr must not run")


class _HostileDict(dict[str, object]):
    def items(self) -> Any:
        raise AssertionError("custom mapping iterator must not run")

    def __iter__(self) -> Any:
        raise AssertionError("custom mapping iterator must not run")

    def __repr__(self) -> str:
        raise AssertionError("custom mapping repr must not run")


class _HostileTzInfo(tzinfo):
    def utcoffset(self, value: datetime | None) -> timedelta | None:
        raise AssertionError("custom tzinfo must not run")

    def dst(self, value: datetime | None) -> timedelta | None:
        raise AssertionError("custom tzinfo must not run")

    def tzname(self, value: datetime | None) -> str | None:
        raise AssertionError("custom tzinfo must not run")


def test_nested_values_are_detached_json_safe_and_original_is_unchanged(
    secret_registry: SecretRegistry,
) -> None:
    secret_registry.register("nested-fixture-secret")
    original = {
        "event": "safe event",
        "payload": _FrozenEnvelope(
            safe="visible",
            authorization="Bearer nested-fixture-secret",
            nested=(
                {"message": "prefix nested-fixture-secret suffix"},
                {"beta", "alpha"},
                b"raw-secret-bytes",
            ),
        ),
        "count": 3,
        "enabled": True,
        "nothing": None,
    }

    event = redact_secrets(None, "info", original)
    serialized = _serialized(event)

    assert cast(_FrozenEnvelope, original["payload"]).authorization == (
        "Bearer nested-fixture-secret"
    )
    assert event is not original
    assert "nested-fixture-secret" not in serialized
    assert "raw-secret-bytes" not in serialized
    assert "visible" in serialized
    assert event["count"] == 3
    assert event["enabled"] is True
    assert event["nothing"] is None
    assert redact_secrets(None, "info", event) == event


def test_finite_float_stays_numeric_and_nonfinite_float_fails_closed() -> None:
    event = redact_secrets(
        None,
        "info",
        {"finite": 1.25, "nan": float("nan"), "positive_inf": float("inf")},
    )

    assert event == {
        "finite": 1.25,
        "nan": "[REDACTED_NONFINITE]",
        "positive_inf": "[REDACTED_NONFINITE]",
    }
    json.dumps(event, allow_nan=False)


def test_cycles_and_hostile_objects_fail_closed_without_invoking_user_code() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    hostile = _HostileObject()
    hostile_list = _HostileList(["must not be inspected"])
    hostile_mapping = _HostileDict(payload="must not be inspected")

    event = redact_secrets(
        None,
        "warning",
        {
            "cycle": cycle,
            "hostile": hostile,
            "hostile_list": hostile_list,
            "hostile_mapping": hostile_mapping,
        },
    )

    assert event == {
        "cycle": ["[REDACTED_CYCLE]"],
        "hostile": "[REDACTED_OBJECT]",
        "hostile_list": "[REDACTED_OBJECT]",
        "hostile_mapping": "[REDACTED_OBJECT]",
    }
    _serialized(event)


def test_datetime_with_hostile_tzinfo_is_not_inspected() -> None:
    value = datetime(2026, 7, 13, tzinfo=_HostileTzInfo())

    event = redact_secrets(None, "info", {"when": value})

    assert event == {"when": "[REDACTED_OBJECT]"}


def test_hostile_instance_class_property_is_never_invoked() -> None:
    event = redact_secrets(None, "info", {"payload": _HostileClassProperty()})

    assert event == {"payload": "[REDACTED_OBJECT]"}


def test_hostile_metaclass_metadata_descriptor_is_never_invoked() -> None:
    _HostileMetadata.metadata_calls.clear()

    event = redact_secrets(None, "info", {"payload": _HostileMetadataObject()})

    assert _HostileMetadata.metadata_calls == []
    assert event == {"payload": "[REDACTED_OBJECT]"}


def test_dataclass_with_non_text_storage_key_is_rejected_without_key_equality() -> None:
    value = _FrozenDictEnvelope(safe="visible")
    instance_values = object.__getattribute__(value, "__dict__")
    instance_values.pop("safe")
    instance_values[_HostileDataclassKey()] = "must not be inspected"

    event = redact_secrets(None, "info", {"payload": value})

    assert event == {"payload": "[REDACTED_OBJECT]"}


def test_dataclass_custom_dict_descriptor_is_never_invoked() -> None:
    calls: list[str] = []

    class HostileDictDescriptor(_FrozenDictEnvelope):
        __dataclass_fields__ = _FrozenDictEnvelope.__dataclass_fields__

        @property
        def __dict__(self) -> dict[str, object]:  # type: ignore[override]
            calls.append("invoked")
            raise AssertionError("custom __dict__ descriptor must not run")

    event = redact_secrets(None, "info", {"payload": HostileDictDescriptor(safe="visible")})

    assert calls == []
    assert event == {"payload": "[REDACTED_OBJECT]"}


def test_exception_args_are_recursively_redacted_without_calling_exception_str(
    secret_registry: SecretRegistry,
) -> None:
    secret_registry.register("exception-fixture-secret")

    class HostileException(RuntimeError):
        def __str__(self) -> str:
            raise AssertionError("exception str must not run")

        def __repr__(self) -> str:
            raise AssertionError("exception repr must not run")

    error = HostileException("prefix exception-fixture-secret suffix", {"api_key": "tiny"})
    event = redact_secrets(None, "error", {"exception": error})
    serialized = _serialized(event)

    assert "exception-fixture-secret" not in serialized
    assert "tiny" not in serialized
    assert "HostileException" in serialized


def test_registered_material_is_removed_from_mapping_keys_and_values(
    secret_registry: SecretRegistry,
) -> None:
    secret_registry.register("registered-key-secret")

    event = redact_secrets(
        None,
        "info",
        {"prefix-registered-key-secret-suffix": "registered-key-secret"},
    )
    serialized = _serialized(event)

    assert "registered-key-secret" not in serialized


def test_internal_redaction_failure_returns_only_a_generic_safe_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("provider-payload-must-not-escape")

    monkeypatch.setattr(logging_module, "_redact_mapping", fail)

    event = redact_secrets(
        None,
        "error",
        {"event": "original-provider-secret", "api_key": "original-provider-secret"},
    )
    serialized = _serialized(event)

    assert event == {"event": "log redaction failed", "redaction_status": "failed_closed"}
    assert "provider-payload" not in serialized
    assert "original-provider-secret" not in serialized


def test_invalid_top_level_event_uses_collision_safe_registered_failure() -> None:
    SecretRegistry().register("failed")

    class InvalidTopLevel(dict[str, object]):
        pass

    event = redact_secrets(None, "error", InvalidTopLevel(event="unsafe"))

    assert event == {}
    assert "failed" not in _serialized(event)


@pytest.mark.parametrize("level", ["", "TRACE", "WARNINGS", "10"])
def test_configure_logging_rejects_unknown_levels(level: str) -> None:
    with pytest.raises(ValueError, match="unsupported logging level"):
        configure_logging(level)


def test_configure_logging_rejects_non_text_level() -> None:
    with pytest.raises(TypeError, match="logging level must be text"):
        configure_logging(20)  # type: ignore[arg-type]


def test_configure_logging_is_idempotent_and_orders_processors_safely() -> None:
    configure_logging("INFO")
    configure_logging("info")

    root = stdlib_logging.getLogger()
    owned_handlers = [
        handler for handler in root.handlers if getattr(handler, _OWN_HANDLER_MARKER, False) is True
    ]
    processors = list(structlog.get_config()["processors"])

    assert len(owned_handlers) == 1
    assert processors.index(logging_module._sanitize_exception_info) < processors.index(
        structlog.processors.format_exc_info
    )
    assert processors.index(structlog.processors.format_exc_info) < processors.index(redact_secrets)
    assert processors.index(redact_secrets) < processors.index(
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter
    )
    assert logging_module._limit_event_size not in processors
    formatter = owned_handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
    formatter_processors = list(formatter.processors)
    remove_metadata = cast(Any, logging_module._remove_processor_metadata)
    limit_size = cast(Any, logging_module._limit_event_size)
    assert formatter_processors.index(remove_metadata) < formatter_processors.index(limit_size)
    assert formatter_processors.index(limit_size) < len(formatter_processors) - 1
    assert isinstance(formatter_processors[-1], structlog.processors.JSONRenderer)


def test_configure_logging_removes_foreign_root_handlers_before_stdlib_emission(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "stdlib-foreign-handler-fixture-secret"
    secret_registry.register(sentinel)
    captured_by_foreign_handler: list[str] = []

    class ForeignHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured_by_foreign_handler.append(record.getMessage())

    foreign_handler = ForeignHandler()
    root = stdlib_logging.getLogger()
    root.addHandler(foreign_handler)

    configure_logging("INFO")
    stdlib_logging.getLogger("foreign-handler-test").error("event contains %s", sentinel)

    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert captured_by_foreign_handler == []
    assert sentinel not in json.dumps(payload, sort_keys=True)


def test_configure_logging_normalizes_propagating_and_nonpropagating_named_loggers(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "named-handler-fixture-secret"
    secret_registry.register(sentinel)
    captured_by_foreign_handlers: list[str] = []

    class ForeignHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured_by_foreign_handlers.append(record.getMessage())

    loggers = (
        stdlib_logging.getLogger("named-handler-propagating-test"),
        stdlib_logging.getLogger("named-handler-nonpropagating-test"),
    )
    original_state = tuple((tuple(logger.handlers), logger.propagate) for logger in loggers)
    try:
        for logger, propagate in zip(loggers, (True, False), strict=True):
            logger.handlers = [ForeignHandler()]
            logger.propagate = propagate

        configure_logging("INFO")
        for logger in loggers:
            logger.error("event contains %s", sentinel)

        payloads = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]
        assert captured_by_foreign_handlers == []
        assert len(payloads) == 2
        assert all(sentinel not in json.dumps(payload, sort_keys=True) for payload in payloads)
        assert all(logger.handlers == [] and logger.propagate for logger in loggers)
    finally:
        for logger, (handlers, propagate) in zip(loggers, original_state, strict=True):
            logger.handlers = list(handlers)
            logger.propagate = propagate


def test_configure_logging_rejects_custom_logger_classes_without_invoking_descriptors() -> None:
    descriptor_calls: list[str] = []

    class HostileLogger(stdlib_logging.Logger):
        @property
        def __dict__(self) -> dict[str, object]:  # type: ignore[override]
            descriptor_calls.append("invoked")
            return {"filters": [], "handlers": []}

    root = stdlib_logging.getLogger()
    logger = HostileLogger("hostile-custom-logger")
    root.manager.loggerDict[logger.name] = logger
    try:
        with pytest.raises(RuntimeError, match="custom logger classes are unsupported"):
            configure_logging("INFO")

        assert descriptor_calls == []
    finally:
        root.manager.loggerDict.pop(logger.name, None)


def test_failed_configuration_clears_cached_enabled_loggers(
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "failure-cache-fixture-secret"
    secret_registry.register(sentinel)
    captured: list[str] = []

    class ForeignHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append(record.getMessage())

    class UnsupportedLogger(stdlib_logging.Logger):
        pass

    root = stdlib_logging.getLogger()
    victim = stdlib_logging.Logger("failure-cache-victim")
    victim.handlers = [ForeignHandler()]
    victim.propagate = False
    unsupported = UnsupportedLogger("failure-cache-unsupported")
    unsupported.handlers = [ForeignHandler()]
    unsupported.propagate = False
    root.manager.loggerDict[victim.name] = victim
    root.manager.loggerDict[unsupported.name] = unsupported
    try:
        assert victim.isEnabledFor(stdlib_logging.ERROR) is True
        assert unsupported.isEnabledFor(stdlib_logging.ERROR) is True

        with pytest.raises(RuntimeError, match="custom logger classes are unsupported"):
            configure_logging("INFO")
        victim.error("event contains %s", sentinel)
        unsupported.error("event contains %s", sentinel)

        assert captured == []
    finally:
        root.manager.loggerDict.pop(victim.name, None)
        root.manager.loggerDict.pop(unsupported.name, None)


def test_configure_logging_detaches_filters_before_they_can_observe_raw_records(
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "filter-observer-fixture-secret"
    secret_registry.register(sentinel)
    observed: list[str] = []

    class ForeignFilter(stdlib_logging.Filter):
        def filter(self, record: stdlib_logging.LogRecord) -> bool:
            observed.append(record.getMessage())
            return True

    logger = stdlib_logging.getLogger("foreign-filter-test")
    original_filters = tuple(logger.filters)
    try:
        logger.filters = [ForeignFilter()]

        configure_logging("INFO")
        logger.error("event contains %s", sentinel)

        assert observed == []
        assert logger.filters == []
    finally:
        logger.filters = list(original_filters)


def test_configure_logging_quarantines_foreign_extension_destructors() -> None:
    destructor_calls: list[str] = []

    class ForeignFilter(stdlib_logging.Filter):
        def __del__(self) -> None:
            destructor_calls.append("filter")

    class ForeignHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            del record

        def __del__(self) -> None:
            destructor_calls.append("handler")

    logger = stdlib_logging.getLogger("foreign-destructor-test")
    original_handlers = tuple(logger.handlers)
    original_filters = tuple(logger.filters)
    try:
        logger.handlers = [ForeignHandler()]
        logger.filters = [ForeignFilter()]

        configure_logging("INFO")
        gc.collect()

        assert destructor_calls == []
    finally:
        logger.handlers = list(original_handlers)
        logger.filters = list(original_filters)


def test_configure_logging_quarantines_displaced_boundary_destructors() -> None:
    destructor_calls: list[str] = []

    class ForeignBoundary:
        def __del__(self) -> None:
            destructor_calls.append("boundary")

    root = stdlib_logging.getLogger()
    logger = stdlib_logging.Logger("foreign-boundary-destructor-test")
    logger.__dict__["_log"] = ForeignBoundary()
    logger.__dict__["makeRecord"] = ForeignBoundary()
    logger.__dict__["findCaller"] = ForeignBoundary()
    root.manager.loggerDict[logger.name] = logger
    try:
        configure_logging("INFO")
        gc.collect()

        assert destructor_calls == []
    finally:
        root.manager.loggerDict.pop(logger.name, None)


def test_configure_logging_retains_displaced_logger_scalar_state() -> None:
    finalizer_calls: list[str] = []

    class FinalizingState:
        def __init__(self, name: str) -> None:
            self.name = name

        def __del__(self) -> None:
            finalizer_calls.append(self.name)

    root = stdlib_logging.getLogger()
    logger = stdlib_logging.Logger("foreign-scalar-state-test")
    logger.__dict__["propagate"] = FinalizingState("propagate")
    root.__dict__["level"] = FinalizingState("root_level")
    root.manager.loggerDict[logger.name] = logger
    try:
        configure_logging("INFO")
        gc.collect()

        assert finalizer_calls == []
    finally:
        root.manager.loggerDict.pop(logger.name, None)


def test_reconfiguration_retains_mutated_owned_handler_state() -> None:
    finalizer_calls: list[str] = []

    class FinalizingObject:
        def __init__(self, name: str) -> None:
            self.name = name

        def __del__(self) -> None:
            finalizer_calls.append(self.name)

    configure_logging("INFO")
    root = stdlib_logging.getLogger()
    handler = root.handlers[0]
    handler.filters = [FinalizingObject("filter")]  # type: ignore[list-item]
    handler.formatter = FinalizingObject("formatter")  # type: ignore[assignment]
    handler.stream = FinalizingObject("stream")  # type: ignore[attr-defined]
    del handler

    configure_logging("INFO")
    gc.collect()

    assert finalizer_calls == []


def test_configure_logging_preserves_disabled_loggers_without_closing_foreign_handlers() -> None:
    close_calls: list[str] = []

    class ForeignHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            del record

        def close(self) -> None:
            close_calls.append("closed")

    logger = stdlib_logging.getLogger("disabled-logger-test")
    original_handlers = tuple(logger.handlers)
    original_propagate = logger.propagate
    original_disabled = logger.disabled
    try:
        logger.handlers = [ForeignHandler()]
        logger.propagate = False
        logger.disabled = True

        configure_logging("INFO")

        assert close_calls == []
        assert logger.handlers == []
        assert logger.propagate is True
        assert logger.disabled is True
    finally:
        logger.handlers = list(original_handlers)
        logger.propagate = original_propagate
        logger.disabled = original_disabled


def test_configure_logging_serializes_concurrent_reconfiguration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_close = logging_module._close_owned_handlers
    first_inside = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_inside = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def controlled_close(handlers: tuple[stdlib_logging.Handler, ...]) -> None:
        nonlocal call_count
        with call_lock:
            call_count += 1
            ordinal = call_count
        if ordinal == 1:
            first_inside.set()
            if not release_first.wait(timeout=2):
                raise AssertionError("concurrent logging test did not release first configure")
        elif ordinal == 2:
            second_inside.set()
        original_close(handlers)

    monkeypatch.setattr(logging_module, "_close_owned_handlers", controlled_close)

    def configure_second() -> None:
        second_started.set()
        configure_logging("INFO")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(configure_logging, "INFO")
        assert first_inside.wait(timeout=1)
        second = pool.submit(configure_second)
        assert second_started.wait(timeout=1)
        concurrent_entry = second_inside.wait(timeout=0.2)
        release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)

    owned_handlers = [
        handler
        for handler in stdlib_logging.getLogger().handlers
        if getattr(handler, _OWN_HANDLER_MARKER, False) is True
    ]
    assert concurrent_entry is False
    assert len(owned_handlers) == 1


@pytest.mark.parametrize(
    "concurrent_level",
    [stdlib_logging.CRITICAL, logging_module._DISABLE_DURING_RECONFIGURE],
)
def test_reconfiguration_preserves_concurrent_more_restrictive_disable(
    monkeypatch: pytest.MonkeyPatch,
    concurrent_level: int,
) -> None:
    configure_logging("INFO")
    original_close = logging_module._close_owned_handlers
    inside_close = threading.Event()
    release_close = threading.Event()

    def controlled_close(handlers: tuple[object, ...]) -> None:
        inside_close.set()
        if not release_close.wait(timeout=2):
            raise AssertionError("disable-level test did not release reconfiguration")
        original_close(handlers)

    monkeypatch.setattr(logging_module, "_close_owned_handlers", controlled_close)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(configure_logging, "INFO")
        assert inside_close.wait(timeout=1)
        stdlib_logging.disable(concurrent_level)
        release_close.set()
        future.result(timeout=2)

    assert stdlib_logging.getLogger().manager.disable == concurrent_level


def test_reconfiguration_serializes_final_disable_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging("INFO")
    original_set_level = logging_module._set_logging_disable_level
    original_clear_cache = stdlib_logging.Manager._clear_cache
    inside_final_restore = threading.Event()
    release_final_restore = threading.Event()
    disable_started = threading.Event()
    disable_reached_cache_clear = threading.Event()
    set_calls = 0

    def controlled_set_level(
        manager: stdlib_logging.Manager,
        root: stdlib_logging.RootLogger,
        managed_loggers: tuple[stdlib_logging.Logger, ...],
        level: int,
    ) -> None:
        nonlocal set_calls
        set_calls += 1
        if set_calls == 2:
            inside_final_restore.set()
            if not release_final_restore.wait(timeout=2):
                raise AssertionError("disable-level test did not release final restore")
        original_set_level(manager, root, managed_loggers, level)

    def controlled_clear_cache(manager: stdlib_logging.Manager) -> None:
        if disable_started.is_set():
            disable_reached_cache_clear.set()
        original_clear_cache(manager)

    monkeypatch.setattr(logging_module, "_set_logging_disable_level", controlled_set_level)
    monkeypatch.setattr(stdlib_logging.Manager, "_clear_cache", controlled_clear_cache)

    def disable_concurrently() -> None:
        disable_started.set()
        stdlib_logging.disable(stdlib_logging.CRITICAL)

    with ThreadPoolExecutor(max_workers=2) as pool:
        configure_future = pool.submit(configure_logging, "INFO")
        assert inside_final_restore.wait(timeout=1)
        disable_future = pool.submit(disable_concurrently)
        assert disable_started.wait(timeout=1)
        disable_reached_cache_clear.wait(timeout=0.2)
        release_final_restore.set()
        configure_future.result(timeout=2)
        disable_future.result(timeout=2)

    assert stdlib_logging.getLogger().manager.disable == stdlib_logging.CRITICAL


def test_reconfiguration_captures_disable_level_under_registry_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging("INFO")
    original_acquire = logging_module._acquire_logging_registry_lock
    before_first_acquire = threading.Event()
    release_first_acquire = threading.Event()
    acquire_calls = 0

    def controlled_acquire() -> None:
        nonlocal acquire_calls
        acquire_calls += 1
        if acquire_calls == 1:
            before_first_acquire.set()
            if not release_first_acquire.wait(timeout=2):
                raise AssertionError("disable-level test did not release registry lock")
        original_acquire()

    monkeypatch.setattr(logging_module, "_acquire_logging_registry_lock", controlled_acquire)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(configure_logging, "INFO")
        assert before_first_acquire.wait(timeout=1)
        stdlib_logging.disable(stdlib_logging.CRITICAL)
        release_first_acquire.set()
        future.result(timeout=2)

    assert stdlib_logging.getLogger().manager.disable == stdlib_logging.CRITICAL


def test_reconfiguration_ignores_disable_writes_to_unrelated_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging("INFO")
    original_close = logging_module._close_owned_handlers
    inside_close = threading.Event()
    release_close = threading.Event()
    other_manager = stdlib_logging.Manager(stdlib_logging.RootLogger(stdlib_logging.WARNING))

    def controlled_close(handlers: tuple[object, ...]) -> None:
        inside_close.set()
        if not release_close.wait(timeout=2):
            raise AssertionError("manager-scope test did not release reconfiguration")
        original_close(handlers)

    monkeypatch.setattr(logging_module, "_close_owned_handlers", controlled_close)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(configure_logging, "INFO")
        assert inside_close.wait(timeout=1)
        other_manager.disable = stdlib_logging.CRITICAL
        release_close.set()
        future.result(timeout=2)

    assert stdlib_logging.getLogger().manager.disable == stdlib_logging.NOTSET
    assert other_manager.disable == stdlib_logging.CRITICAL


def test_safe_manager_disable_accepts_exact_known_level_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging("INFO")
    monkeypatch.setitem(stdlib_logging._nameToLevel, "CUSTOM_DISABLE", 35)  # type: ignore[attr-defined]

    for level_name, expected in (
        ("CRITICAL", stdlib_logging.CRITICAL),
        ("NOTSET", stdlib_logging.NOTSET),
        ("WARN", stdlib_logging.WARNING),
        ("FATAL", stdlib_logging.FATAL),
        ("CUSTOM_DISABLE", 35),
    ):
        stdlib_logging.disable(level_name)  # type: ignore[arg-type]

        assert stdlib_logging.getLogger().manager.disable == expected


def test_initial_configuration_blocks_cached_loggers_before_cache_sweep(
    monkeypatch: pytest.MonkeyPatch,
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "initial-cache-sweep-fixture-secret"
    secret_registry.register(sentinel)
    captured: list[str] = []

    class ForeignHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append(record.getMessage())

    root = stdlib_logging.getLogger()
    victim = stdlib_logging.Logger("initial-cache-sweep-victim")
    victim.handlers = [ForeignHandler()]
    victim.propagate = False
    root.manager.loggerDict[victim.name] = victim
    original_clear = logging_module._clear_logger_cache_without_hooks
    inside_clear = threading.Event()
    release_clear = threading.Event()

    def controlled_clear(candidate: object) -> None:
        if candidate is victim:
            inside_clear.set()
            if not release_clear.wait(timeout=2):
                raise AssertionError("cache-sweep test did not release configuration")
        original_clear(candidate)

    monkeypatch.setattr(logging_module, "_clear_logger_cache_without_hooks", controlled_clear)
    try:
        assert victim.isEnabledFor(stdlib_logging.ERROR) is True
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(configure_logging, "INFO")
            try:
                assert inside_clear.wait(timeout=1)
                assert root.manager.disable == logging_module._DISABLE_DURING_RECONFIGURE
                victim.error("event contains %s", sentinel)
            finally:
                release_clear.set()
            future.result(timeout=2)

        assert captured == []
    finally:
        release_clear.set()
        root.manager.loggerDict.pop(victim.name, None)


def test_reconfiguration_never_exposes_raw_last_resort_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "reconfigure-last-resort-fixture-secret"
    secret_registry.register(sentinel)
    configure_logging("INFO")
    original_close = logging_module._close_owned_handlers
    inside_close = threading.Event()
    release_close = threading.Event()

    def controlled_close(handlers: tuple[stdlib_logging.Handler, ...]) -> None:
        inside_close.set()
        if not release_close.wait(timeout=2):
            raise AssertionError("reconfiguration test did not release close")
        original_close(handlers)

    monkeypatch.setattr(logging_module, "_close_owned_handlers", controlled_close)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(configure_logging, "INFO")
        assert inside_close.wait(timeout=1)
        logger = stdlib_logging.getLogger("reconfigure-emitter-test")
        logger.handlers = [stdlib_logging.NullHandler()]
        logger.filters = [stdlib_logging.Filter()]
        assert logger.isEnabledFor(stdlib_logging.ERROR) is False
        logger.error("event contains %s", sentinel)
        release_close.set()
        future.result(timeout=2)

    assert sentinel not in capsys.readouterr().err
    assert logger.isEnabledFor(stdlib_logging.ERROR) is True
    assert logger.handlers == []
    assert logger.filters == []
    assert logger.propagate is True


def test_reconfiguration_reasserts_safe_logging_globals_after_unlocked_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging("INFO")
    original_close = logging_module._close_owned_handlers
    inside_close = threading.Event()
    release_close = threading.Event()
    factory_calls: list[tuple[object, object]] = []

    class ForeignLastResort(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            del record

    foreign_last_resort = ForeignLastResort()

    def foreign_factory(*args: Any, **kwargs: Any) -> stdlib_logging.LogRecord:
        factory_calls.append((args[4], args[5]))
        return stdlib_logging.LogRecord(*args, **kwargs)

    def controlled_close(handlers: tuple[object, ...]) -> None:
        inside_close.set()
        if not release_close.wait(timeout=2):
            raise AssertionError("reconfiguration test did not release close")
        original_close(handlers)

    monkeypatch.setattr(logging_module, "_close_owned_handlers", controlled_close)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(configure_logging, "INFO")
        assert inside_close.wait(timeout=1)
        stdlib_logging.setLoggerClass(stdlib_logging.Logger)
        stdlib_logging.setLogRecordFactory(foreign_factory)
        stdlib_logging.lastResort = foreign_last_resort
        release_close.set()
        future.result(timeout=2)

    assert stdlib_logging.getLoggerClass() is logging_module._SafeLogger
    assert stdlib_logging.getLogRecordFactory() is logging_module._safe_log_record_factory
    assert stdlib_logging.lastResort is not foreign_last_resort
    stdlib_logging.getLogger("post-reconfigure-global-test").error("visible")
    assert factory_calls == []


def test_configure_logging_replaces_manager_specific_logger_class() -> None:
    class ForeignLogger(stdlib_logging.Logger):
        pass

    root = stdlib_logging.getLogger()
    root.manager.loggerClass = ForeignLogger

    configure_logging("INFO")

    assert root.manager.loggerClass is logging_module._SafeLogger
    assert type(stdlib_logging.getLogger("manager-class-test")) is logging_module._SafeLogger


def test_malformed_stdlib_formatting_drops_record_without_raw_error_diagnostics(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "malformed-format-fixture-secret"
    secret_registry.register(sentinel)
    configure_logging("INFO")

    stdlib_logging.getLogger("malformed-format-test").error("two placeholders: %s %s", sentinel)

    assert sentinel not in capsys.readouterr().err


def test_stdlib_arguments_are_sanitized_before_percent_repr_or_str_formatting(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    text_secret = "repr-fixture\nsecret"
    byte_secret = b"\xff\xfe\x80\x81"
    secret_registry.register(text_secret)
    secret_registry.register(byte_secret)
    hook_calls: list[str] = []

    class HostileArgument:
        def __str__(self) -> str:
            hook_calls.append("str")
            return "hostile-argument-fixture-secret"

        def __repr__(self) -> str:
            hook_calls.append("repr")
            return "hostile-argument-fixture-secret"

    configure_logging("INFO")
    logger = stdlib_logging.getLogger("safe-stdlib-formatting-test")
    logger.error("text=%r", text_secret)
    logger.error("bytes=%s", byte_secret)
    logger.error("object=%s", HostileArgument())

    rendered = capsys.readouterr().err
    assert hook_calls == []
    assert "repr-fixture\\nsecret" not in rendered
    assert "\\xff\\xfe\\x80\\x81" not in rendered
    assert "hostile-argument-fixture-secret" not in rendered


def test_safe_stdlib_percent_formatting_remains_visible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    logger = stdlib_logging.getLogger("visible-stdlib-formatting-test")

    logger.error("ordinary %s %d %.2f", "visible", 7, 1.25)
    logger.error("mapping %(label)s %(count)d", {"label": "visible", "count": 3})

    payloads = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]
    assert [payload["event"] for payload in payloads] == [
        "ordinary visible 7 1.25",
        "mapping visible 3",
    ]


def test_safe_logger_boundaries_preserve_application_caller_metadata() -> None:
    captured: list[tuple[str, str | None]] = []

    class CapturingHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append((record.name, record.funcName))

    configure_logging("INFO")
    logger = stdlib_logging.getLogger("caller-metadata-test")
    logger.handlers = [CapturingHandler()]
    logger.propagate = False
    root = stdlib_logging.getLogger()
    root.addHandler(CapturingHandler())

    def emit_from_application() -> None:
        logger.error("named caller")
        root.error("root caller")

    emit_from_application()

    assert captured == [
        ("caller-metadata-test", "emit_from_application"),
        ("root", "emit_from_application"),
    ]


def test_existing_structlog_logger_preserves_application_caller_metadata() -> None:
    captured: list[str | None] = []

    class CapturingHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append(record.funcName)

    logger = structlog.stdlib.LoggerFactory()("structlog-caller-metadata-test")
    assert type(logger) is logging_module._STRUCTLOG_LOGGER_TYPE
    configure_logging("INFO")
    logger.handlers = [CapturingHandler()]
    logger.propagate = False
    adapter = stdlib_logging.LoggerAdapter(logger, {})

    def emit_from_application() -> None:
        logger.error("structlog caller")
        logger.exception("structlog exception caller")
        adapter.error("structlog adapter caller")
        adapter.exception("structlog adapter exception caller")

    emit_from_application()

    assert captured == ["emit_from_application"] * 4


def test_configured_structlog_logger_preserves_application_caller_metadata() -> None:
    captured: list[str | None] = []

    class CapturingHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append(record.funcName)

    configure_logging("INFO")
    stdlib_logger = stdlib_logging.getLogger("configured-structlog-caller-test")
    stdlib_logger.handlers = [CapturingHandler()]
    stdlib_logger.propagate = False
    logger = structlog.get_logger("configured-structlog-caller-test")

    def emit_from_application() -> None:
        logger.info("configured structlog caller")

    emit_from_application()

    assert captured == ["emit_from_application"]


def test_structlog_factory_preserves_unnamed_module_and_rejects_non_exact_name() -> None:
    configure_logging("INFO")
    factory = structlog.get_config()["logger_factory"]
    hook_calls: list[str] = []

    class HostileName(str):
        def __hash__(self) -> int:
            hook_calls.append("hash")
            return str.__hash__(self)

        def __eq__(self, other: object) -> bool:
            hook_calls.append("eq")
            return str.__eq__(self, other)

    def create_unnamed_logger() -> stdlib_logging.Logger:
        return factory()

    assert create_unnamed_logger().name == __name__
    with pytest.raises(TypeError):
        factory(object())
    with pytest.raises(TypeError):
        factory(HostileName("hostile-logger-name"))
    assert hook_calls == []


def test_configure_logging_replaces_per_instance_find_caller_hook() -> None:
    hook_calls: list[tuple[object, object]] = []
    captured: list[str | None] = []

    class CapturingHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append(record.funcName)

    def foreign_find_caller(
        stack_info: object = False,
        stacklevel: object = 1,
    ) -> tuple[str, int, str, None]:
        hook_calls.append((stack_info, stacklevel))
        return __file__, 1, "foreign_find_caller", None

    root = stdlib_logging.getLogger()
    logger = stdlib_logging.Logger("foreign-find-caller-test")
    logger.__dict__["findCaller"] = foreign_find_caller
    root.manager.loggerDict[logger.name] = logger
    configure_logging("INFO")
    logger.handlers = [CapturingHandler()]
    logger.propagate = False

    def emit_from_application() -> None:
        logger.error("caller hook")

    emit_from_application()

    assert hook_calls == []
    assert captured == ["emit_from_application"]


def test_configure_logging_replaces_per_instance_emission_hooks() -> None:
    hook_calls: list[str] = []
    captured: list[str] = []

    class CapturingHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.append(record.getMessage())

    def suppress_error(logger: object, *args: object, **kwargs: object) -> None:
        del logger, args, kwargs
        hook_calls.append("error")

    def suppress_enabled(logger: object, level: object) -> bool:
        del logger, level
        hook_calls.append("isEnabledFor")
        return False

    def foreign_effective_level(logger: object) -> int:
        del logger
        hook_calls.append("getEffectiveLevel")
        return stdlib_logging.CRITICAL

    root = stdlib_logging.getLogger()
    logger = stdlib_logging.Logger("foreign-emission-hook-test")
    logger.parent = root
    logger.__dict__["error"] = types.MethodType(suppress_error, logger)
    logger.__dict__["isEnabledFor"] = types.MethodType(suppress_enabled, logger)
    logger.__dict__["getEffectiveLevel"] = types.MethodType(foreign_effective_level, logger)
    root.manager.loggerDict[logger.name] = logger
    configure_logging("INFO")
    logger.handlers = [CapturingHandler()]
    logger.propagate = False

    logger.error("visible")

    assert hook_calls == []
    assert captured == ["visible"]


def test_safe_logger_boundary_does_not_delegate_raw_inputs_to_import_hook(
    monkeypatch: pytest.MonkeyPatch,
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "import-hook-fixture-secret"
    secret_registry.register(sentinel)
    observed: list[tuple[object, object, object]] = []

    def import_time_hook(
        logger: object,
        level: object,
        msg: object,
        args: object,
        exc_info: object = None,
        extra: object = None,
        stack_info: object = False,
        stacklevel: object = 1,
    ) -> None:
        del logger, level, exc_info, stack_info, stacklevel
        observed.append((msg, args, extra))

    monkeypatch.setattr(logging_module, "_ORIGINAL_LOGGER_LOG", import_time_hook)
    configure_logging("INFO")
    stdlib_logging.getLogger("import-hook-test").error(
        "event contains %s",
        sentinel,
        extra={"payload": sentinel},
    )

    assert observed == []


def test_safe_logger_boundary_bypasses_preinstalled_handle_hook(
    monkeypatch: pytest.MonkeyPatch,
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "RHC123456789-HANDLE-HOOK"
    secret_registry.register(sentinel)
    observed_tracebacks: list[object] = []
    observed_logger_names: list[object] = []
    original_handle = stdlib_logging.Logger.handle

    def instrumented_handle(
        logger: stdlib_logging.Logger,
        record: stdlib_logging.LogRecord,
    ) -> None:
        state = logging_module._LOG_RECORD_DICT_DESCRIPTOR.__get__(record, type(record))
        exception_info = dict.get(state, "exc_info")
        if type(exception_info) is tuple and len(exception_info) == 3:
            observed_tracebacks.append(tuple.__getitem__(exception_info, 2))
        provenance_logger = dict.get(state, "_logger")
        if isinstance(provenance_logger, stdlib_logging.Logger):
            provenance_state = logging_module._FILTERER_DICT_DESCRIPTOR.__get__(
                provenance_logger,
                type(provenance_logger),
            )
            observed_logger_names.append(dict.get(provenance_state, "name"))
        original_handle(logger, record)

    monkeypatch.setattr(stdlib_logging.Logger, "handle", instrumented_handle)
    configure_logging("INFO")
    try:
        secret_local = sentinel
        raise RuntimeError(secret_local)
    except RuntimeError:
        stdlib_logging.getLogger("handle-exception-test").exception("request failed")
    structlog.get_logger(sentinel).info("visible")

    assert observed_tracebacks == []
    assert observed_logger_names == []


def test_registered_format_template_is_redacted_before_interpolation(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    registered_template = "prefix-%s-suffix"
    secret_registry.register(registered_template)
    configure_logging("INFO")

    stdlib_logging.getLogger("registered-format-template-test").error(
        registered_template,
        "visible",
    )

    payload = json.loads(capsys.readouterr().err)
    assert payload["event"] == "[REDACTED]"
    assert "prefix" not in payload["event"]
    assert "suffix" not in payload["event"]


def test_stdlib_extra_and_exc_info_hooks_are_never_invoked(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "stdlib-pre-factory-hook-fixture-secret"
    secret_registry.register(sentinel)
    hook_calls: list[str] = []

    class HostileExtra(dict[str, object]):
        def __iter__(self) -> Any:
            hook_calls.append("extra_iter")
            return super().__iter__()

    class HostileExcInfo:
        def __bool__(self) -> bool:
            hook_calls.append("exc_bool")
            return True

    class HostileName:
        def __eq__(self, other: object) -> bool:
            del other
            hook_calls.append("name_eq")
            return False

    configure_logging("INFO")
    logger = stdlib_logging.getLogger("safe-extra-test")
    logger.error("safe extra", extra=HostileExtra(payload=sentinel))
    logger.error("safe exc info", exc_info=HostileExcInfo())  # type: ignore[arg-type]
    logger.error(
        "safe provenance",
        extra={"_logger": object(), "_name": HostileName(), "payload": sentinel},
    )

    rendered = capsys.readouterr().err
    assert hook_calls == []
    assert sentinel not in rendered


def test_stdlib_extra_key_collisions_do_not_invoke_foreign_equality(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "stdlib-extra-key-collision-fixture-secret"
    secret_registry.register(sentinel)
    equality_calls: list[str] = []

    class HostileKey:
        def __hash__(self) -> int:
            return hash("_logger")

        def __eq__(self, other: object) -> bool:
            del other
            equality_calls.append("eq")
            return False

    configure_logging("INFO")
    logger = stdlib_logging.getLogger("safe-extra-key-collision-test")
    logger.error("safe key collision", extra={HostileKey(): sentinel})  # type: ignore[dict-item]

    assert equality_calls == []
    assert sentinel not in capsys.readouterr().err


def test_exception_info_is_sanitized_before_traceback_formatting(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "exception-repr-fixture\nsecret"
    secret_registry.register(sentinel)
    hook_calls: list[str] = []

    class HostileException(RuntimeError):
        def __str__(self) -> str:
            hook_calls.append("str")
            return repr(self.args)

    configure_logging("INFO")
    try:
        raise HostileException(sentinel, 2)
    except HostileException:
        structlog.get_logger("safe-exception-test").exception("request failed")

    rendered = capsys.readouterr().err
    assert hook_calls == []
    assert "exception-repr-fixture\\nsecret" not in rendered


def test_configure_logging_replaces_custom_record_factory_before_emission(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "record-factory-fixture-secret"
    secret_registry.register(sentinel)
    captured_by_factory: list[tuple[object, object]] = []

    def foreign_factory(*args: Any, **kwargs: Any) -> stdlib_logging.LogRecord:
        captured_by_factory.append((args[4], args[5]))
        return stdlib_logging.LogRecord(*args, **kwargs)

    stdlib_logging.setLogRecordFactory(foreign_factory)
    configure_logging("INFO")
    stdlib_logging.getLogger("record-factory-test").error("event contains %s", sentinel)

    assert captured_by_factory == []
    assert sentinel not in capsys.readouterr().err


def test_safe_record_factory_redacts_ambient_thread_name(
    monkeypatch: pytest.MonkeyPatch,
    secret_registry: SecretRegistry,
) -> None:
    sentinel = "ambient-record-fixture-secret"
    secret_registry.register(sentinel)
    captured: list[object] = []

    class CapturingHandler(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            captured.extend((record.threadName, record.levelname))

    configure_logging("INFO")
    logger = stdlib_logging.getLogger("ambient-record-test")
    logger.handlers = [CapturingHandler()]
    logger.propagate = False
    thread = threading.current_thread()
    original_name = thread.name
    custom_level = 35
    monkeypatch.setitem(stdlib_logging._levelToName, custom_level, sentinel)  # type: ignore[attr-defined]
    try:
        thread.name = sentinel
        logger.log(custom_level, "visible")
    finally:
        thread.name = original_name

    assert captured == ["[REDACTED]", "[REDACTED]"]


def test_configure_logging_retains_displaced_global_logging_objects() -> None:
    finalizer_calls: list[str] = []

    class FinalizingLoggerMeta(type):
        def __del__(cls) -> None:
            finalizer_calls.append("logger_class")

    class FinalizingFactory:
        def __call__(self, *args: Any, **kwargs: Any) -> stdlib_logging.LogRecord:
            return stdlib_logging.LogRecord(*args, **kwargs)

        def __del__(self) -> None:
            finalizer_calls.append("record_factory")

    foreign_logger_class = FinalizingLoggerMeta(
        "ForeignLogger",
        (stdlib_logging.Logger,),
        {"__module__": __name__},
    )
    stdlib_logging.setLoggerClass(foreign_logger_class)
    stdlib_logging.setLogRecordFactory(FinalizingFactory())
    del foreign_logger_class

    configure_logging("INFO")
    gc.collect()

    assert finalizer_calls == []


def test_configure_logging_retains_displaced_structlog_configuration() -> None:
    finalizer_calls: list[str] = []

    class FinalizingProcessor:
        def __call__(
            self,
            logger: object,
            method_name: str,
            event_dict: dict[str, object],
        ) -> dict[str, object]:
            del logger, method_name
            return event_dict

        def __del__(self) -> None:
            finalizer_calls.append("structlog_processor")

    processor = FinalizingProcessor()
    structlog.configure(processors=[processor])
    del processor

    configure_logging("INFO")
    gc.collect()

    assert finalizer_calls == []


def test_failed_configuration_retains_displaced_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalizer_calls: list[str] = []

    class FinalizingLastResort(stdlib_logging.Handler):
        def emit(self, record: stdlib_logging.LogRecord) -> None:
            del record

        def __del__(self) -> None:
            finalizer_calls.append("last_resort")

    stdlib_logging.lastResort = FinalizingLastResort()

    def fail_normalization(*args: object, **kwargs: object) -> tuple[object, ...]:
        del args, kwargs
        raise RuntimeError("forced normalization failure")

    monkeypatch.setattr(logging_module, "_normalize_logger_extensions", fail_normalization)

    with pytest.raises(RuntimeError, match="forced normalization failure"):
        configure_logging("INFO")
    gc.collect()

    assert finalizer_calls == []


def test_failed_configuration_retains_mutated_owned_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalizer_calls: list[str] = []

    class FinalizingFormatter:
        def __del__(self) -> None:
            finalizer_calls.append("owned_formatter")

    owned_last_resort = logging_module._FailClosedStreamHandler()
    owned_last_resort.formatter = FinalizingFormatter()  # type: ignore[assignment]
    stdlib_logging.lastResort = owned_last_resort
    del owned_last_resort

    def fail_normalization(*args: object, **kwargs: object) -> tuple[object, ...]:
        del args, kwargs
        raise RuntimeError("forced normalization failure")

    monkeypatch.setattr(logging_module, "_normalize_logger_extensions", fail_normalization)

    with pytest.raises(RuntimeError, match="forced normalization failure"):
        configure_logging("INFO")
    gc.collect()

    assert finalizer_calls == []


def test_post_configuration_last_resort_uses_the_redacting_json_sink(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    sentinel = "late-last-resort-fixture-secret"
    secret_registry.register(sentinel)
    configure_logging("INFO")
    logger = stdlib_logging.getLogger("late-nonpropagating-test")
    original_handlers = tuple(logger.handlers)
    original_propagate = logger.propagate
    try:
        logger.handlers = []
        logger.propagate = False
        logger.error("event contains %s", sentinel)

        line = capsys.readouterr().err.strip()
        assert json.loads(line)
        assert sentinel not in line
    finally:
        logger.handlers = list(original_handlers)
        logger.propagate = original_propagate


def test_configure_logging_fails_closed_without_validated_size_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )

    with pytest.raises(RuntimeError, match="logging settings are not installed"):
        configure_logging("INFO")


def test_logging_settings_install_is_exact_enveloped_and_conflict_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )
    configured = LoggingSettings(max_event_bytes=128)
    envelope = LoggingSettings(max_event_bytes=256)

    logging_module._install_logging_settings(configured, envelope)
    logging_module._install_logging_settings(configured, envelope)

    with pytest.raises(ValueError, match="exceeds the release envelope"):
        logging_module._install_logging_settings(LoggingSettings(max_event_bytes=257), envelope)
    with pytest.raises(RuntimeError, match="already installed"):
        logging_module._install_logging_settings(LoggingSettings(max_event_bytes=64), envelope)
    with pytest.raises(TypeError, match="canonical validated model"):
        logging_module._install_logging_settings(object(), envelope)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", [True, 1, "128", None])
def test_logging_settings_install_revalidates_forged_canonical_models(
    invalid: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )
    forged = LoggingSettings.model_construct(max_event_bytes=invalid)

    with pytest.raises(ValueError, match="canonical validation"):
        logging_module._install_logging_settings(
            forged,
            LoggingSettings(max_event_bytes=256),
        )


def test_post_redaction_size_limit_is_config_owned_and_collision_safe(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )
    configured = LoggingSettings(max_event_bytes=128)
    envelope = LoggingSettings(max_event_bytes=256)
    logging_module._install_logging_settings(configured, envelope)

    registry = SecretRegistry()
    raw_secret = "registered-large-value-" * 32
    registry.register(raw_secret)
    configure_logging("INFO")
    logger = structlog.get_logger("size-limit-test")

    logger.info(raw_secret)
    logger.info("visible oversized message " * 32)

    lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert len(lines) == 2
    assert raw_secret not in "".join(lines)
    assert "truncation_status" not in lines[0]
    assert "truncation_status" in lines[1]
    assert len(lines[1].encode("utf-8")) <= configured.max_event_bytes


def test_oversized_stdlib_event_emits_a_bounded_replacement(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )
    settings = LoggingSettings(max_event_bytes=128)
    logging_module._install_logging_settings(settings, settings)
    configure_logging("INFO")

    stdlib_logging.getLogger("oversized-stdlib-test").error("visible oversized message " * 32)

    line = capsys.readouterr().err.strip()
    payload = json.loads(line)
    assert payload["truncation_status"] == "size_limit"
    assert len(line.encode("utf-8")) <= settings.max_event_bytes


def test_foreign_redaction_failure_still_emits_the_generic_safe_event(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_logging("INFO")

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("redaction-failure-detail-must-not-escape")

    monkeypatch.setattr(logging_module, "_redact_mapping", fail)
    stdlib_logging.getLogger("foreign-redaction-failure-test").error("original-provider-secret")

    line = capsys.readouterr().err.strip()
    assert json.loads(line) == {
        "event": "log redaction failed",
        "redaction_status": "failed_closed",
    }
    assert "provider-secret" not in line
    assert "failure-detail" not in line


def test_oversized_replacement_event_is_safe_when_registered_material_overlaps_marker(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        logging_module, "_LOGGING_RUNTIME_STATE", logging_module._LoggingRuntimeState()
    )
    settings = LoggingSettings(max_event_bytes=64)
    logging_module._install_logging_settings(settings, settings)
    SecretRegistry().register("trunc")
    configure_logging("INFO")

    structlog.get_logger("size-marker-collision-test").info("visible oversized message " * 32)

    line = capsys.readouterr().err.strip()
    assert json.loads(line) == {}
    assert "trunc" not in line
    assert len(line.encode("utf-8")) <= settings.max_event_bytes


def test_configured_structlog_emits_secret_free_aware_utc_json(
    capsys: pytest.CaptureFixture[str], secret_registry: SecretRegistry
) -> None:
    secret_registry.register("logged-fixture-secret")
    configure_logging("INFO")
    logger = structlog.get_logger("redaction-test")

    try:
        raise RuntimeError("failure contains logged-fixture-secret")
    except RuntimeError:
        logger.exception(
            "request failed",
            authorization="Bearer logged-fixture-secret",
            endpoint="https://host/path?account_id=RHC123456789",
        )

    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip().splitlines()[-1])
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["event"] == "request failed"
    assert payload["level"] == "error"
    assert payload["timestamp"].endswith("Z") or payload["timestamp"].endswith("+00:00")
    assert "logged-fixture-secret" not in serialized
    assert "RHC123456789" not in serialized
    assert "Bearer" not in serialized


def test_makefile_has_exact_baseline_targets_and_commands() -> None:
    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY:"))
    assert {"format", "lint", "typecheck", "test", "security"} <= set(phony.split()[1:])
    assert "format:\n\tuv run ruff format ." in makefile
    assert "lint:\n\tuv run ruff check ." in makefile
    assert "typecheck:\n\tuv run mypy src" in makefile
    assert (
        "test:\n\tuv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80"
        in makefile
    )
    assert ("security:\n\tuv run bandit -c pyproject.toml -r src\n\tuv run pip-audit") in makefile


def test_ci_is_read_only_and_has_only_the_baseline_offline_test_matrix() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    folded = workflow.casefold()

    assert 'python-version: ["3.12", "3.13", "3.14"]' in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in workflow
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run mypy src" in workflow
    assert "uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80" in workflow
    for forbidden in (
        "pull_request_target",
        "secret",
        "credential",
        "oauth",
        "api_key",
        "authenticated",
    ):
        assert forbidden not in folded


@pytest.mark.parametrize("relative_path", ["README.md", "Codex.md", "docs/architecture.md"])
def test_baseline_docs_describe_only_the_current_safe_implementation(relative_path: str) -> None:
    document = (_REPO_ROOT / relative_path).read_text(encoding="utf-8").casefold()

    for required in (
        "foundation",
        "broker protocols",
        "paper-safe",
        "fail-closed",
        "connected-shadow",
        "write-incapable",
        "prediction live execution is unsupported",
        "no live order has been placed",
        "no profitability claim",
    ):
        assert required in document
    if relative_path == "README.md":
        assert "offline `backtest`, `simulate`, and one-cycle `paper` cli" in document
