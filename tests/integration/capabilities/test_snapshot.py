"""Integration tests for schema-only MCP capability capture."""

from __future__ import annotations

import asyncio
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
from trading_bot.capabilities import snapshot as snapshot_module
from trading_bot.capabilities.snapshot import text_contains_sensitive_material

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
COMPACT_CREDENTIAL_VALUE_NAMES = (
    "secretaccesskey",
    "awssecretaccesskey",
    "privatekeyvalue",
    "clientsecretvalue",
    "apikeyvalue",
    "clientsecretvalues",
    "apikeydata",
    "signingkeybytes",
    "consumersecretmaterial",
    "privatekeypem",
    "passwordvalue",
    "passphrasedata",
    "credentialbytes",
    "signaturematerial",
    "cookiepem",
    "walletprivatekey",
    "webhooksecret",
    "idtoken",
    "csrftoken",
    "sessioncookievalue",
    "tradingapikey",
    "webhooksignature",
    "providerclientsecretdata",
    "vaultsecret",
    "custodysignature",
    "browsercookie",
    "operatorpassword",
    "servicecredential",
    "recoverypassphrase",
    "authvalue",
    "accountdata",
    "headervalue",
    "bearermaterial",
    "oauthvalue",
    "verificationtoken",
    "resettoken",
    "continuationtoken",
)
BENIGN_COMPACT_VALUE_NAMES = (
    "publickeyvalue",
    "keyvalue",
    "secretaryvalue",
    "authorvalue",
    "marketdata",
    "materiality",
    "pembridge",
    "tokenization",
    "tokenizationdata",
    "tokenbucket",
    "monkey",
    "monkeyvalue",
    "accountingdata",
    "headerlessvalue",
)
SENSITIVE_ACCOUNT_AUTH_ALIASES = (
    "accountidentifier",
    "accountidentifiers",
    "accountidentifiervalue",
    "accountidentifiervalues",
    "accountreference",
    "accountreferences",
    "accountreferencevalue",
    "accountreferencevalues",
    "acctid",
    "acctidentifier",
    "acctnumber",
    "acctuuid",
    "acctreference",
    "acctno",
    "accountno",
    "authorizationcode",
    "authorizationcodes",
    "authorizationcodevalue",
    "authorization_code",
    "oauthcode",
    "oauth_code",
    "authcode",
    "auth_code",
    "verificationcode",
    "verification_code",
    "mfacode",
    "mfa_code",
    "recoverycode",
    "recovery_code",
    "otpcode",
    "otp_code",
)
BENIGN_ACCOUNT_AUTH_CONTROLS = (
    "accountingreference",
    "accounting_reference",
    "authorizationstatus",
    "authorization_status",
    "oauthscope",
    "oauth_scope",
    "postcode",
    "post_code",
    "zipcode",
    "zip_code",
    "codepoint",
    "code_point",
    "referenceprice",
    "reference_price",
    "identifierformat",
    "identifier_format",
)
ACCOUNT_ABBREVIATION_ALIASES = (
    "acctNum",
    "acctNums",
    "acctNumValue",
    "accountNbr",
    "accountNbrs",
    "accountNbrData",
    "acctRef",
    "acctRefs",
    "acctRefBytes",
)
SESSION_IDENTIFIER_ALIASES = (
    "sessionIdentifier",
    "sessionIdentifiers",
    "sessionIdentifierValue",
    "sessionReference",
    "sessionReferences",
    "sessionReferenceValues",
    "sessionNumber",
    "sessionNumbers",
    "sessionNumberData",
    "sessionUuid",
    "sessionUuids",
    "sessionUuidBytes",
    "sessionNo",
    "sessionNos",
    "sessionNoValue",
)
STANDARD_BASE64_TEST_VALUE = "xQoZprzZRMK3vuPuR0K8f8gA+GK+8DFUeXQ3diC/qpg="


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


class EndlessCursorSession:
    """Return unique cursors forever unless the finite page gate stops capture."""

    def __init__(self) -> None:
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
        # Yield without wall-clock delay so the external RED timeout can fire.
        await asyncio.sleep(0)
        return types.ListToolsResult(
            tools=[],
            nextCursor=f"page-{len(self.list_tools_params) + 1}",
        )


