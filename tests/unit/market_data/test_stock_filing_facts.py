"""Fictional native-shape filing evidence, never retained provider payloads."""

import importlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_bot.market_data.stock_events import normalize_filing_index

NOW = datetime(2026, 10, 21, 22, tzinfo=UTC)
FILING = "fictional-opaque-filing"
CONCEPT = "fictional:ReportedAmount"
DEFAULT = object()
FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.stock_filing_facts")
    except ModuleNotFoundError:
        pytest.fail("native filing evidence pure adapter is not implemented")


def period(**changes):
    return {"period": "native-period-A", "end_date": "2026-06-30"} | changes


def concept(**changes):
    return {
        "concept": CONCEPT,
        "is_text_block": False,
        "periods": [period()],
        "axis_names": [],
    } | changes


def catalog_payload(**changes):
    return {"data": {"concepts": [concept()], "count": 50} | changes, "guide": "untrusted guide"}


def fact(**changes):
    return {
        "filing_id": FILING,
        "concept": CONCEPT,
        "entity": "native entity text",
        "period": "native-period-A",
        "axises": [],
        "char_value": "<b>uninterpreted\ntext</b>",
        "end_date": "2026-06-30",
        "value": "123.4500",
        "unit": "native-unit",
        "decimals": -6,
    } | changes


def facts_payload(rows=None):
    return {"data": {"facts": [fact()] if rows is None else rows}, "guide": "untrusted guide"}


def catalog(payload=DEFAULT, **changes):
    return api().normalize_filing_catalog(
        catalog_payload() if payload is DEFAULT else payload,
        **(
            {
                "received_at": NOW,
                "observation_sha256": "a" * 64,
                "requested_filing_id": FILING,
                "requested_offset": 0,
            }
            | changes
        ),
    )


def facts(payload=DEFAULT, **changes):
    return api().normalize_filing_facts(
        facts_payload() if payload is DEFAULT else payload,
        **(
            {
                "received_at": NOW,
                "observation_sha256": "b" * 64,
                "requested_filing_ids": (FILING,),
                "requested_concepts": (CONCEPT,),
            }
            | changes
        ),
    )


def index(**changes):
    return normalize_filing_index(
        {
            "data": {
                "symbol": "ALFA",
                "filings": [
                    {
                        "filing_id": FILING,
                        "date_filed": "2026-10-20",
                        "form_type": "10-Q",
                        "description": "Fictional",
                    }
                ],
            }
        },
        **(
            {"received_at": NOW, "observation_sha256": "c" * 64, "requested_symbol": "ALFA"}
            | changes
        ),
    )


def bind(i=None, c=None, f=None, **changes):
    return api().bind_filing_evidence(
        index() if i is None else i,
        catalog() if c is None else c,
        facts() if f is None else f,
        **({"as_of": NOW} | changes),
    )


def invalid(call):
    with pytest.raises(ValueError, match=r"^stock_filing_facts_invalid$") as caught:
        call()
    assert caught.value.__cause__ is None


def test_catalog_preserves_page_identity_periods_and_unknown_completeness():
    payload = catalog_payload(concepts=[None, concept(periods=[None, period()])], next_offset=50)
    result = catalog(payload, requested_offset=25)
    assert result.requested_filing_id == FILING and result.requested_offset == 25
    assert result.count == 50 and result.next_offset_present is True and result.next_offset == 50
    assert result.concepts_missing is False and result.null_row_indices == (0,)
    item = result.records[0]
    assert item.row_index == 1 and item.concept == CONCEPT and item.is_text_block is False
    assert item.axis_names_raw == () and item.periods_missing is False
    assert item.null_period_indices == (0,) and item.periods[0].row_index == 1
    p = item.periods[0]
    assert p.period == "native-period-A" and p.end_date == date(2026, 6, 30)
    assert p.start_date_present is False and p.start_date_raw is p.start_date is None
    assert item.receipt is result.receipt and p.receipt is result.receipt
    assert result.receipt.tool == "get_sec_filing_facts_catalog"
    assert result.receipt.observation_sha256 == "a" * 64
    assert result.history_complete is False and result.available_at == NOW
    assert result.catalog_hash == catalog(payload, requested_offset=25).catalog_hash
    assert result.catalog_hash != catalog(payload).catalog_hash
    assert not hasattr(result, "guide")
    assert "untrusted" not in repr(result) and CONCEPT not in repr(item)
    with pytest.raises(FrozenInstanceError):
        item.is_text_block = True


