"""Integration tests for schema-only MCP capability capture."""

from __future__ import annotations

import json
import os
import runpy
import stat
import traceback
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from mcp import types

from trading_bot.capabilities import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    CapabilitySnapshotError,
    DuplicateToolNameError,
    EvidenceLevel,
    InvalidCapabilityManifest,
    OperationKind,
    PaginationCycleError,
    SanitizedToolSchema,
    ToolsListSnapshot,
    UnsafeCapabilitySnapshot,
    canonical_sha256,
    capture_tools_list,
    capture_tools_snapshot,
    load_capability_manifest,
    render_capability_matrix,
    write_tools_snapshot,
)

OBSERVED_AT = datetime(2026, 7, 12, 12, tzinfo=UTC)
ROOT = Path(__file__).parents[3]
FIXTURE = ROOT / "tests/fixtures/capabilities/documented_robinhood.json"
SCRIPT = ROOT / "scripts/capture_mcp_capabilities.py"
COMPACT_SENSITIVE_NAMES = (
    "apikey",
    "xapikey",
    "privatekey",
    "signingkey",
    "accesskey",
    "clientkey",
    "consumerkey",
    "clientsecret",
    "accesstoken",
    "refreshtoken",
    "sessionid",
    "sessionkey",
    "sessiontoken",
    "sessioncookie",
    "accountid",
    "accountnumber",
    "accountuuid",
    "authheader",
    "authorizationheader",
)
GRAMMAR_SENSITIVE_NAMES = (
    "api_keys",
    "private_keys",
    "signing_keys",
    "authtoken",
    "oauthtoken",
    "bearertoken",
    "secretkey",
    "accesskeyid",
    "clientsecret[]",
    "apisecret",
    "api_secrets",
    "consumersecret",
    "accesssecret",
    "oauthclientsecret",
    "authorizationtoken",
)


class FakeToolsListSession:
    """MCP 1.28.1-shaped tools/list fake with no transport behavior."""

    def __init__(self, pages: Sequence[types.ListToolsResult]) -> None:
        self._pages = iter(pages)
        self.list_tools_params: list[types.PaginatedRequestParams | None] = []
        self.call_tool_calls: list[object] = []

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        assert cursor is None
        self.list_tools_params.append(params)
        return next(self._pages)


class SecretFailingSession:
    """External session failure whose message must never cross the boundary."""

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        raise RuntimeError("actual-secret-value")


class PydanticFailingSession:
    """Simulate MCP response validation that embeds invalid payload in its error."""

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        types.Tool.model_validate({"name": ["actual-secret-value"], "inputSchema": {}})
        raise AssertionError("invalid MCP tool unexpectedly validated")


class StaticResultSession:
    """Return one preconstructed result, including deliberately malformed models."""

    def __init__(self, result: types.ListToolsResult) -> None:
        self.result = result

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        return self.result


class ExplodingListToolsResult(types.ListToolsResult):
    """An untrusted SDK-model subclass with secret-bearing property access."""

    def __getattribute__(self, name: str) -> object:
        if name in {"tools", "nextCursor"}:
            raise RuntimeError("actual-secret-value")
        return super().__getattribute__(name)


class SecretBearingDatetime(datetime):
    """A hostile datetime subclass whose methods expose sensitive text."""

    def utcoffset(self) -> timedelta | None:
        raise RuntimeError("Authorization: Bearer tiny")

    def isoformat(self, sep: str = "T", timespec: str = "auto") -> str:
        raise RuntimeError("Authorization: Bearer tiny")


class DatetimeSubclass(datetime):
    """Semantically UTC but outside the exact timestamp boundary."""


class AlwaysEqualCapabilityRecord(CapabilityRecord):
    """Nested model subclass that attempts to bypass manifest comparison."""

    def __eq__(self, other: object) -> bool:
        return True


class AlwaysEqualCapabilityEvidence(CapabilityEvidence):
    """Evidence subclass that attempts to bypass nested model comparison."""

    def __eq__(self, other: object) -> bool:
        return True


def tool(
    name: str = "get_equity_quotes",
    *,
    description: str | None = "Officially reviewed name; description is not classification.",
    input_schema: dict[str, object] | None = None,
    output_schema: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
) -> types.Tool:
    return types.Tool(
        name=name,
        description=description,
        inputSchema=input_schema
        or {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
        },
        outputSchema=output_schema,
        _meta=meta,
    )


def direct_sanitized_tool(input_schema: dict[str, object]) -> SanitizedToolSchema:
    """Construct an exported schema with a valid digest for boundary tests."""
    return SanitizedToolSchema(
        name="get_equity_quotes",
        description=None,
        _input_schema_json=json.dumps(input_schema, separators=(",", ":")),
        _output_schema_json=None,
        schema_sha256=canonical_sha256(
            {"inputSchema": input_schema, "outputSchema": None}  # type: ignore[dict-item]
        ),
    )


def forged_sanitized_tool(
    source: SanitizedToolSchema,
    **changes: object,
) -> SanitizedToolSchema:
    """Build an exact dataclass instance without running its public constructor."""
    forged = object.__new__(SanitizedToolSchema)
    values: dict[str, object] = {
        "name": source.name,
        "description": source.description,
        "_input_schema_json": source._input_schema_json,
        "_output_schema_json": source._output_schema_json,
        "schema_sha256": source.schema_sha256,
    }
    values.update(changes)
    for field_name, field_value in values.items():
        object.__setattr__(forged, field_name, field_value)
    return forged


@pytest.mark.asyncio
async def test_one_page_capture_uses_tools_list_exactly_once_and_ignores_meta() -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        meta={
                            "Authorization": "Bearer actual-secret-value",
                            "account_id": "RHC123456789",
                        }
                    )
                ]
            )
        ]
    )

    manifest = await capture_tools_list(session, observed_at=OBSERVED_AT)

    assert len(manifest.records) == 1
    assert session.list_tools_params == [None]
    assert session.call_tool_calls == []
    record = manifest.records[0]
    assert record.operation == "get_equity_quotes"
    assert record.operation_kind is OperationKind.READ
    assert record.evidence[0].level is EvidenceLevel.SCHEMA_DECLARED
    assert record.evidence[0].authenticated is False


