"""Pure experimental execution: reserve before fill, keep ambiguity encumbered."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.accounting import buy_lot, dispose
from trading_bot.hybrid.models import (
    Account,
    AllocationEpisode,
    ExitProgress,
    FillFact,
    PaperOrder,
    Quote,
    Settlement,
)

ZERO = Decimal(0)


def mark_equity(account: Account, quotes: dict[str, Quote]) -> Decimal:
    if any(lot.symbol not in quotes for lot in account.lots):
        raise ValueError("missing exposure data")
    return (
        account.cash
        + sum((item.amount for item in account.settlements), ZERO)
        + sum((lot.quantity * quotes[lot.symbol].bid for lot in account.lots), ZERO)
    )


def _update(account: Account, **changes: object) -> Account:
    return Account.model_validate(account.model_dump() | changes)


def reserve_order(
    account: Account,
    order: PaperOrder,
    quote: Quote,
    now: datetime,
    policy: HybridSettings,
    *,
    exposure_quotes: dict[str, Quote] | None = None,
) -> Account:
    require_utc(now)
    quotes = (exposure_quotes or {}) | {quote.symbol: quote}
    if account.kill_switch or account.paused:
        raise ValueError("kill switch or suspension blocks new orders")
    if (
        order.symbol != quote.symbol
        or not quote.tradable
        or quote.halted
        or not quote.regular_session
        or quote.ask < quote.bid
        or not ZERO <= Decimal(str((now - quote.as_of).total_seconds())) <= 5
    ):
        raise ValueError("quote, market session or tradability invalid")
    if (quote.ask - quote.bid) / quote.ask > Decimal(".0035"):
        raise ValueError("spread exceeds limit")
    if order.quantity % Decimal(".000001") != 0:
        raise ValueError("quantity precision unsupported")
    fractional = order.quantity != order.quantity.to_integral_value()
    if fractional and (not quote.fractional or order.limit_price is not None):
        raise ValueError("fractional orders require eligible regular-hours market execution")
    active = tuple(o for o in account.orders if o.status in {"open", "partial"})
    if any(o.id == order.id for o in account.orders) or any(
        o.symbol == order.symbol for o in active
    ):
        raise ValueError("duplicate order or pending symbol")
    if (
        order.filled
        or order.reserved_cash
        or order.status != "open"
        or (order.threshold and order.threshold in account.completed_thresholds)
    ):
        raise ValueError("order must be new and threshold unused")
    equity = mark_equity(account, quotes)
    for symbol in {lot.symbol for lot in account.lots}:
        mark = quotes[symbol]
        if not 0 <= (now - mark.as_of).total_seconds() <= 5 or mark.bid > mark.ask:
            raise ValueError("stale exposure mark")
    drawdown = (account.high_watermark - equity) / account.high_watermark * 100
    daily_loss = (account.daily_reference - equity) / account.daily_reference * 100
    if order.side == "buy":
        if any(episode.id == (order.episode_id or order.id) for episode in account.episodes):
            raise ValueError("additional capital requires a new allocation episode")
        if order.sleeve == "tactical" and (
            equity <= 0 or daily_loss >= 1 or drawdown >= 10 or account.tactical_suspended
        ):
            raise ValueError("loss suspension blocks tactical entries")
        if (
            quote.average_dollar_volume is None
            or quote.average_dollar_volume < 20000000
            or quote.ask < 10
            or not quote.earnings_clear
        ):
            raise ValueError("liquidity or event evidence missing")
        if not quote.diversified_etf and not quote.sector:
            raise ValueError("sector exposure unknown")
        executable_price = max(
            quote.ask * (1 + policy.simulation_slippage_bps / 10000), order.limit_price or ZERO
        )
        reserved = order.quantity * executable_price
        reserved += policy.simulation_fee_usd
        if reserved > account.buying_power:
            raise ValueError("insufficient buying power")
        if account.buying_power - reserved < equity * policy.reserve_pct / 100:
            raise ValueError("liquidity reserve would be breached")
        symbol_exposure = sum(
            (
                lot.quantity * quotes[lot.symbol].ask
                for lot in account.lots
                if lot.symbol == order.symbol
            ),
            ZERO,
        )
        cap = policy.long_term_pct if quote.diversified_etf else policy.company_pct
        if order.sleeve == "tactical":
            cap = min(cap, policy.tactical_position_pct)
            if order.risk_stop is None or not ZERO < order.risk_stop < quote.bid:
                raise ValueError("tactical risk stop required")
            if order.quantity * (reserved / order.quantity - order.risk_stop) > equity * Decimal(
                ".005"
            ):
                raise ValueError("trade risk exceeds limit")
        if symbol_exposure + reserved > equity * cap / 100:
            raise ValueError("position concentration exceeded")
        sleeve_value = sum(
            (
                lot.quantity * quotes[lot.symbol].ask
                for lot in account.lots
                if lot.sleeve == order.sleeve
            ),
            ZERO,
        )
        sleeve_value += sum((o.reserved_cash for o in active if o.sleeve == order.sleeve), ZERO)
        target = policy.tactical_pct if order.sleeve == "tactical" else policy.long_term_pct
        if sleeve_value + reserved > equity * target / 100:
            raise ValueError("sleeve allocation exceeded")
        if not quote.diversified_etf:
            sector_value = ZERO
            for lot in account.lots:
                mark = quotes[lot.symbol]
                if not mark.diversified_etf and not mark.sector:
                    raise ValueError("sector exposure unknown")
                if not mark.diversified_etf and mark.sector == quote.sector:
                    sector_value += lot.quantity * mark.ask
            # Pending orders also consume sector capacity; unknown metadata blocks.
            for pending in active:
                if pending.side == "buy":
                    pending_mark = quotes.get(pending.symbol)
                    if pending_mark is None:
                        raise ValueError("pending exposure metadata missing")
                    if (
                        pending_mark.symbol != pending.symbol
                        or not 0 <= (now - pending_mark.as_of).total_seconds() <= 5
                        or (not pending_mark.diversified_etf and not pending_mark.sector)
                    ):
                        raise ValueError("pending exposure metadata invalid")
                    if not pending_mark.diversified_etf and pending_mark.sector == quote.sector:
                        sector_value += pending.reserved_cash
            if sector_value + reserved > equity * policy.sector_pct / 100:
                raise ValueError("sector concentration exceeded")
        order = order.model_copy(update={"reserved_cash": reserved})
    else:
        available = sum(
            (
                lot.quantity
                for lot in account.lots
                if lot.symbol == order.symbol and lot.sleeve == order.sleeve
            ),
            ZERO,
        )
        if order.quantity > available:
            raise ValueError("insufficient owned shares")
    progress = account.exit_progress
    if order.threshold:
        if order.side != "sell":
            raise ValueError("threshold belongs only to an exit")
        existing = next((p for p in progress if p.threshold == order.threshold), None)
        if existing is not None:
            if (
                existing.symbol != order.symbol
                or existing.sleeve != order.sleeve
                or order.quantity > existing.target - existing.filled
            ):
                raise ValueError("exit threshold remainder exceeded")
        else:
            progress = (
                *progress,
                ExitProgress(
                    threshold=order.threshold,
                    symbol=order.symbol,
                    sleeve=order.sleeve,
                    target=order.quantity,
                ),
            )
    return _update(account, orders=(*account.orders, order), exit_progress=progress)


def fill_order(
    account: Account,
    fill: FillFact,
    policy: HybridSettings,
    *,
    settlement_at: datetime | None = None,
) -> Account:
    previous = next((item for item in account.fills if item.id == fill.id), None)
    if previous is not None:
        if previous != fill:
            raise ValueError("conflicting fill identity")
        return account
    order = next((item for item in account.orders if item.id == fill.order_id), None)
    if order is None or order.status not in {"open", "partial"}:
        raise ValueError("fill has no owned active order")
    if fill.quantity > order.quantity - order.filled:
        raise ValueError("fill exceeds remaining quantity")
    if order.limit_price is not None and (
        (order.side == "buy" and fill.price > order.limit_price)
        or (order.side == "sell" and fill.price < order.limit_price)
    ):
        raise ValueError("fill violates limit")
    if fill.quantity % Decimal(".000001") != 0:
        raise ValueError("fill precision unsupported")
    lots, cash, reserve = account.lots, account.cash, account.tax_reserve
    gain, settlements = account.realized_gain, account.settlements
    order_reserve = order.reserved_cash
    episodes = account.episodes
    if order.side == "buy":
        cost = fill.quantity * fill.price + fill.fee
        if cost > order_reserve or cost > cash - reserve:
            raise ValueError("fill exceeds committed funds; reconciliation required")
        lots = (
            *lots,
            buy_lot(
                fill.id, order.symbol, order.sleeve, fill.quantity, fill.price, fill.at, fill.fee
            ),
        )
        lots = (
            *lots[:-1],
            lots[-1].model_copy(update={"episode_id": order.episode_id or order.id}),
        )
        episode_id = order.episode_id or order.id
        old_episode = next((e for e in episodes if e.id == episode_id), None)
        if old_episode is not None and (
            old_episode.symbol != order.symbol or old_episode.sleeve != order.sleeve
        ):
            raise ValueError("allocation episode identity conflict")
        updated_episode = AllocationEpisode(
            id=episode_id,
            symbol=order.symbol,
            sleeve=order.sleeve,
            original_cash=cost + (old_episode.original_cash if old_episode else ZERO),
            original_quantity=fill.quantity
            + (old_episode.original_quantity if old_episode else ZERO),
        )
        episodes = (*(e for e in episodes if e.id != episode_id), updated_episode)
        cash -= cost
        order_reserve -= cost
    else:
        if settlement_at is None or require_utc(settlement_at) <= fill.at:
            raise ValueError("explicit future trading-calendar settlement required")
        selected = tuple(
            lot
            for lot in lots
            if lot.symbol == order.symbol
            and lot.sleeve == order.sleeve
            and (order.episode_id is None or lot.episode_id == order.episode_id)
        )
        sale = dispose(
            selected, fill.quantity, fill.price, fill.at, fee=fill.fee, tax_rate=policy.tax_rate
        )
        lots = tuple(lot for lot in lots if lot not in selected) + sale.lots
        gain += sale.gain
        # Unknown tax assumptions reserve the full positive gain instead of zero.
        reserve += max(ZERO, sale.gain) if sale.tax_reserve is None else sale.tax_reserve
        settlements = (
            *settlements,
            Settlement(id=fill.id, amount=sale.proceeds, due_at=settlement_at),
        )
    filled = order.filled + fill.quantity
    full = filled == order.quantity
    updated = order.model_copy(
        update={
            "filled": filled,
            "status": "filled" if full else "partial",
            "reserved_cash": ZERO if full else order_reserve,
        }
    )
    completed = account.completed_thresholds
    progress = account.exit_progress
    if order.threshold:
        previous_progress = next((p for p in progress if p.threshold == order.threshold), None)
        if (
            previous_progress is None
            or previous_progress.filled + fill.quantity > previous_progress.target
        ):
            raise ValueError("exit progress missing or exceeded")
        current_progress = previous_progress.model_copy(
            update={"filled": previous_progress.filled + fill.quantity}
        )
        progress = tuple(
            current_progress if p.threshold == order.threshold else p for p in progress
        )
        if current_progress.filled == current_progress.target:
            completed = (*completed, order.threshold)
    return _update(
        account,
        lots=lots,
        cash=cash,
        tax_reserve=reserve,
        realized_gain=gain,
        fees=account.fees + fill.fee,
        settlements=settlements,
        orders=tuple(updated if o.id == order.id else o for o in account.orders),
        fills=(*account.fills, fill),
        completed_thresholds=completed,
        exit_progress=progress,
        episodes=episodes,
    )


def cancel_order(account: Account, order_id: str) -> Account:
    order = next((o for o in account.orders if o.id == order_id), None)
    if order is None:
        raise ValueError("unknown order")
    if order.status not in {"open", "partial"}:
        return account
    updated = order.model_copy(update={"status": "cancelled", "reserved_cash": ZERO})
    return _update(
        account, orders=tuple(updated if o.id == order_id else o for o in account.orders)
    )


def settle(account: Account, now: datetime) -> Account:
    require_utc(now)
    cleared = sum((item.amount for item in account.settlements if item.due_at <= now), ZERO)
    return _update(
        account,
        cash=account.cash + cleared,
        settlements=tuple(item for item in account.settlements if item.due_at > now),
    )


def mark_account(account: Account, quotes: dict[str, Quote], now: datetime) -> Account:
    """Advance durable loss references only from complete fresh observations."""
    require_utc(now)
    if account.valuation_at is not None and now <= account.valuation_at:
        raise ValueError("valuation clock must advance")
    for symbol, mark in quotes.items():
        if mark.symbol != symbol or not 0 <= (now - mark.as_of).total_seconds() <= 5:
            raise ValueError("valuation quote identity or freshness invalid")
    equity = mark_equity(account, quotes)
    if equity <= 0:
        raise ValueError("positive equity required; trading remains blocked")
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    week = f"{day.isocalendar().year}-{day.isocalendar().week}"
    daily = account.daily_reference
    weekly = account.weekly_reference
    if account.daily_reference_date != day:
        daily = account.last_equity or account.starting_capital
    if account.weekly_reference_key != week:
        weekly = account.last_equity or account.starting_capital
    high = max(account.high_watermark, equity)
    suspended = (
        account.tactical_suspended
        or (daily - equity) / daily >= Decimal(".01")
        or (high - equity) / high >= Decimal(".10")
    )
    review = account.weekly_review_required or (weekly - equity) / weekly >= Decimal(".03")
    return _update(
        account,
        marks=tuple(quotes.values()),
        valuation_at=now,
        last_equity=equity,
        high_watermark=high,
        daily_reference=daily,
        weekly_reference=weekly,
        daily_reference_date=day,
        weekly_reference_key=week,
        tactical_suspended=suspended,
        weekly_review_required=review,
    )
