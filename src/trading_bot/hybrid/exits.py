"""Episode-bound tactical exit proposals; long-term holdings are excluded."""

from decimal import Decimal
from typing import Literal

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.accounting import exit_quantity
from trading_bot.hybrid.models import Account, PaperOrder


def propose_exit(
    account: Account,
    episode_id: str,
    method: Literal["principal", "partial_first", "partial_second", "trend"],
    executable_price: Decimal,
    peak_price: Decimal,
    policy: HybridSettings,
    *,
    fractional: bool = True,
) -> PaperOrder | None:
    episode = next((e for e in account.episodes if e.id == episode_id), None)
    if episode is None:
        raise ValueError("unknown allocation episode")
    if episode.sleeve != "tactical":
        return None
    threshold = f"{episode_id}:{method}"
    quantity = sum(
        (lot.quantity for lot in account.lots if lot.episode_id == episode_id), Decimal(0)
    )
    if not quantity:
        return None
    target = exit_quantity(
        method,
        quantity,
        executable_price,
        episode.original_cash,
        peak_price,
        original_quantity=episode.original_quantity,
        fractional=fractional,
        completed=threshold in account.completed_thresholds,
        trigger_pct=policy.principal_trigger_pct,
        trailing_pct=policy.trailing_pct,
    )
    progress = next((p for p in account.exit_progress if p.threshold == threshold), None)
    if progress:
        target = min(target, progress.target - progress.filled)
    if target <= 0:
        return None
    attempts = sum(order.threshold == threshold for order in account.orders)
    return PaperOrder(
        id=f"exit:{threshold}:{attempts}",
        symbol=episode.symbol,
        side="sell",
        sleeve="tactical",
        quantity=target,
        threshold=threshold,
        episode_id=episode_id,
        reason="experimental exit proposal; not strategy qualification",
    )
