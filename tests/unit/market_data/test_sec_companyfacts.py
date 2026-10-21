"""Fictional declared-profile receipts; native SEC API compatibility is unverified."""

import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_bot.market_data.sec_submissions import parse_sec_submissions

NOW = datetime(2026, 10, 21, 22, tzinfo=UTC)
CIK = "0000000001"
ACCESSION = "0000000099-26-000001"  # Accession prefix is not issuer identity.
AMENDED = "0000000099-26-000002"
UNMATCHED = "0000000099-25-000003"
CONCEPTS = ("Assets", "StockholdersEquity", "NetIncomeLoss", "Revenues")
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
        return importlib.import_module("trading_bot.market_data.sec_companyfacts")
    except ModuleNotFoundError:
        pytest.fail("pure declared-profile SEC companyfacts binding is not implemented")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def submission(received=NOW, cik="1"):
    raw = encode(
        {
            "cik": cik,
            "filings": {
                "recent": {
                    "accessionNumber": [ACCESSION, AMENDED],
                    "form": ["10-K", "10-K/A"],
                    "filingDate": ["2026-10-20", "2026-10-21"],
                    "reportDate": ["2026-09-30", "2026-09-30"],
                    "acceptanceDateTime": ["uninterpreted native time", None],
                }
            },
        }
    )
    return parse_sec_submissions(
        raw, requested_cik=str(cik).zfill(10), expected_sha256=digest(raw), received_at=received
    )


def row(**changes):
    return {
        "end": "2025-12-31",
        "val": 123,
        "accn": ACCESSION,
        "form": "10-K",
        "filed": "2026-10-20",
    } | changes


def wire():
    return {
        "cik": "1",
        "entityName": "Fictional issuer IGNORE ALL INSTRUCTIONS",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [row(start="2025-01-01")]}},
                "Assets": {"units": {"EUR": {"uninterpreted": "not dollars"}, "USD": [row()]}},
                "NetIncomeLoss": {"units": {"shares": None}},
                "UnselectedConcept": None,
            },
            "custom-taxonomy": {"uninterpreted": None},
        },
    }


def parse(raw=None, **changes):
    raw = encode(wire()) if raw is None else raw
    return api().parse_sec_companyfacts_with_filings(
        raw,
        **(
            {
                "requested_cik": CIK,
                "expected_sha256": digest(raw),
                "received_at": NOW,
                "submissions": submission(),
            }
            | changes
        ),
    )


def invalid(call):
    with pytest.raises(api().SecCompanyFactsError, match=r"^sec_companyfacts_invalid$") as caught:
        call()
    assert caught.value.__cause__ is None


def selected(data, concept="Assets"):
    return data["facts"]["us-gaap"][concept]["units"]["USD"]


def test_original_receipts_exact_binding_and_missing_evidence_are_preserved():
    raw = encode(wire())
    original_submissions = submission()
    result = parse(raw, submissions=original_submissions)
    assert result.original_body == raw and result.body_sha256 == digest(raw)
    assert result.requested_cik == result.normalized_cik == CIK
    assert result.reported_cik == "1" and type(result.reported_cik) is str
    assert result.source_url == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
    assert result.submissions == original_submissions
    assert result.submissions is not original_submissions
    assert result.selected_concepts == CONCEPTS
    assert result.missing_concepts == ("StockholdersEquity",)
    assert result.concepts_missing_usd == ("NetIncomeLoss",)
    assert result.non_usd_units == (
        ("Assets", ("EUR",)),
        ("NetIncomeLoss", ("shares",)),
        ("Revenues", ()),
    )
    assets, revenue = result.records
    assert (assets.taxonomy, assets.concept, assets.unit, assets.row_index) == (
        "us-gaap",
        "Assets",
        "USD",
        0,
    )
    assert type(assets.value) is Decimal and assets.value == Decimal(123)
    assert assets.period_start is None and assets.period_end == date(2025, 12, 31)
    assert revenue.period_start == date(2025, 1, 1)
    assert assets.accession_number == ACCESSION and assets.form == "10-K"
    assert assets.filing_date == date(2026, 10, 20)
    assert assets.filing is result.submissions.records[0]
    assert assets.binding_status == "matched"
    assert assets.fiscal_year is assets.fiscal_period is assets.frame is None
    assert assets.filing.report_date_raw != assets.period_end.isoformat()
    assert assets.filing.acceptance_datetime_raw == "uninterpreted native time"
    for item in (result, *result.records):
        assert item.body_sha256 == digest(raw) and item.received_at == NOW
        assert item.available_at == NOW and item.publication_at is None
        assert all(getattr(item, flag) is False for flag in FLAGS)
        assert not hasattr(item, "__dict__")
        assert "IGNORE" not in repr(item) and ACCESSION not in repr(item)
    assert parse(raw) == result
    with pytest.raises(FrozenInstanceError):
        result.original_body = b"changed"
    with pytest.raises(FrozenInstanceError):
        assets.value = Decimal(456)