@pytest.mark.asyncio
async def test_capture_paginates_with_paginated_request_params() -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(tools=[tool("get_equity_quotes")], nextCursor="page-2"),
            types.ListToolsResult(tools=[tool("review_equity_order")]),
        ]
    )

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert [item.name for item in snapshot.tools] == [
        "get_equity_quotes",
        "review_equity_order",
    ]
    assert session.list_tools_params[0] is None
    assert session.list_tools_params[1] == types.PaginatedRequestParams(cursor="page-2")
    assert session.call_tool_calls == []


@pytest.mark.asyncio
async def test_capture_rejects_duplicate_names_across_pages() -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(tools=[tool()], nextCursor="again"),
            types.ListToolsResult(tools=[tool()]),
        ]
    )

    with pytest.raises(DuplicateToolNameError, match="duplicate"):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.asyncio
async def test_capture_rejects_repeated_pagination_cursor() -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(tools=[tool()], nextCursor="again"),
            types.ListToolsResult(tools=[], nextCursor="again"),
        ]
    )

    with pytest.raises(PaginationCycleError, match="cursor"):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("session", (SecretFailingSession(), PydanticFailingSession()))
@pytest.mark.asyncio
async def test_session_and_sdk_errors_are_generic_and_suppress_secret_tracebacks(
    session: SecretFailingSession | PydanticFailingSession,
) -> None:
    with pytest.raises(CapabilitySnapshotError) as captured:
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "MCP tools/list failed safely"
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_result_subclass_property_errors_are_rejected_before_field_access() -> None:
    result = ExplodingListToolsResult(tools=[])
    session = StaticResultSession(result)

    with pytest.raises(CapabilitySnapshotError) as captured:
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "MCP tools/list failed safely"
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_model_construct_malformed_tool_fields_fail_generically() -> None:
    malformed = types.Tool.model_construct(
        name=["actual-secret-value"],
        inputSchema={},
    )
    result = types.ListToolsResult.model_construct(tools=[malformed], nextCursor=None)
    session = StaticResultSession(result)

    with pytest.raises(CapabilitySnapshotError) as captured:
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "MCP tools/list failed safely"
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_snapshot_preserves_exact_allowed_fields_and_explicit_null_output() -> None:
    input_schema: dict[str, object] = {
        "required": ["symbol", "quantity"],
        "type": "object",
        "properties": {
            "account_number": {"type": "string"},
            "token": {"type": "string"},
        },
    }
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        description=None,
                        input_schema=input_schema,
                        output_schema=None,
                        meta={"sensitive-extra": "must never be serialized"},
                    )
                ]
            )
        ]
    )

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    artifact = snapshot.as_json()

    assert artifact["tools"] == [
        {
            "name": "get_equity_quotes",
            "description": None,
            "inputSchema": input_schema,
            "outputSchema": None,
            "schemaSha256": snapshot.tools[0].schema_sha256,
        }
    ]
    assert "sensitive-extra" not in json.dumps(artifact)
    different_output = FakeToolsListSession(
        [types.ListToolsResult(tools=[tool(input_schema=input_schema, output_schema={})])]
    )
    other = await capture_tools_snapshot(different_output, observed_at=OBSERVED_AT)
    assert snapshot.tools[0].schema_sha256 != other.tools[0].schema_sha256


@pytest.mark.asyncio
async def test_safe_snapshot_writes_complete_artifact(tmp_path: Path) -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    output = tmp_path / "snapshot.json"

    snapshot = await write_tools_snapshot(session, output, observed_at=OBSERVED_AT)

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact == snapshot.as_json()
    assert artifact["tools"][0]["inputSchema"] == snapshot.tools[0].input_schema
    assert artifact["tools"][0]["outputSchema"] is None
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


@pytest.mark.asyncio
async def test_snapshot_write_is_atomic_and_cleans_temp_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    output = tmp_path / "snapshot.json"
    output.write_text("old-complete-artifact\n", encoding="utf-8")

    def fail_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failure"):
        await write_tools_snapshot(session, output, observed_at=OBSERVED_AT)

    assert output.read_text(encoding="utf-8") == "old-complete-artifact\n"
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


@pytest.mark.asyncio
async def test_snapshot_write_rejects_destination_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    target = tmp_path / "target.json"
    target.write_text("target-must-remain\n", encoding="utf-8")
    output = tmp_path / "snapshot.json"
    output.symlink_to(target)

    with pytest.raises(CapabilitySnapshotError, match="symlink"):
        await write_tools_snapshot(session, output, observed_at=OBSERVED_AT)

    assert output.is_symlink()
    assert target.read_text(encoding="utf-8") == "target-must-remain\n"
    assert list(tmp_path.glob(".snapshot.json.*.tmp")) == []


@pytest.mark.asyncio
async def test_captured_schema_and_artifact_views_are_detached_and_digest_stable() -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    captured = snapshot.tools[0]
    original_digest = captured.schema_sha256

    first_view = captured.input_schema
    first_view["mutated"] = True
    first_artifact = snapshot.as_json()
    tools_value = first_artifact["tools"]
    assert isinstance(tools_value, list)
    first_tool = tools_value[0]
    assert isinstance(first_tool, dict)
    first_tool["inputSchema"] = {"mutated": True}

    assert "mutated" not in captured.input_schema
    assert snapshot.as_json()["tools"] != first_artifact["tools"]
    assert captured.schema_sha256 == original_digest
    assert captured.schema_sha256 == canonical_sha256(
        {
            "inputSchema": captured.input_schema,
            "outputSchema": captured.output_schema,
        }
    )


def test_direct_sanitized_tool_construction_rejects_secret_json_and_false_digest() -> None:
    with pytest.raises(CapabilitySnapshotError):
        SanitizedToolSchema(
            name="get_equity_quotes",
            description=None,
            _input_schema_json=json.dumps(
                {
                    "type": "object",
                    "properties": {"auth_token": {"type": "string", "default": "tiny"}},
                },
                separators=(",", ":"),
            ),
            _output_schema_json=None,
            schema_sha256="0" * 64,
        )

    with pytest.raises(CapabilitySnapshotError):
        SanitizedToolSchema(
            name="get_equity_quotes",
            description=None,
            _input_schema_json='{"type":"object"}',
            _output_schema_json=None,
            schema_sha256="0" * 64,
        )