def test_facts_preserve_numeric_lexeme_without_scaling_and_never_parse_char_text():
    result = facts()
    (item,) = result.records
    assert item.row_index == 0 and item.filing_id == FILING and item.concept == CONCEPT
    assert item.entity == "native entity text" and item.period == "native-period-A"
    assert item.axes_raw == () and item.char_value == "<b>uninterpreted\ntext</b>"
    assert item.end_date == date(2026, 6, 30)
    assert item.value_present is True and item.value_raw == "123.4500"
    assert item.numeric_value.as_tuple() == Decimal("123.4500").as_tuple()
    assert item.unit_present is True and item.unit_raw == "native-unit"
    assert item.decimals_present is True and item.decimals_raw == -6
    assert item.start_date_present is False and item.start_date_raw is item.start_date is None
    assert item.receipt is result.receipt and result.receipt.tool == "get_sec_filing_facts"
    assert result.facts_missing is False and result.null_row_indices == ()
    assert result.missing_requested_concepts == ()
    assert result.facts_hash == facts().facts_hash and result.available_at == NOW
    assert CONCEPT not in repr(item) and "uninterpreted" not in repr(item)


@pytest.mark.parametrize("field", ["value", "unit", "start_date", "decimals"])
@pytest.mark.parametrize("state", ["absent", "null", "empty"])
def test_optional_states_are_distinct_and_missing_numeric_never_becomes_zero(field, state):
    if state == "empty" and field in ("start_date", "decimals"):
        invalid(lambda: facts(facts_payload([fact(**{field: ""})])))
        return
    item = fact()
    item.pop(field, None)
    if state != "absent":
        item[field] = None if state == "null" else ""
    result = facts(facts_payload([item])).records[0]
    assert getattr(result, field + "_present") is (state != "absent")
    assert getattr(result, field + "_raw") == ("" if state == "empty" else None)
    if field == "value":
        assert result.numeric_value is None


@pytest.mark.parametrize("raw", ["0", "-0.00", "+123", "-12.300", "1e1000", "1e-1000", "9" * 128])
def test_exact_finite_bounded_numbers_are_retained(raw):
    item = facts(facts_payload([fact(value=raw, decimals=1000)])).records[0]
    assert item.numeric_value.as_tuple() == Decimal(raw).as_tuple()


@pytest.mark.parametrize(
    "raw",
    [
        "01",
        "00.1",
        ".1",
        "1.",
        " 1",
        "1 ",
        "NaN",
        "Infinity",
        "1_000",
        "\uff11",
        "1e1001",
        "1e-1001",
        "9" * 129,
        "1" * 513,
        1,
        True,
        1.25,
    ],
)
def test_invalid_nonempty_numeric_or_wrong_value_types_deny(raw):
    invalid(lambda: facts(facts_payload([fact(value=raw)])))


def test_repeated_comparative_rows_nulls_and_missing_requested_concepts_are_preserved():
    rows = [None, fact(), fact(), fact(period="native-B", end_date="2025-06-30")]
    result = facts(facts_payload(rows), requested_concepts=(CONCEPT, "fictional:Missing"))
    assert tuple(item.row_index for item in result.records) == (1, 2, 3)
    assert result.null_row_indices == (0,) and len(result.records) == 3
    assert result.missing_requested_concepts == ("fictional:Missing",)


