"""Frozen latest-vintage SPY workbook contract, independent synthetic OOXML fixtures.

The bytes-only parser verifies the supplied exact SHA256 before interpreting a
bounded non-macro XLSX. It returns immutable dated Decimal records and source/row
hashes, never publication times, qualification, promotion or execution evidence.
Required explicit 2016--2025 bounds are hash-bound; every SPY ex-date is classified.
Financial validation is scoped to that window and excluded SPY rows are counted.
Missing quarterly coverage adds a limitation. Conflicting/duplicate ex-dates and
malformed SPY data deny the entire archive with a fixed sanitized error.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import struct
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from trading_bot.domain.decimal_utils import DomainValidationError


@pytest.mark.parametrize(
    "attribute,value", [("amount", Decimal("-1")), ("pay_date", date(2016, 3, 17))]
)
def test_archive_revalidates_unsafe_nested_financial_records(attribute, value):
    module = importlib.import_module("trading_bot.market_data.etf_issuer_distributions")
    result = _parse(_pack(_parts()))
    object.__setattr__(result.distributions[0], attribute, value)
    digest = module._archive_hash(
        result.source_hash,
        result.start_date,
        result.end_date,
        result.distributions,
        result.excluded_spy_rows,
        result.limitations,
    )
    with pytest.raises(DomainValidationError):
        replace(result, archive_hash=digest)


_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_HEADERS = (
    "FUND NAME",
    "TICKER",
    "CUSIP",
    "EX-DATE",
    "RECORD DATE",
    "PAYABLE DATE",
    "DIVIDEND ($)",
    "SHORT TERM CAPITAL GAIN ($)",
    "LONG TERM CAPITAL GAIN ($)",
    "FREQUENCY",
)
_ROW = (
    "State Street SPDR S&P 500 ETF Trust",
    "SPY",
    "78462F103",
    "03/18/2016",
    "03/21/2016",
    "03/29/2016",
    "1.234567890123456789",
    "",
    "0.000000",
    "Quarterly",
)


def _parse(
    body: bytes,
    expected: str | None = None,
    *,
    start_date: date = date(2016, 1, 1),
    end_date: date = date(2025, 12, 31),
) -> Any:
    module = importlib.import_module("trading_bot.market_data.etf_issuer_distributions")
    return module.parse_spy_issuer_distributions(
        body,
        expected or hashlib.sha256(body).hexdigest(),
        start_date=start_date,
        end_date=end_date,
    )


def _pack(parts: dict[str, bytes | str]) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


def _parts(rows: tuple[tuple[str, ...], ...] = (_ROW,)) -> dict[str, bytes | str]:
    strings: list[str] = []
    xml_rows: list[str] = []
    for row_no, values in enumerate((_HEADERS, *rows), 1):
        cells = []
        for col, value in enumerate(values):
            index = len(strings)
            strings.append(value)
            cells.append(f'<c r="{chr(65 + col)}{row_no}" t="s"><v>{index}</v></c>')
        xml_rows.append(f'<row r="{row_no}">{"".join(cells)}</row>')
    return {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.sheet.main+xml"/></Types>'
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{_PKG}"><Relationship Id="rId1" '
            f'Target="xl/workbook.xml" Type="{_REL}/officeDocument"/></Relationships>'
        ),
        "xl/workbook.xml": (
            f'<workbook xmlns="{_NS}" xmlns:r="{_REL}"><workbookPr date1904="0"/>'
            '<sheets><sheet name="dividend" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{_PKG}"><Relationship Id="rId1" '
            f'Target="worksheets/sheet1.xml" Type="{_REL}/worksheet"/>'
            f'<Relationship Id="rId2" Target="styles.xml" Type="{_REL}/styles"/>'
            f'<Relationship Id="rId3" Target="sharedStrings.xml" '
            f'Type="{_REL}/sharedStrings"/></Relationships>'
        ),
        "xl/styles.xml": (
            f'<styleSheet xmlns="{_NS}"><numFmts count="1">'
            '<numFmt numFmtId="164" formatCode="0.000000"/></numFmts>'
            '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14"/>'
            '<xf numFmtId="164"/></cellXfs></styleSheet>'
        ),
        "xl/sharedStrings.xml": (
            f'<sst xmlns="{_NS}">'
            + "".join(f"<si><t>{escape(value)}</t></si>" for value in strings)
            + "</sst>"
        ),
        "xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns="{_NS}"><sheetData>' + "".join(xml_rows) + "</sheetData></worksheet>"
        ),
    }


def _replace(parts: dict[str, bytes | str], name: str, old: str, new: str) -> None:
    parts[name] = str(parts[name]).replace(old, new)


def test_exact_decimal_dates_and_permanently_ineligible_immutable_result() -> None:
    # Catches float conversion, fabricated availability, or a permissive evidence flag.
    body = _pack(_parts())
    result = _parse(body)
    assert result.source_hash == hashlib.sha256(body).hexdigest()
    assert result.start_date == date(2016, 1, 1)
    assert result.end_date == date(2025, 12, 31)
    assert len(result.archive_hash) == 64
    assert result.excluded_spy_rows == 0
    assert result.source_kind == "issuer_workbook"
    assert result.vintage == "latest_vintage"
    assert result.point_in_time_qualified is False
    assert result.source_qualified is False
    assert result.evidence_promotable is False
    assert result.production_pretrade_eligible is False
    assert "original_publication_and_correction_history_unverified" in result.limitations
    assert "requested_window_incomplete" in result.limitations
    assert type(result.distributions) is tuple
    item = result.distributions[0]
    assert (item.ex_date, item.record_date, item.pay_date) == (
        date(2016, 3, 18),
        date(2016, 3, 21),
        date(2016, 3, 29),
    )
    assert item.amount.as_tuple() == Decimal("1.234567890123456789").as_tuple()
    assert len(item.row_hash) == 64
    assert not hasattr(item, "published_at")
    with pytest.raises(FrozenInstanceError):
        item.amount = Decimal("1")
    with pytest.raises(FrozenInstanceError):
        result.source_qualified = True


def test_complete_window_is_diagnostic_only_and_sorted() -> None:
    rows = []
    for year in range(2016, 2026):
        for month in (3, 6, 9, 12):
            values = list(_ROW)
            values[3:6] = [f"{month:02d}/15/{year}"] * 3
            rows.append(tuple(values))
    result = _parse(_pack(_parts(tuple(reversed(rows)))))
    assert len(result.distributions) == 40
    assert result.distributions[0].ex_date == date(2016, 3, 15)
    assert result.distributions[-1].ex_date == date(2025, 12, 15)
    assert "requested_window_incomplete" not in result.limitations
    assert result.source_qualified is False


def test_numeric_cells_use_verified_1900_styles_and_exact_xml_amount() -> None:
    parts = _parts()
    for col, index, value in (("D", 13, "42447"), ("E", 14, "42450"), ("F", 15, "42458")):
        _replace(
            parts,
            "xl/worksheets/sheet1.xml",
            f'<c r="{col}2" t="s"><v>{index}</v></c>',
            f'<c r="{col}2" s="1"><v>{value}</v></c>',
        )
    _replace(
        parts,
        "xl/worksheets/sheet1.xml",
        '<c r="G2" t="s"><v>16</v></c>',
        '<c r="G2" s="2"><v>1.230000</v></c>',
    )
    item = _parse(_pack(parts)).distributions[0]
    assert item.ex_date == date(2016, 3, 18)
    assert item.amount.as_tuple() == Decimal("1.230000").as_tuple()


def test_row_hash_binds_original_decimal_spelling_and_source_bytes() -> None:
    values = list(_ROW)
    values[6] = "1.00"
    one = _parse(_pack(_parts((tuple(values),))))
    values[6] = "1.000"
    two = _parse(_pack(_parts((tuple(values),))))
    assert one.distributions[0].amount == two.distributions[0].amount
    assert one.distributions[0].row_hash != two.distributions[0].row_hash


def test_archive_identity_also_binds_normalized_financial_payload() -> None:
    archive = _parse(_pack(_parts()))
    changed = replace(archive.distributions[0], amount=Decimal("9"))
    with pytest.raises(DomainValidationError):
        replace(archive, distributions=(changed,))


@pytest.mark.parametrize(
    "column,value",
    [
        (2, "wrong-cusip"),
        (3, "02/30/2016"),
        (3, "3/18/2016"),
        (4, "03/17/2016"),
        (5, "03/20/2016"),
        (6, "NaN"),
        (6, "Infinity"),
        (6, "1e2"),
        (6, "-1"),
        (6, "0"),
        (6, "9" * 513),
        (7, "0.000001"),
        (8, "-1"),
        (9, "Monthly"),
    ],
)
def test_invalid_spy_financial_or_identity_fields_deny(column: int, value: str) -> None:
    values = list(_ROW)
    values[column] = value
    with pytest.raises(DomainValidationError, match=r"^etf_issuer_workbook_invalid$"):
        _parse(_pack(_parts((tuple(values),))))


def test_outside_window_financial_anomaly_is_explicitly_excluded_and_counted() -> None:
    values = list(_ROW)
    values[3:6] = ["03/15/2006", "03/14/2006", "03/13/2006"]
    values[6] = "invalid-private-sentinel"
    archive = _parse(_pack(_parts((_ROW, tuple(values)))))
    assert len(archive.distributions) == 1
    assert archive.excluded_spy_rows == 1


def test_unclassifiable_spy_ex_date_denies_even_outside_window() -> None:
    values = list(_ROW)
    values[3] = "private-sentinel"
    with pytest.raises(DomainValidationError) as error:
        _parse(_pack(_parts((_ROW, tuple(values)))))
    assert str(error.value) == "etf_issuer_workbook_invalid"
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2015, 1, 1), date(2025, 12, 31)),
        (date(2016, 1, 1), date(2026, 12, 31)),
        (date(2025, 12, 31), date(2016, 1, 1)),
        ("2016-01-01", date(2025, 12, 31)),
    ],
)
def test_unsupported_or_inexact_requested_window_denies(start: Any, end: Any) -> None:
    with pytest.raises(DomainValidationError):
        _parse(_pack(_parts()), start_date=start, end_date=end)


@pytest.mark.parametrize("duplicate_amount", [_ROW[6], "2.000000"])
def test_duplicate_spy_ex_dates_are_not_silently_deduplicated(duplicate_amount: str) -> None:
    values = list(_ROW)
    values[6] = duplicate_amount
    with pytest.raises(DomainValidationError):
        _parse(_pack(_parts((_ROW, tuple(values)))))


def test_non_spy_rows_do_not_become_distributions() -> None:
    values = list(_ROW)
    values[1] = "SPYM"
    values[2] = "000000000"
    result = _parse(_pack(_parts((tuple(values),))))
    assert result.distributions == ()
    assert "requested_window_incomplete" in result.limitations


def test_cusip_identified_spy_with_mismatched_ticker_is_not_skipped() -> None:
    values = list(_ROW)
    values[1] = "SPYM"
    with pytest.raises(DomainValidationError):
        _parse(_pack(_parts((tuple(values),))))


@pytest.mark.parametrize(
    "name,closing,extra",
    [
        ("xl/workbook.xml", "</workbook>", '<workbookPr date1904="1"/>'),
        ("xl/workbook.xml", "</workbook>", "<sheets/>"),
        ("xl/styles.xml", "</styleSheet>", '<cellXfs><xf numFmtId="0"/></cellXfs>'),
        ("xl/worksheets/sheet1.xml", "</worksheet>", "<sheetData/>"),
    ],
)
def test_duplicate_critical_xml_sections_are_ambiguous_and_deny(
    name: str,
    closing: str,
    extra: str,
) -> None:
    parts = _parts()
    _replace(parts, name, closing, extra + closing)
    with pytest.raises(DomainValidationError):
        _parse(_pack(parts))


def test_invalid_xml_in_unused_metadata_still_denies_whole_archive() -> None:
    parts = _parts()
    parts["docProps/custom.xml"] = '<!DOCTYPE a [<!ENTITY b "private-sentinel">]><a/>'
    with pytest.raises(DomainValidationError):
        _parse(_pack(parts))


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("xl/workbook.xml", 'date1904="0"', 'date1904="1"'),
        ("xl/workbook.xml", 'name="dividend"', 'name="unknown"'),
        ("xl/_rels/workbook.xml.rels", 'Target="worksheets/sheet1.xml"', 'Target="../secret.xml"'),
        (
            "xl/_rels/workbook.xml.rels",
            'Target="styles.xml"',
            'Target="https://example.invalid/private-sentinel" TargetMode="External"',
        ),
        ("xl/styles.xml", 'formatCode="0.000000"', 'formatCode="0.00%"'),
        ("xl/worksheets/sheet1.xml", '<c r="G2" t="s">', '<c r="G2" t="s" s="99">'),
        (
            "xl/worksheets/sheet1.xml",
            '<c r="G2" t="s"><v>16</v></c>',
            '<c r="G2" s="1"><v>1</v></c>',
        ),
        ("xl/worksheets/sheet1.xml", '<c r="D2" t="s"><v>13</v></c>', '<c r="D2"><v>42447</v></c>'),
        (
            "xl/worksheets/sheet1.xml",
            '<c r="D2" t="s"><v>13</v></c>',
            '<c r="D2" s="1"><v>60</v></c>',
        ),
        (
            "xl/worksheets/sheet1.xml",
            '<c r="D2" t="s"><v>13</v></c>',
            '<c r="D2" s="1"><v>42447.5</v></c>',
        ),
        (
            "xl/worksheets/sheet1.xml",
            '<c r="G2" t="s"><v>16</v></c>',
            '<c r="G2" t="s"><f>external()</f><v>16</v></c>',
        ),
        (
            "xl/worksheets/sheet1.xml",
            '<c r="G2" t="s"><v>16</v></c>',
            '<c r="G2" t="s"><v>999999</v></c>',
        ),
        (
            "xl/worksheets/sheet1.xml",
            '<c r="G2" t="s"><v>16</v></c>',
            '<c r="G2" t="e"><v>#VALUE!</v></c>',
        ),
        ("xl/worksheets/sheet1.xml", 'r="G2"', 'r="F2"'),
        ("xl/worksheets/sheet1.xml", '<row r="2">', '<row r="1">'),
        ("xl/sharedStrings.xml", "<t>EX-DATE</t>", "<t>unknown</t>"),
    ],
)
def test_unsupported_or_corrupt_schema_denies(name: str, old: str, new: str) -> None:
    parts = _parts()
    _replace(parts, name, old, new)
    with pytest.raises(DomainValidationError):
        _parse(_pack(parts))


@pytest.mark.parametrize(
    "member",
    [
        "../secret.xml",
        "/absolute.xml",
        "xl\\secret.xml",
        "xl/vbaProject.bin",
        "xl/externalLinks/externalLink1.xml",
    ],
)
def test_forbidden_zip_members_deny(member: str) -> None:
    parts = _parts()
    parts[member] = "private-sentinel"
    with pytest.raises(DomainValidationError):
        _parse(_pack(parts))


def test_external_hyperlink_metadata_is_inert_not_a_data_relationship() -> None:
    parts = _parts()
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
        f'<Relationships xmlns="{_PKG}"><Relationship Id="rId1" Type="{_REL}/hyperlink" '
        'Target="https://example.invalid/no-request" TargetMode="External"/></Relationships>'
    )
    assert len(_parse(_pack(parts)).distributions) == 1


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE sst [<!ENTITY token "private-sentinel">]><sst/>',
        '<!DOCTYPE sst SYSTEM "file:///private-sentinel"><sst/>',
        "<sst><broken></sst>",
        "<sst>" + "<a>" * 40 + "</a>" * 40 + "</sst>",
    ],
)
def test_entity_malformed_or_excessively_deep_xml_denies(xml: str) -> None:
    parts = _parts()
    parts["xl/sharedStrings.xml"] = xml
    with pytest.raises(DomainValidationError) as error:
        _parse(_pack(parts))
    assert str(error.value) == "etf_issuer_workbook_invalid"
    assert error.value.__cause__ is None


def test_digest_mismatch_and_malformed_archive_are_sanitized() -> None:
    body = _pack(_parts())
    for payload, digest in ((body, "0" * 64), (body, "NOT-A-DIGEST"), (b"private-sentinel", None)):
        with pytest.raises(DomainValidationError) as error:
            _parse(payload, digest)
        assert str(error.value) == "etf_issuer_workbook_invalid"
        assert error.value.__cause__ is None


def test_member_count_uncompressed_and_input_bounds_deny() -> None:
    parts = _parts()
    for i in range(129):
        parts[f"custom{i}.xml"] = "<a/>"
    with pytest.raises(DomainValidationError):
        _parse(_pack(parts))
    parts = _parts()
    parts["custom.xml"] = "a" * (8 * 1024 * 1024 + 1)
    with pytest.raises(DomainValidationError):
        _parse(_pack(parts))
    with pytest.raises(DomainValidationError):
        _parse(b"a" * (2 * 1024 * 1024 + 1))


def test_encrypted_zip_flag_denies_without_password_or_payload_leak() -> None:
    body = bytearray(_pack(_parts()))
    central = body.find(b"PK\x01\x02")
    local_flag = struct.unpack_from("<H", body, 6)[0]
    central_flag = struct.unpack_from("<H", body, central + 8)[0]
    struct.pack_into("<H", body, 6, local_flag | 1)
    struct.pack_into("<H", body, central + 8, central_flag | 1)
    with pytest.raises(DomainValidationError):
        _parse(bytes(body))
