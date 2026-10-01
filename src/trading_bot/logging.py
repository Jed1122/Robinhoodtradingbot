"""Structured logging whose event data is redacted before JSON serialization."""

from __future__ import annotations

import dataclasses as _dataclasses
import io as _io
import json as _json
import logging as _stdlib_logging
import math as _math
import sys as _sys
import threading as _threading
import traceback as _traceback
import types as _types
from decimal import Decimal as _Decimal
from typing import Final as _Final
from typing import TextIO as _TextIO
from typing import cast as _cast

import structlog as _structlog
from pydantic import ValidationError as _ValidationError

from trading_bot.capabilities.sanitization import (
    name_is_sensitive as _name_is_sensitive,
)
from trading_bot.capabilities.sanitization import (
    text_contains_sensitive_material as _text_contains_sensitive_material,
)
from trading_bot.config.models import LoggingSettings as _LoggingSettings

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
_TRUNCATED_EVENT: _Final[dict[str, object]] = {
    "event": "log event truncated",
    "truncation_status": "size_limit",
}
_MISSING: _Final[object] = object()
_OWN_HANDLER_MARKER: _Final = "_trading_bot_json_handler"
_LOGGER_EMISSION_OVERRIDE_NAMES: _Final = (
    "callHandlers",
    "critical",
    "debug",
    "error",
    "exception",
    "fatal",
    "filter",
    "getEffectiveLevel",
    "handle",
    "info",
    "isEnabledFor",
    "log",
    "warn",
    "warning",
)
_LEVELS: _Final[dict[str, int]] = {
    "DEBUG": _stdlib_logging.DEBUG,
    "INFO": _stdlib_logging.INFO,
    "WARNING": _stdlib_logging.WARNING,
    "ERROR": _stdlib_logging.ERROR,
    "CRITICAL": _stdlib_logging.CRITICAL,
}
_EXCEPTION_ARGS_DESCRIPTOR = BaseException.__dict__["args"]
_EXCEPTION_TRACEBACK_DESCRIPTOR = BaseException.__dict__["__traceback__"]
_FILTERER_DICT_DESCRIPTOR = _stdlib_logging.Filterer.__dict__["__dict__"]
_LOG_RECORD_DICT_DESCRIPTOR = _stdlib_logging.LogRecord.__dict__["__dict__"]
_MANAGER_DICT_DESCRIPTOR = _stdlib_logging.Manager.__dict__["__dict__"]
_ORIGINAL_MANAGER_DISABLE_DESCRIPTOR: _Final = _stdlib_logging.Manager.__dict__["disable"]
_TYPE_DICT_DESCRIPTOR = type.__dict__["__dict__"]
_TYPE_MRO_DESCRIPTOR = type.__dict__["__mro__"]
_TYPE_NAME_DESCRIPTOR = type.__dict__["__name__"]
_ORIGINAL_LOGGER_LOG: _Final = _stdlib_logging.Logger._log
_DISABLE_DURING_RECONFIGURE: _Final = _sys.maxsize
_STRUCTLOG_LOGGER_TYPE: _Final = _structlog.stdlib._FixedFindCallerLogger


class _FailClosedStreamHandler(_stdlib_logging.StreamHandler[_TextIO]):
    """Drop formatting failures without allowing stdlib to print the raw record."""

    def handleError(self, record: _stdlib_logging.LogRecord) -> None:
        del record


class _SafeLogException(Exception):
    """Internal exact exception whose formatting cannot invoke application hooks."""


class _SafeLogger(_stdlib_logging.Logger):
    """Route every stdlib record through the fail-closed construction boundary."""

    def _log(
        self,
        level: object,
        msg: object,
        args: object,
        exc_info: object = None,
        extra: object = None,
        stack_info: object = False,
        stacklevel: object = 1,
    ) -> None:
        safe_stacklevel = stacklevel if type(stacklevel) is int and stacklevel >= 1 else 1
        _safe_logger_log(
            self,
            level,
            msg,
            args,
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=safe_stacklevel,
        )

    def makeRecord(
        self,
        name: object,
        level: object,
        fn: object,
        lno: object,
        msg: object,
        args: object,
        exc_info: object,
        func: object = None,
        extra: object = None,
        sinfo: object = None,
    ) -> _stdlib_logging.LogRecord:
        return _safe_logger_make_record(
            self,
            name,
            level,
            fn,
            lno,
            msg,
            args,
            exc_info,
            func=func,
            extra=extra,
            sinfo=sinfo,
        )


_SAFE_PROVENANCE_LOGGER: _Final = _SafeLogger("")


class _ExactLoggerFactory:
    """Return only exact stdlib loggers without mutating the global logger class."""

    __slots__ = ()

    def __call__(self, *args: object) -> _stdlib_logging.Logger:
        if args:
            if type(args[0]) is not str:
                raise TypeError("logger name must be exact text")
            return _stdlib_logging.getLogger(args[0])
        frame = _first_application_frame()
        module_name = None if frame is None else dict.get(frame.f_globals, "__name__")
        name = module_name if type(module_name) is str else "trading_bot"
        return _stdlib_logging.getLogger(name)


def _class_namespace(
    value_type: type[object],
) -> _types.MappingProxyType[str, object]:
    namespace = _TYPE_DICT_DESCRIPTOR.__get__(value_type, type(value_type))
    if type(namespace) is not _types.MappingProxyType:
        raise RuntimeError("class namespace is not an exact mapping proxy")
    return namespace


def _class_mro(value_type: type[object]) -> tuple[type[object], ...]:
    mro = _TYPE_MRO_DESCRIPTOR.__get__(value_type, type(value_type))
    if type(mro) is not tuple:
        raise RuntimeError("class MRO is not an exact tuple")
    return _cast(tuple[type[object], ...], mro)


def _class_name(value_type: type[object]) -> str:
    name = _TYPE_NAME_DESCRIPTOR.__get__(value_type, type(value_type))
    if type(name) is not str:
        raise RuntimeError("class name is not exact text")
    return name


def _is_exception_instance(value: object) -> bool:
    return any(owner is BaseException for owner in _class_mro(type(value)))