def test_binding_retains_checked_inputs_and_existing_filing_and_both_period_states():
    i, c, f = index(), catalog(), facts()
    evidence = bind(i, c, f)
    assert evidence.index == i and evidence.catalog == c and evidence.facts == f
    assert evidence.index is not i and evidence.catalog is not c and evidence.facts is not f
    assert evidence.facts.records[0] is not f.records[0]
    assert evidence.filing is evidence.index.records[0]
    assert evidence.as_of == evidence.available_at == NOW
    assert evidence.filing.publication_at is evidence.publication_at is None
    assert evidence.evidence_hash == bind(i, c, f).evidence_hash
    assert evidence.evidence_hash != bind(i, c, f, as_of=NOW + timedelta(seconds=1)).evidence_hash


@pytest.mark.parametrize("kind", ["index", "catalog", "facts"])
def test_latest_receipt_gates_evidence_and_late_receipts_reject_binding(kind):
    later = NOW + timedelta(seconds=1)
    values = {"i": index(), "c": catalog(), "f": facts()}
    if kind == "index":
        values["i"] = index(received_at=later)
    elif kind == "catalog":
        values["c"] = catalog(received_at=later)
    else:
        values["f"] = facts(received_at=later)
    invalid(lambda: bind(**values))
    evidence = bind(**values, as_of=later)
    assert evidence.available_at == later


@pytest.mark.parametrize(
    "changes",
    [
        {"received_at": NOW.replace(tzinfo=None)},
        {"received_at": NOW.astimezone(timezone(timedelta(hours=1)))},
        {"observation_sha256": "A" * 64},
        {"observation_sha256": "x" * 64},
        {"observation_sha256": None},
    ],
)
@pytest.mark.parametrize("normalizer", [catalog, facts])
def test_receipts_and_hashes_are_strict(normalizer, changes):
    invalid(lambda: normalizer(**changes))


@pytest.mark.parametrize("bad", [[], None, "", True, 0, {}])
@pytest.mark.parametrize("normalizer", [catalog, facts])
def test_closed_payload_and_required_guide_are_enforced(normalizer, bad):
    invalid(lambda: normalizer(bad))


@pytest.mark.parametrize("where", ["root", "data", "row", "guide_absent", "guide_null"])
@pytest.mark.parametrize("normalizer", [catalog, facts])
def test_unknown_fields_and_invalid_guide_deny(normalizer, where):
    payload = catalog_payload() if normalizer is catalog else facts_payload()
    if where == "root":
        payload["unknown"] = 1
    elif where == "data":
        payload["data"]["unknown"] = 1
    elif where == "row":
        payload["data"]["concepts" if normalizer is catalog else "facts"][0]["unknown"] = 1
    elif where == "guide_absent":
        del payload["guide"]
    else:
        payload["guide"] = None
    invalid(lambda: normalizer(payload))


@pytest.mark.parametrize("bad", [-1, True, 1.0, None, 2**63])
def test_invalid_catalog_count_does_not_become_completeness(bad):
    invalid(lambda: catalog(catalog_payload(count=bad)))


@pytest.mark.parametrize("offset", [-1, True, 1.0, None, 2**31])
def test_invalid_requested_offsets_deny(offset):
    invalid(lambda: catalog(requested_offset=offset))


@pytest.mark.parametrize("state", ["absent", None, 0, 2**31 - 1, 2**63])
def test_catalog_offset_states_and_bounded_count_are_retained(state):
    payload = catalog_payload(count=2**63 - 1)
    if state != "absent":
        payload["data"]["next_offset"] = state
    result = catalog(payload, requested_offset=2**31 - 1)
    assert result.next_offset_present is (state != "absent")
    assert result.next_offset == (None if state == "absent" else state)
    assert result.history_complete is False


@pytest.mark.parametrize("offset", [-1, True, 1.0, "0"])
def test_invalid_next_offset_deny(offset):
    invalid(lambda: catalog(catalog_payload(next_offset=offset)))


@pytest.mark.parametrize(
    "change",
    [
        {"concept": ""},
        {"concept": "x" * 513},
        {"is_text_block": 0},
        {"axis_names": ["x", "x"]},
        {"axis_names": ""},
        {"axis_names": [""]},
        {"periods": {}},
        {"periods": [period(), period()]},
        {"periods": [period(start_date="2026-07-01")]},
        {"periods": [period(start_date="")]},
        {"periods": [period(end_date="20260630")]},
        {"periods": [period(unknown=1)]},
    ],
)
def test_invalid_catalog_concepts_periods_and_dimensions_deny(change):
    invalid(lambda: catalog(catalog_payload(concepts=[concept(**change)])))