class HangingToolsListSession:
    """Never return a page; the per-call timeout must cancel the await."""

    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = False

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        self.calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


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


def forged_manifest_with_unsafe_freeform(
    source: CapabilityRecord,
    *,
    field: str,
    value: str,
) -> CapabilityManifest:
    """Bypass direct-model validation to exercise the renderer's own boundary."""
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "limitations",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(source, field_name))
    if field == "notes":
        source_evidence = source.evidence[0]
        forged_evidence = object.__new__(CapabilityEvidence)
        for evidence_field in (
            "level",
            "source_uri",
            "observed_at",
            "schema_sha256",
            "authenticated",
            "contains_account_data",
            "notes",
        ):
            object.__setattr__(
                forged_evidence,
                evidence_field,
                getattr(source_evidence, evidence_field),
            )
        object.__setattr__(forged_evidence, "notes", (value,))
        object.__setattr__(forged_record, "evidence", (forged_evidence,))
    elif field == "limitations":
        object.__setattr__(forged_record, field, (value,))
    else:
        object.__setattr__(forged_record, field, value)
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))
    return forged_manifest


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
async def test_capture_omits_provider_prose_before_persisting_schema() -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "account_number": {
                "type": "string",
                "description": "Authorization: Bearer actual-secret-value",
            }
        },
        "required": ["account_number"],
    }
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        description="account number = actual-secret-value",
                        input_schema=input_schema,
                    )
                ]
            )
        ]
    )

    snapshot = await capture_tools_snapshot(
        session,
        observed_at=OBSERVED_AT,
        omit_descriptions=True,
    )

    assert snapshot.tools[0].description is None
    assert snapshot.tools[0].input_schema == {
        "type": "object",
        "properties": {"account_number": {"type": "string"}},
        "required": ["account_number"],
    }


@pytest.mark.asyncio
async def test_capture_preserves_bounded_long_declaration_identifiers() -> None:
    property_name = "rounded_uncollared_estimated_notional_with_estimated_fee"
    schema: dict[str, object] = {
        "type": "object",
        "properties": {property_name: {"type": "string"}},
        "required": [property_name],
    }
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        name="get_crypto_account_onboarding_info",
                        description=None,
                        input_schema=schema,
                    )
                ]
            )
        ]
    )

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].name == "get_crypto_account_onboarding_info"
    assert snapshot.tools[0].input_schema == schema


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


@pytest.mark.parametrize("alias", COMPACT_CREDENTIAL_VALUE_NAMES)
def test_compact_credential_value_names_are_sensitive_in_direct_assignments(alias: str) -> None:
    assert text_contains_sensitive_material(f"{alias}=tiny")


@pytest.mark.parametrize("alias", COMPACT_CREDENTIAL_VALUE_NAMES)
@pytest.mark.parametrize(
    "carrier",
    ("property_default", "assignment", "nested_assignment", "query", "fragment", "path"),
)
@pytest.mark.asyncio
async def test_compact_credential_value_names_are_rejected_across_representative_carriers(
    alias: str,
    carrier: str,
) -> None:
    if carrier == "property_default":
        input_schema: dict[str, object] = {
            "type": "object",
            "properties": {alias: {"type": "string", "default": "tiny"}},
        }
    else:
        sensitive_text = {
            "assignment": f"{alias}=tiny",
            "nested_assignment": f"safe={alias}=tiny",
            "query": f"https://robinhood.com/path?{alias}=tiny",
            "fragment": f"https://robinhood.com/path#{alias}=tiny",
            "path": f"https://robinhood.com/{alias}/tiny",
        }[carrier]
        input_schema = {
            "type": "object",
            "properties": {"safe_value": {"type": "string", "description": sensitive_text}},
        }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("benign_name", BENIGN_COMPACT_VALUE_NAMES)
def test_compact_credential_suffix_grammar_preserves_direct_benign_names(
    benign_name: str,
) -> None:
    assert not text_contains_sensitive_material(f"{benign_name}=ordinary")