@pytest.mark.asyncio
async def test_direct_tools_snapshot_construction_enforces_all_invariants() -> None:
    session = FakeToolsListSession(
        [types.ListToolsResult(tools=[tool("review_equity_order"), tool("get_equity_quotes")])]
    )
    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    invalid_values: tuple[dict[str, object], ...] = (
        {"provider": "other-provider"},
        {"observed_at": datetime(2026, 7, 12, 12)},
        {"tools": list(snapshot.tools)},
        {"tools": tuple(reversed(snapshot.tools))},
        {"tools": ("not-a-tool",)},
        {"manifest": CapabilityManifest(records=())},
    )
    for changes in invalid_values:
        with pytest.raises(CapabilitySnapshotError):
            replace(snapshot, **changes)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_direct_snapshot_reconstructs_and_stores_sanitized_tool_copies() -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    captured = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    forged_safe_copy = forged_sanitized_tool(captured.tools[0])

    rebuilt = ToolsListSnapshot(
        provider=captured.provider,
        observed_at=captured.observed_at,
        tools=(forged_safe_copy,),
        manifest=captured.manifest,
    )

    assert rebuilt.tools == captured.tools
    assert rebuilt.tools[0] is not forged_safe_copy
    assert rebuilt.manifest is not captured.manifest
    assert rebuilt.manifest.records[0] is not captured.manifest.records[0]


@pytest.mark.parametrize(
    "forgery",
    (
        "unsafe_description",
        "unsafe_schema",
        "stale_digest",
        "false_digest",
        "wrong_schema_field",
        "missing_schema_field",
    ),
)
@pytest.mark.asyncio
async def test_direct_snapshot_rejects_forged_exact_nested_tool_values(
    forgery: str,
) -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    captured = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    original = captured.tools[0]
    manifest = captured.manifest

    if forgery == "unsafe_description":
        forged = forged_sanitized_tool(original, description="safe=clientsecret=tiny")
    elif forgery == "unsafe_schema":
        unsafe_schema: dict[str, object] = {
            "type": "object",
            "properties": {"auth_token": {"type": "string", "default": "tiny"}},
        }
        unsafe_digest = canonical_sha256(
            {"inputSchema": unsafe_schema, "outputSchema": original.output_schema}  # type: ignore[dict-item]
        )
        forged = forged_sanitized_tool(
            original,
            _input_schema_json=json.dumps(unsafe_schema, separators=(",", ":")),
            schema_sha256=unsafe_digest,
        )
        evidence = replace(manifest.records[0].evidence[0], schema_sha256=unsafe_digest)
        manifest = CapabilityManifest(records=(replace(manifest.records[0], evidence=(evidence,)),))
    elif forgery == "stale_digest":
        changed_safe_schema = {"type": "object", "properties": {"symbol": {"type": "number"}}}
        forged = forged_sanitized_tool(
            original,
            _input_schema_json=json.dumps(changed_safe_schema, separators=(",", ":")),
        )
    elif forgery == "false_digest":
        false_digest = "0" * 64
        forged = forged_sanitized_tool(original, schema_sha256=false_digest)
        evidence = replace(manifest.records[0].evidence[0], schema_sha256=false_digest)
        manifest = CapabilityManifest(records=(replace(manifest.records[0], evidence=(evidence,)),))
    elif forgery == "wrong_schema_field":
        forged = forged_sanitized_tool(original, _input_schema_json=123)
    else:
        forged = forged_sanitized_tool(original)
        object.__delattr__(forged, "_output_schema_json")

    with pytest.raises(CapabilitySnapshotError) as captured_error:
        ToolsListSnapshot(
            provider=captured.provider,
            observed_at=captured.observed_at,
            tools=(forged,),
            manifest=manifest,
        )

    assert str(captured_error.value) == "snapshot tool is invalid"
    assert captured_error.value.__cause__ is None
    assert captured_error.value.__context__ is None


@pytest.mark.asyncio
async def test_direct_snapshot_rejects_equality_overriding_nested_record_forgery() -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    expected = snapshot.manifest.records[0]
    forged_record = AlwaysEqualCapabilityRecord(
        provider=expected.provider,
        operation=expected.operation,
        asset_class=expected.asset_class,
        operation_kind=expected.operation_kind,
        evidence=expected.evidence,
        limitations=expected.limitations,
        locked_reason=expected.locked_reason,
    )
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(CapabilitySnapshotError) as captured:
        ToolsListSnapshot(
            provider=snapshot.provider,
            observed_at=snapshot.observed_at,
            tools=snapshot.tools,
            manifest=forged_manifest,
        )

    assert str(captured.value) == "snapshot manifest is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_direct_snapshot_rejects_equality_overriding_nested_evidence_forgery() -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    expected_record = snapshot.manifest.records[0]
    expected_evidence = expected_record.evidence[0]
    forged_evidence = AlwaysEqualCapabilityEvidence(
        level=expected_evidence.level,
        source_uri=expected_evidence.source_uri,
        observed_at=expected_evidence.observed_at,
        schema_sha256=expected_evidence.schema_sha256,
        authenticated=expected_evidence.authenticated,
        contains_account_data=expected_evidence.contains_account_data,
        notes=expected_evidence.notes,
    )
    forged_record = object.__new__(CapabilityRecord)
    object.__setattr__(forged_record, "provider", expected_record.provider)
    object.__setattr__(forged_record, "operation", expected_record.operation)
    object.__setattr__(forged_record, "asset_class", expected_record.asset_class)
    object.__setattr__(forged_record, "operation_kind", expected_record.operation_kind)
    object.__setattr__(forged_record, "evidence", (forged_evidence,))
    object.__setattr__(forged_record, "limitations", expected_record.limitations)
    object.__setattr__(forged_record, "locked_reason", expected_record.locked_reason)
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(CapabilitySnapshotError) as captured:
        ToolsListSnapshot(
            provider=snapshot.provider,
            observed_at=snapshot.observed_at,
            tools=snapshot.tools,
            manifest=forged_manifest,
        )

    assert str(captured.value) == "snapshot manifest is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_direct_snapshot_revalidates_nested_evidence_timestamp() -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    expected_record = snapshot.manifest.records[0]
    expected_evidence = expected_record.evidence[0]
    forged_evidence = object.__new__(CapabilityEvidence)
    object.__setattr__(forged_evidence, "level", expected_evidence.level)
    object.__setattr__(forged_evidence, "source_uri", expected_evidence.source_uri)
    object.__setattr__(
        forged_evidence,
        "observed_at",
        DatetimeSubclass(2026, 7, 12, 12, tzinfo=UTC),
    )
    object.__setattr__(forged_evidence, "schema_sha256", expected_evidence.schema_sha256)
    object.__setattr__(forged_evidence, "authenticated", expected_evidence.authenticated)
    object.__setattr__(
        forged_evidence,
        "contains_account_data",
        expected_evidence.contains_account_data,
    )
    object.__setattr__(forged_evidence, "notes", expected_evidence.notes)
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "limitations",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(expected_record, field_name))
    object.__setattr__(forged_record, "evidence", (forged_evidence,))
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(CapabilitySnapshotError) as captured:
        ToolsListSnapshot(
            provider=snapshot.provider,
            observed_at=snapshot.observed_at,
            tools=snapshot.tools,
            manifest=forged_manifest,
        )

    assert str(captured.value) == "snapshot manifest is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_capture_rejects_datetime_subclass_before_external_or_timestamp_methods() -> None:
    hostile_timestamp = SecretBearingDatetime(2026, 7, 12, 12, tzinfo=UTC)
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])

    with pytest.raises(CapabilitySnapshotError) as captured:
        await capture_tools_snapshot(session, observed_at=hostile_timestamp)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "observed_at must be an exact aware UTC datetime"
    assert "Authorization" not in rendered
    assert "Bearer tiny" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert session.list_tools_params == []