@pytest.mark.parametrize("axis", [None, [], ["fictional-axis"]])
def test_native_axis_states_are_preserved_without_dimension_inference(axis):
    c = catalog(catalog_payload(concepts=[concept(axis_names=axis)]))
    f = facts(facts_payload([fact(axises=axis)]))
    assert c.records[0].axis_names_raw == (None if axis is None else tuple(axis))
    assert f.records[0].axes_raw == (None if axis is None else tuple(axis))
    if axis != []:
        invalid(lambda: bind(c=c))
        invalid(lambda: bind(f=f))


@pytest.mark.parametrize(
    "change",
    [
        {"filing_id": "other"},
        {"concept": "other"},
        {"entity": ""},
        {"period": ""},
        {"axises": ["x", "x"]},
        {"axises": [""]},
        {"axises": False},
        {"char_value": None},
        {"char_value": "bad\x00text"},
        {"char_value": "x" * 65537},
        {"end_date": "2026-6-30"},
        {"start_date": "2026-07-01"},
        {"unit": 1},
        {"unit": "x" * 129},
        {"decimals": True},
        {"decimals": -1001},
        {"decimals": 1001},
        {"decimals": 1.0},
    ],
)
def test_invalid_native_facts_deny_entire_collection(change):
    invalid(lambda: facts(facts_payload([fact(), fact(**change)])))


@pytest.mark.parametrize(
    "field", ["filing_id", "concept", "entity", "period", "axises", "char_value", "end_date"]
)
def test_required_native_fact_fields_cannot_be_absent(field):
    value = fact()
    del value[field]
    invalid(lambda: facts(facts_payload([value])))


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_filing_ids": ()},
        {"requested_filing_ids": [FILING]},
        {"requested_filing_ids": (FILING, FILING)},
        {"requested_filing_ids": tuple("abcd")},
        {"requested_filing_ids": (True,)},
        {"requested_concepts": ()},
        {"requested_concepts": [CONCEPT]},
        {"requested_concepts": (CONCEPT, CONCEPT)},
        {"requested_concepts": tuple(str(i) for i in range(11))},
    ],
)
def test_request_scope_is_exact_bounded_and_unique(changes):
    invalid(lambda: facts(**changes))


def test_catalog_duplicate_concepts_and_facts_request_scope_conflicts_deny():
    invalid(lambda: catalog(catalog_payload(concepts=[concept(), concept()])))
    invalid(lambda: catalog(requested_filing_id=""))
    invalid(lambda: bind(c=catalog(requested_filing_id="other")))
    invalid(lambda: bind(f=facts(requested_filing_ids=(FILING, "other"))))
    invalid(lambda: bind(i=replace(index(), records=())))
    invalid(lambda: bind(c=catalog(catalog_payload(concepts=[concept(is_text_block=True)]))))


@pytest.mark.parametrize("state", ["absent", "null", "date"])
def test_period_matching_requires_exact_start_presence_and_raw_state(state):
    p, f = period(), fact()
    if state != "absent":
        p["start_date"] = f["start_date"] = None if state == "null" else "2026-01-01"
    c = catalog(catalog_payload(concepts=[concept(periods=[p])]))
    fs = facts(facts_payload([f]))
    assert bind(c=c, f=fs).facts == fs
    assert bind(c=c, f=fs).facts is not fs
    # Absent and explicit null must never become the same contextual identity.
    other = deepcopy(f)
    if state == "absent":
        other["start_date"] = None
    else:
        del other["start_date"]
    invalid(lambda: bind(c=c, f=facts(facts_payload([other]))))


@pytest.mark.parametrize(
    "periods", [None, [], [None], [period(period="other")], [period(end_date="2025-06-30")]]
)
def test_unknown_missing_or_contradictory_catalog_period_cannot_bind(periods):
    invalid(lambda: bind(c=catalog(catalog_payload(concepts=[concept(periods=periods)]))))


