"""Fail-closed tests for immutable capability evidence records."""

import traceback
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from trading_bot.capabilities import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    EvidenceLevel,
    InvalidCapabilityEvidence,
    InvalidCapabilityManifest,
    InvalidCapabilityRecord,
    OperationKind,
)
from trading_bot.domain import AssetClass

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
DIGEST = "a" * 64
AUTHENTICATED_LEVELS = frozenset(
    {
        EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
        EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED,
    }
)
DIGEST_LEVELS = frozenset(
    {
        EvidenceLevel.SCHEMA_DECLARED,
        EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
        EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED,
    }
)


class HostileTimezone(tzinfo):
    """Exact-datetime timezone whose offset lookup carries sensitive text."""

    def __init__(self, error_type: type[Exception]) -> None:
        self._error_type = error_type

    def utcoffset(self, value: datetime | None) -> timedelta | None:
        raise self._error_type("Authorization: Bearer actual-secret-value")

    def dst(self, value: datetime | None) -> timedelta | None:
        return None

    def tzname(self, value: datetime | None) -> str | None:
        return "HOSTILE"


class DatetimeSubclass(datetime):
    """Semantically UTC but not an exact built-in datetime."""


class ArmedString(str):
    """String subclass that exposes sensitive text if string methods run."""

    def strip(self, chars: str | None = None) -> str:
        raise RuntimeError("Authorization: Bearer actual-secret-value")


class ArmedCapabilityEvidence(CapabilityEvidence):
    """Evidence subclass that explodes only after construction is complete."""

    armed = False

    def __getattribute__(self, name: str) -> object:
        if name == "level" and object.__getattribute__(self, "armed"):
            raise RuntimeError("Authorization: Bearer actual-secret-value")
        return super().__getattribute__(name)


class ArmedCapabilityRecord(CapabilityRecord):
    """Record subclass that explodes only after construction is complete."""

    armed = False

    def __getattribute__(self, name: str) -> object:
        if name in {"provider", "operation"} and object.__getattribute__(self, "armed"):
            raise RuntimeError("Authorization: Bearer actual-secret-value")
        return super().__getattribute__(name)


def evidence_for(level: EvidenceLevel = EvidenceLevel.DOCUMENTED) -> CapabilityEvidence:
    return CapabilityEvidence(
        level=level,
        source_uri="https://robinhood.com/support/articles/official-interface",
        observed_at=NOW,
        schema_sha256=DIGEST if level in DIGEST_LEVELS else None,
        authenticated=level in AUTHENTICATED_LEVELS,
        contains_account_data=False,
        notes=("sanitized committed evidence",),
    )


def record_for(
    level: EvidenceLevel = EvidenceLevel.DOCUMENTED,
    *,
    provider: str = "robinhood-trading",
    operation: str = "get_quote",
    asset_class: AssetClass = AssetClass.EQUITY,
    operation_kind: OperationKind = OperationKind.READ,
    locked_reason: str | None = None,
) -> CapabilityRecord:
    if level is EvidenceLevel.UNSUPPORTED and locked_reason is None:
        locked_reason = "official operation is unsupported"
    return CapabilityRecord(
        provider=provider,
        operation=operation,
        asset_class=asset_class,
        operation_kind=operation_kind,
        evidence=(evidence_for(level),),
        limitations=("evidence is limited to the recorded category",),
        locked_reason=locked_reason,
    )


def forged_evidence(
    **changes: object,
) -> CapabilityEvidence:
    """Build an exact evidence object without executing validation."""
    source = evidence_for(EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED)
    forged = object.__new__(CapabilityEvidence)
    values: dict[str, object] = {
        "level": source.level,
        "source_uri": source.source_uri,
        "observed_at": source.observed_at,
        "schema_sha256": source.schema_sha256,
        "authenticated": source.authenticated,
        "contains_account_data": source.contains_account_data,
        "notes": source.notes,
    }
    values.update(changes)
    for field_name, field_value in values.items():
        object.__setattr__(forged, field_name, field_value)
    return forged