class _RegistryState:
    __slots__ = ("byte_values", "lock", "text_values")

    def __init__(self) -> None:
        self.lock = _threading.RLock()
        self.text_values: tuple[str, ...] = ()
        self.byte_values: tuple[bytes, ...] = ()


_REGISTRY_STATE = _RegistryState()


class _LoggingRuntimeState:
    __slots__ = (
        "concurrent_disable_level",
        "lock",
        "max_event_bytes",
        "quarantined_extension_ids",
        "quarantined_extensions",
        "reconfiguration_active",
        "reconfiguration_manager",
    )

    def __init__(self) -> None:
        self.lock = _threading.RLock()
        self.max_event_bytes: int | None = None
        self.quarantined_extensions: list[object] = []
        self.quarantined_extension_ids: set[int] = set()
        self.reconfiguration_active = False
        self.concurrent_disable_level: int | None = None
        self.reconfiguration_manager: _stdlib_logging.Manager | None = None


_LOGGING_RUNTIME_STATE = _LoggingRuntimeState()


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


def contains_registered_secret(value: str) -> bool:
    """Return whether exact registered secret material occurs in safe identifier text."""
    if type(value) is not str:
        return True
    try:
        return any(secret in value for secret in _registered_text_snapshot())
    except Exception:
        return True


def _install_logging_settings(
    settings: _LoggingSettings,
    envelope: _LoggingSettings,
) -> None:
    """Install one validated, release-bounded log size for process bootstrap."""
    if type(settings) is not _LoggingSettings or type(envelope) is not _LoggingSettings:
        raise TypeError("logging settings must use the canonical validated model")
    try:
        configured_limit = _LoggingSettings(
            max_event_bytes=settings.max_event_bytes
        ).max_event_bytes
        release_limit = _LoggingSettings(max_event_bytes=envelope.max_event_bytes).max_event_bytes
    except _ValidationError:
        raise ValueError("logging settings failed canonical validation") from None
    if configured_limit > release_limit:
        raise ValueError("logging max_event_bytes exceeds the release envelope")
    with _LOGGING_RUNTIME_STATE.lock:
        installed = _LOGGING_RUNTIME_STATE.max_event_bytes
        if installed is None:
            _LOGGING_RUNTIME_STATE.max_event_bytes = configured_limit
            return
        if installed != configured_limit:
            raise RuntimeError("logging settings are already installed")


def _configured_max_event_bytes() -> int:
    with _LOGGING_RUNTIME_STATE.lock:
        value = _LOGGING_RUNTIME_STATE.max_event_bytes
    if value is None:
        raise RuntimeError("logging settings are not installed")
    return value


def _safe_marker(value: str, registered: tuple[str, ...]) -> str:
    return "" if any(secret in value for secret in registered) else value


def _redact_text(value: str, registered: tuple[str, ...]) -> str:
    marker = _safe_marker(_REDACTED, registered)
    if _text_contains_sensitive_material(value):
        return marker
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
    for owner in _class_mro(value_type):
        namespace = _class_namespace(owner)
        descriptor = namespace.get(name)
        if type(descriptor) is _types.MemberDescriptorType:
            return descriptor.__get__(value, value_type)
    return _safe_marker(_REDACTED_OBJECT, registered)


def _safe_instance_values(value: object) -> tuple[bool, dict[object, object] | None]:
    value_type = type(value)
    for owner in _class_mro(value_type):
        namespace = _class_namespace(owner)
        descriptor = namespace.get("__dict__")
        if descriptor is None:
            continue
        if type(descriptor) is not _types.GetSetDescriptorType:
            return False, None
        instance_values = descriptor.__get__(value, value_type)
        if type(instance_values) is not dict:
            return False, None
        return True, _cast(dict[object, object], instance_values)
    return True, None


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
    namespace = _class_namespace(value_type)
    field_map = namespace.get("__dataclass_fields__")
    if type(field_map) is not dict or any(
        type(field) is not _dataclasses.Field for field in dict.values(field_map)
    ):
        return _safe_marker(_REDACTED_OBJECT, registered)
    storage_is_safe, instance_values = _safe_instance_values(value)
    if not storage_is_safe:
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
        safe_type = _redact_text(_class_name(exception_type), registered)
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
    if _is_exception_instance(value):
        return _redact_exception(
            _cast(BaseException, value), registered=registered, active_ids=active_ids
        )
    if "__dataclass_fields__" in _class_namespace(type(value)):
        return _redact_dataclass(value, registered=registered, active_ids=active_ids)
    return _safe_marker(_REDACTED_OBJECT, registered)


def _failed_event(registered: tuple[str, ...]) -> dict[str, object]:
    return _static_event(_FAILED_EVENT, registered)


def _static_event(template: dict[str, object], registered: tuple[str, ...]) -> dict[str, object]:
    if any(
        secret in key or (type(value) is str and secret in value)
        for secret in registered
        for key, value in template.items()
    ):
        return {}
    return dict(template)


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


def _safe_exception_info(
    value: object,
    *,
    registered: tuple[str, ...],
) -> tuple[type[BaseException], BaseException, _types.TracebackType | None] | None:
    try:
        if value is True:
            candidate: object = _sys.exc_info()
        elif type(value) is tuple:
            candidate = value
        elif _is_exception_instance(value):
            candidate = (
                type(value),
                value,
                _EXCEPTION_TRACEBACK_DESCRIPTOR.__get__(value, type(value)),
            )
        else:
            return None
        if type(candidate) is not tuple or len(candidate) != 3:
            return None
        error = tuple.__getitem__(candidate, 1)
        if not _is_exception_instance(error):
            return None
        if type(error) is _SafeLogException:
            args = _EXCEPTION_ARGS_DESCRIPTOR.__get__(error, _SafeLogException)
            if type(args) is tuple and len(args) == 1:
                rendered_value = tuple.__getitem__(args, 0)
                rendered = (
                    _redact_text(rendered_value, registered)
                    if type(rendered_value) is str
                    else _safe_marker(_REDACTED_OBJECT, registered)
                )
                return (_SafeLogException, _SafeLogException(rendered), None)
        payload = _redact_exception(
            _cast(BaseException, error),
            registered=registered,
            active_ids=set(),
        )
    except Exception:
        payload = _failed_event(registered)
    rendered = _json.dumps(payload, ensure_ascii=True, sort_keys=True, allow_nan=False)
    safe_exception = _SafeLogException(rendered)
    return (_SafeLogException, safe_exception, None)