@pytest.mark.parametrize("benign_name", BENIGN_COMPACT_VALUE_NAMES)
@pytest.mark.parametrize("carrier", ("property_default", "assignment", "query", "fragment", "path"))
@pytest.mark.asyncio
async def test_compact_credential_suffix_grammar_preserves_benign_carriers(
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


@pytest.mark.parametrize("alias", COMPACT_CREDENTIAL_VALUE_NAMES)
def test_fixture_loader_rejects_compact_credential_value_carriers(
    tmp_path: Path,
    alias: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["limitations"] = [f"safe={alias}=tiny"]
    path = tmp_path / "compact-credential-value.json"
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
    unsafe_manifests = (
        forged_manifest_with_unsafe_freeform(
            record,
            field="provider",
            value="brokerage_account_id=short-secret",
        ),
        forged_manifest_with_unsafe_freeform(
            record,
            field="operation",
            value="csrf_token=short-secret",
        ),
        forged_manifest_with_unsafe_freeform(
            record,
            field="limitations",
            value="Authorization: Bearer short-secret",
        ),
        forged_manifest_with_unsafe_freeform(
            record,
            field="locked_reason",
            value="oauth_session_id=short-secret",
        ),
        forged_manifest_with_unsafe_freeform(
            record,
            field="notes",
            value="csrf_token=short-secret",
        ),
    )

    for unsafe_manifest in unsafe_manifests:
        with pytest.raises(InvalidCapabilityManifest) as captured:
            render_capability_matrix(unsafe_manifest)
        assert str(captured.value) == "capability manifest contains unsafe text"
        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None


@pytest.mark.parametrize("alias", GRAMMAR_SENSITIVE_NAMES)
def test_matrix_renderer_rejects_nested_sensitive_compound_assignments(alias: str) -> None:
    record = load_capability_manifest(FIXTURE).records[0]
    unsafe_manifest = forged_manifest_with_unsafe_freeform(
        record,
        field="limitations",
        value=f"safe={alias}=tiny",
    )

    with pytest.raises(InvalidCapabilityManifest) as captured:
        render_capability_matrix(unsafe_manifest)

    assert str(captured.value) == "capability manifest contains unsafe text"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("alias", COMPACT_CREDENTIAL_VALUE_NAMES)
def test_matrix_renderer_rejects_compact_credential_value_carriers(alias: str) -> None:
    record = load_capability_manifest(FIXTURE).records[0]
    unsafe_manifest = forged_manifest_with_unsafe_freeform(
        record,
        field="limitations",
        value=f"safe={alias}=tiny",
    )

    with pytest.raises(InvalidCapabilityManifest) as captured:
        render_capability_matrix(unsafe_manifest)

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


def _read_tool_accessor(tool_value: SanitizedToolSchema, accessor: str) -> object:
    if accessor == "input_schema":
        return tool_value.input_schema
    if accessor == "output_schema":
        return tool_value.output_schema
    return tool_value.as_json()


@pytest.mark.parametrize("accessor", ("input_schema", "output_schema", "as_json"))
@pytest.mark.parametrize(
    "forgery",
    ("unsafe_description", "unsafe_schema", "false_digest", "wrong_field", "missing_field"),
)
def test_standalone_tool_accessors_revalidate_mutated_normal_objects(
    accessor: str,
    forgery: str,
) -> None:
    value = direct_sanitized_tool({"type": "object", "properties": {"symbol": {"type": "string"}}})
    if forgery == "unsafe_description":
        object.__setattr__(value, "description", "Authorization: Bearer actual-secret-value")
    elif forgery == "unsafe_schema":
        object.__setattr__(
            value,
            "_input_schema_json",
            '{"type":"object","properties":{"clientsecret":{"default":"tiny"}}}',
        )
    elif forgery == "false_digest":
        object.__setattr__(value, "schema_sha256", "0" * 64)
    elif forgery == "wrong_field":
        object.__setattr__(value, "description", 123)
    else:
        object.__delattr__(value, "_input_schema_json")

    with pytest.raises(CapabilitySnapshotError) as captured:
        _read_tool_accessor(value, accessor)

    rendered = "".join(traceback.format_exception(captured.value))
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("accessor", ("input_schema", "output_schema", "as_json"))
def test_standalone_tool_accessors_revalidate_exact_object_new_forgery(accessor: str) -> None:
    original = direct_sanitized_tool({"type": "object"})
    forged = forged_sanitized_tool(
        original,
        description="safe=clientsecret=actual-secret-value",
    )

    with pytest.raises(CapabilitySnapshotError) as captured:
        _read_tool_accessor(forged, accessor)

    rendered = "".join(traceback.format_exception(captured.value))
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("forgery", ("provider", "nested_description", "nested_digest"))
@pytest.mark.asyncio
async def test_snapshot_as_json_revalidates_mutated_normal_state(forgery: str) -> None:
    snapshot = await capture_tools_snapshot(
        FakeToolsListSession([types.ListToolsResult(tools=[tool()])]),
        observed_at=OBSERVED_AT,
    )
    if forgery == "provider":
        object.__setattr__(snapshot, "provider", "other-provider")
    elif forgery == "nested_description":
        object.__setattr__(
            snapshot.tools[0],
            "description",
            "Authorization: Bearer actual-secret-value",
        )
    else:
        object.__setattr__(snapshot.tools[0], "schema_sha256", "0" * 64)

    with pytest.raises(CapabilitySnapshotError) as captured:
        snapshot.as_json()

    rendered = "".join(traceback.format_exception(captured.value))
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_snapshot_as_json_revalidates_missing_exact_forged_fields() -> None:
    source = await capture_tools_snapshot(
        FakeToolsListSession([types.ListToolsResult(tools=[tool()])]),
        observed_at=OBSERVED_AT,
    )
    forged = object.__new__(ToolsListSnapshot)
    object.__setattr__(forged, "provider", source.provider)
    object.__setattr__(forged, "observed_at", source.observed_at)
    object.__setattr__(forged, "manifest", source.manifest)

    with pytest.raises(CapabilitySnapshotError) as captured:
        forged.as_json()

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "sensitive_text",
    (
        "clientsecret=tiny",
        "safe=clientsecret=tiny",
        "safe=" + "a." * 80 + ";clientsecret=tiny",
        "'clientsecret'='tiny'",
        "/clientsecret=tiny",
        "api~key=tiny",
        "safe%3D" + "a." * 80 + "%3Bclientsecret%3Dtiny",
    ),
)
def test_assignment_scanner_finds_direct_nested_padded_and_encoded_credentials(
    sensitive_text: str,
) -> None:
    assert text_contains_sensitive_material(sensitive_text)


def test_assignment_scanner_fails_closed_on_overlong_continuous_name_span() -> None:
    assert text_contains_sensitive_material("a" * 129 + "=ordinary")


def test_assignment_scanner_preserves_benign_long_prose() -> None:
    value = "ordinary public market description without assignments. " * 500

    assert not text_contains_sensitive_material(value)


@pytest.mark.asyncio
async def test_padded_assignment_is_rejected_from_property_description() -> None:
    sensitive_text = "safe=" + "a." * 80 + ";clientsecret=tiny"
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {
                                "safe": {"type": "string", "description": sensitive_text}
                            },
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


def test_fixture_loader_rejects_padded_assignment(tmp_path: Path) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["limitations"] = ["safe=" + "a." * 80 + ";clientsecret=tiny"]
    path = tmp_path / "padded-assignment.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_matrix_renderer_rejects_padded_assignment_from_forged_manifest() -> None:
    source = load_capability_manifest(FIXTURE).records[0]
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(source, field_name))
    object.__setattr__(
        forged_record,
        "limitations",
        ("safe=" + "a." * 80 + ";clientsecret=tiny",),
    )
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(InvalidCapabilityManifest):
        render_capability_matrix(forged_manifest)