def test_null_empty_collections_missing_concepts_and_numeric_gaps_remain_explicit():
    for rows in (None, []):
        cp = catalog_payload(concepts=rows)
        fp = facts_payload()
        fp["data"]["facts"] = rows
        c, f = catalog(cp), facts(fp)
        assert c.concepts_missing is (rows is None) and f.facts_missing is (rows is None)
        assert c.records == f.records == ()
        assert f.missing_requested_concepts == (CONCEPT,)
        invalid(lambda c=c, f=f: bind(c=c, f=f))
        # Known catalog context permits explicit missing returned facts as a gap.
        assert bind(f=f).facts.facts_missing is (rows is None)
    item = fact(char_value="999")
    del item["value"]
    f = facts(facts_payload([item]))
    assert bind(f=f).facts.records[0].numeric_value is None


@pytest.mark.parametrize("target", ["catalog", "concept", "period", "facts", "fact", "receipt"])
@pytest.mark.parametrize("flag", FLAGS)
def test_caller_forged_flags_are_rejected_by_binding(target, flag):
    c, f = catalog(), facts()
    obj = {
        "catalog": c,
        "concept": c.records[0],
        "period": c.records[0].periods[0],
        "facts": f,
        "fact": f.records[0],
        "receipt": f.receipt,
    }[target]
    object.__setattr__(obj, flag, 0 if flag == "qualified" else True)
    invalid(lambda: bind(c=c, f=f))


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("fact", "numeric_value", Decimal("999")),
        ("fact", "value_present", False),
        ("fact", "row_index", True),
        ("fact", "receipt", None),
        ("concept", "row_index", 1),
        ("period", "start_date_present", 0),
        ("catalog", "null_row_indices", (0,)),
        ("facts", "missing_requested_concepts", (CONCEPT,)),
        ("index", "scope_verified", 0),
    ],
)
def test_caller_forged_rows_and_receipts_cannot_bypass_normalization(target, field, value):
    i, c, f = index(), catalog(), facts()
    obj = {
        "index": i,
        "catalog": c,
        "concept": c.records[0],
        "period": c.records[0].periods[0],
        "facts": f,
        "fact": f.records[0],
    }[target]
    object.__setattr__(obj, field, value)
    invalid(lambda: bind(i, c, f))


def test_all_new_models_are_repr_safe_frozen_slotted_and_permanently_unqualified():
    e = bind()
    for value in (
        e,
        e.catalog,
        e.facts,
        e.catalog.records[0],
        e.catalog.records[0].periods[0],
        e.facts.records[0],
        e.catalog.receipt,
        e.facts.receipt,
    ):
        assert not hasattr(value, "__dict__") and value.publication_at is None
        for flag in FLAGS:
            assert getattr(value, flag) is False
            assert next(field for field in fields(value) if field.name == flag).init is False
            with pytest.raises((TypeError, ValueError)):
                replace(value, **{flag: True})
            assert getattr(value, flag) is False


@pytest.mark.parametrize(
    "as_of", [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=1))), None]
)
def test_binding_requires_canonical_utc_cutoff(as_of):
    invalid(lambda: bind(as_of=as_of))


def test_resource_boundaries_are_closed_and_guide_is_utf8_byte_bounded():
    payload = catalog_payload()
    payload["guide"] = "é" * 524288
    assert catalog(payload).records
    payload["guide"] += "é"
    invalid(lambda: catalog(payload))
    invalid(lambda: catalog(catalog_payload(concepts=[None] * 5001)))
    assert len(catalog(catalog_payload(concepts=[None] * 5000)).null_row_indices) == 5000
    invalid(lambda: catalog(catalog_payload(concepts=[concept(periods=[None] * 257)])))
    assert (
        len(
            catalog(catalog_payload(concepts=[concept(periods=[None] * 256)]))
            .records[0]
            .null_period_indices
        )
        == 256
    )
    invalid(lambda: facts(facts_payload([None] * 20001)))
    assert len(facts(facts_payload([None] * 20000)).null_row_indices) == 20000
    invalid(lambda: facts(facts_payload([fact(axises=[str(i) for i in range(65)])])))
    assert (
        len(facts(facts_payload([fact(axises=[str(i) for i in range(64)])])).records[0].axes_raw)
        == 64
    )
    invalid(
        lambda: catalog(catalog_payload(concepts=[concept(axis_names=[str(i) for i in range(65)])]))
    )
    invalid(lambda: facts(facts_payload([fact(char_value="x" * 65536)] * 128)))


