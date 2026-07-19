from types import SimpleNamespace

from trading_bot.reporting.tax import build_tax_rows


def test_missing_basis_is_unknown() -> None:
    assert build_tax_rows((SimpleNamespace(id="f"),))[0].cost_basis_status == "unknown"
