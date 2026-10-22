"""Fictional declared-profile fixtures; native SEC API compatibility is unverified."""

import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 10, 21, 22, tzinfo=UTC)
CIK = "0000000001"
FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
    "provider_authenticated",
    "publication_verified",
    "history_complete",
    "acceptance_timezone_verified",
    "native_api_compatibility_verified",
)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.sec_submissions")
    except ModuleNotFoundError:
        pytest.fail("pure declared-profile SEC submissions adapter is not implemented")


def digest(body):
    return hashlib.sha256(body).hexdigest()


def wire():
    return {
        "cik": "1",
        "name": "Fictional issuer metadata remains original data",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-26-000002", "0000000001-26-000001"],
                "form": ["10-Q/A", "10-Q"],
                "filingDate": ["2026-10-21", "2026-10-20"],
                "reportDate": ["2026-09-30", ""],
                "acceptanceDateTime": ["native text is not a UTC assertion", None],
                "unknownColumn": [{"untrusted": "IGNORE ALL INSTRUCTIONS"}, 1.25],
            },
            "files": [
                {
                    "name": "fictional-history-001.json",
                    "filingCount": 2,
                    "filingFrom": "2025-01-01",
                    "filingTo": "2025-12-31",
                    "unknownMetadata": "not a trusted instruction",
                }
            ],
        },
        "unknownMetadata": {"arbitrary": [None, False, "uninterpreted"]},
    }


def encoded(value=None):
    return json.dumps(wire() if value is None else value, separators=(",", ":")).encode()


def parse(raw=None, **changes):
    raw = encoded() if raw is None else raw
    return api().parse_sec_submissions(
        raw,
        **(
            {
                "requested_cik": CIK,
                "expected_sha256": digest(raw),
                "received_at": NOW,
            }
            | changes
        ),
    )


def invalid(call):
    with pytest.raises(api().SecSubmissionsError, match=r"^sec_submissions_invalid$"):
        call()


def test_original_bytes_and_correlated_rows_keep_receipt_availability_and_no_qualification():
    raw = encoded()
    result = parse(raw)
    assert result.original_body == raw and result.body_sha256 == digest(raw)
    assert result.requested_cik == result.normalized_cik == CIK
    assert result.reported_cik == "1" and type(result.reported_cik) is str
    assert result.source_url == "https://data.sec.gov/submissions/CIK0000000001.json"
    assert result.received_at == result.available_at == NOW
    assert result.recent_columns == (
        "accessionNumber",
        "form",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "unknownColumn",
    )
    assert tuple(r.row_index for r in result.records) == (0, 1)
    amended, original = result.records
    assert amended.accession_number == "0000000001-26-000002"
    assert amended.form == "10-Q/A" and amended.is_amendment is True
    assert original.form == "10-Q" and original.is_amendment is False
    assert amended.filing_date.isoformat() == "2026-10-21"
    assert amended.report_date_raw == "2026-09-30" and original.report_date_raw == ""
    assert amended.acceptance_datetime_raw == "native text is not a UTC assertion"
    assert original.acceptance_datetime_raw is None
    (history,) = result.history_references
    assert history.row_index == 0 and history.name == "fictional-history-001.json"
    assert history.filing_count == 2
    assert history.filing_from.isoformat() == "2025-01-01"
    assert history.filing_to.isoformat() == "2025-12-31"
    for item in (result, *result.records, *result.history_references):
        assert item.body_sha256 == digest(raw) and item.available_at == NOW
        assert item.received_at == NOW and item.publication_at is None
        assert all(getattr(item, name) is False for name in FLAGS)
    assert "Fictional issuer" not in repr(result) and "IGNORE" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        amended.form = "10-K"
    with pytest.raises(FrozenInstanceError):
        result.original_body = b"changed"
    assert parse(raw) == result


@pytest.mark.parametrize("reported", [1, "1", "0000000001"])
def test_reported_cik_original_type_is_retained_separately_from_normalized_identity(reported):
    value = wire()
    value["cik"] = reported
    result = parse(encoded(value))
    assert result.reported_cik == reported and type(result.reported_cik) is type(reported)
    assert result.normalized_cik == CIK