def _sanitize_exception_info(
    logger: object,
    method_name: str,
    event_dict: dict[str, object],
) -> dict[str, object]:
    """Replace raw exception information before any traceback formatting hook runs."""
    del logger, method_name
    registered: tuple[str, ...] = ()
    try:
        registered = _registered_text_snapshot()
        if type(event_dict) is not dict:
            return _failed_event(registered)
        if "exc_info" not in event_dict:
            return event_dict
        raw = dict.pop(event_dict, "exc_info")
        safe = _safe_exception_info(raw, registered=registered)
        if safe is not None:
            event_dict["exc_info"] = safe
        return event_dict
    except Exception:
        return _failed_event(registered)


def _safe_log_value(value: object, registered: tuple[str, ...]) -> object:
    try:
        return _redact_value(value, registered=registered, active_ids=set())
    except Exception:
        return _safe_marker(_REDACTED_OBJECT, registered)


def _safe_log_arguments(
    value: object,
    registered: tuple[str, ...],
) -> tuple[object, ...] | dict[str, object]:
    try:
        if type(value) is tuple:
            return tuple(
                _safe_log_value(item, registered)
                for item in tuple.__iter__(_cast(tuple[object, ...], value))
            )
        if type(value) is dict:
            redacted = _redact_mapping(
                _cast(dict[object, object], value),
                registered=registered,
                active_ids=set(),
            )
            return redacted if type(redacted) is dict else {}
    except Exception:
        return ()
    return ()


def _safe_log_record_values(
    message: object,
    arguments: object,
    exception_info: object,
) -> tuple[
    object,
    tuple[object, ...] | dict[str, object],
    tuple[type[BaseException], BaseException, _types.TracebackType | None] | None,
]:
    registered = _registered_text_snapshot()
    safe_arguments = _safe_log_arguments(arguments, registered)
    if type(message) is str:
        if any(secret in message for secret in registered):
            safe_message: object = _safe_marker(_REDACTED, registered)
        else:
            formatting_arguments: object = safe_arguments
            if type(safe_arguments) is tuple and len(safe_arguments) == 1:
                first_argument = tuple.__getitem__(safe_arguments, 0)
                if type(first_argument) is dict:
                    formatting_arguments = first_argument
            if len(safe_arguments) > 0:
                try:
                    formatted_message = str.__mod__(message, formatting_arguments)
                except Exception:
                    safe_message = _safe_marker(_REDACTED, registered)
                else:
                    safe_message = _redact_text(formatted_message, registered)
            else:
                safe_message = _redact_text(message, registered)
        safe_arguments = ()
    else:
        safe_message = _safe_log_value(message, registered)
        safe_arguments = ()
    safe_exception = _safe_exception_info(exception_info, registered=registered)
    return safe_message, safe_arguments, safe_exception


def _safe_log_record_factory(
    name: object,
    level: object,
    pathname: object,
    lineno: object,
    message: object,
    arguments: object,
    exception_info: object,
    func: object = None,
    sinfo: object = None,
    **kwargs: object,
) -> _stdlib_logging.LogRecord:
    """Build an exact stdlib record only after raw formatting inputs are detached."""
    del kwargs
    registered = _registered_text_snapshot()
    safe_message, safe_arguments, safe_exception = _safe_log_record_values(
        message,
        arguments,
        exception_info,
    )
    record = _stdlib_logging.LogRecord(
        _redact_text(name, registered) if type(name) is str else "",
        level if type(level) is int else 0,
        _redact_text(pathname, registered) if type(pathname) is str else "",
        lineno if type(lineno) is int else 0,
        safe_message,
        safe_arguments,
        safe_exception,
        _redact_text(func, registered) if type(func) is str else None,
        _redact_text(sinfo, registered) if type(sinfo) is str else None,
    )
    state = _LOG_RECORD_DICT_DESCRIPTOR.__get__(record, type(record))
    for field_name in ("levelname", "threadName", "processName", "taskName"):
        if field_name not in state:
            continue
        value = dict.get(state, field_name)
        state[field_name] = _redact_text(value, registered) if type(value) is str else None
    return record


def _trusted_logger(value: object) -> bool:
    return type(value) in {
        _stdlib_logging.Logger,
        _SafeLogger,
        _STRUCTLOG_LOGGER_TYPE,
    }


def _safe_logger_make_record(
    logger: _stdlib_logging.Logger,
    name: object,
    level: object,
    fn: object,
    lno: object,
    msg: object,
    args: object,
    exc_info: object,
    func: object = None,
    extra: object = None,
    sinfo: object = None,
) -> _stdlib_logging.LogRecord:
    """Build one exact record without iterating or comparing foreign metadata."""
    record = _safe_log_record_factory(
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func,
        sinfo,
    )
    if type(extra) is not dict:
        return record

    registered = _registered_text_snapshot()
    record_state = _LOG_RECORD_DICT_DESCRIPTOR.__get__(record, type(record))
    if type(record_state) is not dict:
        raise RuntimeError("log record state is not an exact mapping")
    raw_extra = _cast(dict[object, object], extra)
    raw_logger: object = None
    raw_method_name: object = None
    for raw_key, raw_value in dict.items(raw_extra):
        if type(raw_key) is not str:
            continue
        if raw_key == "_logger":
            raw_logger = raw_value
        elif raw_key == "_name":
            raw_method_name = raw_value
    preserve_provenance = (
        type(msg) is dict
        and raw_logger is logger
        and _trusted_logger(raw_logger)
        and type(raw_method_name) is str
    )

    for raw_key, raw_value in dict.items(raw_extra):
        if type(raw_key) is str and raw_key in {"_logger", "_name"}:
            continue
        safe_key, sensitive = _safe_key(raw_key, registered)
        if safe_key in {"message", "asctime", "_logger", "_name"}:
            continue
        if safe_key in record_state:
            continue
        record_state[safe_key] = (
            _safe_marker(_REDACTED, registered)
            if sensitive
            else _safe_log_value(raw_value, registered)
        )

    if preserve_provenance:
        record_state["_logger"] = _SAFE_PROVENANCE_LOGGER
        record_state["_name"] = _redact_text(
            _cast(str, raw_method_name),
            registered,
        )
    return record