def forged_record(
    source: CapabilityRecord | None = None,
    **changes: object,
) -> CapabilityRecord:
    """Build an exact record object without executing validation."""
    source = source or record_for()
    forged = object.__new__(CapabilityRecord)
    values: dict[str, object] = {
        "provider": source.provider,
        "operation": source.operation,
        "asset_class": source.asset_class,
        "operation_kind": source.operation_kind,
        "evidence": source.evidence,
        "limitations": source.limitations,
        "locked_reason": source.locked_reason,
    }
    values.update(changes)
    for field_name, field_value in values.items():
        object.__setattr__(forged, field_name, field_value)
    return forged


def test_enumerations_expose_only_reviewed_categories() -> None:
    assert {item.value for item in EvidenceLevel} == {
        "documented",
        "schema-declared",
        "authenticated-read-verified",
        "authenticated-write-reviewed",
        "unsupported",
    }
    assert {item.value for item in OperationKind} == {
        "discover",
        "read",
        "review",
        "place",
        "cancel",
    }
    with pytest.raises(ValueError):
        OperationKind("unknown")


def test_capability_records_are_frozen_and_slotted() -> None:
    evidence = evidence_for()
    record = record_for()
    manifest = CapabilityManifest(records=(record,))

    with pytest.raises(FrozenInstanceError):
        evidence.authenticated = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.operation = "place_order"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        manifest.records = ()  # type: ignore[misc]
    assert not hasattr(evidence, "__dict__")


def test_record_and_manifest_store_deeply_revalidated_model_copies() -> None:
    evidence = evidence_for()
    record = record_for()

    rebuilt_record = replace(record, evidence=(evidence,))
    manifest = CapabilityManifest(records=(rebuilt_record,))

    assert rebuilt_record.evidence == (evidence,)
    assert rebuilt_record.evidence[0] is not evidence
    assert manifest.records == (rebuilt_record,)
    assert manifest.records[0] is not rebuilt_record
    assert manifest.records[0].evidence[0] is not rebuilt_record.evidence[0]


@pytest.mark.parametrize("level", tuple(AUTHENTICATED_LEVELS))
def test_authenticated_evidence_requires_authenticated_true(level: EvidenceLevel) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="authenticated"):
        replace(evidence_for(level), authenticated=False)


@pytest.mark.parametrize(
    "level",
    (
        EvidenceLevel.DOCUMENTED,
        EvidenceLevel.SCHEMA_DECLARED,
        EvidenceLevel.UNSUPPORTED,
    ),
)
def test_non_authenticated_categories_reject_authenticated_true(level: EvidenceLevel) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="unauthenticated"):
        replace(evidence_for(level), authenticated=True)


def test_committed_evidence_rejects_account_data() -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="account data"):
        replace(evidence_for(), contains_account_data=True)


@pytest.mark.parametrize(
    "observed_at",
    (
        datetime(2026, 7, 12, 12),
        datetime(2026, 7, 12, 12, tzinfo=timezone(timedelta(hours=1))),
    ),
)
def test_evidence_rejects_non_utc_or_naive_timestamps(observed_at: datetime) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="UTC"):
        replace(evidence_for(), observed_at=observed_at)


@pytest.mark.parametrize("error_type", (ValueError, RuntimeError))
def test_evidence_rejects_hostile_exact_datetime_without_leaking_external_error(
    error_type: type[Exception],
) -> None:
    observed_at = datetime(2026, 7, 12, 12, tzinfo=HostileTimezone(error_type))

    with pytest.raises(InvalidCapabilityEvidence) as captured:
        replace(evidence_for(), observed_at=observed_at)

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "observed_at must be aware UTC"
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_evidence_rejects_datetime_subclass_before_overridable_method_access() -> None:
    observed_at = DatetimeSubclass(2026, 7, 12, 12, tzinfo=UTC)

    with pytest.raises(InvalidCapabilityEvidence) as captured:
        replace(evidence_for(), observed_at=observed_at)

    assert str(captured.value) == "observed_at must be aware UTC"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_evidence_stores_exact_zero_offset_datetime_in_canonical_utc() -> None:
    zero_offset = datetime(
        2026,
        7,
        12,
        12,
        tzinfo=timezone(timedelta(0), name="ZERO"),
    )

    evidence = replace(evidence_for(), observed_at=zero_offset)

    assert evidence.observed_at.tzinfo is UTC