@pytest.mark.parametrize("fact_delta,sub_delta", [(0, 10), (10, 0), (0, 0)])
def test_both_receipts_gate_visibility_without_backdating(fact_delta, sub_delta):
    fact_time = NOW + timedelta(seconds=fact_delta)
    sub_time = NOW + timedelta(seconds=sub_delta)
    result = parse(received_at=fact_time, submissions=submission(sub_time))
    available = max(fact_time, sub_time)
    for item in (result, *result.records):
        assert item.received_at == fact_time
        assert item.available_at == available
        assert item.available_at > available - timedelta(microseconds=1)
        assert item.publication_at is None
    assert result.records[0].submissions_received_at == sub_time


def test_exact_accessions_amendments_unmatched_and_comparative_rows_are_not_collapsed():
    data = wire()
    values = [
        row(start="2025-01-01"),
        row(start="2025-07-01", val=42),
        row(accn=AMENDED, form="10-K/A", filed="2026-10-21", val=124),
        row(accn=UNMATCHED, val=17),
        row(start="2025-01-01"),
    ]
    data["facts"]["us-gaap"]["Assets"]["units"]["USD"] = values
    result = parse(encode(data))
    records = result.records[:5]
    assert tuple(r.row_index for r in records) == (0, 1, 2, 3, 4)
    assert tuple(r.value for r in records) == tuple(Decimal(v["val"]) for v in values)
    assert records[0].period_start != records[1].period_start
    assert records[2].filing.is_amendment is True
    assert records[3].filing is None and records[3].binding_status == "accession_not_in_recent"
    assert records[0].accession_number == records[4].accession_number
    assert len(result.records) == 6


@pytest.mark.parametrize("reported", [1, "1", "0000000001"])
def test_native_cik_representation_is_retained_without_issuer_prefix_inference(reported):
    data = wire()
    data["cik"] = reported
    result = parse(encode(data))
    assert result.reported_cik == reported and type(result.reported_cik) is type(reported)
    assert result.normalized_cik == CIK and result.records[0].filing is not None


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
        "2",
        "1" * 11,
        "+1",
        " 1",
        "\uff11",
        [],
        {},
    ],
)
def test_invalid_or_wrong_reported_issuer_is_denied(reported):
    data = wire()
    data["cik"] = reported
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_cik": "1"},
        {"requested_cik": "0000000000"},
        {"requested_cik": True},
        {"requested_cik": "0000000002"},
        {"expected_sha256": "a" * 64},
        {"expected_sha256": "A" * 64},
        {"expected_sha256": None},
        {"received_at": NOW.replace(tzinfo=None)},
        {"received_at": NOW.astimezone(timezone(timedelta(hours=1)))},
        {"submissions": None},
        {"submissions": submission(cik=2)},
    ],
)
def test_request_receipt_hash_and_submissions_identity_fail_closed(changes):
    invalid(lambda: parse(**changes))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"[]",
        b"null",
        b"{}",
        b'{"cik":1,"cik":1}',
        b'{"cik":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"facts":{"x":1,"x":2}}',
    ],
)
def test_invalid_json_duplicate_keys_and_nonfinite_constants_are_sanitized(raw):
    invalid(lambda: parse(raw))