@pytest.mark.asyncio
async def test_direct_snapshot_rejects_datetime_subclass_without_method_access() -> None:
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])
    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)
    hostile_timestamp = SecretBearingDatetime(2026, 7, 12, 12, tzinfo=UTC)

    with pytest.raises(CapabilitySnapshotError) as captured:
        ToolsListSnapshot(
            provider=snapshot.provider,
            observed_at=hostile_timestamp,
            tools=snapshot.tools,
            manifest=snapshot.manifest,
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "snapshot timestamp must be an exact aware UTC datetime"
    assert "Authorization" not in rendered
    assert "Bearer tiny" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_capture_canonicalizes_exact_zero_offset_timestamp_to_utc() -> None:
    zero_offset = datetime(
        2026,
        7,
        12,
        12,
        tzinfo=timezone(timedelta(0), name="ZERO"),
    )
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool()])])

    snapshot = await capture_tools_snapshot(session, observed_at=zero_offset)

    assert snapshot.observed_at.tzinfo is UTC
    assert snapshot.manifest.records[0].evidence[0].observed_at.tzinfo is UTC
    assert snapshot.as_json()["observedAt"] == "2026-07-12T12:00:00Z"


def test_direct_tools_snapshot_rejects_manifest_with_wrong_observation() -> None:
    schema_json = '{"type":"object"}'
    digest = canonical_sha256({"inputSchema": {"type": "object"}, "outputSchema": None})
    captured_tool = SanitizedToolSchema(
        name="get_equity_quotes",
        description=None,
        _input_schema_json=schema_json,
        _output_schema_json=None,
        schema_sha256=digest,
    )

    with pytest.raises(CapabilitySnapshotError):
        ToolsListSnapshot(
            provider="robinhood-trading",
            observed_at=OBSERVED_AT,
            tools=(captured_tool,),
            manifest=CapabilityManifest(records=()),
        )


@pytest.mark.parametrize("property_name", ("auth_token", "account_number"))
@pytest.mark.parametrize(
    "unsafe_declaration",
    (
        {"type": "tiny"},
        {"format": "tiny"},
        {"$ref": "tiny"},
        {"required": ["tiny"]},
        {"minLength": 123456},
    ),
)
@pytest.mark.asyncio
async def test_capture_rejects_unvalidated_structural_values_in_sensitive_schema_scope(
    property_name: str,
    unsafe_declaration: dict[str, object],
) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {property_name: unsafe_declaration},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("property_name", ("auth_token", "account_number"))
@pytest.mark.parametrize(
    "unsafe_declaration",
    (
        {"type": "tiny"},
        {"format": "tiny"},
        {"$ref": "tiny"},
        {"required": ["tiny"]},
        {"minLength": 123456},
    ),
)
def test_direct_schema_rejects_unvalidated_structural_values_in_sensitive_scope(
    property_name: str,
    unsafe_declaration: dict[str, object],
) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {property_name: unsafe_declaration},
    }

    with pytest.raises(UnsafeCapabilitySnapshot):
        direct_sanitized_tool(input_schema)


@pytest.mark.parametrize(
    "sensitive_declaration",
    (
        {"type": "string"},
        {"type": "string", "format": "password"},
        {"$ref": "#/$defs/SafeString"},
        {
            "$defs": {"NestedSafeString": {"type": "string"}},
            "$ref": "#/$defs/NestedSafeString",
        },
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    ),
)
@pytest.mark.asyncio
async def test_capture_allows_exact_schema_only_shapes_under_sensitive_scope(
    sensitive_declaration: dict[str, object],
) -> None:
    input_schema: dict[str, object] = {
        "$defs": {"SafeString": {"type": "string"}},
        "type": "object",
        "properties": {"auth_token": sensitive_declaration},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].input_schema == input_schema


@pytest.mark.parametrize(
    "sensitive_value",
    (
        "Authorization: Bearer actual-secret-value",
        "Bearer standalone-secret-value",
        "Cookie=session=actual-secret-value",
        "x-api-key=actual-secret-value",
        "-----BEGIN PRIVATE KEY-----\nactual-secret-value\n-----END PRIVATE KEY-----",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhY2NvdW50In0.signaturevalue",
        "https://robinhood.com/path?access_token=actual-secret-value",
        "signature=actual-secret-value",
        "sk_actual-secret-value",
        "RHC123456789",
        "00000000-0000-4000-8000-000000000000",
        "aB3dE5fG7hJ9kL1mN3pQ5rS7tV9xY2zA",
    ),
)
@pytest.mark.asyncio
async def test_capture_rejects_nested_sensitive_values_before_any_write(
    tmp_path: Path,
    sensitive_value: str,
) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {
                                "safe": {
                                    "type": "string",
                                    "examples": [{"nested": sensitive_value}],
                                }
                            },
                        }
                    )
                ]
            )
        ]
    )
    output = tmp_path / "must-not-exist.json"

    with pytest.raises(UnsafeCapabilitySnapshot):
        await write_tools_snapshot(session, output, observed_at=OBSERVED_AT)

    assert not output.exists()