@pytest.mark.parametrize("level", tuple(DIGEST_LEVELS))
def test_schema_and_authenticated_evidence_require_digest(level: EvidenceLevel) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="schema_sha256"):
        replace(evidence_for(level), schema_sha256=None)


@pytest.mark.parametrize(
    "digest",
    ("A" * 64, "a" * 63, "g" * 64, "sha256:" + "a" * 64),
)
def test_any_supplied_digest_must_be_lowercase_sha256(digest: str) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="schema_sha256"):
        replace(evidence_for(), schema_sha256=digest)


@pytest.mark.parametrize(
    "source_uri",
    (
        "https://operator:password@robinhood.com/support",
        "https://robinhood.com/support?access_token=actual-secret-value",
        "https://robinhood.com/support?x-api-key=actual-secret-value",
        "https://robinhood.com/support?account_number=RHC123456789",
        "https://robinhood.com/support?q=Bearer%20actual-secret-value",
        (
            "https://robinhood.com/support?session="
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhY2NvdW50In0.signaturevalue"
        ),
        "https://robinhood.com/support?session=sk-testtokenvalue1234",
        "https://robinhood.com/support?session=RHC123456789",
        "https://robinhood.com/support?sig=actual-secret-value",
        "https://robinhood.com/support?signatures=actual-secret-value",
        "https://robinhood.com/support?account=actual-secret-value",
        "https://robinhood.com/support?%2573ig=actual-secret-value",
        "https://robinhood.com/support?%2561ccount=actual-secret-value",
        "https://robinhood.com/support?accountUuid=00000000-0000-4000-8000-000000000000",
        "https://robinhood.com/support?accountUrl=00000000-0000-4000-8000-000000000000",
        "https://robinhood.com/support?acct_id=00000000-0000-4000-8000-000000000000",
        "https://robinhood.com/support?sessionId=synthetic-session",
        "https://robinhood.com/support?sa%00fe=metadata",
        "https://robinhood.com/support?sa%01fe=metadata",
        "https://robinhood.com/support?safe%7F=metadata",
        "https://robinhood.com/support#access_token=fake-oauth-token",
        "https://robinhood.com/account=00000000-0000-4000-8000-000000000000",
        "https://robinhood.com/support#account_uuid=00000000-0000-4000-8000-000000000000",
        "https://robinhood.com/safe path",
        "https://robinhood.com/access_token%25253Dactual-secret-value",
        "https://robinhood.com/support#access_token%25253Dactual-secret-value",
        "https://sk-testtokenvalue1234.robinhood.com/support",
        "https://RHC123456789.robinhood.com/support",
        "https://robin hood.com/support",
        "https://robinhood..com/support",
        "https://-robinhood.com/support",
        "https://%20robinhood.com/support",
        "https://robinhood.com/support%ZZ",
        "https://robinhood.com/support%00",
        "https://evil.com/official",
        "https://localhost/support",
        "https://127.0.0.1/support",
        "https://robinhood.com:8443/support",
        "https://robinhood.com:/support",
        "mcp://evil/tools/get_equity_quotes",
        "mcp://robinhood-trading:443/tools/get_equity_quotes",
        "https://ROBINHOOD.com/support",
        "https://robinhood.com/accounts/00000000-0000-4000-8000-000000000000",
        "mcp://robinhood-trading/accounts/00000000-0000-4000-8000-000000000000",
        "https://robinhood.com/account-123456789",
        "https://robinhood.com/support/order123456789",
        "https://robinhood.com/support/xRHC123456789",
        "https://robinhood.com/support/x00000000-0000-4000-8000-000000000000y",
        "https://robinhood.com/support/xsk-testtokenvalue1234y",
        "data:text/plain,Bearer%20fake-token",
        "http://robinhood.com/support",
        "https://robinhood.com:not-a-port/support",
        " https://robinhood.com/support",
        "not-a-uri",
    ),
)
def test_source_uri_rejects_credentials_sensitive_queries_and_malformed_values(
    source_uri: str,
) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="source_uri"):
        replace(evidence_for(), source_uri=source_uri)


