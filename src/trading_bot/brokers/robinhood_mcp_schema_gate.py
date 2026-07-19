"""Canonical MCP tools/list compatibility gate."""

import hashlib
import json
from dataclasses import dataclass

type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def _canonical(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class DeclaredMcpTool:
    name: str
    description: str | None
    input_schema: JsonValue
    output_schema: JsonValue | None
    schema_sha256: str

    @classmethod
    def create(
        cls,
        name: str,
        description: str | None,
        input_schema: JsonValue,
        output_schema: JsonValue | None,
    ) -> "DeclaredMcpTool":
        digest = hashlib.sha256(
            _canonical({"input": input_schema, "output": output_schema}).encode()
        ).hexdigest()
        return cls(name, description, input_schema, output_schema, digest)


@dataclass(frozen=True, slots=True)
class SchemaDrift:
    tool_name: str
    code: str
    expected_hash: str | None
    observed_hash: str | None


@dataclass(frozen=True, slots=True)
class SchemaDriftReport:
    live_ready: bool
    incompatible: bool
    drifts: tuple[SchemaDrift, ...]


def compare_mcp_schema(
    observed: tuple[DeclaredMcpTool, ...], expected: tuple[DeclaredMcpTool, ...]
) -> SchemaDriftReport:
    observed_map = {tool.name: tool for tool in observed}
    drifts = []
    for required in expected:
        actual = observed_map.get(required.name)
        if actual is None:
            drifts.append(
                SchemaDrift(required.name, "required_tool_missing", required.schema_sha256, None)
            )
        elif actual.schema_sha256 != required.schema_sha256:
            drifts.append(
                SchemaDrift(
                    required.name,
                    "incompatible_schema",
                    required.schema_sha256,
                    actual.schema_sha256,
                )
            )
    incompatible = bool(drifts)
    return SchemaDriftReport(not incompatible, incompatible, tuple(drifts))


__all__ = ["DeclaredMcpTool", "JsonValue", "SchemaDrift", "SchemaDriftReport", "compare_mcp_schema"]