@pytest.mark.parametrize("field,value", [("count", float("nan")), ("count", float("inf"))])
def test_nonfinite_json_payload_numbers_are_denied(field, value):
    invalid(lambda: catalog(catalog_payload(**{field: value})))


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("catalog", "history_complete", 0),
        ("receipt", "hash_is_caller_declared", 1),
    ],
)
def test_additional_permanent_flag_identities_cannot_be_forged(target, field, value):
    c = catalog()
    object.__setattr__(c if target == "catalog" else c.receipt, field, value)
    invalid(lambda: bind(c=c))


def test_empty_string_subclass_is_not_a_native_exact_numeric_string():
    class ForeignText(str):
        pass

    invalid(lambda: facts(facts_payload([fact(value=ForeignText(""))])))


@pytest.mark.parametrize("value", ["1e1000", "1e-1000", "-0.000", "9" * 128])
def test_versioned_fact_and_evidence_hashes_support_the_entire_native_numeric_range(value):
    f = facts(facts_payload([fact(value=value)]))
    assert len(f.facts_hash) == len(bind(f=f).evidence_hash) == 64
    assert bind(f=f).facts.records[0].numeric_value.as_tuple() == Decimal(value).as_tuple()


def test_hashes_distinguish_absent_null_empty_and_lexically_distinct_equal_values():
    observations = []
    for raw in (DEFAULT, None, "", "0", "-0.0", "+0"):
        value = fact()
        if raw is DEFAULT:
            del value["value"]
        else:
            value["value"] = raw
        observations.append(facts(facts_payload([value])))
    assert len({observation.facts_hash for observation in observations}) == len(observations)


def test_checked_index_cursor_does_not_establish_complete_history():
    original = replace(index(), next_cursor="")
    result = bind(i=original)
    assert result.index.next_cursor == "" and result.index.history_complete is False
    assert result.index is not original


@pytest.mark.parametrize("pointer", [None, 0, 2**63])
def test_binding_reconstructs_catalog_pointer_states_without_following_them(pointer):
    c = catalog(catalog_payload(next_offset=pointer))
    result = bind(c=c)
    assert result.catalog.next_offset_present is True and result.catalog.next_offset == pointer
    assert result.catalog.history_complete is False
    assert result.catalog.receipt.available_at == NOW


@pytest.mark.parametrize("raw,forged", [("123.4500", "123.45"), ("-0.00", "0.00")])
def test_forged_equal_numeric_value_with_different_representation_is_rejected(raw, forged):
    f = facts(facts_payload([fact(value=raw)]))
    assert f.records[0].numeric_value == Decimal(forged)
    object.__setattr__(f.records[0], "numeric_value", Decimal(forged))
    invalid(lambda: bind(f=f))


def test_requested_but_missing_catalog_concept_denies_even_when_no_fact_returned():
    f = facts(requested_concepts=(CONCEPT, "fictional:Missing"))
    assert f.missing_requested_concepts == ("fictional:Missing",)
    invalid(lambda: bind(f=f))


def test_canonical_envelope_boundary_and_binder_reconstruction_are_bounded():
    payload = facts_payload([fact(char_value="x" * 65536)] * 120)
    payload["guide"] = ""
    size = len(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    payload["guide"] = "x" * (8_388_608 - size)
    f = facts(payload)
    assert len(f.records) == 120
    payload["guide"] += "x"
    invalid(lambda: facts(payload))
    template = facts()
    oversized = replace(
        template,
        records=tuple(
            replace(template.records[0], row_index=i, char_value="x" * 65536) for i in range(128)
        ),
    )
    invalid(lambda: bind(f=oversized))