@pytest.mark.parametrize(
    "keyword",
    (
        "account_number",
        "token",
        "signature",
        "x-api-key",
        "client_secret",
        "password",
        "session_id",
        "acct_id",
        "account_reference",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_property_labels_without_values_are_allowed(keyword: str) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {keyword: {"type": "string"}},
                        }
                    )
                ]
            )
        ]
    )

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    properties = snapshot.tools[0].input_schema["properties"]
    assert isinstance(properties, dict)
    assert keyword in properties


@pytest.mark.parametrize("value_key", ("default", "const", "example", "examples"))
@pytest.mark.asyncio
async def test_sensitive_schema_property_rejects_embedded_values(value_key: str) -> None:
    value: object = ["synthetic-account-value"] if value_key == "examples" else "value"
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {"account_number": {"type": "string", value_key: value}},
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "property_name",
    (
        "client_secret",
        "password",
        "secret_value",
        "session_id",
        "acct_id",
        "account_reference",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_alias_defaults_nested_under_defs_are_rejected(
    property_name: str,
) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "$defs": {
                                "credentials": {
                                    "type": "object",
                                    "properties": {
                                        property_name: {
                                            "type": "string",
                                            "default": "short-secret",
                                        }
                                    },
                                }
                            }
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "alias",
    (
        "auth_token",
        "oauth_token",
        "id_token",
        "bearer_token",
        "csrf_token",
        "brokerage_account_id",
        "brokerage_account_number",
        "originating_account_id",
        "credential",
        "client_credential",
        "oauth_access_token",
        "signing_private_key",
        "order_sig",
        "csrf_cookie",
        "x_auth_header",
        "provider_api_key",
        "oauth_session_id",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_component_aliases_reject_short_defaults_but_allow_schema_only(
    alias: str,
) -> None:
    unsafe = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {alias: {"type": "string", "default": "tiny"}},
                        }
                    )
                ]
            )
        ]
    )
    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(unsafe, observed_at=OBSERVED_AT)

    schema_only = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {alias: {"type": "string"}},
                        }
                    )
                ]
            )
        ]
    )
    snapshot = await capture_tools_snapshot(schema_only, observed_at=OBSERVED_AT)
    properties = snapshot.tools[0].input_schema["properties"]
    assert isinstance(properties, dict)
    assert alias in properties


@pytest.mark.parametrize("alias", ("access_key", "client_key", "consumer_key"))
@pytest.mark.parametrize(
    "carrier",
    ("property_default", "assignment", "query", "encoded_query", "path"),
)
@pytest.mark.asyncio
async def test_key_aliases_are_rejected_across_schema_and_text_carriers(
    alias: str,
    carrier: str,
) -> None:
    if carrier == "property_default":
        input_schema: dict[str, object] = {
            "type": "object",
            "properties": {alias: {"type": "string", "default": "tiny"}},
        }
    else:
        encoded_alias = alias.replace("_", "%5F")
        sensitive_text = {
            "assignment": f"{alias}=tiny",
            "query": f"https://robinhood.com/path?{alias}=tiny",
            "encoded_query": f"https://robinhood.com/path?{encoded_alias}=tiny",
            "path": f"https://robinhood.com/{alias}/tiny",
        }[carrier]
        input_schema = {
            "type": "object",
            "properties": {"safe_value": {"type": "string", "description": sensitive_text}},
        }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("alias", COMPACT_SENSITIVE_NAMES)
@pytest.mark.parametrize(
    "carrier",
    ("property_default", "assignment", "query", "encoded_query", "path"),
)
@pytest.mark.asyncio
async def test_compact_sensitive_names_are_rejected_across_schema_and_text_carriers(
    alias: str,
    carrier: str,
) -> None:
    if carrier == "property_default":
        input_schema: dict[str, object] = {
            "type": "object",
            "properties": {alias: {"type": "string", "default": "tiny"}},
        }
    else:
        encoded_alias = "".join(f"%{ord(character):02X}" for character in alias)
        sensitive_text = {
            "assignment": f"{alias}=tiny",
            "query": f"https://robinhood.com/path?{alias}=tiny",
            "encoded_query": f"https://robinhood.com/path?{encoded_alias}=tiny",
            "path": f"https://robinhood.com/{alias}/tiny",
        }[carrier]
        input_schema = {
            "type": "object",
            "properties": {"safe_value": {"type": "string", "description": sensitive_text}},
        }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("alias", GRAMMAR_SENSITIVE_NAMES)
@pytest.mark.parametrize(
    "carrier",
    (
        "property_default",
        "assignment",
        "nested_assignment",
        "query",
        "fragment",
        "encoded_query",
        "path",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_compound_grammar_rejects_plural_decorated_and_compact_aliases(
    alias: str,
    carrier: str,
) -> None:
    if carrier == "property_default":
        input_schema: dict[str, object] = {
            "type": "object",
            "properties": {alias: {"type": "string", "default": "tiny"}},
        }
    else:
        encoded_alias = "".join(f"%{ord(character):02X}" for character in alias)
        sensitive_text = {
            "assignment": f"{alias}=tiny",
            "nested_assignment": f"safe={alias}=tiny",
            "query": f"https://robinhood.com/path?{alias}=tiny",
            "fragment": f"https://robinhood.com/path#{alias}=tiny",
            "encoded_query": f"https://robinhood.com/path?{encoded_alias}=tiny",
            "path": f"https://robinhood.com/{alias}/tiny",
        }[carrier]
        input_schema = {
            "type": "object",
            "properties": {"safe_value": {"type": "string", "description": sensitive_text}},
        }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "benign_name",
    (
        "author",
        "signal",
        "designation",
        "assignment",
        "accounting_period",
        "session_duration",
        "client_order_id",
        "public_keys",
        "authentication_method",
        "api_version",
        "keynote_title",
        "secretary_name",
        "consumer_sentiment",
        "accessibility_label",
        "clientele_segment",
        "apiculture_method",
        "authoritative_source",
        "author[]",
        "public_keys[]",
        "client_order_id[]",
    ),
)
@pytest.mark.parametrize(
    "carrier",
    ("property_default", "assignment", "nested_assignment", "query", "fragment", "path"),
)
@pytest.mark.asyncio
async def test_sensitive_compound_grammar_preserves_benign_names_across_carriers(
    benign_name: str,
    carrier: str,
) -> None:
    if carrier == "property_default":
        input_schema: dict[str, object] = {
            "type": "object",
            "properties": {benign_name: {"type": "string", "default": "ordinary"}},
        }
    else:
        benign_text = {
            "assignment": f"{benign_name}=ordinary",
            "nested_assignment": f"safe={benign_name}=ordinary",
            "query": f"https://robinhood.com/path?{benign_name}=ordinary",
            "fragment": f"https://robinhood.com/path#{benign_name}=ordinary",
            "path": f"https://robinhood.com/{benign_name}/ordinary",
        }[carrier]
        input_schema = {
            "type": "object",
            "properties": {"safe_value": {"type": "string", "description": benign_text}},
        }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].input_schema == input_schema


