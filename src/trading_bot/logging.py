"""Structured logging whose event data is redacted before JSON serialization."""

from __future__ import annotations

import dataclasses as _dataclasses
import json as _json
import logging as _stdlib_logging
import math as _math
import threading as _threading
import types as _types
from decimal import Decimal as _Decimal
from typing import Final as _Final
from typing import cast as _cast

import structlog as _structlog

from trading_bot.capabilities.sanitization import (
    name_is_sensitive as _name_is_sensitive,
)
from trading_bot.capabilities.sanitization import (
    text_contains_sensitive_material as _text_contains_sensitive_material,
)

_REDACTED: _Final = "[REDACTED]"
_REDACTED_BYTES: _Final = "[REDACTED_BYTES]"
_REDACTED_CYCLE: _Final = "[REDACTED_CYCLE]"
_REDACTED_KEY: _Final = "[REDACTED_KEY]"
_REDACTED_OBJECT: _Final = "[REDACTED_OBJECT]"
_REDACTED_NONFINITE: _Final = "[REDACTED_NONFINITE]"
_FAILED_EVENT: _Final[dict[str, object]] = {
    "event": "log redaction failed",
    "redaction_status": "failed_closed",
}
_OWN_HANDLER_MARKER: _Final = "_trading_bot_json_handler"
_LEVELS: _Final[dict[str, int]] = {
    "DEBUG": _stdlib_logging.DEBUG,
    "INFO": _stdlib_logging.INFO,
    "WARNING": _stdlib_logging.WARNING,
    "ERROR": _stdlib_logging.ERROR,
    "CRITICAL": _stdlib_logging.CRITICAL,
}
_EXCEPTION_ARGS_DESCRIPTOR = BaseException.__dict__["args"]


class _RegistryState:
    __slots__ = ("byte_values", "lock", "text_values")

    def __init__(self) -> None:
        self.lock = _threading.RLock()
        self.text_values: tuple[str, ...] = ()
        self.byte_values: tuple[bytes, ...] = ()


_REGISTRY_STATE = _RegistryState()


class SecretRegistry:
    """Register exact in-memory secret values for process-wide log redaction."""

    __slots__ = ()

    def register(self, value: str | bytes) -> None:
        """Register a nonempty exact text or byte value without exposing it."""
        if type(value) not in {str, bytes}:
            raise TypeError("secret must be exact text or bytes")
        if not value:
            raise ValueError("secret must not be empty")

        with _REGISTRY_STATE.lock:
            if type(value) is str:
                text_values = {*_REGISTRY_STATE.text_values, value}
                _REGISTRY_STATE.text_values = tuple(
                    sorted(text_values, key=lambda item: (-len(item), item))
                )
                return

            byte_value = _cast(bytes, value)
            byte_values = {*_REGISTRY_STATE.byte_values, byte_value}
            _REGISTRY_STATE.byte_values = tuple(
                sorted(byte_values, key=lambda item: (-len(item), item))
            )
            try:
                decoded = bytes.decode(byte_value, "utf-8", "strict")
            except UnicodeDecodeError:
                return
            text_values = {*_REGISTRY_STATE.text_values, decoded}
            _REGISTRY_STATE.text_values = tuple(
                sorted(text_values, key=lambda item: (-len(item), item))
            )

    def __repr__(self) -> str:
        return "SecretRegistry()"


def _registered_text_snapshot() -> tuple[str, ...]:
    with _REGISTRY_STATE.lock:
        return _REGISTRY_STATE.text_values


def _safe_marker(value: str, registered: tuple[str, ...]) -> str:
    return "" if any(secret in value for secret in registered) else value


def _redact_text(value: str, registered: tuple[str, ...]) -> str:
    marker = _safe_marker(_REDACTED, registered)
    redacted = value
    for secret in registered:
        redacted = redacted.replace(secret, marker)
    if _text_contains_sensitive_material(redacted):
        redacted = marker
    if any(secret in redacted for secret in registered):
        return ""
    return redacted


def _safe_key(value: object, registered: tuple[str, ...]) -> tuple[str, bool]:
    if type(value) is not str:
        return _safe_marker(_REDACTED_KEY, registered), True
    redacted = _redact_text(value, registered)
    if redacted == _safe_marker(_REDACTED, registered):
        return _safe_marker(_REDACTED_KEY, registered), True
    return redacted, _name_is_sensitive(value)