@pytest.mark.parametrize(
    "source_uri",
    (
        "https://robinhood.com/support?section=tools&page=2",
        "https://robinhood.com/support#tools",
        "https://robinhood.com/support?",
        "https://robinhood.com/support#",
        "https://robinhood.com/support?#",
    ),
)
def test_source_uri_rejects_query_and_fragment_metadata(source_uri: str) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="source_uri"):
        replace(evidence_for(), source_uri=source_uri)


@pytest.mark.parametrize(
    "source_uri",
    (
        "https://robinhood.com/us/en/support/articles/agentic-trading-overview/",
        "https://robinhood.com/us/en/support/articles/trading-with-your-agent/",
        "https://docs.robinhood.com/crypto/trading/",
    ),
)
def test_source_uri_allows_canonical_official_https_sources(source_uri: str) -> None:
    evidence = replace(evidence_for(), source_uri=source_uri)

    assert evidence.source_uri == source_uri


def test_source_uri_allows_sanitized_mcp_schema_reference() -> None:
    evidence = replace(
        evidence_for(EvidenceLevel.SCHEMA_DECLARED),
        source_uri="mcp://robinhood-trading/tools/get_equity_quotes",
    )

    assert evidence.source_uri == "mcp://robinhood-trading/tools/get_equity_quotes"


@pytest.mark.parametrize(
    "source_uri",
    (
        "https://[actual-secret-value",
        "https://robinhood.com:actual-secret-value/support",
    ),
)
def test_malformed_source_uri_does_not_chain_parser_input(source_uri: str) -> None:
    with pytest.raises(InvalidCapabilityEvidence) as captured:
        replace(evidence_for(), source_uri=source_uri)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("notes", ([], {"note"}, iter(("note",))))
def test_evidence_requires_exact_immutable_note_tuple(notes: object) -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="immutable tuple"):
        replace(evidence_for(), notes=notes)  # type: ignore[arg-type]


def test_evidence_rejects_empty_note_and_coercive_scalar_types() -> None:
    with pytest.raises(InvalidCapabilityEvidence, match="notes"):
        replace(evidence_for(), notes=(" ",))
    with pytest.raises(InvalidCapabilityEvidence, match="EvidenceLevel"):
        replace(evidence_for(), level="documented")  # type: ignore[arg-type]
    with pytest.raises(InvalidCapabilityEvidence, match="boolean"):
        replace(evidence_for(), authenticated=1)  # type: ignore[arg-type]
    with pytest.raises(InvalidCapabilityEvidence, match="boolean"):
        replace(evidence_for(), contains_account_data=0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        (
            "source_uri",
            ArmedString("https://robinhood.com/support/articles/official-interface"),
        ),
        ("schema_sha256", ArmedString(DIGEST)),
        ("notes", (ArmedString("sanitized committed evidence"),)),
    ),
)
def test_evidence_requires_exact_builtin_strings_without_subclass_method_access(
    field: str,
    value: object,
) -> None:
    with pytest.raises(InvalidCapabilityEvidence) as captured:
        replace(evidence_for(), **{field: value})  # type: ignore[arg-type]

    rendered = "".join(traceback.format_exception(captured.value))
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("evidence", ([], {"value"}, iter(())))
def test_record_requires_exact_immutable_evidence_tuple(evidence: object) -> None:
    with pytest.raises(InvalidCapabilityRecord, match="immutable tuple"):
        replace(record_for(), evidence=evidence)  # type: ignore[arg-type]