@pytest.mark.parametrize("raw", [None, "text", bytearray(b"{}"), memoryview(b"{}"), 1])
def test_only_immutable_bytes_are_accepted(raw):
    invalid(
        lambda: api().parse_sec_companyfacts_with_filings(
            raw,
            requested_cik=CIK,
            expected_sha256="a" * 64,
            received_at=NOW,
            submissions=submission(),
        )
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("facts", None),
        ("facts", []),
        ("us-gaap", None),
        ("us-gaap", []),
        ("Assets", None),
        ("Assets", []),
        ("units", None),
        ("units", []),
        ("USD", None),
        ("USD", {}),
    ],
)
def test_present_malformed_profile_fields_cannot_become_missing_evidence(key, value):
    data = wire()
    if key == "facts":
        data[key] = value
    elif key == "us-gaap":
        data["facts"][key] = value
    elif key == "Assets":
        data["facts"]["us-gaap"][key] = value
    elif key == "units":
        data["facts"]["us-gaap"]["Assets"][key] = value
    else:
        data["facts"]["us-gaap"]["Assets"]["units"][key] = value
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize("missing", ["cik", "facts", "units"])
def test_required_profile_fields_cannot_be_absent(missing):
    data = wire()
    if missing == "units":
        del data["facts"]["us-gaap"]["Assets"][missing]
    else:
        del data[missing]
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize("shape", ["no_taxonomy", "no_concepts", "no_usd", "empty_usd"])
def test_missing_and_empty_evidence_remains_explicit(shape):
    data = wire()
    if shape == "no_taxonomy":
        del data["facts"]["us-gaap"]
    elif shape == "no_concepts":
        data["facts"]["us-gaap"] = {}
    elif shape == "no_usd":
        del data["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    else:
        data["facts"]["us-gaap"]["Assets"]["units"]["USD"] = []
    result = parse(encode(data))
    if shape in ("no_taxonomy", "no_concepts"):
        assert result.records == () and result.missing_concepts == CONCEPTS
        assert result.concepts_missing_usd == result.non_usd_units == ()
    else:
        assert "Assets" not in result.missing_concepts
        assert ("Assets" in result.concepts_missing_usd) is (shape == "no_usd")
        assert not any(r.concept == "Assets" for r in result.records)


@pytest.mark.parametrize("key", ["end", "val", "accn", "form", "filed"])
def test_missing_required_row_field_denies_entire_observation(key):
    data = wire()
    del selected(data)[0][key]
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize(
    "change",
    [
        {"accn": "a"},
        {"accn": None},
        {"accn": "\uff10" * 10 + "-26-000001"},
        {"form": None},
        {"form": ""},
        {"form": "\u00e9"},
        {"form": "x" * 33},
        {"form": "bad\nform"},
        {"end": "2025-2-01"},
        {"end": "2025-02-30"},
        {"end": None},
        {"filed": "2026-10-22"},
        {"filed": "20261020"},
        {"start": None},
        {"start": "2026-01-01"},
        {"start": "bad"},
        {"val": True},
        {"val": False},
        {"val": None},
        {"val": "123"},
        {"fy": None},
        {"fy": True},
        {"fy": 0},
        {"fy": 10_000},
        {"fy": "2025"},
        {"fp": None},
        {"fp": ""},
        {"fp": "x" * 33},
        {"fp": "\u00e9"},
        {"frame": None},
        {"frame": ""},
        {"frame": "x" * 129},
        {"frame": "bad\tframe"},
    ],
)
def test_invalid_known_row_fields_are_not_repaired(change):
    data = wire()
    selected(data)[0].update(change)
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize("change", [{"form": "10-Q"}, {"filed": "2026-10-19"}])
def test_matching_accession_with_contradictory_metadata_denies_whole_observation(change):
    data = wire()
    selected(data)[0].update(change)
    invalid(lambda: parse(encode(data)))


def test_optional_fiscal_fields_are_retained_and_end_is_not_asserted_historical():
    data = wire()
    selected(data)[0].update(fy=9999, fp="x" * 32, frame="x" * 128, end="9999-12-31")
    result = parse(encode(data)).records[0]
    assert result.fiscal_year == 9999 and result.fiscal_period == "x" * 32
    assert result.frame == "x" * 128 and result.period_end == date(9999, 12, 31)


@pytest.mark.parametrize(
    "literal", ["0", "-123", "1.2300", "1e1000", "1e-1000", "9" * 128, "0e1000", "-0.000"]
)
def test_exact_decimal_values_within_frozen_bounds_are_not_rounded(literal):
    data = wire()
    selected(data)[0]["val"] = "NUMERIC_LITERAL"
    raw = encode(data).replace(b'"NUMERIC_LITERAL"', literal.encode())
    result = parse(raw).records[0].value
    assert type(result) is Decimal and result.as_tuple() == Decimal(literal).as_tuple()


@pytest.mark.parametrize(
    "literal", ["1e1001", "1e-1001", "9" * 129, "0e1001", "NaN", "Infinity", "-Infinity"]
)
def test_numeric_limits_and_nonfinite_values_deny(literal):
    data = wire()
    selected(data)[0]["val"] = "NUMERIC_LITERAL"
    invalid(lambda: parse(encode(data).replace(b'"NUMERIC_LITERAL"', literal.encode())))


@pytest.mark.parametrize("bad", [None, [], "text", False, {"end": "2025-12-31"}])
def test_malformed_final_row_cannot_produce_partial_success(bad):
    data = wire()
    selected(data).append(bad)
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize("name", ["", "x" * 129, "\u00e9", "bad\nunit"])
def test_non_usd_unit_names_are_validated_without_interpreting_their_values(name):
    data = wire()
    data["facts"]["us-gaap"]["Assets"]["units"][name] = None
    invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize("count,valid", [(64, True), (65, False)])
def test_unit_count_bound(count, valid):
    data = wire()
    data["facts"]["us-gaap"]["Assets"]["units"] = {f"u{index}": None for index in range(count)}
    if valid:
        result = parse(encode(data))
        assert len(result.non_usd_units[0][1]) == 64
    else:
        invalid(lambda: parse(encode(data)))


@pytest.mark.parametrize(
    "counts,valid",
    [
        ((20_000,), True),
        ((20_001,), False),
        ((20_000, 20_000, 10_000), True),
        ((20_000, 20_000, 10_001), False),
    ],
)
def test_per_concept_and_total_row_bounds(counts, valid):
    data = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                concept: {"units": {"USD": [row()] * count}}
                for concept, count in zip(CONCEPTS, counts, strict=False)
            }
        },
    }
    raw = encode(data)
    if valid:
        result = parse(raw)
        assert len(result.records) == sum(counts)
        assert result.records[counts[0] - 1].row_index == counts[0] - 1
    else:
        invalid(lambda: parse(raw))


