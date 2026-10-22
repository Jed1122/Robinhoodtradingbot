"""Bounded public-source normalization. Raw text never enters research instructions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("UTC timestamp required")
    return value


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value):
        raise ValueError("invalid structured identifier")
    return value


@dataclass(frozen=True)
class SourceFact:
    symbol: str
    metric: str
    value: Decimal
    period_end: datetime
    available_at: datetime
    source_url: str
    event_id: str
    period_start: datetime | None = None

    def __post_init__(self) -> None:
        identifier(self.symbol)
        identifier(self.metric)
        identifier(self.event_id)
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("finite Decimal required")
        if self.period_start is not None and utc(self.period_start) > utc(self.period_end):
            raise ValueError("invalid duration period")
        if abs(self.value) > Decimal("1e30"):
            raise ValueError("numeric magnitude unsupported")
        if utc(self.available_at) < utc(self.period_end):
            raise ValueError("availability precedes period")
        parsed = urlsplit(self.source_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"data.sec.gov", "api.stlouisfed.org"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("public source URL required without secrets")


def visible_facts(facts: tuple[SourceFact, ...], as_of: datetime) -> tuple[SourceFact, ...]:
    utc(as_of)
    unique: dict[tuple[str, str, str], SourceFact] = {}
    for fact in facts:
        key = (fact.symbol, fact.metric, fact.event_id)
        existing = unique.get(key)
        if existing is not None:
            if replace(existing, available_at=fact.available_at) != fact:
                raise ValueError("conflicting duplicate source event")
            unique[key] = min((existing, fact), key=lambda f: f.available_at)
        else:
            unique[key] = fact
    return tuple(
        sorted(
            (f for f in unique.values() if f.available_at <= as_of),
            key=lambda f: (f.symbol, f.metric, f.period_end, f.available_at, f.event_id),
        )
    )


class PublicResearchClient:
    """Caller must inject transport; never opens a default network transport.

    Date-only source availability uses next UTC midnight, then receipt time,
    whichever is later. Newly fetched current aggregates cannot backfill an earlier
    historical decision. No response bodies, free text, credentials or errors persist.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport,
        *,
        sec_user_agent: str = "HybridResearch contact-unconfigured",
        max_response_bytes: int = 10_000_000,
    ) -> None:
        if (
            not sec_user_agent
            or len(sec_user_agent) > 256
            or any(ord(c) < 32 or ord(c) > 126 for c in sec_user_agent)
        ):
            raise ValueError("invalid SEC User-Agent")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 10_000_000:
            raise ValueError("invalid response bound")
        self._transport = transport
        self._sec_user_agent = sec_user_agent
        self._max_response_bytes = max_response_bytes

    def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        headers = {"Accept-Encoding": "identity"}
        if urlsplit(url).hostname == "data.sec.gov":
            headers["User-Agent"] = self._sec_user_agent
        try:
            with (
                httpx.Client(
                    transport=self._transport, timeout=10, follow_redirects=False
                ) as client,
                client.stream("GET", url, params=params, headers=headers) as response,
            ):
                if response.status_code != 200:
                    raise ValueError("public source unavailable")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("unsupported public source encoding")
                body = bytearray()
                chunks = (
                    response.iter_bytes() if response.is_stream_consumed else response.iter_raw()
                )
                for chunk in chunks:
                    if len(body) + len(chunk) > self._max_response_bytes:
                        raise ValueError("public source oversized")
                    body.extend(chunk)
                payload = json.loads(body)
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise ValueError("public source unavailable or invalid") from None
        if not isinstance(payload, dict):
            raise ValueError("invalid public source schema")
        return payload

    @staticmethod
    def _cik(cik: str) -> str:
        if not re.fullmatch(r"[0-9]{1,10}", cik):
            raise ValueError("invalid CIK")
        return cik.zfill(10)

    def sec_facts(self, symbol: str, cik: str, received_at: datetime) -> tuple[SourceFact, ...]:
        utc(received_at)
        identifier(symbol)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self._cik(cik)}.json"
        payload = self._get(url)
        result = []
        # Deliberately raw financial amounts; ratios need period-matched derivation.
        tags = {
            "Assets": "assets",
            "StockholdersEquity": "equity",
            "NetIncomeLoss": "net_income",
            "Revenues": "revenue",
        }
        for tag, metric in tags.items():
            units = payload.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
            for row in units.get("USD", []):
                end = datetime.fromisoformat(row["end"]).replace(tzinfo=UTC)
                filed = datetime.fromisoformat(row["filed"]).replace(tzinfo=UTC) + timedelta(days=1)
                start = (
                    datetime.fromisoformat(row["start"]).replace(tzinfo=UTC)
                    if "start" in row
                    else None
                )
                event = identifier(f"{row['accn']}:{row.get('start', 'instant')}:{row['end']}")
                available = max(filed, received_at)
                if available <= received_at:
                    result.append(
                        SourceFact(
                            symbol,
                            metric,
                            Decimal(str(row["val"])),
                            end,
                            available,
                            url,
                            event,
                            start,
                        )
                    )
        return visible_facts(tuple(result), received_at)

    def sec_submissions(
        self, symbol: str, cik: str, received_at: datetime
    ) -> tuple[SourceFact, ...]:
        utc(received_at)
        identifier(symbol)
        url = f"https://data.sec.gov/submissions/CIK{self._cik(cik)}.json"
        recent = self._get(url).get("filings", {}).get("recent", {})
        result = []
        for form, accession, filed in zip(
            recent.get("form", []),
            recent.get("accessionNumber", []),
            recent.get("filingDate", []),
            strict=True,
        ):
            if form not in {"10-K", "10-Q", "8-K"}:
                continue
            day = datetime.fromisoformat(filed).replace(tzinfo=UTC)
            available = max(day + timedelta(days=1), received_at)
            if available <= received_at:
                result.append(
                    SourceFact(
                        symbol,
                        "filing_event",
                        Decimal(1),
                        day,
                        available,
                        url,
                        identifier(accession),
                    )
                )
        return visible_facts(tuple(result), received_at)

    def fred_observations(
        self, series: str, received_at: datetime, *, api_key: str | None = None
    ) -> tuple[SourceFact, ...]:
        """Optional adapter for transport-supplied FRED responses; credentials are external.

        A custom transport may inject authentication outside this layer. This method
        accepts an optional key only for request construction, never returned source URLs.
        No transport exception details escape. Realtime vintage is preserved in identity.
        """
        identifier(series)
        utc(received_at)
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {"series_id": series, "file_type": "json"}
        if api_key is not None:
            if (
                not api_key
                or len(api_key) > 256
                or not api_key.isascii()
                or not re.fullmatch(r"[A-Za-z0-9_-]+", api_key)
            ):
                raise ValueError("invalid FRED authentication input")
            params["api_key"] = api_key
        payload = self._get(url, params)
        result = []
        for row in payload.get("observations", []):
            if row["value"] == ".":
                continue
            day = datetime.fromisoformat(row["date"]).replace(tzinfo=UTC)
            vintage = datetime.fromisoformat(row["realtime_start"]).replace(tzinfo=UTC)
            available = max(day, vintage) + timedelta(days=1)
            available = max(available, received_at)
            if available <= received_at:
                event = identifier(f"{row['date']}:{row['realtime_start']}")
                result.append(
                    SourceFact(
                        series, "macro_value", Decimal(row["value"]), day, available, url, event
                    )
                )
        return visible_facts(tuple(result), received_at)