@pytest.mark.parametrize("limitations", ([], {"value"}, iter(())))
def test_record_requires_exact_immutable_limitations_tuple(limitations: object) -> None:
    with pytest.raises(InvalidCapabilityRecord, match="immutable tuple"):
        replace(record_for(), limitations=limitations)  # type: ignore[arg-type]


def test_record_rejects_empty_evidence_and_mixed_support_states() -> None:
    with pytest.raises(InvalidCapabilityRecord, match="at least one"):
        replace(record_for(), evidence=())

    mixed = (evidence_for(EvidenceLevel.DOCUMENTED), evidence_for(EvidenceLevel.UNSUPPORTED))
    with pytest.raises(InvalidCapabilityRecord, match="mix"):
        replace(record_for(), evidence=mixed, locked_reason="unsupported")


def test_unsupported_record_requires_nonempty_locked_reason() -> None:
    unsupported = record_for(EvidenceLevel.UNSUPPORTED)

    with pytest.raises(InvalidCapabilityRecord, match="locked_reason"):
        replace(unsupported, locked_reason=None)
    with pytest.raises(InvalidCapabilityRecord, match="locked_reason"):
        replace(unsupported, locked_reason=" ")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", " "),
        ("operation", ""),
        ("limitations", ("",)),
        ("locked_reason", " "),
    ),
)
def test_record_rejects_empty_strings(field: str, value: object) -> None:
    with pytest.raises(InvalidCapabilityRecord):
        replace(record_for(), **{field: value})  # type: ignore[arg-type]


def test_record_rejects_coercive_enum_inputs_and_non_evidence_members() -> None:
    with pytest.raises(InvalidCapabilityRecord, match="AssetClass"):
        replace(record_for(), asset_class="equity")  # type: ignore[arg-type]
    with pytest.raises(InvalidCapabilityRecord, match="OperationKind"):
        replace(record_for(), operation_kind="read")  # type: ignore[arg-type]
    with pytest.raises(InvalidCapabilityRecord, match="CapabilityEvidence"):
        replace(record_for(), evidence=("documented",))  # type: ignore[arg-type]