@pytest.mark.parametrize("candidate_name", ("api\u200bkey", "tökén", "safe\x01name"))
@pytest.mark.parametrize("carrier", ("property", "assignment", "query", "path"))
@pytest.mark.asyncio
async def test_candidate_names_fail_closed_for_non_ascii_control_and_format_characters(
    candidate_name: str,
    carrier: str,
) -> None:
    if carrier == "property":
        input_schema: dict[str, object] = {
            "type": "object",
            "properties": {candidate_name: {"type": "string"}},
        }
    else:
        sensitive_text = {
            "assignment": f"{candidate_name}=tiny",
            "query": f"https://robinhood.com/path?{candidate_name}=tiny",
            "path": f"https://robinhood.com/{candidate_name}/tiny",
        }[carrier]
        input_schema = {
            "type": "object",
            "properties": {"safe_value": {"type": "string", "description": sensitive_text}},
        }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "encoded_property_name",
    ("access%5Fkey", "client%5Fkey", "consumer%5Fkey"),
)
@pytest.mark.asyncio
async def test_percent_encoded_sensitive_property_names_are_rejected(
    encoded_property_name: str,
) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {encoded_property_name: {"type": "string", "default": "tiny"}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "unsafe_ref",
    (
        "#/$defs/token/tiny",
        "#/$defs/account/private_key/session_id",
        "#/token/tiny",
        "#/$defs/%74oken/tiny",
        "#/$defs/token%2Ftiny",
        "#/$defs/access%5Fkey/tiny",
        "#/$defs/access_key%2Ftiny",
        "#/$defs/AuthToken/tiny",
        "#/$defs/access_token~1tiny",
        "#/$defs/access_token%7E1tiny",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_local_ref_rejects_value_bearing_pointer_pairs(unsafe_ref: str) -> None:
    input_schema: dict[str, object] = {
        "$defs": {"AuthToken": {"type": "string"}},
        "type": "object",
        "properties": {"auth_token": {"$ref": unsafe_ref}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "unsafe_ref",
    (
        "#/$defs/Safe\x00Name",
        "#/$defs/Safe\x1bName",
        "#/$defs/Safe\u202eName",
        "#/$defs/SaféName",
        "#/$defs/Safe%00Name",
    ),
)
@pytest.mark.asyncio
async def test_local_ref_rejects_unsafe_characters_in_every_decoded_pointer_segment(
    unsafe_ref: str,
) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"auth_token": {"$ref": unsafe_ref}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "safe_ref",
    (
        "#/$defs/AuthToken",
        "#/$defs/Safe~0Name",
        "#/$defs/Safe~01Name",
        "#/properties/author",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_local_ref_allows_safe_terminal_and_escaped_schema_names(
    safe_ref: str,
) -> None:
    input_schema: dict[str, object] = {
        "$defs": {"AuthToken": {"type": "string"}},
        "type": "object",
        "properties": {"auth_token": {"$ref": safe_ref}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].input_schema == input_schema


@pytest.mark.parametrize(
    "benign_property_name",
    (
        "author",
        "signal",
        "signal_type",
        "designation",
        "assignment",
        "accounting_period",
        "session_duration",
        "client_order_id",
    ),
)
@pytest.mark.asyncio
async def test_boundary_aware_name_matching_allows_benign_property_metadata(
    benign_property_name: str,
) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            benign_property_name: {
                "type": "string",
                "description": "Ordinary public request metadata.",
                "default": "ordinary",
            }
        },
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].input_schema == input_schema


@pytest.mark.parametrize(
    "sensitive_schema",
    (
        {
            "type": "object",
            "properties": {"auth_token": {"type": "string", "x-current": "tiny"}},
        },
        {
            "type": "object",
            "properties": {"auth_token": {"allOf": [{"type": "string", "x-current": "tiny"}]}},
        },
        {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "current value tiny",
                }
            },
        },
    ),
)
@pytest.mark.asyncio
async def test_sensitive_schema_scope_rejects_custom_and_metadata_values(
    sensitive_schema: dict[str, object],
) -> None:
    session = FakeToolsListSession(
        [types.ListToolsResult(tools=[tool(input_schema=sensitive_schema)])]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("definition_name", ("client_secret", "account_number"))
@pytest.mark.asyncio
async def test_sensitive_named_definition_default_is_rejected(
    definition_name: str,
) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "$defs": {
                                definition_name: {
                                    "type": "string",
                                    "default": "short-secret",
                                }
                            }
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "property_name",
    (
        "RHC123456789",
        "Authorization: Bearer actual-secret-value",
    ),
)
@pytest.mark.asyncio
async def test_sensitive_material_used_as_property_key_is_rejected(property_name: str) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {property_name: {"type": "string"}},
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.asyncio
async def test_sensitive_property_label_with_direct_scalar_value_is_rejected() -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {"account_reference": "short-secret"},
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "sensitive_value",
    (
        "https://actual-secret-value@robinhood.com/path",
        "https://robinhood.com/path?session_id=short-secret",
        "https://robinhood.com/path?%73ession_id=short-secret",
        "https://robinhood.com/path#session_id=short-secret",
        "%61ccess_token%3Dactual-secret-value",
        "%2561ccess_token%253Dactual-secret-value",
        "%FFsession_id=short-secret",
        "https://robinhood.com/path?oauth_token=tiny",
        "https://robinhood.com/path#brokerage_account_id=tiny",
        "%63srf_token%3Dtiny",
        "access_%ZZtoken=short-secret",
        "https://robinhood.com/account_id/short-secret",
        "Bearer tiny",
    ),
)
@pytest.mark.asyncio
async def test_encoded_userinfo_query_and_fragment_secrets_are_rejected(
    sensitive_value: str,
) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {
                                "safe": {"type": "string", "description": sensitive_value}
                            },
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.asyncio
async def test_unknown_name_remains_locked_discovery_despite_order_prose() -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        "totally_safe_buy_now",
                        description="Safe reviewed write; place an order immediately.",
                    )
                ]
            )
        ]
    )

    manifest = await capture_tools_list(session, observed_at=OBSERVED_AT)
    record = manifest.records[0]

    assert record.operation_kind is OperationKind.DISCOVER
    assert record.locked_reason == "tool name is not in the reviewed operation allowlist"
    assert not record.satisfies(EvidenceLevel.SCHEMA_DECLARED)


