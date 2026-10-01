"""Bounded bytes-only State Street SPY distribution import; never source qualification.

Contract: SHA256 binds the exact supplied XLSX bytes. The supported public workbook
has one ``dividend`` sheet with the ten fixed headers below, SPY CUSIP 78462F103,
MM/DD/YYYY shared-string dates and decimal-text amounts. Verified numeric variants
use Excel's 1900 epoch and built-in date format 14, or custom amount format 164
(``0.000000``). Unsupported styles, formulas, macros, external data relationships,
entities, unclassifiable SPY ex-dates, corrupt in-window financial records and
duplicate in-window SPY ex-dates deny the whole import.

All SPY ex-dates are classified before retaining the explicit 2016--2025 window.
Financial validation is scoped to that window, and excluded SPY rows are counted.
Out-of-window anomalies are not repaired or treated as valid financial records.
Four quarterly rows per year is a coverage diagnostic, not a completeness or authenticity verdict;
missing coverage returns a limitation. Amount Decimal construction uses exact XML
text, never a float. Each row hash binds source bytes, ordinal, dates and original
financial text. No publication/correction timestamp is inferred from ex/record/pay
dates or workbook metadata. This is latest-vintage research under an explicit
point-in-time waiver, with qualification/promotion/execution flags fixed false.

No paths, networking, credentials, corporate-action scheduling, eligible-share or
portfolio accounting logic belongs here. The caller retains source bytes and
independently establishes retrieval, licensing and any later research authority.
Public source: https://www.ssga.com/library-content/products/fund-data/etfs/us/
spdr-etf-historical-distributions.xlsx ; issuer context:
https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Literal, cast

# Stdlib only: bounded UTF-8 with DTD/entities denied by _xml before parsing.
from xml.etree import ElementTree as ET  # nosec B405
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_sha256_hex,
    require_bounded_decimal,
)
from trading_bot.market_data.bundle_codec import _date
from trading_bot.market_data.recording import content_hash

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
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
_BASE_LIMITATIONS = (
    "original_publication_and_correction_history_unverified",
    "source_authenticity_and_license_unverified",
    "latest_vintage_point_in_time_waived_research_only",
)
_MAX_INPUT = 2 * 1024 * 1024
_MAX_MEMBER = 8 * 1024 * 1024
_MAX_EXPANDED = 12 * 1024 * 1024
_ERROR = "etf_issuer_workbook_invalid"
_CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,5})\Z")
_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,5})\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,31})(?:\.[0-9]{1,32})?\Z")


def _check(condition: bool) -> None:
    if not condition:
        raise DomainValidationError(_ERROR)


@dataclass(frozen=True, slots=True)
class EtfIssuerDistribution:
    ex_date: date
    record_date: date
    pay_date: date
    amount: Decimal
    row_hash: str

    def __post_init__(self) -> None:
        _check(
            all(type(value) is date for value in (self.ex_date, self.record_date, self.pay_date))
        )
        _check(
            date(1990, 1, 1)
            <= self.ex_date
            <= self.record_date
            <= self.pay_date
            <= date(2100, 12, 31)
        )
        require_bounded_decimal(self.amount, "issuer amount", positive=True)
        _require_sha256_hex(self.row_hash, "issuer row")


@dataclass(frozen=True, slots=True)
class EtfIssuerDistributionArchive:
    source_hash: str
    start_date: date
    end_date: date
    distributions: tuple[EtfIssuerDistribution, ...]
    excluded_spy_rows: int
    limitations: tuple[str, ...]
    archive_hash: str
    vintage: Literal["latest_vintage"] = field(default="latest_vintage", init=False)
    source_kind: Literal["issuer_workbook"] = field(default="issuer_workbook", init=False)
    point_in_time_qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    production_pretrade_eligible: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.source_hash, "issuer source")
        _window(self.start_date, self.end_date)
        _check(type(self.excluded_spy_rows) is int and 0 <= self.excluded_spy_rows <= 200)
        _check(type(self.distributions) is tuple and len(self.distributions) <= 200)
        _check(all(type(item) is EtfIssuerDistribution for item in self.distributions))
        days = tuple(item.ex_date for item in self.distributions)
        _check(days == tuple(sorted(set(days))))
        _check(all(2016 <= day.year <= 2025 for day in days))
        _check(
            self.limitations
            in (_BASE_LIMITATIONS, (*_BASE_LIMITATIONS, "requested_window_incomplete"))
        )
        _require_sha256_hex(self.archive_hash, "issuer archive")
        _check(
            self.archive_hash
            == _archive_hash(
                self.source_hash,
                self.start_date,
                self.end_date,
                self.distributions,
                self.excluded_spy_rows,
                self.limitations,
            )
        )


def _xml(body: bytes) -> ET.Element:
    # UTF-8-only denies UTF-16 disguises of entity declarations before parsing.
    text = body.decode("utf-8")
    _check("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper())
    depth = count = 0
    root: ET.Element | None = None
    # Only bounded UTF-8 with DTD/entities rejected reaches this parser.
    for event, node in ET.iterparse(io.StringIO(text), events=("start", "end")):  # nosec B314
        if event == "start":
            if root is None:
                root = node
            depth += 1
            count += 1
            _check(depth <= 32 and count <= 500_000 and len(node.attrib) <= 32)
            _check(
                all(len(key) <= 256 and len(value) <= 4096 for key, value in node.attrib.items())
            )
        else:
            _check(len(node.text or "") <= 8192 and len(node.tail or "") <= 8192)
            depth -= 1
    _check(root is not None and depth == 0)
    return cast(ET.Element, root)


def _parts(body: bytes) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    with ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        _check(1 <= len(members) <= 128)
        names = [item.filename for item in members]
        _check(len(names) == len(set(names)))
        _check(sum(item.file_size for item in members) <= _MAX_EXPANDED)
        for item in members:
            name = item.filename
            path = PurePosixPath(name)
            _check(0 < len(name) <= 128 and not path.is_absolute())
            _check(str(path) == name and ".." not in path.parts and "\\" not in name)
            _check(not item.is_dir() and not item.flag_bits & 1)
            _check(item.compress_type in (ZIP_STORED, ZIP_DEFLATED))
            _check(0 < item.file_size <= _MAX_MEMBER)
            _check(item.file_size <= max(1, item.compress_size) * 100)
            _check((item.external_attr >> 16) & 0o170000 not in (0o120000, 0o040000))
            forbidden = (
                "vbaproject",
                "externallinks",
                "activex",
                "embeddings",
                "connections",
                "querytables",
            )
            _check(not any(token in name.lower() for token in forbidden))
            raw = archive.read(item)
            _check(len(raw) == item.file_size)
            if name.endswith((".xml", ".rels")):
                result[name] = _xml(raw)
            else:
                _check(
                    re.fullmatch(r"xl/printerSettings/printerSettings[1-9][0-9]*\.bin", name)
                    is not None
                )
    for name, root in result.items():
        if name.endswith(".rels"):
            _relationships(root)
    content = result["[Content_Types].xml"]
    _check(content.tag == f"{{{_CONTENT}}}Types")
    for declaration in content:
        kind = declaration.get("ContentType", "").lower()
        _check(not any(token in kind for token in ("macro", "vba", "activex", "external")))
    main = [item for item in content if item.get("PartName") == "/xl/workbook.xml"]
    _check(
        len(main) == 1
        and main[0].get("ContentType")
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    return result


def _relationships(root: ET.Element) -> dict[str, ET.Element]:
    _check(root.tag == f"{{{_PKG}}}Relationships" and len(root) <= 128)
    result = {}
    for item in root:
        _check(item.tag == f"{{{_PKG}}}Relationship")
        identifier, target, kind = item.get("Id", ""), item.get("Target", ""), item.get("Type", "")
        _check(bool(identifier) and identifier not in result and bool(target) and bool(kind))
        _check(item.get("TargetMode") in (None, "External"))
        if item.get("TargetMode") == "External":
            # Inert hyperlink metadata is never resolved, fetched or used as data.
            _check(kind == f"{_REL}/hyperlink")
        else:
            _check(":" not in target and "\\" not in target and not target.startswith("/"))
            _check(
                not any(
                    token in kind.lower()
                    for token in ("externallink", "vba", "oleobject", "connection")
                )
            )
        result[identifier] = item
    return result


def _one(root: ET.Element, name: str) -> ET.Element | None:
    matches = root.findall(f"{{{_NS}}}{name}")
    _check(len(matches) <= 1)
    return matches[0] if matches else None


def _styles(root: ET.Element) -> tuple[int, ...]:
    _check(root.tag == f"{{{_NS}}}styleSheet")
    formats = _one(root, "numFmts")
    identifiers: set[str] = set()
    if formats is not None:
        _check(len(formats) <= 128)
        for item in formats:
            identifier = item.get("numFmtId", "")
            _check(identifier not in identifiers)
            identifiers.add(identifier)
            if identifier == "164":
                _check(item.get("formatCode") == "0.000000")
    xfs = _one(root, "cellXfs")
    _check(xfs is not None and 1 <= len(xfs) <= 128)
    result = tuple(_integer(item.get("numFmtId", "")) for item in cast(ET.Element, xfs))
    _check(164 not in result or "164" in identifiers)
    return result


def _integer(text: str) -> int:
    _check(_INTEGER.fullmatch(text) is not None)
    return int(text)


def _shared_strings(root: ET.Element) -> tuple[str, ...]:
    _check(root.tag == f"{{{_NS}}}sst" and len(root) <= 30_000)
    values = []
    for item in root:
        _check(item.tag == f"{{{_NS}}}si")
        value = "".join(node.text or "" for node in item.iter(f"{{{_NS}}}t"))
        _check(len(value) <= 8192)
        values.append(value)
    return tuple(values)


def _cell(
    cell: ET.Element, strings: tuple[str, ...], styles: tuple[int, ...]
) -> tuple[str, int, str]:
    _check(cell.tag == f"{{{_NS}}}c")
    _check(all(node.tag == f"{{{_NS}}}v" for node in cell) and len(cell) <= 1)
    kind = cell.get("t", "n")
    _check(kind in ("s", "n"))
    style = _integer(cell.get("s", "0"))
    _check(style < len(styles))
    value = cell[0].text or "" if len(cell) else ""
    if kind == "s":
        index = _integer(value)
        _check(index < len(strings))
        value = strings[index]
    return value, styles[style], kind


def _dated(cell: tuple[str, int, str]) -> date:
    text, style, kind = cell
    if kind == "s":
        _check(style in (0, 14) and re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", text) is not None)
        result = _date(f"{text[6:10]}-{text[0:2]}-{text[3:5]}")
    else:
        _check(style == 14)
        serial = _integer(text)
        _check(serial > 60)
        result = date(1899, 12, 30) + timedelta(days=serial)
    _check(date(1990, 1, 1) <= result <= date(2100, 12, 31))
    return result


def _amount(cell: tuple[str, int, str], *, positive: bool) -> Decimal:
    text, style, _ = cell
    _check(style in (0, 164) and len(text) <= 65 and _DECIMAL.fullmatch(text) is not None)
    return require_bounded_decimal(
        Decimal(text), "issuer amount", positive=positive, nonnegative=True
    )


def _distributions(
    parts: dict[str, ET.Element],
    source_hash: str,
    start_date: date,
    end_date: date,
) -> tuple[tuple[EtfIssuerDistribution, ...], int]:
    workbook = parts["xl/workbook.xml"]
    _check(workbook.tag == f"{{{_NS}}}workbook")
    properties = _one(workbook, "workbookPr")
    _check(properties is None or properties.get("date1904", "0") in ("0", "false"))
    sheets = _one(workbook, "sheets")
    _check(sheets is not None and len(sheets) == 1)
    sheet = cast(ET.Element, sheets)[0]
    _check(sheet.tag == f"{{{_NS}}}sheet" and sheet.get("name") == "dividend")
    _check(sheet.get("state", "visible") == "visible")
    relationships = _relationships(parts["xl/_rels/workbook.xml.rels"])
    relation = relationships[sheet.get(f"{{{_REL}}}id", "")]
    _check(
        relation.get("Type") == f"{_REL}/worksheet"
        and relation.get("Target") == "worksheets/sheet1.xml"
    )
    for kind, target in (("styles", "styles.xml"), ("sharedStrings", "sharedStrings.xml")):
        _check(
            sum(
                item.get("Type") == f"{_REL}/{kind}" and item.get("Target") == target
                for item in relationships.values()
            )
            == 1
        )
    root_relationships = _relationships(parts["_rels/.rels"])
    _check(
        sum(
            item.get("Type") == f"{_REL}/officeDocument" and item.get("Target") == "xl/workbook.xml"
            for item in root_relationships.values()
        )
        == 1
    )
    styles = _styles(parts["xl/styles.xml"])
    strings = _shared_strings(parts["xl/sharedStrings.xml"])
    worksheet = parts["xl/worksheets/sheet1.xml"]
    _check(worksheet.tag == f"{{{_NS}}}worksheet")
    data = _one(worksheet, "sheetData")
    _check(data is not None and 1 <= len(data) <= 20_000)
    result: list[EtfIssuerDistribution] = []
    previous = 0
    excluded = 0
    ex_dates: set[date] = set()
    for row in cast(ET.Element, data):
        _check(row.tag == f"{{{_NS}}}row")
        ordinal = _integer(row.get("r", ""))
        _check(previous < ordinal <= 20_000 and len(row) <= 32)
        cells = {}
        for cell in row:
            match = _CELL.fullmatch(cell.get("r", ""))
            _check(match is not None)
            col, number = cast(re.Match[str], match).groups()
            _check(int(number) == ordinal and col not in cells)
            cells[col] = _cell(cell, strings, styles)
        if previous == 0:
            _check(
                ordinal == 1
                and tuple(cells.get(chr(65 + i), ("", 0, ""))[0] for i in range(10)) == _HEADERS
            )
        elif (
            cells.get("B", ("", 0, ""))[0] == "SPY" or cells.get("C", ("", 0, ""))[0] == "78462F103"
        ):
            _check(set(cells) == set("ABCDEFGHIJ"))
            _check(cells["B"][1] == cells["C"][1] == cells["J"][1] == 0)
            _check(cells["B"][0] == "SPY" and cells["C"][0] == "78462F103")
            ex_day = _dated(cells["D"])
            _check(len(ex_dates) + excluded < 200)
            if not start_date <= ex_day <= end_date:
                excluded += 1
                previous = ordinal
                continue
            _check(cells["J"][0] == "Quarterly")
            record_day, pay_day = (_dated(cells[col]) for col in "EF")
            amount = _amount(cells["G"], positive=True)
            for col in "HI":
                _check(cells[col][1] in (0, 164))
                if cells[col][0]:
                    _check(_amount(cells[col], positive=False) == 0)
            _check(ex_day not in ex_dates)
            ex_dates.add(ex_day)
            row_hash = str(
                content_hash(
                    {
                        "schema": "spy-issuer-distribution-v1",
                        "source_hash": source_hash,
                        "source_row": ordinal,
                        "ex_date": ex_day,
                        "record_date": record_day,
                        "pay_date": pay_day,
                        "financial_text": tuple(cells[col][0] for col in "GHI"),
                    }
                )
            )
            item = EtfIssuerDistribution(ex_day, record_day, pay_day, amount, row_hash)
            result.append(item)
        previous = ordinal
    return tuple(sorted(result, key=lambda item: item.ex_date)), excluded


def _window(start_date: date, end_date: date) -> None:
    _check(type(start_date) is date and type(end_date) is date)
    _check(start_date == date(2016, 1, 1) and end_date == date(2025, 12, 31))


def _archive_hash(
    source_hash: str,
    start_date: date,
    end_date: date,
    rows: tuple[EtfIssuerDistribution, ...],
    excluded: int,
    limitations: tuple[str, ...],
) -> str:
    return str(
        content_hash(
            {
                "schema": "spy-issuer-distribution-archive-v1",
                "source_hash": source_hash,
                "start_date": start_date,
                "end_date": end_date,
                "distributions": rows,
                "excluded_spy_rows": excluded,
                "limitations": limitations,
                "vintage": "latest_vintage",
                "source_kind": "issuer_workbook",
                "point_in_time_qualified": False,
                "source_qualified": False,
                "evidence_promotable": False,
                "production_pretrade_eligible": False,
            }
        )
    )


def parse_spy_issuer_distributions(
    body: bytes,
    expected_sha256: str,
    *,
    start_date: date,
    end_date: date,
) -> EtfIssuerDistributionArchive:
    """Verify exact immutable bytes and return only latest-vintage 2016--2025 SPY rows.

    Fixed bounds: 2 MiB compressed input, 128 members, 8 MiB per member, 12 MiB
    expanded archive, compression ratio 100, XML depth 32 / 500,000 nodes, 20,000
    worksheet rows, 30,000 shared strings, 200 SPY rows. Errors are sanitized.
    Original publication/correction history, licensing and source qualification
    remain unverified even when all forty quarterly records are present.
    """
    try:
        _window(start_date, end_date)
        _check(type(body) is bytes and 0 < len(body) <= _MAX_INPUT)
        _require_sha256_hex(expected_sha256, "issuer expected source")
        _check(hashlib.sha256(body).hexdigest() == expected_sha256)
        rows, excluded = _distributions(_parts(body), expected_sha256, start_date, end_date)
        quarters = {(item.ex_date.year, (item.ex_date.month - 1) // 3) for item in rows}
        expected = {(year, quarter) for year in range(2016, 2026) for quarter in range(4)}
        limitations: tuple[str, ...] = _BASE_LIMITATIONS
        if len(rows) != 40 or quarters != expected:
            limitations = (*limitations, "requested_window_incomplete")
        return EtfIssuerDistributionArchive(
            expected_sha256,
            start_date,
            end_date,
            rows,
            excluded,
            limitations,
            _archive_hash(expected_sha256, start_date, end_date, rows, excluded, limitations),
        )
    except Exception:
        # Raise outside the handler: no raw exception context, member names or values.
        error = DomainValidationError(_ERROR)
    raise error