def test_record_rejects_capability_evidence_subclass_before_field_access() -> None:
    evidence = ArmedCapabilityEvidence(
        level=EvidenceLevel.DOCUMENTED,
        source_uri="https://robinhood.com/support/articles/official-interface",
        observed_at=NOW,
        schema_sha256=None,
        authenticated=False,
        contains_account_data=False,
        notes=("sanitized committed evidence",),
    )
    object.__setattr__(evidence, "armed", True)

    with pytest.raises(InvalidCapabilityRecord) as captured:
        replace(record_for(), evidence=(evidence,))

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "evidence must contain CapabilityEvidence records"
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "changes",
    (
        {"authenticated": False},
        {"contains_account_data": True},
        {"source_uri": "Authorization: Bearer actual-secret-value"},
        {"observed_at": datetime(2026, 7, 12, 12)},
        {"notes": ("ordinary\x00text",)},
    ),
)
def test_record_revalidates_forged_exact_evidence_before_storage(
    changes: dict[str, object],
) -> None:
    forged = forged_evidence(**changes)

    with pytest.raises(InvalidCapabilityRecord) as captured:
        replace(
            record_for(EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED),
            evidence=(forged,),
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "evidence contains an invalid CapabilityEvidence value"
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_manifest_revalidates_forged_exact_record_and_nested_evidence() -> None:
    unsafe_evidence = forged_evidence(contains_account_data=True)
    unsafe_record = forged_record(
        record_for(EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED),
        evidence=(unsafe_evidence,),
    )

    with pytest.raises(InvalidCapabilityManifest) as captured:
        CapabilityManifest(records=(unsafe_record,))

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "records contain an invalid CapabilityRecord value"
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_manifest_rejects_capability_record_subclass_before_key_access() -> None:
    base = record_for()
    record = ArmedCapabilityRecord(
        provider=base.provider,
        operation=base.operation,
        asset_class=base.asset_class,
        operation_kind=base.operation_kind,
        evidence=base.evidence,
        limitations=base.limitations,
        locked_reason=base.locked_reason,
    )
    object.__setattr__(record, "armed", True)

    with pytest.raises(InvalidCapabilityManifest) as captured:
        CapabilityManifest(records=(record,))

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "records must contain CapabilityRecord values"
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "unsafe_text", ("ordinary\x00text", "ordinary\x1btext", "ordinary\u202etext")
)
@pytest.mark.parametrize("field", ("limitations", "locked_reason"))
def test_record_rejects_control_and_bidi_freeform_text(
    field: str,
    unsafe_text: str,
) -> None:
    value: object = (unsafe_text,) if field == "limitations" else unsafe_text

    with pytest.raises(InvalidCapabilityRecord):
        replace(record_for(), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "unsafe_text", ("ordinary\x00text", "ordinary\x1btext", "ordinary\u202etext")
)
def test_evidence_rejects_control_and_bidi_note_text(unsafe_text: str) -> None:
    with pytest.raises(InvalidCapabilityEvidence):
        replace(evidence_for(), notes=(unsafe_text,))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", ArmedString("robinhood-trading")),
        ("operation", ArmedString("get_quote")),
        ("limitations", (ArmedString("evidence is limited to the recorded category"),)),
        ("locked_reason", ArmedString("operation remains locked")),
    ),
)
def test_record_requires_exact_builtin_strings_without_subclass_method_access(
    field: str,
    value: object,
) -> None:
    with pytest.raises(InvalidCapabilityRecord) as captured:
        replace(record_for(), **{field: value})  # type: ignore[arg-type]

    rendered = "".join(traceback.format_exception(captured.value))
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("available", tuple(EvidenceLevel))
@pytest.mark.parametrize("required", tuple(EvidenceLevel))
def test_evidence_satisfaction_is_exact_categorical_membership(
    available: EvidenceLevel,
    required: EvidenceLevel,
) -> None:
    record = record_for(available)

    assert record.satisfies(required) is (available is required)


def test_each_positive_category_must_be_recorded_independently() -> None:
    record = replace(
        record_for(),
        evidence=(
            evidence_for(EvidenceLevel.DOCUMENTED),
            evidence_for(EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED),
        ),
    )

    assert record.satisfies(EvidenceLevel.DOCUMENTED)
    assert record.satisfies(EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED)
    assert not record.satisfies(EvidenceLevel.SCHEMA_DECLARED)
    assert not record.satisfies(EvidenceLevel.AUTHENTICATED_READ_VERIFIED)
    assert not record.satisfies(EvidenceLevel.UNSUPPORTED)


def test_locked_positive_evidence_does_not_unlock_capability() -> None:
    locked = record_for(locked_reason="operation name has not been safely classified")

    assert not locked.satisfies(EvidenceLevel.DOCUMENTED)


@pytest.mark.parametrize(
    "level",
    tuple(level for level in EvidenceLevel if level is not EvidenceLevel.UNSUPPORTED),
)
def test_manifest_rejects_positive_prediction_placement(level: EvidenceLevel) -> None:
    record = record_for(
        level,
        operation="place_prediction_order",
        asset_class=AssetClass.PREDICTION,
        operation_kind=OperationKind.PLACE,
        locked_reason="prediction execution remains locked",
    )

    with pytest.raises(InvalidCapabilityManifest, match="prediction"):
        CapabilityManifest(records=(record,))


def test_manifest_allows_explicitly_unsupported_prediction_placement() -> None:
    record = record_for(
        EvidenceLevel.UNSUPPORTED,
        operation="place_prediction_order",
        asset_class=AssetClass.PREDICTION,
        operation_kind=OperationKind.PLACE,
    )

    manifest = CapabilityManifest(records=(record,))

    assert manifest.records == (record,)
    assert record.satisfies(EvidenceLevel.UNSUPPORTED)