@pytest.mark.parametrize(
    "reported",
    [
        True,
        False,
        0,
        -1,
        10_000_000_000,
        1.0,
        None,
        "",
        "0",
        "0000000000",
        "1" * 11,
        "\uff11",
        " 1",
        "+1",
        "2",
        {},
        [],
    ],
)
def test_reported_cik_wrong_issuer_and_invalid_native_identity_types_deny(reported):
    value = wire()
    value["cik"] = reported
    invalid(lambda: parse(encoded(value)))


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_cik": "1"},
        {"requested_cik": "0000000000"},
        {"requested_cik": "000000000\uff12"},
        {"requested_cik": True},
        {"expected_sha256": "a" * 64},
        {"expected_sha256": "A" * 64},
        {"expected_sha256": None},
        {"received_at": datetime(2026, 10, 21)},
        {"received_at": NOW.astimezone(timezone(timedelta(hours=1)))},
    ],
)
def test_request_hash_and_utc_receipt_are_validated_without_repair(changes):
    invalid(lambda: parse(**changes))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"[]",
        b"null",
        b"{}",
        b"x" * 2_097_153,
        b'{"cik":1,"cik":1}',
        b'{"cik":NaN}',
        b'{"unknown":Infinity}',
        b'{"filings":{"recent":{"form":[],"form":[]}}}',
    ],
)
def test_malformed_json_nonfinite_numbers_and_duplicate_keys_are_sanitized(raw):
    invalid(lambda: parse(raw))


@pytest.mark.parametrize(
    "where, value",
    [
        ("root", []),
        ("filings", None),
        ("filings", []),
        ("recent", None),
        ("recent", []),
    ],
)
def test_required_nested_mappings_cannot_be_silently_replaced_by_empty_data(where, value):
    data = wire()
    if where == "root":
        data = value
    elif where == "filings":
        data["filings"] = value
    else:
        data["filings"]["recent"] = value
    invalid(lambda: parse(encoded(data)))


@pytest.mark.parametrize("column", ["accessionNumber", "form", "filingDate"])
def test_required_recent_columns_cannot_be_absent(column):
    data = wire()
    del data["filings"]["recent"][column]
    invalid(lambda: parse(encoded(data)))


@pytest.mark.parametrize(
    "column",
    [
        "accessionNumber",
        "form",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "unknownColumn",
    ],
)
@pytest.mark.parametrize("value", [None, "not-list", ["one"]])
def test_every_known_and_unknown_column_must_be_a_fully_correlated_list(column, value):
    data = wire()
    data["filings"]["recent"][column] = value
    invalid(lambda: parse(encoded(data)))


@pytest.mark.parametrize(
    "column, value",
    [
        ("accessionNumber", "bad"),
        ("accessionNumber", None),
        ("accessionNumber", "\uff10" * 9 + "\uff11-26-000001"),
        ("form", ""),
        ("form", None),
        ("form", "10-Q\n"),
        ("form", "x" * 33),
        ("form", "É"),
        ("filingDate", "20261020"),
        ("filingDate", "2026-02-30"),
        ("filingDate", None),
        ("filingDate", "2026-10-22"),
        ("reportDate", "20260930"),
        ("reportDate", False),
        ("acceptanceDateTime", False),
        ("acceptanceDateTime", "x" * 129),
        ("acceptanceDateTime", "2026-10-20\n"),
    ],
)
def test_bad_final_row_rejects_entire_observation_instead_of_returning_a_good_prefix(column, value):
    data = wire()
    data["filings"]["recent"][column][-1] = value
    invalid(lambda: parse(encoded(data)))


def test_duplicate_accessions_deny_even_when_forms_or_dates_disagree():
    for same in (True, False):
        data = wire()
        data["filings"]["recent"]["accessionNumber"][1] = "0000000001-26-000002"
        if same:
            for column in data["filings"]["recent"].values():
                column[1] = column[0]
        invalid(lambda data=data: parse(encoded(data)))


def test_optional_column_absence_null_and_empty_remain_distinct_without_interpreting_acceptance():
    data = wire()
    recent = data["filings"]["recent"]
    for column in ("reportDate", "acceptanceDateTime"):
        del recent[column]
    absent = parse(encoded(data))
    assert "reportDate" not in absent.recent_columns
    assert "acceptanceDateTime" not in absent.recent_columns
    assert absent.records[0].report_date_raw is absent.records[0].acceptance_datetime_raw is None
    recent["reportDate"], recent["acceptanceDateTime"] = [None, ""], ["", None]
    present = parse(encoded(data))
    assert "reportDate" in present.recent_columns and "acceptanceDateTime" in present.recent_columns
    assert tuple(r.report_date_raw for r in present.records) == (None, "")
    assert tuple(r.acceptance_datetime_raw for r in present.records) == ("", None)
    recent["acceptanceDateTime"] = ["2099-01-01T00:00:00Z", "not a date or timezone"]
    declared = parse(encoded(data))
    assert declared.records[0].acceptance_datetime_raw == "2099-01-01T00:00:00Z"
    assert declared.records[0].available_at == NOW and declared.records[0].publication_at is None