@pytest.mark.parametrize("alias", SENSITIVE_ACCOUNT_AUTH_ALIASES)
@pytest.mark.asyncio
async def test_account_identifier_and_auth_code_alias_defaults_are_rejected(alias: str) -> None:
    default: object = 12345678 if alias == "acctnumber" else "tiny"
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "properties": {alias: {"type": "string", "default": default}},
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
    ("accountidentifier", "accountreferencevalues", "acctno", "authorizationcode", "mfacode"),
)
@pytest.mark.parametrize("carrier", ("assignment", "query", "path"))
def test_account_identifier_and_auth_code_aliases_cross_text_carriers(
    alias: str,
    carrier: str,
) -> None:
    value = {
        "assignment": f"{alias}=tiny",
        "query": f"https://robinhood.com/path?{alias}=tiny",
        "path": f"https://robinhood.com/{alias}/tiny",
    }[carrier]

    assert text_contains_sensitive_material(value)


@pytest.mark.parametrize("benign_name", BENIGN_ACCOUNT_AUTH_CONTROLS)
@pytest.mark.asyncio
async def test_account_auth_alias_grammar_preserves_reviewed_benign_names(
    benign_name: str,
) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {benign_name: {"type": "string", "default": "ordinary"}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].input_schema == input_schema
    assert not text_contains_sensitive_material(f"{benign_name}=ordinary")


