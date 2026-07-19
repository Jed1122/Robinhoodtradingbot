"""Equity mapping boundary remains empty until authenticated shape evidence exists."""

VERIFIED_EQUITY_FIELDS: tuple[str, ...] = ()


def mapping_ready() -> bool:
    return bool(VERIFIED_EQUITY_FIELDS)


__all__ = ["VERIFIED_EQUITY_FIELDS", "mapping_ready"]
