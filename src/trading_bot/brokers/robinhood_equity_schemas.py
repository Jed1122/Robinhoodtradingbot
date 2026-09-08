"""Strict DTOs for authenticated Robinhood Trading MCP read shapes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr


class StrictMcpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EquityAccountDto(StrictMcpModel):
    account_number: StrictStr
    affiliate: StrictStr | None = None
    agentic_allowed: StrictBool
    brokerage_account_type: StrictStr
    deactivated: StrictBool
    is_default: StrictBool
    management_type: StrictStr | None = None
    nickname: StrictStr | None = None
    option_level: StrictStr
    permanently_deactivated: StrictBool
    rhc_account_number: StrictStr | None = None
    rhs_account_number: StrictStr
    state: StrictStr
    type: StrictStr
    unsettled_funds: StrictStr | None = None


class AccountsDataDto(StrictMcpModel):
    accounts: list[EquityAccountDto]


class AccountsResultDto(StrictMcpModel):
    data: AccountsDataDto
    guide: StrictStr


class EquityBuyingPowerDto(StrictMcpModel):
    buying_power: StrictStr
    display_currency: StrictStr
    intraday_buying_power: StrictStr | None = None
    off_intraday_buying_power: StrictStr | None = None
    unleveraged_buying_power: StrictStr


class CryptoBuyingPowerDto(StrictMcpModel):
    buying_power: StrictStr


class PortfolioDataDto(StrictMcpModel):
    buying_power: EquityBuyingPowerDto
    cash: StrictStr
    crypto_buying_power: CryptoBuyingPowerDto | None = None
    crypto_value: StrictStr
    currency: StrictStr
    equity_value: StrictStr
    event_contracts_value: StrictStr
    fixed_income_value: StrictStr
    futures_value: StrictStr
    mutual_funds_value: StrictStr
    options_value: StrictStr
    pending_deposits: StrictStr
    total_value: StrictStr


class PortfolioResultDto(StrictMcpModel):
    data: PortfolioDataDto
    guide: StrictStr


class PositionsDataDto(StrictMcpModel):
    positions: list[dict[str, object] | None]
    next: StrictStr | None = None


class PositionsResultDto(StrictMcpModel):
    data: PositionsDataDto
    guide: StrictStr


class OrdersDataDto(StrictMcpModel):
    orders: list[dict[str, object] | None]
    next: StrictStr | None = None


class OrdersResultDto(StrictMcpModel):
    data: OrdersDataDto
    guide: StrictStr


class EquityQuoteDto(StrictMcpModel):
    adjusted_previous_close: StrictStr
    ask_price: StrictStr
    bid_price: StrictStr
    has_traded: StrictBool
    last_non_reg_trade_price: StrictStr | None
    last_trade_price: StrictStr
    previous_close: StrictStr
    previous_close_date: StrictStr | None
    state: StrictStr
    symbol: StrictStr
    venue_ask_time: StrictStr
    venue_bid_time: StrictStr
    venue_last_non_reg_trade_time: StrictStr | None
    venue_last_trade_time: StrictStr


class EquityCloseDto(StrictMcpModel):
    date: StrictStr | None
    interpolated: StrictBool | None
    price: StrictStr | None
    source: StrictStr | None
    symbol: StrictStr


class EquityQuoteResultDto(StrictMcpModel):
    close: EquityCloseDto | None = None
    quote: EquityQuoteDto


class EquityQuotesDataDto(StrictMcpModel):
    results: list[EquityQuoteResultDto]
    closes_error: StrictStr | None = None


class EquityQuotesResultDto(StrictMcpModel):
    data: EquityQuotesDataDto
    guide: StrictStr


class AccountTypeTradabilityDto(StrictMcpModel):
    account_type: StrictStr
    account_type_tradability: StrictStr


class EquityTradabilityDto(StrictMcpModel):
    account_type_tradabilities: list[AccountTypeTradabilityDto] | None = None
    all_day_tradability: StrictStr | None = None
    country: StrictStr | None = None
    extended_hours_fractional_tradability: StrictBool
    fractional_tradability: StrictStr | None = None
    internal_halt_details: StrictStr | None = None
    internal_halt_end_time: StrictStr | None = None
    internal_halt_reason: StrictStr | None = None
    internal_halt_sessions: list[StrictStr] | None = None
    internal_halt_start_time: StrictStr | None = None
    name: StrictStr | None = None
    short_selling_tradability: StrictStr | None = None
    simple_name: StrictStr | None = None
    state: StrictStr | None = None
    symbol: StrictStr
    tradeable: StrictBool
    twenty_four_seven_tradability: StrictStr | None = None


class EquityTradabilityDataDto(StrictMcpModel):
    results: list[EquityTradabilityDto]
    not_found: list[StrictStr] | None = None


class EquityTradabilityResultDto(StrictMcpModel):
    data: EquityTradabilityDataDto
    guide: StrictStr


class EquityBarDto(StrictMcpModel):
    begins_at: StrictStr
    close_price: StrictStr
    high_price: StrictStr
    interpolated: StrictBool | None = None
    low_price: StrictStr
    open_price: StrictStr
    session: StrictStr
    volume: StrictInt


class EquityHistoricalResultDto(StrictMcpModel):
    bars: list[EquityBarDto]
    bounds: StrictStr
    interval: StrictStr
    symbol: StrictStr


class EquityHistoricalsDataDto(StrictMcpModel):
    results: list[EquityHistoricalResultDto]
    not_found: list[StrictStr] | None = None


class EquityHistoricalsResultDto(StrictMcpModel):
    data: EquityHistoricalsDataDto
    guide: StrictStr


__all__ = [
    "AccountsResultDto",
    "EquityAccountDto",
    "EquityBarDto",
    "EquityHistoricalResultDto",
    "EquityHistoricalsResultDto",
    "EquityQuotesResultDto",
    "EquityTradabilityResultDto",
    "OrdersResultDto",
    "PortfolioResultDto",
    "PositionsResultDto",
]