@pytest.mark.parametrize("alias", ("accountidentifier", "acctreference", "authorizationcode"))
def test_fixture_loader_rejects_account_and_auth_aliases(
    tmp_path: Path,
    alias: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["limitations"] = [f"{alias}=tiny"]
    path = tmp_path / "account-auth-alias.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest):
        load_capability_manifest(path)


@pytest.mark.parametrize("alias", ("accountreference", "acctno", "oauthcode"))
def test_matrix_renderer_rejects_account_and_auth_aliases_from_forged_manifest(
    alias: str,
) -> None:
    source = load_capability_manifest(FIXTURE).records[0]
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(source, field_name))
    object.__setattr__(forged_record, "limitations", (f"{alias}=tiny",))
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(InvalidCapabilityManifest):
        render_capability_matrix(forged_manifest)


def test_bare_eight_digit_identifier_text_is_sensitive_but_public_controls_remain_safe() -> None:
    assert text_contains_sensitive_material("public identifier 12345678")
    assert not text_contains_sensitive_material(
        "checked on ISO date 2026-07-13 with public value 1234567"
    )


def test_matrix_renderer_rejects_bare_eight_digit_identifier_from_forged_manifest() -> None:
    source = load_capability_manifest(FIXTURE).records[0]
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(source, field_name))
    object.__setattr__(forged_record, "limitations", ("public identifier 12345678",))
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(InvalidCapabilityManifest):
        render_capability_matrix(forged_manifest)


@pytest.mark.parametrize("encoded_control", ("%00", "%1B", "%7F", "%E2%80%AE"))
def test_percent_decoded_controls_are_sensitive(encoded_control: str) -> None:
    assert text_contains_sensitive_material(f"ordinary{encoded_control}public")


@pytest.mark.parametrize("encoded_control", ("%00", "%1B", "%7F", "%E2%80%AE"))
@pytest.mark.asyncio
async def test_percent_decoded_controls_are_rejected_from_descriptions(
    encoded_control: str,
) -> None:
    session = FakeToolsListSession(
        [
            types.ListToolsResult(
                tools=[
                    tool(
                        input_schema={
                            "type": "object",
                            "description": f"ordinary{encoded_control}public",
                        }
                    )
                ]
            )
        ]
    )

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("encoded_control", ("%00", "%1B", "%7F", "%E2%80%AE"))
def test_fixture_and_matrix_reject_percent_decoded_controls(
    tmp_path: Path,
    encoded_control: str,
) -> None:
    unsafe_text = f"ordinary{encoded_control}public"
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["limitations"] = [unsafe_text]
    path = tmp_path / "encoded-control.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest):
        load_capability_manifest(path)

    source = load_capability_manifest(FIXTURE).records[0]
    forged_record = object.__new__(CapabilityRecord)
    for field_name in (
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "locked_reason",
    ):
        object.__setattr__(forged_record, field_name, getattr(source, field_name))
    object.__setattr__(forged_record, "limitations", (unsafe_text,))
    forged_manifest = object.__new__(CapabilityManifest)
    object.__setattr__(forged_manifest, "records", (forged_record,))

    with pytest.raises(InvalidCapabilityManifest):
        render_capability_matrix(forged_manifest)