def _normalize_exception_input(
    value: object,
) -> (
    bool
    | tuple[type[BaseException], BaseException, _types.TracebackType | None]
    | tuple[None, None, None]
    | None
):
    if value is True:
        return value
    if type(value) is tuple:
        return _cast(
            tuple[type[BaseException], BaseException, _types.TracebackType | None]
            | tuple[None, None, None],
            value,
        )
    try:
        if _is_exception_instance(value):
            return (
                _cast(type[BaseException], type(value)),
                _cast(BaseException, value),
                _EXCEPTION_TRACEBACK_DESCRIPTOR.__get__(value, type(value)),
            )
    except Exception:
        return None
    return None


def _safe_logger_log(
    logger: _stdlib_logging.Logger,
    level: object,
    msg: object,
    args: object,
    exc_info: object = None,
    extra: object = None,
    stack_info: object = False,
    stacklevel: object = 1,
) -> None:
    """Normalize hook-bearing inputs before stdlib evaluates any of them."""
    safe_args = args if type(args) is tuple else ()
    safe_extra = extra if type(extra) is dict else None
    safe_stacklevel = stacklevel if type(stacklevel) is int and stacklevel >= 1 else 1
    safe_level = level if type(level) is int else _stdlib_logging.NOTSET
    filename, line_number, function_name, stack_text = _safe_logger_find_caller(
        logger,
        stack_info=stack_info is True,
        stacklevel=safe_stacklevel,
    )
    logger_state = _logger_state(logger)
    record = _safe_logger_make_record(
        logger,
        logger_state.get("name"),
        safe_level,
        filename,
        line_number,
        msg,
        safe_args,
        _normalize_exception_input(exc_info),
        function_name,
        extra=safe_extra,
        sinfo=stack_text,
    )
    _safe_dispatch_record(logger, record)


def _first_application_frame() -> _types.FrameType | None:
    try:
        frame: _types.FrameType | None = _sys._getframe()
    except (AttributeError, ValueError):
        return None

    while frame is not None:
        frame_globals = frame.f_globals
        module_name = dict.get(frame_globals, "__name__")
        is_internal = type(module_name) is str and (
            module_name == __name__
            or module_name == "logging"
            or module_name.startswith("logging.")
            or module_name == "structlog"
            or module_name.startswith("structlog.")
        )
        if not is_internal:
            break
        frame = frame.f_back
    return frame


def _safe_logger_find_caller(
    logger: _stdlib_logging.Logger,
    stack_info: object = False,
    stacklevel: object = 1,
) -> tuple[str, int, str, str | None]:
    """Find application callers without invoking displaced logger hooks."""
    del logger
    safe_stacklevel = stacklevel if type(stacklevel) is int and stacklevel >= 1 else 1
    frame = _first_application_frame()

    if frame is None:
        return "(unknown file)", 0, "(unknown function)", None
    for _ in range(safe_stacklevel - 1):
        next_frame = frame.f_back
        if next_frame is None:
            break
        frame = next_frame

    stack_text: str | None = None
    if stack_info is True:
        try:
            with _io.StringIO() as stream:
                stream.write("Stack (most recent call last):\n")
                _traceback.print_stack(frame, file=stream)
                stack_text = stream.getvalue().removesuffix("\n")
        except Exception:
            stack_text = None
    code = frame.f_code
    return code.co_filename, frame.f_lineno, code.co_name, stack_text


def _safe_dispatch_record(
    logger: _stdlib_logging.Logger,
    record: _stdlib_logging.LogRecord,
) -> None:
    """Dispatch a sanitized record without invoking displaced logger hooks."""
    logger_state = _logger_state(logger)
    if logger_state.get("disabled") is not False:
        return
    record_state = _LOG_RECORD_DICT_DESCRIPTOR.__get__(record, type(record))
    if type(record_state) is not dict:
        return
    record_level = dict.get(record_state, "levelno")
    if type(record_level) is not int:
        return

    current: _stdlib_logging.Logger | None = logger
    visited_ids: set[int] = set()
    found_handler = False
    while current is not None:
        current_id = id(current)
        if current_id in visited_ids:
            return
        visited_ids.add(current_id)
        current_state = _logger_state(current)
        handlers = current_state.get("handlers")
        if type(handlers) is not list:
            return
        for handler in list.__iter__(_cast(list[object], handlers)):
            if _stdlib_logging.Handler not in _class_mro(type(handler)):
                return
            handler_state = _FILTERER_DICT_DESCRIPTOR.__get__(handler, type(handler))
            if type(handler_state) is not dict:
                return
            handler_level = dict.get(handler_state, "level")
            if type(handler_level) is not int:
                return
            found_handler = True
            if record_level >= handler_level:
                _stdlib_logging.Handler.handle(
                    _cast(_stdlib_logging.Handler, handler),
                    record,
                )

        propagate = current_state.get("propagate")
        if propagate is False:
            break
        if propagate is not True:
            return
        parent = current_state.get("parent")
        if parent is None:
            break
        if type(parent) not in {
            _stdlib_logging.Logger,
            _stdlib_logging.RootLogger,
            _SafeLogger,
            _STRUCTLOG_LOGGER_TYPE,
        }:
            return
        current = _cast(_stdlib_logging.Logger, parent)

    if found_handler:
        return
    last_resort = _stdlib_logging.lastResort
    if last_resort is None or _stdlib_logging.Handler not in _class_mro(type(last_resort)):
        return
    last_resort_state = _FILTERER_DICT_DESCRIPTOR.__get__(last_resort, type(last_resort))
    if type(last_resort_state) is not dict:
        return
    last_resort_level = dict.get(last_resort_state, "level")
    if type(last_resort_level) is int and record_level >= last_resort_level:
        _stdlib_logging.Handler.handle(last_resort, record)


