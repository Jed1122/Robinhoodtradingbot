"""Tests for fail-closed, pre-serialization structured-log redaction."""

from __future__ import annotations

import json
import logging as stdlib_logging
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, cast

import pytest
import structlog

import trading_bot.logging as logging_module
from trading_bot.logging import SecretRegistry, configure_logging, redact_secrets

_OWN_HANDLER_MARKER = "_trading_bot_json_handler"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_logging_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    root = stdlib_logging.getLogger()
    original_handlers = tuple(root.handlers)
    original_level = root.level
    yield
    for handler in tuple(root.handlers):
        root.removeHandler(handler)
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_level)
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
        "redact_secrets",
    ]


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


def test_dataclass_with_non_text_storage_key_is_rejected_without_key_equality() -> None:
    value = _FrozenDictEnvelope(safe="visible")
    instance_values = object.__getattribute__(value, "__dict__")
    instance_values.pop("safe")
    instance_values[_HostileDataclassKey()] = "must not be inspected"

    event = redact_secrets(None, "info", {"payload": value})

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
    assert processors.index(structlog.processors.format_exc_info) < processors.index(redact_secrets)
    assert processors.index(redact_secrets) < processors.index(
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter
    )
    formatter = owned_handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
    assert isinstance(formatter.processors[-1], structlog.processors.JSONRenderer)


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

    assert ".PHONY: format lint typecheck test security" in makefile.splitlines()
    assert "format:\n\tuv run ruff format ." in makefile
    assert "lint:\n\tuv run ruff check ." in makefile
    assert "typecheck:\n\tuv run mypy src" in makefile
    assert "test:\n\tuv run pytest --cov=trading_bot --cov-branch" in makefile
    assert ("security:\n\tuv run bandit -c pyproject.toml -r src\n\tuv run pip-audit") in makefile


def test_ci_is_read_only_and_has_only_the_baseline_offline_test_matrix() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    folded = workflow.casefold()

    assert 'python-version: ["3.12", "3.13", "3.14"]' in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run mypy src" in workflow
    assert "uv run pytest --cov=trading_bot --cov-branch" in workflow
    for forbidden in (
        "pull_request_target",
        "secret",
        "credential",
        "oauth",
        "api_key",
        "authenticated",
        "broker",
        "place_order",
        "live",
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
        "trading mcp is not configured",
        "prediction live execution is unsupported",
        "no live order has been placed",
        "no profitability claim",
        "trader cli is not implemented",
        "broker adapters are not implemented",
        "account access is not implemented",
    ):
        assert required in document
    for absent_command_claim in ("`trader status`", "`trader preflight`", "`trader run`"):
        assert absent_command_claim not in document