@pytest.mark.asyncio
async def test_safe_percent_encoded_public_text_remains_supported() -> None:
    description = "ordinary%20public%20market%20metadata"
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(description=description)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].description == description


@pytest.mark.parametrize(
    "sensitive_text",
    (
        "api key=tiny",
        "private key : tiny",
        "account number = tiny",
        "authorization code\uff1atiny",
        "session reference\uff1dtiny",
        "api%20key%EF%BC%9Dtiny",
        "safe=ordinary; private%20key%EF%BC%9Atiny",
    ),
)
def test_assignment_scanner_rejects_spaced_names_and_wide_delimiters(
    sensitive_text: str,
) -> None:
    assert text_contains_sensitive_material(sensitive_text)


@pytest.mark.parametrize(
    "benign_text",
    (
        "public key = ordinary",
        "reference price: 12.34",
        "authorization status = pending",
        "accounting reference\uff1apublic",
        "session duration\uff1d30",
        "api version = v2",
    ),
)
def test_assignment_scanner_preserves_spaced_public_controls(benign_text: str) -> None:
    assert not text_contains_sensitive_material(benign_text)


@pytest.mark.asyncio
async def test_capture_rejects_spaced_assignment_from_schema_description() -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"safe": {"type": "string", "description": "account number = tiny"}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize("alias", ACCOUNT_ABBREVIATION_ALIASES)
@pytest.mark.asyncio
async def test_account_abbreviation_alias_defaults_are_rejected(alias: str) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {alias: {"type": "string", "default": "tiny"}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "sensitive_text",
    (
        "acctNum=tiny",
        "https://robinhood.com/path?accountNbr=tiny",
        "https://robinhood.com/path#acctRef=tiny",
        "https://robinhood.com/accountNbrData/tiny",
    ),
)
def test_account_abbreviation_aliases_cross_representative_text_carriers(
    sensitive_text: str,
) -> None:
    assert text_contains_sensitive_material(sensitive_text)


@pytest.mark.asyncio
async def test_account_abbreviation_grammar_preserves_benign_names() -> None:
    benign_names = (
        "accountingNumber",
        "accountingNbr",
        "accountingReference",
        "referencePrice",
        "accountNotification",
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {name: {"type": "string", "default": "ordinary"} for name in benign_names},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert snapshot.tools[0].input_schema == input_schema


@pytest.mark.parametrize("alias", SESSION_IDENTIFIER_ALIASES)
@pytest.mark.asyncio
async def test_session_identifier_alias_defaults_are_rejected(alias: str) -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {alias: {"type": "string", "default": "tiny"}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "sensitive_text",
    (
        "sessionIdentifier=tiny",
        "https://robinhood.com/path?sessionReference=tiny",
        "https://robinhood.com/path#sessionNumber=tiny",
        "https://robinhood.com/sessionUuid/tiny",
        "https://robinhood.com/path?sessionNoValue=tiny",
    ),
)
def test_session_identifier_grammar_crosses_representative_text_carriers(
    sensitive_text: str,
) -> None:
    assert text_contains_sensitive_material(sensitive_text)


@pytest.mark.parametrize(
    "sensitive_text",
    (
        STANDARD_BASE64_TEST_VALUE,
        STANDARD_BASE64_TEST_VALUE.rstrip("="),
        STANDARD_BASE64_TEST_VALUE.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D"),
    ),
)
def test_standard_base64_high_entropy_material_is_rejected_standalone(
    sensitive_text: str,
) -> None:
    assert text_contains_sensitive_material(sensitive_text)


@pytest.mark.parametrize(
    "benign_text",
    (
        "UHVibGlj",
        "C++ / public = format",
        "https://robinhood.com/us/en/support/articles/trading-with-your-agent/",
    ),
)
def test_standard_base64_scanner_preserves_public_controls(benign_text: str) -> None:
    assert not text_contains_sensitive_material(benign_text)


@pytest.mark.asyncio
async def test_capture_rejects_standalone_standard_base64_in_schema_text() -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"safe": {"type": "string", "description": STANDARD_BASE64_TEST_VALUE}},
    }
    session = FakeToolsListSession([types.ListToolsResult(tools=[tool(input_schema=input_schema)])])

    with pytest.raises(UnsafeCapabilitySnapshot):
        await capture_tools_snapshot(session, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "unsafe_text",
    ("sessionReferenceValues=tiny", STANDARD_BASE64_TEST_VALUE),
)
def test_fixture_loader_rejects_new_sensitive_text_boundaries(
    tmp_path: Path,
    unsafe_text: str,
) -> None:
    payload = fixture_payload()
    records = payload["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["limitations"] = [unsafe_text]
    path = tmp_path / "new-sensitive-boundary.json"
    write_fixture(path, payload)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        load_capability_manifest(path)

    assert str(captured.value) == "capability fixture is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "unsafe_text",
    ("sessionNos=tiny", STANDARD_BASE64_TEST_VALUE),
)
def test_matrix_renderer_rejects_new_sensitive_text_boundaries(unsafe_text: str) -> None:
    source = load_capability_manifest(FIXTURE).records[0]
    forged_manifest = forged_manifest_with_unsafe_freeform(
        source,
        field="limitations",
        value=unsafe_text,
    )

    with pytest.raises(InvalidCapabilityManifest) as captured:
        render_capability_matrix(forged_manifest)

    assert str(captured.value) == "capability manifest contains unsafe text"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def _pagination_pages(count: int, *, terminate: bool) -> list[types.ListToolsResult]:
    pages: list[types.ListToolsResult] = []
    for index in range(count):
        is_last = index == count - 1
        cursor = None if terminate and is_last else f"page-{index + 2}"
        pages.append(
            types.ListToolsResult(
                tools=[tool(f"public_tool_{index:02d}")],
                nextCursor=cursor,
            )
        )
    return pages