def _blocked_logger_log(
    logger: object,
    level: object,
    msg: object,
    args: object,
    exc_info: object = None,
    extra: object = None,
    stack_info: object = False,
    stacklevel: object = 1,
) -> None:
    del logger, level, msg, args, exc_info, extra, stack_info, stacklevel


def _sanitize_log_record(record: _stdlib_logging.LogRecord) -> None:
    state = _LOG_RECORD_DICT_DESCRIPTOR.__get__(record, type(record))
    if type(state) is not dict:
        raise RuntimeError("log record state is not an exact mapping")
    safe_message, safe_arguments, safe_exception = _safe_log_record_values(
        state.get("msg"),
        state.get("args"),
        state.get("exc_info"),
    )
    state["msg"] = safe_message
    state["args"] = safe_arguments
    state["exc_info"] = safe_exception
    raw_logger = state.get("_logger")
    raw_method_name = state.get("_name")
    if type(safe_message) is dict and _trusted_logger(raw_logger) and type(raw_method_name) is str:
        state["_name"] = _redact_text(
            raw_method_name,
            _registered_text_snapshot(),
        )
    else:
        dict.pop(state, "_logger", None)
        dict.pop(state, "_name", None)


def _serialized_event_size(event_dict: dict[str, object]) -> int:
    rendered = _json.dumps(event_dict, ensure_ascii=True)
    return len(rendered.encode("utf-8"))