def _redact_mapping(
    value: dict[object, object],
    *,
    registered: tuple[str, ...],
    active_ids: set[int],
) -> dict[str, object] | str:
    value_id = id(value)
    if value_id in active_ids:
        return _safe_marker(_REDACTED_CYCLE, registered)
    active_ids.add(value_id)
    try:
        result: dict[str, object] = {}
        for raw_key, raw_value in dict.items(value):
            key, sensitive = _safe_key(raw_key, registered)
            if key in result:
                result[key] = _safe_marker(_REDACTED, registered)
                continue
            result[key] = (
                _safe_marker(_REDACTED, registered)
                if sensitive
                else _redact_value(raw_value, registered=registered, active_ids=active_ids)
            )
        return result
    finally:
        active_ids.remove(value_id)


def _redact_sequence(
    value: list[object] | tuple[object, ...],
    *,
    registered: tuple[str, ...],
    active_ids: set[int],
) -> list[object] | str:
    value_id = id(value)
    if value_id in active_ids:
        return _safe_marker(_REDACTED_CYCLE, registered)
    active_ids.add(value_id)
    try:
        iterator = (
            list.__iter__(value)
            if type(value) is list
            else tuple.__iter__(_cast(tuple[object, ...], value))
        )
        return [
            _redact_value(item, registered=registered, active_ids=active_ids) for item in iterator
        ]
    finally:
        active_ids.remove(value_id)


def _json_sort_key(value: object) -> str:
    return _json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _redact_set(
    value: set[object] | frozenset[object],
    *,
    registered: tuple[str, ...],
    active_ids: set[int],
) -> list[object] | str:
    value_id = id(value)
    if value_id in active_ids:
        return _safe_marker(_REDACTED_CYCLE, registered)
    active_ids.add(value_id)
    try:
        iterator = (
            set.__iter__(value)
            if type(value) is set
            else frozenset.__iter__(_cast(frozenset[object], value))
        )
        items = [
            _redact_value(item, registered=registered, active_ids=active_ids) for item in iterator
        ]
        return sorted(items, key=_json_sort_key)
    finally:
        active_ids.remove(value_id)


def _slot_value(value: object, name: str, registered: tuple[str, ...]) -> object:
    value_type = type(value)
    mro = type.__getattribute__(value_type, "__mro__")
    for owner in mro:
        namespace = type.__getattribute__(owner, "__dict__")
        descriptor = namespace.get(name)
        if type(descriptor) is _types.MemberDescriptorType:
            return descriptor.__get__(value, value_type)
    return _safe_marker(_REDACTED_OBJECT, registered)


def _redact_dataclass(
    value: object,
    *,
    registered: tuple[str, ...],
    active_ids: set[int],
) -> dict[str, object] | str:
    value_id = id(value)
    if value_id in active_ids:
        return _safe_marker(_REDACTED_CYCLE, registered)
    value_type = type(value)
    namespace = type.__getattribute__(value_type, "__dict__")
    field_map = namespace.get("__dataclass_fields__")
    if type(field_map) is not dict or any(
        type(field) is not _dataclasses.Field for field in dict.values(field_map)
    ):
        return _safe_marker(_REDACTED_OBJECT, registered)
    try:
        instance_values = object.__getattribute__(value, "__dict__")
    except AttributeError:
        instance_values = None
    if instance_values is not None and type(instance_values) is not dict:
        return _safe_marker(_REDACTED_OBJECT, registered)
    safe_instance_values: dict[str, object] | None = None
    if type(instance_values) is dict:
        safe_instance_values = {}
        for stored_name, stored_value in dict.items(instance_values):
            if type(stored_name) is not str:
                return _safe_marker(_REDACTED_OBJECT, registered)
            safe_instance_values[stored_name] = stored_value

    active_ids.add(value_id)
    try:
        result: dict[str, object] = {}
        for field in dict.values(field_map):
            name = object.__getattribute__(field, "name")
            if type(name) is not str:
                return _safe_marker(_REDACTED_OBJECT, registered)
            if safe_instance_values is not None and name in safe_instance_values:
                field_value = dict.__getitem__(safe_instance_values, name)
            else:
                field_value = _slot_value(value, name, registered)
            key, sensitive = _safe_key(name, registered)
            if key in result:
                result[key] = _safe_marker(_REDACTED, registered)
                continue
            result[key] = (
                _safe_marker(_REDACTED, registered)
                if sensitive
                else _redact_value(field_value, registered=registered, active_ids=active_ids)
            )
        return result
    finally:
        active_ids.remove(value_id)