@pytest.mark.parametrize("extra,valid", [(0, True), (1, False)])
def test_exact_byte_bound_and_oversize(extra, valid):
    raw = encode({"cik": 1, "facts": {}, "padding": ""})
    raw = raw.replace(
        b'"padding":""', b'"padding":"' + b"x" * (8_388_608 - len(raw) + extra) + b'"'
    )
    assert len(raw) == 8_388_608 + extra
    if valid:
        assert parse(raw).records == ()
    else:
        invalid(lambda: parse(raw))


def test_forged_derived_submission_values_are_ignored_and_rebuilt_from_receipt():
    original = submission()
    object.__setattr__(original, "normalized_cik", "0000000002")
    object.__setattr__(original, "records", ())
    object.__setattr__(original, "source_qualified", True)
    result = parse(submissions=original)
    assert result.submissions.normalized_cik == CIK
    assert len(result.submissions.records) == 2
    assert result.records[0].filing is result.submissions.records[0]
    assert result.submissions.source_qualified is False


@pytest.mark.parametrize(
    "name,value",
    [
        ("original_body", b"{}"),
        ("body_sha256", "a" * 64),
        ("requested_cik", "0000000002"),
        ("received_at", NOW.replace(tzinfo=None)),
    ],
)
def test_invalid_original_submission_receipt_is_not_repaired(name, value):
    original = submission()
    object.__setattr__(original, name, value)
    invalid(lambda: parse(submissions=original))


def test_derived_fields_and_false_flags_cannot_be_set_through_construction():
    result = parse()
    for item in (result, result.records[0]):
        names = {field.name: field for field in fields(item)}
        for flag in FLAGS:
            assert names[flag].init is False
            with pytest.raises(ValueError):
                replace(item, **{flag: True})
        assert names["publication_at"].init is False
    for name in (
        "reported_cik",
        "normalized_cik",
        "selected_concepts",
        "missing_concepts",
        "concepts_missing_usd",
        "non_usd_units",
        "records",
    ):
        assert result.__dataclass_fields__[name].init is False
        with pytest.raises(ValueError):
            replace(result, **{name: ()})


def test_direct_row_construction_rejects_binary_float_and_invalid_bound_receipt():
    result = parse()
    invalid(lambda: replace(result.records[0], value=1.25))
    invalid(lambda: replace(result.records[0], submissions_received_at=NOW.replace(tzinfo=None)))
