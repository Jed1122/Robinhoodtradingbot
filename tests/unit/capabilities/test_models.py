"""Fail-closed tests for immutable capability evidence records."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

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
