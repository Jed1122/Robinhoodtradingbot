from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.brokers.robinhood_equity_mapping import EquityMappingError, map_account
from trading_bot.brokers.robinhood_equity_schemas import AccountsResultDto, PortfolioResultDto
from trading_bot.domain import AssetClass, DataHash

NOW = datetime(2026, 7, 21, 18, tzinfo=UTC)


def account_payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "account_number": "synthetic-account",
        "affiliate": "synthetic-affiliate",
        "agentic_allowed": True,
        "brokerage_account_type": "individual",
        "deactivated": False,
        "is_default": True,
        "management_type": "self_directed",
        "nickname": None,
        "option_level": "none",
        "permanently_deactivated": False,
        "rhc_account_number": None,
        "rhs_account_number": "synthetic-brokerage-account",
        "state": "active",
        "type": "cash",
    }
    value.update(overrides)
    return value


def portfolio_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "buying_power": {
            "buying_power": "125.50",
            "display_currency": "USD",
            "unleveraged_buying_power": "125.50",
        },
        "cash": "125.50",
        "crypto_value": "0",
        "currency": "USD",
        "equity_value": "125.50",
        "event_contracts_value": "0",
        "fixed_income_value": "0",
        "futures_value": "0",
        "mutual_funds_value": "0",
        "options_value": "0",
        "pending_deposits": "0",
        "total_value": "125.50",
    }
    data.update(overrides)
    return {"data": data, "guide": "synthetic-read-shape"}


def parsed_account(**overrides: object):
    response = AccountsResultDto.model_validate(
        {
            "data": {"accounts": [account_payload(**overrides)]},
            "guide": "synthetic-read-shape",
        }
    )
    return response.data.accounts[0]


def test_strict_account_and_portfolio_shapes_map_exact_cash_values() -> None:
    portfolio = PortfolioResultDto.model_validate(portfolio_payload())

    snapshot = map_account(
        parsed_account(),
        portfolio,
        observed_at=NOW,
        data_hash=DataHash("a" * 64),
    )

    assert snapshot.equity == Decimal("125.50")
    assert snapshot.cash == Decimal("125.50")
    assert snapshot.buying_power_for(AssetClass.EQUITY) == Decimal("125.50")
    assert not snapshot.restricted
    assert snapshot.observed_at == NOW


@pytest.mark.parametrize(
    "payload",
    (
        {
            "data": {
                "accounts": [account_payload(unreviewed_provider_field="value")],
            },
            "guide": "synthetic-read-shape",
        },
        portfolio_payload(cash=125.50),
        {**portfolio_payload(), "unreviewed_provider_field": "value"},
    ),
)
def test_unreviewed_or_coerced_account_and_portfolio_shapes_fail(
    payload: dict[str, object],
) -> None:
    model = AccountsResultDto if "accounts" in payload.get("data", {}) else PortfolioResultDto
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("account_overrides", "portfolio_overrides", "message"),
    (
        ({"type": "margin"}, {}, "individual cash account"),
        ({"brokerage_account_type": "joint"}, {}, "individual cash account"),
        ({}, {"currency": "EUR"}, "USD"),
        (
            {},
            {
                "buying_power": {
                    "buying_power": "250.00",
                    "display_currency": "USD",
                    "unleveraged_buying_power": "125.50",
                }
            },
            "leverage",
        ),
    ),
)
def test_account_mapping_fails_closed_on_unreviewed_semantics(
    account_overrides: dict[str, object],
    portfolio_overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(EquityMappingError, match=message):
        map_account(
            parsed_account(**account_overrides),
            PortfolioResultDto.model_validate(portfolio_payload(**portfolio_overrides)),
            observed_at=NOW,
            data_hash=DataHash("a" * 64),
        )