def fixture_payload() -> dict[str, object]:
    """Return a detached mutable copy of the committed public fixture."""
    value: object = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def write_fixture(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")


@pytest.mark.parametrize("location", ("root", "record", "evidence"))
def test_fixture_loader_rejects_extra_fields_at_every_level(
    tmp_path: Path,
    location: str,
) -> None:
    payload = deepcopy(fixture_payload())
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    evidence_values = record["evidence"]
    assert isinstance(evidence_values, list)
    evidence = evidence_values[0]
    assert isinstance(evidence, dict)
    target = {"root": payload, "record": record, "evidence": evidence}[location]
    target["unexpected"] = "actual-secret-value"
    path = tmp_path / "invalid.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest, match="fixture is invalid") as captured:
        load_capability_manifest(path)

    assert "actual-secret-value" not in str(captured.value)


def test_fixture_loader_rejects_duplicate_keys_without_sensitive_context(
    tmp_path: Path,
) -> None:
    raw = FIXTURE.read_text(encoding="utf-8").replace(
        '"format_version": 1,',
        '"format_version": 1, "format_version": "actual-secret-value",',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert "actual-secret-value" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_fixture_loader_rejects_nonfinite_json_constants(tmp_path: Path) -> None:
    raw = FIXTURE.read_text(encoding="utf-8").replace(
        '"format_version": 1',
        '"format_version": NaN',
        1,
    )
    path = tmp_path / "nonfinite.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(InvalidCapabilityManifest, match="fixture is invalid"):
        load_capability_manifest(path)


@pytest.mark.parametrize("version", (True, 1.0, "1", 2))
def test_fixture_loader_requires_exact_integer_format_version(
    tmp_path: Path,
    version: object,
) -> None:
    payload = fixture_payload()
    payload["format_version"] = version
    path = tmp_path / "version.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest, match="fixture is invalid"):
        load_capability_manifest(path)


@pytest.mark.parametrize(
    "checked_at",
    (None, "not-a-timestamp", "2026-07-12T00:00:00-04:00", 123),
)
def test_fixture_loader_rejects_missing_invalid_or_non_utc_checked_at(
    tmp_path: Path,
    checked_at: object,
) -> None:
    payload = fixture_payload()
    if checked_at is None:
        del payload["checked_at"]
    else:
        payload["checked_at"] = checked_at
    path = tmp_path / "checked-at.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest, match="fixture is invalid"):
        load_capability_manifest(path)


@pytest.mark.parametrize(
    ("field", "sensitive_value"),
    (
        ("provider", "brokerage_account_id=short-secret"),
        ("operation", "csrf_token=short-secret"),
        ("limitations", "Authorization: Bearer short-secret"),
        ("locked_reason", "oauth_session_id=short-secret"),
        ("notes", "client_credential=short-secret"),
    ),
)
def test_fixture_loader_rejects_sensitive_free_form_values_generically(
    tmp_path: Path,
    field: str,
    sensitive_value: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    evidence_values = record["evidence"]
    assert isinstance(evidence_values, list)
    evidence = evidence_values[0]
    assert isinstance(evidence, dict)
    if field == "limitations":
        record[field] = [sensitive_value]
    elif field == "notes":
        evidence[field] = [sensitive_value]
    else:
        record[field] = sensitive_value
    path = tmp_path / "sensitive.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert sensitive_value not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "sensitive_path",
    (
        "/secret/tiny",
        "/token/tiny",
        "/access_key/tiny",
        "/auth/tiny",
        "/cookie/tiny",
        "/signature/tiny",
        "/private_key/tiny",
    ),
)
def test_fixture_loader_scans_official_source_uri_before_uri_validation(
    tmp_path: Path,
    sensitive_path: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    evidence_values = record["evidence"]
    assert isinstance(evidence_values, list)
    evidence = evidence_values[0]
    assert isinstance(evidence, dict)
    evidence["source_uri"] = f"https://robinhood.com{sensitive_path}"
    path = tmp_path / "sensitive-source.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "capability fixture is invalid"
    assert sensitive_path not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("alias", COMPACT_SENSITIVE_NAMES)
def test_fixture_loader_rejects_compact_sensitive_source_uri_path_pairs(
    tmp_path: Path,
    alias: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    evidence_values = record["evidence"]
    assert isinstance(evidence_values, list)
    evidence = evidence_values[0]
    assert isinstance(evidence, dict)
    evidence["source_uri"] = f"https://robinhood.com/{alias}/tiny"
    path = tmp_path / "compact-sensitive-source.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "capability fixture is invalid"
    assert alias not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("alias", GRAMMAR_SENSITIVE_NAMES)
def test_fixture_loader_rejects_nested_sensitive_compound_assignments(
    tmp_path: Path,
    alias: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["limitations"] = [f"safe={alias}=tiny"]
    path = tmp_path / "nested-sensitive-compound.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("alias", GRAMMAR_SENSITIVE_NAMES[:-1])
def test_fixture_loader_rejects_sensitive_compound_source_uri_path_pairs(
    tmp_path: Path,
    alias: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    evidence_values = record["evidence"]
    assert isinstance(evidence_values, list)
    evidence = evidence_values[0]
    assert isinstance(evidence, dict)
    evidence["source_uri"] = f"https://robinhood.com/{alias}/tiny"
    path = tmp_path / "sensitive-compound-source.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "unsafe_text", ("ordinary\x00text", "ordinary\x1btext", "ordinary\u202etext")
)
@pytest.mark.parametrize("field", ("limitations", "locked_reason", "notes"))
def test_fixture_loader_rejects_control_and_bidi_freeform_text(
    tmp_path: Path,
    field: str,
    unsafe_text: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    evidence_values = record["evidence"]
    assert isinstance(evidence_values, list)
    evidence = evidence_values[0]
    assert isinstance(evidence, dict)
    if field == "limitations":
        record[field] = [unsafe_text]
    elif field == "notes":
        evidence[field] = [unsafe_text]
    else:
        record[field] = unsafe_text
    path = tmp_path / "unsafe-freeform-control.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert unsafe_text not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_matrix_renderer_never_emits_sensitive_free_form_record_values() -> None:
    record = load_capability_manifest(FIXTURE).records[0]
    unsafe_evidence = replace(
        record.evidence[0],
        notes=("csrf_token=short-secret",),
    )
    unsafe_records = (
        replace(record, provider="brokerage_account_id=short-secret"),
        replace(record, operation="csrf_token=short-secret"),
        replace(record, limitations=("Authorization: Bearer short-secret",)),
        replace(record, locked_reason="oauth_session_id=short-secret"),
        replace(record, evidence=(unsafe_evidence,)),
    )

    for unsafe_record in unsafe_records:
        with pytest.raises(InvalidCapabilityManifest) as captured:
            render_capability_matrix(CapabilityManifest(records=(unsafe_record,)))
        assert str(captured.value) == "capability manifest contains unsafe text"
        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None


@pytest.mark.parametrize("alias", GRAMMAR_SENSITIVE_NAMES)
def test_matrix_renderer_rejects_nested_sensitive_compound_assignments(alias: str) -> None:
    record = load_capability_manifest(FIXTURE).records[0]
    unsafe_record = replace(record, limitations=(f"safe={alias}=tiny",))

    with pytest.raises(InvalidCapabilityManifest) as captured:
        render_capability_matrix(CapabilityManifest(records=(unsafe_record,)))

    assert str(captured.value) == "capability manifest contains unsafe text"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "unsafe_text", ("ordinary\x00text", "ordinary\x1btext", "ordinary\u202etext")
)
def test_matrix_renderer_rejects_control_and_bidi_text_from_forged_manifest(
    unsafe_text: str,
) -> None:
    record = load_capability_manifest(FIXTURE).records[0]
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(record, field_name))
    object.__setattr__(forged_record, "limitations", (unsafe_text,))
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(InvalidCapabilityManifest) as captured:
        render_capability_matrix(forged_manifest)

    assert str(captured.value) == "capability manifest contains unsafe text"
    assert unsafe_text not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_documented_fixture_uses_only_public_evidence_and_locked_states() -> None:
    manifest = load_capability_manifest(FIXTURE)

    assert len(manifest.records) == 19
    assert {
        item.operation for item in manifest.records if item.provider == "robinhood-trading"
    } == {
        "cancel_equity_order",
        "get_equity_fundamentals",
        "get_equity_historicals",
        "get_equity_orders",
        "get_equity_positions",
        "get_equity_quotes",
        "get_equity_technical_indicators",
        "get_equity_tradability",
        "place_equity_order",
        "review_equity_order",
    }
    assert {
        item.operation for item in manifest.records if item.provider == "robinhood-crypto-v2"
    } == {
        "GET /api/v2/crypto/marketdata/best_bid_ask/",
        "GET /api/v2/crypto/trading/accounts/",
        "GET /api/v2/crypto/trading/estimated_price/",
        "GET /api/v2/crypto/trading/holdings/",
        "GET /api/v2/crypto/trading/orders/",
        "GET /api/v2/crypto/trading/trading_pairs/",
        "POST /api/v2/crypto/trading/orders/",
        "POST /api/v2/crypto/trading/orders/{id}/cancel/",
    }
    assert {item.evidence[0].level for item in manifest.records} == {
        EvidenceLevel.DOCUMENTED,
        EvidenceLevel.UNSUPPORTED,
    }
    assert all(
        not evidence.authenticated for item in manifest.records for evidence in item.evidence
    )
    assert all(
        not evidence.contains_account_data
        for item in manifest.records
        for evidence in item.evidence
    )
    assert all(item.locked_reason for item in manifest.records)
    assert (
        manifest.find(
            provider="robinhood-prediction",
            operation="place_prediction_order",
        )
        .evidence[0]
        .level
        is EvidenceLevel.UNSUPPORTED
    )
    assert not any(
        "websocket" in note.casefold()
        for item in manifest.records
        for note in item.limitations
        if item.asset_class.value == "crypto"
    )


def test_matrix_rendering_is_deterministic_under_record_reordering() -> None:
    manifest = load_capability_manifest(FIXTURE)
    reverse = CapabilityManifest(records=tuple(reversed(manifest.records)))

    assert render_capability_matrix(manifest) == render_capability_matrix(reverse)
    assert "documented_locked_external_pending" in render_capability_matrix(manifest)
    assert "unsupported_locked" in render_capability_matrix(manifest)


def test_unconfigured_cli_exits_two_writes_nothing_and_prints_setup_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ROBINHOOD_MCP_SERVER_URL", raising=False)
    monkeypatch.setattr("sys.argv", [str(SCRIPT)])

    with pytest.raises(SystemExit) as captured_exit:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert captured.err.strip() == (
        "codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading"
    )
    assert list(tmp_path.iterdir()) == []


def test_public_endpoint_env_alone_does_not_claim_configured_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ROBINHOOD_MCP_SERVER_URL",
        "https://agent.robinhood.com/mcp/trading",
    )
    monkeypatch.setattr("sys.argv", [str(SCRIPT)])

    with pytest.raises(SystemExit) as captured_exit:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.err.strip() == (
        "codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading"
    )
    assert list(tmp_path.iterdir()) == []


def test_cli_help_promises_tools_list_only_and_no_account_data(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--help"])

    with pytest.raises(SystemExit) as captured_exit:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    captured = capsys.readouterr()
    assert captured_exit.value.code == 0
    assert "tools/list only" in captured.out
    assert "no account data" in captured.out


def test_configured_cli_capture_failure_is_generic_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    script_globals = runpy.run_path(str(SCRIPT))
    main = script_globals["main"]
    assert callable(main)

    result = main(
        ["--output", str(tmp_path / "snapshot.json")],
        configured_session=SecretFailingSession(),
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err.strip() == "capability capture failed safely"
    assert "actual-secret-value" not in captured.err
    assert not (tmp_path / "snapshot.json").exists()