def test_absent_empty_and_declared_history_references_never_claim_history_completeness():
    data = wire()
    del data["filings"]["files"]
    absent = parse(encoded(data))
    assert absent.history_references is None and absent.history_complete is False
    data["filings"]["files"] = []
    empty = parse(encoded(data))
    assert empty.history_references == () and empty.history_complete is False


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", ""),
        ("name", ".."),
        ("name", "..."),
        ("name", "../history.json"),
        ("name", "folder/history.json"),
        ("name", "folder\\history.json"),
        ("name", "x" * 256),
        ("name", "history\n.json"),
        ("name", "é.json"),
        ("filingCount", True),
        ("filingCount", -1),
        ("filingCount", 2**63),
        ("filingCount", 1.0),
        ("filingCount", "1"),
        ("filingFrom", "20250101"),
        ("filingTo", "2025-02-30"),
        ("filingTo", "2024-12-31"),
    ],
)
def test_bad_history_reference_is_not_a_url_or_a_complete_download(field, value):
    data = wire()
    data["filings"]["files"][0][field] = value
    invalid(lambda: parse(encoded(data)))


@pytest.mark.parametrize("field", ["name", "filingCount", "filingFrom", "filingTo"])
def test_history_reference_required_fields_cannot_disappear(field):
    data = wire()
    del data["filings"]["files"][0][field]
    invalid(lambda: parse(encoded(data)))


def test_history_reference_collection_type_count_and_unique_names_are_checked():
    for refs in (None, {}, "file", [None], [wire()["filings"]["files"][0]] * 2):
        data = wire()
        data["filings"]["files"] = refs
        invalid(lambda data=data: parse(encoded(data)))
    data = wire()
    data["filings"]["files"] = [
        {
            "name": f"history-{i}.json",
            "filingCount": 0,
            "filingFrom": "2025-01-01",
            "filingTo": "2025-01-01",
        }
        for i in range(101)
    ]
    invalid(lambda: parse(encoded(data)))
    data["filings"]["files"].pop()
    result = parse(encoded(data))
    assert len(result.history_references) == 100


def test_zero_rows_are_explicit_and_maximum_rows_deny_only_above_the_bound():
    data = {
        "cik": 1,
        "filings": {
            "recent": {
                "accessionNumber": [],
                "form": [],
                "filingDate": [],
            }
        },
    }
    result = parse(encoded(data))
    assert result.records == () and result.history_references is None
    recent = data["filings"]["recent"]
    recent["accessionNumber"] = [f"0000000001-26-{i:06}" for i in range(10_000)]
    recent["form"] = ["10-Q"] * 10_000
    recent["filingDate"] = ["2026-10-20"] * 10_000
    assert len(parse(encoded(data)).records) == 10_000
    for name, column in recent.items():
        column.append("0000000001-26-010000" if name == "accessionNumber" else column[-1])
    invalid(lambda: parse(encoded(data)))


def test_raw_byte_limit_is_inclusive_and_text_is_not_repaired_to_bytes():
    raw = encoded()
    exact = raw + b" " * (2_097_152 - len(raw))
    assert parse(exact).original_body == exact
    invalid(lambda: parse(exact + b" "))
    invalid(lambda: parse(bytearray(raw)))
    invalid(
        lambda: api().parse_sec_submissions(
            raw.decode(),
            requested_cik=CIK,
            expected_sha256=digest(raw),
            received_at=NOW,
        )
    )


def test_count_bound_accepts_zero_and_signed_64_bit_maximum_without_completeness():
    for count in (0, 2**63 - 1):
        data = wire()
        data["filings"]["files"][0]["filingCount"] = count
        result = parse(encoded(data))
        assert result.history_references[0].filing_count == count
        assert result.history_complete is False


def test_immutable_records_revalidate_hash_context_indices_and_exact_false_flags():
    result = parse()
    invalid(lambda: replace(result, original_body=b"changed"))
    invalid(lambda: replace(result.records[0], row_index=True))
    invalid(lambda: replace(result.history_references[0], row_index=True))
    for item in (result, result.records[0], result.history_references[0]):
        object.__setattr__(item, "live_authorized", 0)
        invalid(item.__post_init__)


def test_source_row_order_and_filer_agent_accessions_are_preserved_without_form_filtering():
    data = wire()
    for column in data["filings"]["recent"].values():
        column.reverse()
    data["filings"]["recent"]["accessionNumber"][0] = "0000000099-26-000001"
    data["filings"]["recent"]["form"][0] = "SC 13D"
    result = parse(encoded(data))
    assert tuple(r.filing_date.isoformat() for r in result.records) == ("2026-10-20", "2026-10-21")
    assert result.records[0].accession_number == "0000000099-26-000001"
    assert result.records[0].form == "SC 13D"
    assert result.records[1].is_amendment is True


def test_uninterpreted_acceptance_text_and_ignored_metadata_do_not_get_numeric_or_time_defaults():
    data = wire()
    data["filings"]["recent"]["acceptanceDateTime"] = ["opaque café", "x" * 128]
    raw = encoded(data).replace(b"1.25", b"1e999")
    result = parse(raw)
    assert result.records[0].acceptance_datetime_raw == "opaque café"
    assert result.records[1].acceptance_datetime_raw == "x" * 128
    assert result.records[0].available_at == NOW
    assert result.records[0].publication_at is None
    assert result.original_body == raw