def _redact_exception(
    value: BaseException,
    *,
    registered: tuple[str, ...],
    active_ids: set[int],
) -> dict[str, object] | str:
    value_id = id(value)
    if value_id in active_ids:
        return _safe_marker(_REDACTED_CYCLE, registered)
    active_ids.add(value_id)
    try:
        exception_type = type(value)
        type_name = type.__getattribute__(exception_type, "__name__")
        safe_type = (
            _redact_text(type_name, registered)
            if type(type_name) is str
            else _safe_marker(_REDACTED_OBJECT, registered)
        )
        args = _EXCEPTION_ARGS_DESCRIPTOR.__get__(value, exception_type)
        return {
            "type": safe_type,
            "args": _redact_value(args, registered=registered, active_ids=active_ids),
        }
    finally:
        active_ids.remove(value_id)


def _redact_value(
    value: object,
    *,
    registered: tuple[str, ...],
    active_ids: set[int],
) -> object:
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        return value if _math.isfinite(value) else _safe_marker(_REDACTED_NONFINITE, registered)
    if type(value) is str:
        return _redact_text(value, registered)
    if type(value) in {bytes, bytearray, memoryview}:
        return _safe_marker(_REDACTED_BYTES, registered)
    if type(value) is _Decimal:
        return str(value) if value.is_finite() else _safe_marker(_REDACTED_NONFINITE, registered)
    if type(value) is dict:
        return _redact_mapping(
            _cast(dict[object, object], value),
            registered=registered,
            active_ids=active_ids,
        )
    if type(value) in {list, tuple}:
        return _redact_sequence(
            _cast(list[object] | tuple[object, ...], value),
            registered=registered,
            active_ids=active_ids,
        )
    if type(value) in {set, frozenset}:
        return _redact_set(
            _cast(set[object] | frozenset[object], value),
            registered=registered,
            active_ids=active_ids,
        )
    if isinstance(value, BaseException):
        return _redact_exception(value, registered=registered, active_ids=active_ids)
    if "__dataclass_fields__" in type.__getattribute__(type(value), "__dict__"):
        return _redact_dataclass(value, registered=registered, active_ids=active_ids)
    return _safe_marker(_REDACTED_OBJECT, registered)


def _failed_event(registered: tuple[str, ...]) -> dict[str, object]:
    if any(
        secret in key or (type(value) is str and secret in value)
        for secret in registered
        for key, value in _FAILED_EVENT.items()
    ):
        return {}
    return dict(_FAILED_EVENT)


def redact_secrets(
    logger: object, method_name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    """Return detached, JSON-safe event data with secrets removed before serialization."""
    del logger, method_name
    registered: tuple[str, ...] = ()
    try:
        registered = _registered_text_snapshot()
        if type(event_dict) is not dict:
            return _failed_event(registered)
        return _cast(
            dict[str, object],
            _redact_mapping(
                _cast(dict[object, object], event_dict),
                registered=registered,
                active_ids=set(),
            ),
        )
    except Exception:
        return _failed_event(registered)


def _logging_processors() -> list[_structlog.typing.Processor]:
    return [
        _structlog.contextvars.merge_contextvars,
        _structlog.stdlib.add_log_level,
        _structlog.processors.TimeStamper(fmt="iso", utc=True),
        _structlog.processors.format_exc_info,
        _cast(_structlog.typing.Processor, redact_secrets),
    ]


def configure_logging(level: str) -> None:
    """Configure stdlib and Structlog JSON output at one validated standard level."""
    if type(level) is not str:
        raise TypeError("logging level must be text")
    normalized = level.upper()
    if normalized not in _LEVELS:
        raise ValueError("unsupported logging level")
    numeric_level = _LEVELS[normalized]

    root = _stdlib_logging.getLogger()
    for existing in tuple(root.handlers):
        root.removeHandler(existing)
        try:
            state = object.__getattribute__(existing, "__dict__")
        except AttributeError:
            continue
        if (
            type(existing) is _stdlib_logging.StreamHandler
            and type(state) is dict
            and state.get(_OWN_HANDLER_MARKER) is True
        ):
            _stdlib_logging.Handler.close(existing)

    pre_render = _logging_processors()
    renderer = _structlog.processors.JSONRenderer()
    formatter = _structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=pre_render,
    )
    handler = _stdlib_logging.StreamHandler()
    setattr(handler, _OWN_HANDLER_MARKER, True)
    handler.setLevel(numeric_level)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(numeric_level)

    _structlog.configure(
        processors=[
            *pre_render,
            _structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=_structlog.stdlib.LoggerFactory(),
        wrapper_class=_structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


__all__ = ["SecretRegistry", "configure_logging", "redact_secrets"]