def _limit_event_size(
    logger: object, method_name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    """Replace oversized already-redacted events before the final JSON renderer."""
    del logger, method_name
    try:
        maximum = _configured_max_event_bytes()
        if type(event_dict) is dict and _serialized_event_size(event_dict) <= maximum:
            return event_dict
        registered = _registered_text_snapshot()
        replacement = _static_event(_TRUNCATED_EVENT, registered)
        if _serialized_event_size(replacement) <= maximum:
            return replacement
    except Exception:
        return {}
    return {}


def _render_failed_log_line() -> str:
    registered = _registered_text_snapshot()
    event = _limit_event_size(None, "error", _failed_event(registered))
    return _json.dumps(event, ensure_ascii=True)


class _SafeProcessorFormatter(_structlog.stdlib.ProcessorFormatter):
    """Sanitize exact records before Structlog or stdlib can format their contents."""

    def format(self, record: _stdlib_logging.LogRecord) -> str:
        if type(record) is not _stdlib_logging.LogRecord:
            return _render_failed_log_line()
        try:
            _sanitize_log_record(record)
            return super().format(record)
        except Exception:
            return _render_failed_log_line()


def _remove_processor_metadata(
    logger: object,
    method_name: str,
    event_dict: dict[str, object],
) -> dict[str, object]:
    """Tolerantly remove Structlog metadata from any exact fail-closed event."""
    del logger, method_name
    if type(event_dict) is not dict:
        return {}
    dict.pop(event_dict, "_record", None)
    dict.pop(event_dict, "_from_structlog", None)
    return event_dict


def _logging_processors() -> list[_structlog.typing.Processor]:
    return [
        _structlog.contextvars.merge_contextvars,
        _structlog.stdlib.add_log_level,
        _structlog.processors.TimeStamper(fmt="iso", utc=True),
        _cast(_structlog.typing.Processor, _sanitize_exception_info),
        _structlog.processors.format_exc_info,
        _cast(_structlog.typing.Processor, redact_secrets),
    ]


def _logger_state(logger: _stdlib_logging.Logger) -> dict[str, object]:
    state = _FILTERER_DICT_DESCRIPTOR.__get__(logger, type(logger))
    if type(state) is not dict:
        raise RuntimeError("logger state is not an exact mapping")
    return _cast(dict[str, object], state)


def _validate_logger_state(logger: _stdlib_logging.Logger) -> None:
    state = _logger_state(logger)
    if any(type(key) is not str for key in dict.keys(state)):
        raise RuntimeError("logger state keys must be exact text")
    if type(state.get("handlers")) is not list:
        raise RuntimeError("logger handlers are not an exact list")
    if type(state.get("filters")) is not list:
        raise RuntimeError("logger filters are not an exact list")
    if type(state.get("_cache")) is not dict:
        raise RuntimeError("logger cache is not an exact mapping")


def _is_owned_boundary_method(
    value: object,
    logger: _stdlib_logging.Logger,
    function: object,
) -> bool:
    return (
        type(value) is _types.MethodType and value.__self__ is logger and value.__func__ is function
    )


def _install_safe_logger_boundary(logger: _stdlib_logging.Logger) -> None:
    state = _logger_state(logger)
    displaced: list[object] = []
    for method_name in _LOGGER_EMISSION_OVERRIDE_NAMES:
        override = dict.pop(state, method_name, _MISSING)
        if override is not _MISSING:
            displaced.append(override)
    existing_log = state.get("_log", _MISSING)
    if existing_log is not _MISSING and not _is_owned_boundary_method(
        existing_log,
        logger,
        _safe_logger_log,
    ):
        displaced.append(existing_log)
    existing_make_record = state.get("makeRecord", _MISSING)
    if existing_make_record is not _MISSING and not _is_owned_boundary_method(
        existing_make_record,
        logger,
        _safe_logger_make_record,
    ):
        displaced.append(existing_make_record)
    existing_find_caller = state.get("findCaller", _MISSING)
    if existing_find_caller is not _MISSING and not _is_owned_boundary_method(
        existing_find_caller,
        logger,
        _safe_logger_find_caller,
    ):
        displaced.append(existing_find_caller)
    _retain_quarantined_objects(tuple(displaced))
    state["_log"] = _types.MethodType(_safe_logger_log, logger)
    state["makeRecord"] = _types.MethodType(_safe_logger_make_record, logger)
    state["findCaller"] = _types.MethodType(_safe_logger_find_caller, logger)


def _managed_loggers(root: _stdlib_logging.RootLogger) -> tuple[_stdlib_logging.Logger, ...]:
    manager = object.__getattribute__(root, "manager")
    if type(manager) is not _stdlib_logging.Manager:
        raise RuntimeError("custom logging managers are unsupported")
    logger_dict = object.__getattribute__(manager, "loggerDict")
    if type(logger_dict) is not dict:
        raise RuntimeError("logging manager registry is not an exact mapping")
    managed: list[_stdlib_logging.Logger] = []
    for candidate in tuple(dict.values(logger_dict)):
        candidate_type = type(candidate)
        if candidate_type in {
            _stdlib_logging.Logger,
            _SafeLogger,
            _STRUCTLOG_LOGGER_TYPE,
        }:
            managed.append(_cast(_stdlib_logging.Logger, candidate))
            continue
        if type(candidate) is _stdlib_logging.PlaceHolder:
            continue
        raise RuntimeError("custom logger classes are unsupported")
    for logger in managed:
        _validate_logger_state(logger)
    _validate_logger_state(root)
    return tuple(managed)


def _clear_logger_cache_without_hooks(logger: object) -> None:
    try:
        state = _FILTERER_DICT_DESCRIPTOR.__get__(logger, type(logger))
    except Exception:
        return
    if type(state) is not dict:
        return
    cache: object = None
    for raw_key, raw_value in dict.items(state):
        if type(raw_key) is str and raw_key == "_cache":
            cache = raw_value
            break
    if type(cache) is not dict:
        return
    foreign_cache_values: list[object] = []
    for raw_key, raw_value in dict.items(cache):
        if type(raw_key) is not int or type(raw_value) is not bool:
            foreign_cache_values.extend((raw_key, raw_value))
    _retain_quarantined_objects(tuple(foreign_cache_values))
    dict.clear(cache)


def _disable_logging_fail_closed(
    manager: _stdlib_logging.Manager,
    root: _stdlib_logging.RootLogger,
) -> None:
    """Disable globally and clear supported caches without touching custom loggers."""
    manager_state = _MANAGER_DICT_DESCRIPTOR.__get__(manager, type(manager))
    if type(manager_state) is not dict:
        return
    manager_state["_disable"] = _DISABLE_DURING_RECONFIGURE
    logger_dict = object.__getattribute__(manager, "loggerDict")
    candidates = tuple(dict.values(logger_dict)) if type(logger_dict) is dict else ()
    for candidate in candidates:
        _clear_logger_cache_without_hooks(candidate)
    _clear_logger_cache_without_hooks(root)


def _set_logging_disable_level(
    manager: _stdlib_logging.Manager,
    root: _stdlib_logging.RootLogger,
    managed_loggers: tuple[_stdlib_logging.Logger, ...],
    level: int,
) -> None:
    manager_state = _MANAGER_DICT_DESCRIPTOR.__get__(manager, type(manager))
    if type(manager_state) is not dict:
        raise RuntimeError("logging manager state is not an exact mapping")
    manager_state["_disable"] = level
    for logger in (*managed_loggers, root):
        cache = _logger_state(logger).get("_cache")
        if type(cache) is not dict:
            raise RuntimeError("logger cache changed after validation")
        _clear_logger_cache_without_hooks(logger)


def _safe_manager_disable_get(manager: _stdlib_logging.Manager) -> int:
    state = _MANAGER_DICT_DESCRIPTOR.__get__(manager, type(manager))
    if type(state) is not dict:
        raise RuntimeError("logging manager state is not an exact mapping")
    level = dict.get(state, "_disable")
    if type(level) is not int:
        raise RuntimeError("logging disable level is not an exact integer")
    return level


def _safe_manager_disable_set(manager: _stdlib_logging.Manager, level: object) -> None:
    if type(level) is str:
        level_names = _stdlib_logging._nameToLevel
        if type(level_names) is not dict:
            raise RuntimeError("logging level names are not an exact mapping")
        safe_level: int | None = None
        for raw_name, raw_level in dict.items(level_names):
            if (
                type(raw_name) is str
                and str.__eq__(raw_name, level) is True
                and type(raw_level) is int
            ):
                safe_level = raw_level
                break
        if safe_level is None:
            raise ValueError("unknown logging level") from None
    elif type(level) is int:
        safe_level = level
    else:
        raise TypeError("logging disable level must be exact text or an exact integer")
    _acquire_logging_registry_lock()
    try:
        state = _MANAGER_DICT_DESCRIPTOR.__get__(manager, type(manager))
        if type(state) is not dict:
            raise RuntimeError("logging manager state is not an exact mapping")
        state["_disable"] = safe_level
        if (
            _LOGGING_RUNTIME_STATE.reconfiguration_active
            and manager is _LOGGING_RUNTIME_STATE.reconfiguration_manager
        ):
            concurrent_level = _LOGGING_RUNTIME_STATE.concurrent_disable_level
            _LOGGING_RUNTIME_STATE.concurrent_disable_level = (
                safe_level if concurrent_level is None else max(concurrent_level, safe_level)
            )
    finally:
        _release_logging_registry_lock()


_SAFE_MANAGER_DISABLE_DESCRIPTOR: _Final = property(
    _safe_manager_disable_get,
    _safe_manager_disable_set,
)


def _install_safe_manager_disable_boundary() -> None:
    manager_namespace = _class_namespace(_stdlib_logging.Manager)
    displaced = manager_namespace.get("disable")
    if displaced is not None and displaced is not _SAFE_MANAGER_DISABLE_DESCRIPTOR:
        _retain_quarantined_objects((displaced,))
    type.__setattr__(
        _stdlib_logging.Manager,
        "disable",
        _SAFE_MANAGER_DISABLE_DESCRIPTOR,
    )


def _acquire_logging_registry_lock() -> None:
    # Use the same registry RLock as stdlib; 3.13 removed its helper functions.
    _stdlib_logging._lock.acquire()  # type: ignore[attr-defined]


def _release_logging_registry_lock() -> None:
    _stdlib_logging._lock.release()  # type: ignore[attr-defined]


def _replace_logger_extensions(
    logger: _stdlib_logging.Logger,
    *,
    replacement_handlers: tuple[_stdlib_logging.Handler, ...],
    propagate: bool,
) -> tuple[object, ...]:
    state = _logger_state(logger)
    existing_handlers = state.get("handlers")
    filters = state.get("filters")
    if type(existing_handlers) is not list or type(filters) is not list:
        raise RuntimeError("logger extensions changed after validation")
    retained_handler_ids = {id(handler) for handler in replacement_handlers}
    detached_handlers = tuple(
        handler
        for handler in list.__iter__(_cast(list[object], existing_handlers))
        if id(handler) not in retained_handler_ids
    )
    detached_filters = tuple(list.__iter__(_cast(list[object], filters)))
    state["handlers"] = list(replacement_handlers)
    state["filters"] = []
    if type(state["handlers"]) is not list:
        raise RuntimeError("logger handlers are not an exact list")
    if propagate:
        displaced_propagate = state.get("propagate", _MISSING)
        if displaced_propagate is not _MISSING and type(displaced_propagate) is not bool:
            _retain_quarantined_objects((displaced_propagate,))
        state["propagate"] = True
    return (*detached_handlers, *detached_filters)


def _retain_quarantined_objects(values: tuple[object, ...]) -> None:
    for value in values:
        value_id = id(value)
        if value_id in _LOGGING_RUNTIME_STATE.quarantined_extension_ids:
            continue
        _LOGGING_RUNTIME_STATE.quarantined_extension_ids.add(value_id)
        _LOGGING_RUNTIME_STATE.quarantined_extensions.append(value)


def _quarantine_foreign_extensions(extensions: tuple[object, ...]) -> tuple[object, ...]:
    owned: list[object] = []
    foreign: list[object] = []
    for extension in extensions:
        if type(extension) is _FailClosedStreamHandler:
            owned.append(extension)
        else:
            foreign.append(extension)
    _retain_quarantined_objects(tuple(owned))
    _retain_quarantined_objects(tuple(foreign))
    return tuple(owned)


def _retain_displaced_structlog_config() -> None:
    config = _structlog.get_config()
    if type(config) is not dict:
        raise RuntimeError("Structlog configuration is not an exact mapping")
    _retain_quarantined_objects((config,))


def _close_owned_handlers(handlers: tuple[object, ...]) -> None:
    retired = tuple(handler for handler in handlers if type(handler) is _FailClosedStreamHandler)
    _retain_quarantined_objects(retired)


def _set_root_level(root: _stdlib_logging.RootLogger, level: int) -> None:
    state = _logger_state(root)
    displaced_level = state.get("level", _MISSING)
    if displaced_level is not _MISSING and type(displaced_level) is not int:
        _retain_quarantined_objects((displaced_level,))
    state["level"] = level


def _normalize_logger_extensions(
    managed_loggers: tuple[_stdlib_logging.Logger, ...],
    root: _stdlib_logging.RootLogger,
    handler: _FailClosedStreamHandler,
) -> tuple[object, ...]:
    owned: list[object] = []
    for logger in managed_loggers:
        _install_safe_logger_boundary(logger)
        owned.extend(
            _quarantine_foreign_extensions(
                _replace_logger_extensions(
                    logger,
                    replacement_handlers=(),
                    propagate=True,
                )
            )
        )
    _install_safe_logger_boundary(root)
    owned.extend(
        _quarantine_foreign_extensions(
            _replace_logger_extensions(
                root,
                replacement_handlers=(handler,),
                propagate=False,
            )
        )
    )
    return tuple(owned)


def _validate_configured_root(
    root: _stdlib_logging.RootLogger,
    handler: _FailClosedStreamHandler,
    numeric_level: int,
) -> None:
    state = _logger_state(root)
    handlers = state.get("handlers")
    filters = state.get("filters")
    if (
        type(handlers) is not list
        or len(handlers) != 1
        or list.__getitem__(handlers, 0) is not handler
    ):
        raise RuntimeError("root logging handler changed during configuration")
    if type(filters) is not list or len(filters) != 0:
        raise RuntimeError("root logging filters changed during configuration")
    configured_level = state.get("level")
    if type(configured_level) is not int or configured_level != numeric_level:
        raise RuntimeError("root logging level changed during configuration")


def _validate_logging_globals(
    handler: _FailClosedStreamHandler,
    manager: _stdlib_logging.Manager,
) -> None:
    if _stdlib_logging.getLoggerClass() is not _SafeLogger:
        raise RuntimeError("safe logger class changed during configuration")
    if _stdlib_logging.getLogRecordFactory() is not _safe_log_record_factory:
        raise RuntimeError("safe record factory changed during configuration")
    if _stdlib_logging.lastResort is not handler:
        raise RuntimeError("safe lastResort handler changed during configuration")
    if object.__getattribute__(manager, "loggerClass") is not _SafeLogger:
        raise RuntimeError("safe manager logger class changed during configuration")
    logger_namespace = _class_namespace(_stdlib_logging.Logger)
    if logger_namespace.get("_log") is not _safe_logger_log:
        raise RuntimeError("safe base logger boundary changed during configuration")
    if logger_namespace.get("makeRecord") is not _safe_logger_make_record:
        raise RuntimeError("safe base record boundary changed during configuration")
    if logger_namespace.get("findCaller") is not _safe_logger_find_caller:
        raise RuntimeError("safe base caller boundary changed during configuration")
    manager_namespace = _class_namespace(_stdlib_logging.Manager)
    if manager_namespace.get("disable") is not _SAFE_MANAGER_DISABLE_DESCRIPTOR:
        raise RuntimeError("safe logging disable boundary changed during configuration")


def _block_base_logger_emission() -> None:
    logger_namespace = _class_namespace(_stdlib_logging.Logger)
    displaced = logger_namespace.get("_log")
    if displaced is not None:
        _retain_quarantined_objects((displaced,))
    type.__setattr__(_stdlib_logging.Logger, "_log", _blocked_logger_log)


def _install_safe_base_logger_boundary() -> None:
    logger_namespace = _class_namespace(_stdlib_logging.Logger)
    displaced = tuple(
        value
        for value in (
            logger_namespace.get("_log"),
            logger_namespace.get("makeRecord"),
            logger_namespace.get("findCaller"),
        )
        if value is not None
    )
    _retain_quarantined_objects(displaced)
    type.__setattr__(_stdlib_logging.Logger, "makeRecord", _safe_logger_make_record)
    type.__setattr__(_stdlib_logging.Logger, "findCaller", _safe_logger_find_caller)
    type.__setattr__(_stdlib_logging.Logger, "_log", _safe_logger_log)


def _retain_displaced_logging_globals(manager: _stdlib_logging.Manager) -> None:
    displaced: list[object] = [
        _stdlib_logging.getLoggerClass(),
        _stdlib_logging.getLogRecordFactory(),
    ]
    manager_logger_class = object.__getattribute__(manager, "loggerClass")
    if manager_logger_class is not None:
        displaced.append(manager_logger_class)
    _retain_quarantined_objects(tuple(displaced))


def configure_logging(level: str) -> None:
    """Configure stdlib and Structlog JSON output at one validated standard level."""
    if type(level) is not str:
        raise TypeError("logging level must be text")
    normalized = level.upper()
    if normalized not in _LEVELS:
        raise ValueError("unsupported logging level")
    numeric_level = _LEVELS[normalized]
    with _LOGGING_RUNTIME_STATE.lock:
        _configured_max_event_bytes()

        pre_render = _logging_processors()
        renderer = _structlog.processors.JSONRenderer()
        formatter = _SafeProcessorFormatter(
            processors=[
                _cast(_structlog.typing.Processor, _remove_processor_metadata),
                _cast(_structlog.typing.Processor, _limit_event_size),
                renderer,
            ],
            foreign_pre_chain=pre_render,
        )
        handler = _FailClosedStreamHandler()
        setattr(handler, _OWN_HANDLER_MARKER, True)
        handler.setLevel(numeric_level)
        handler.setFormatter(formatter)

        root = _stdlib_logging.getLogger()
        if type(root) is not _stdlib_logging.RootLogger:
            raise RuntimeError("custom root logger classes are unsupported")
        manager = object.__getattribute__(root, "manager")
        if type(manager) is not _stdlib_logging.Manager:
            raise RuntimeError("custom logging managers are unsupported")
        previous_disable: int | None = None
        managed_loggers: tuple[_stdlib_logging.Logger, ...] = ()
        try:
            _acquire_logging_registry_lock()
            try:
                _install_safe_manager_disable_boundary()
                _LOGGING_RUNTIME_STATE.reconfiguration_active = True
                _LOGGING_RUNTIME_STATE.reconfiguration_manager = manager
                _LOGGING_RUNTIME_STATE.concurrent_disable_level = None
                previous_disable = object.__getattribute__(manager, "disable")
                if type(previous_disable) is not int:
                    raise RuntimeError("logging disable level is not an exact integer")
                _block_base_logger_emission()
                _disable_logging_fail_closed(manager, root)
                managed_loggers = _managed_loggers(root)
                _set_logging_disable_level(
                    manager,
                    root,
                    managed_loggers,
                    _DISABLE_DURING_RECONFIGURE,
                )
                _retain_displaced_logging_globals(manager)
                _stdlib_logging.setLoggerClass(_SafeLogger)
                object.__setattr__(manager, "loggerClass", _SafeLogger)
                _stdlib_logging.setLogRecordFactory(_safe_log_record_factory)
                previous_last_resort = _stdlib_logging.lastResort
                owned_handlers: list[object] = []
                if previous_last_resort is not None and previous_last_resort is not handler:
                    owned_handlers.extend(_quarantine_foreign_extensions((previous_last_resort,)))
                _stdlib_logging.lastResort = handler
                owned_handlers.extend(_normalize_logger_extensions(managed_loggers, root, handler))
                _set_root_level(root, numeric_level)
                _install_safe_base_logger_boundary()
            finally:
                _release_logging_registry_lock()

            _close_owned_handlers(tuple(owned_handlers))

            _retain_displaced_structlog_config()
            _structlog.configure(
                processors=[
                    *pre_render,
                    _structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
                ],
                context_class=dict,
                logger_factory=_ExactLoggerFactory(),
                wrapper_class=_structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=False,
            )

            _acquire_logging_registry_lock()
            try:
                _block_base_logger_emission()
                _install_safe_manager_disable_boundary()
                displaced_last_resort = _stdlib_logging.lastResort
                _retain_displaced_logging_globals(manager)
                _stdlib_logging.setLoggerClass(_SafeLogger)
                object.__setattr__(manager, "loggerClass", _SafeLogger)
                _stdlib_logging.setLogRecordFactory(_safe_log_record_factory)
                _stdlib_logging.lastResort = handler
                if displaced_last_resort is not None and displaced_last_resort is not handler:
                    displaced_owned_handlers = _quarantine_foreign_extensions(
                        (displaced_last_resort,)
                    )
                    if displaced_owned_handlers:
                        _close_owned_handlers(displaced_owned_handlers)
                current_loggers = _managed_loggers(root)
                final_detached = _normalize_logger_extensions(
                    current_loggers,
                    root,
                    handler,
                )
                _set_root_level(root, numeric_level)
                _install_safe_base_logger_boundary()
                _validate_configured_root(root, handler, numeric_level)
                _validate_logging_globals(handler, manager)
                final_owned_handlers = _quarantine_foreign_extensions(final_detached)
                if final_owned_handlers:
                    _close_owned_handlers(final_owned_handlers)
                if type(previous_disable) is not int:
                    raise RuntimeError("previous logging disable level was not captured")
                concurrent_disable = _LOGGING_RUNTIME_STATE.concurrent_disable_level
                restore_disable = (
                    previous_disable
                    if concurrent_disable is None
                    else max(previous_disable, concurrent_disable)
                )
                _set_logging_disable_level(
                    manager,
                    root,
                    current_loggers,
                    restore_disable,
                )
                _LOGGING_RUNTIME_STATE.reconfiguration_active = False
                _LOGGING_RUNTIME_STATE.reconfiguration_manager = None
                _LOGGING_RUNTIME_STATE.concurrent_disable_level = None
            finally:
                _release_logging_registry_lock()
        except Exception:
            _acquire_logging_registry_lock()
            try:
                _disable_logging_fail_closed(manager, root)
                _LOGGING_RUNTIME_STATE.reconfiguration_active = False
                _LOGGING_RUNTIME_STATE.reconfiguration_manager = None
                _LOGGING_RUNTIME_STATE.concurrent_disable_level = None
            finally:
                _release_logging_registry_lock()
            raise


__all__ = [
    "SecretRegistry",
    "configure_logging",
    "contains_registered_secret",
    "redact_secrets",
]
