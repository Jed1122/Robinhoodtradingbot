"""Reviewed 2016--2025 statutory equity rates, NOT Robinhood customer costs.

This is a reference catalog, not another configuration or fee engine. It
cannot construct EtfCostEvidence, backdate known_at, debit cash, or certify
broker pass-through, rounding, grouping, calibration or eligibility.
SEC epochs use charge date; FINRA epochs use trade date. No trade-to-charge
date mapping or customer rounding is inferred. Sources reviewed 2026-10-02.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from trading_bot.market_data.recording import content_hash

_START = date(2016, 1, 1)
_END = date(2026, 1, 1)
_FINRA = "https://www.finra.org/sites/default/files/2020-10/NOF%20IMM%20EFF%20FINRA-2020-032.pdf"
_SEC = (
    ("2016-01-01", "18.40", "https://www.sec.gov/news/pressrelease/2016-2.html"),
    ("2016-02-16", "21.80", "https://www.sec.gov/news/pressrelease/2016-2.html"),
    ("2017-07-04", "23.10", "https://www.sec.gov/newsroom/press-releases/2017-111"),
    ("2018-05-22", "13.00", "https://www.sec.gov/newsroom/press-releases/2018-67"),
    ("2019-04-16", "20.70", "https://www.sec.gov/newsroom/press-releases/2019-30"),
    ("2020-02-18", "22.10", "https://www.sec.gov/newsroom/press-releases/2020-7"),
    ("2021-02-25", "5.10", "https://www.sec.gov/newsroom/press-releases/2021-8"),
    ("2022-05-14", "22.90", "https://www.sec.gov/newsroom/press-releases/2022-60"),
    ("2023-02-27", "8.00", "https://www.sec.gov/newsroom/press-releases/2023-15"),
    ("2024-05-22", "27.80", "https://www.sec.gov/rules-regulations/fee-rate-advisories/2024-2"),
    ("2025-05-14", "0.00", "https://www.sec.gov/rules-regulations/fee-rate-advisories/2025-2"),
)
_TAF = (
    ("2016-01-01", "0.000119", "5.95"),
    ("2022-01-01", "0.000130", "6.49"),
    ("2023-01-01", "0.000145", "7.27"),
    ("2024-01-01", "0.000166", "8.30"),
)


@dataclass(frozen=True, slots=True)
class EquityStatutoryFeeReference:
    role: Literal["sec_section31", "finra_member_taf"]
    starts_on: date
    ends_before: date
    rate: Decimal
    unit: Literal["USD/million_USD_covered_sales", "USD/share_covered_sales"]
    date_basis: Literal["charge_date", "trade_date"]
    source_url: str
    maximum_usd: Decimal | None = None
    scope: Literal["statutory_reference_only"] = field(
        default="statutory_reference_only", init=False
    )
    rounding_rule: None = field(default=None, init=False)
    customer_costs_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def fee_reference_catalog() -> tuple[EquityStatutoryFeeReference, ...]:
    """Immutable code-owned source facts; no arbitrary rate manifest is accepted."""
    rows = []
    for index, (start, rate, url) in enumerate(_SEC):
        end = date.fromisoformat(_SEC[index + 1][0]) if index + 1 < len(_SEC) else _END
        rows.append(
            EquityStatutoryFeeReference(
                "sec_section31",
                date.fromisoformat(start),
                end,
                Decimal(rate),
                "USD/million_USD_covered_sales",
                "charge_date",
                url,
            )
        )
    for index, (start, rate, maximum) in enumerate(_TAF):
        end = date.fromisoformat(_TAF[index + 1][0]) if index + 1 < len(_TAF) else _END
        rows.append(
            EquityStatutoryFeeReference(
                "finra_member_taf",
                date.fromisoformat(start),
                end,
                Decimal(rate),
                "USD/share_covered_sales",
                "trade_date",
                _FINRA,
                Decimal(maximum),
            )
        )
    return tuple(rows)


def fee_reference_catalog_hash() -> str:
    return content_hash(("etf-statutory-equity-fee-reference-v1", fee_reference_catalog()))


def _lookup(role: str, day: date) -> EquityStatutoryFeeReference:
    if type(day) is not date or not _START <= day < _END:
        raise ValueError("etf_fee_reference_invalid")
    return next(
        row
        for row in fee_reference_catalog()
        if row.role == role and row.starts_on <= day < row.ends_before
    )


def sec_equity_reference(*, charge_date: date) -> EquityStatutoryFeeReference:
    return _lookup("sec_section31", charge_date)


def taf_equity_reference(*, trade_date: date) -> EquityStatutoryFeeReference:
    return _lookup("finra_member_taf", trade_date)