@pytest.mark.asyncio
async def test_capture_allows_exact_finite_page_limit() -> None:
    session = FakeToolsListSession(_pagination_pages(32, terminate=True))

    snapshot = await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert len(snapshot.tools) == 32
    assert len(session.list_tools_params) == 32


@pytest.mark.asyncio
async def test_capture_rejects_one_page_over_limit_without_extra_call_or_write(
    tmp_path: Path,
) -> None:
    session = FakeToolsListSession(_pagination_pages(33, terminate=True))
    output = tmp_path / "snapshot.json"

    with pytest.raises(CapabilitySnapshotError) as captured:
        await write_tools_snapshot(session, output, observed_at=OBSERVED_AT)

    assert str(captured.value) == "MCP tools/list pagination limit exceeded"
    assert len(session.list_tools_params) == 32
    assert session.call_tool_calls == []
    assert not output.exists()
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_unique_endless_cursors_fail_at_monkeypatched_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = EndlessCursorSession()
    monkeypatch.setattr(snapshot_module, "_MAX_TOOLS_LIST_PAGES", 3, raising=False)
    monkeypatch.setattr(
        snapshot_module,
        "_TOOLS_LIST_PAGE_TIMEOUT_SECONDS",
        0.05,
        raising=False,
    )

    with pytest.raises(CapabilitySnapshotError, match="pagination limit"):
        async with asyncio.timeout(0.1):
            await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert len(session.list_tools_params) == 3
    assert session.call_tool_calls == []


@pytest.mark.asyncio
async def test_hanging_tools_page_fails_with_generic_per_call_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = HangingToolsListSession()
    monkeypatch.setattr(
        snapshot_module,
        "_TOOLS_LIST_PAGE_TIMEOUT_SECONDS",
        0.0,
        raising=False,
    )

    with pytest.raises(CapabilitySnapshotError) as captured:
        async with asyncio.timeout(0.1):
            await capture_tools_snapshot(session, observed_at=OBSERVED_AT)

    assert str(captured.value) == "MCP tools/list failed safely"
    assert session.calls == 1
    assert session.cancelled
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_through_tools_page_timeout() -> None:
    session = HangingToolsListSession()
    task = asyncio.create_task(capture_tools_snapshot(session, observed_at=OBSERVED_AT))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert session.calls == 1
    assert session.cancelled
