"""Private original-bound research scheduling, never real settlement evidence."""

from datetime import date
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from trading_bot.domain import Bar, BarInterval, Side
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_capital_actions import CapitalActionArchive
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_capital_account import (
    _CONTEXT,
    CapitalAccountEvent,
    CapitalAccountSubmission,
    CapitalEpisodeFeesFinal,
    CapitalSaleSettlement,
    replay_capital_action_account,
    replay_capital_action_account_prefixes,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalActionEvent,
    CapitalDistributionEntitled,
    CapitalDistributionPaid,
    CapitalSplitApplied,
)
from trading_bot.simulation.etf_capital_daily_owner import (
    CapitalDailyOriginalFact,
    _active,
    _cursor,
)
from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent

type _Event = CapitalAccountEvent | CapitalActionEvent
_SYMBOLS = ("SPY", "QQQ", "IWM", "SHY", "IEF")
_ZONE = ZoneInfo("America/New_York")


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_due_facts_invalid")


def _capital_due_facts(
    *,
    initial_cash: Decimal,
    events: tuple[_Event, ...],
    observations: tuple[CapitalRiskObservation, ...],
    calendar: EtfCalendarArchive,
    actions: tuple[CapitalActionArchive, ...],
    session: date,
    raw_bars: tuple[Bar, ...],
) -> tuple[CapitalDailyOriginalFact, ...]:
    """Derive declared T+2/payment/finality facts from invocation-owned originals.

    The original-input evaluator must own every argument. This private helper
    grants no source, account, broker, fee-completeness or risk authority.
    No terminal-input completion, cancellation or liquidation is synthesized.
    """
    try:
        with localcontext(_CONTEXT):
            _check(type(calendar) is EtfCalendarArchive and type(session) is date)
            calendar.__post_init__()
            dates = tuple(s.session_date for s in calendar.sessions)
            current = dates.index(session)
            clock = calendar.sessions[current]
            _check(type(raw_bars) is tuple and len(raw_bars) == 5)
            prices: dict[str, Decimal] = {}
            for bar in raw_bars:
                _check(type(bar) is Bar)
                bar.__post_init__()
                _check(bar.interval is BarInterval.ONE_DAY and bar.interpolated is False)
                _check((bar.starts_at, bar.ends_at) == (clock.opens_at, clock.closes_at))
                symbol = str(bar.instrument_id)
                _check(symbol in _SYMBOLS and symbol not in prices)
                prices[symbol] = bar.open
            _check(type(actions) is tuple and len(actions) == 5)
            _check(tuple(a.symbol for a in actions) == _SYMBOLS)
            for archive in actions:
                _check(type(archive) is CapitalActionArchive)
                archive.__post_init__()
                _check(archive.start <= session < archive.end)
                if archive.splits is None or archive.distributions is None:
                    raise ValueError("capital_due_facts_invalid")
                records = tuple(row.record_hash for row in archive.splits) + tuple(
                    row.record_hash for row in archive.distributions
                )
                _check(len(records) == len(set(records)))

            prefixes = replay_capital_action_account_prefixes(
                initial_cash=initial_cash, events=events
            )
            unique = tuple(
                (index, event)
                for index, event in enumerate(events)
                if prefixes[index].economic_hash != prefixes[index + 1].economic_hash
            )
            originals = tuple(event for _, event in unique)
            _check(type(observations) is tuple and len(observations) <= 4096)
            for observation in observations:
                _check(type(observation) is CapitalRiskObservation)
                observation.__post_init__()
                _check(observation.source_count <= len(events))
            cursors = (*(_cursor(e) for e in originals), *(o.cursor for o in observations))
            _check(all(c.occurred_at <= clock.opens_at for c in cursors))
            sequence = max((c.sequence for c in cursors), default=-1) + 1
            result: list[CapitalDailyOriginalFact] = []
            candidate_events = events
            account = prefixes[-1]
            buys = tuple(
                (index, event)
                for index, event in unique
                if type(event) is CapitalAccountSubmission and event.request.order.side is Side.BUY
            )
            if not buys:
                return ()
            opening_index, opening = buys[-1]
            identity = opening.request.order
            bound = (identity.account_id, identity.id, opening.symbol)
            entitlements = [
                (
                    event,
                    prefixes[index + 1].distribution_receivable
                    - prefixes[index].distribution_receivable,
                )
                for index, event in unique
                if type(event) is CapitalDistributionEntitled
            ]

            def cursor() -> EventCursor:
                nonlocal sequence
                value = EventCursor(sequence, clock.opens_at)
                sequence += 1
                return value

            def event_id(kind: str, original_id: str) -> str:
                return content_hash(
                    (
                        "capital-assumed-due-fact-v1",
                        kind,
                        bound,
                        original_id,
                        calendar.archive_hash,
                        clock.opens_at,
                    )
                )

            def append(event: _Event) -> None:
                nonlocal candidate_events, account
                before = account
                candidate_events = (*candidate_events, event)
                account = replay_capital_action_account(
                    initial_cash=initial_cash, events=candidate_events
                )
                result.append(
                    CapitalDailyOriginalFact(
                        event, prices[opening.symbol] if account.quantity else None
                    )
                )
                if type(event) is CapitalDistributionEntitled:
                    entitlements.append(
                        (event, account.distribution_receivable - before.distribution_receivable)
                    )

            # Entitlement/ex mark is atomic BEFORE another same-opening fact
            # observes prices; a settlement cannot create a phantom dividend loss.
            if account.quantity > 0:
                archive = actions[_SYMBOLS.index(opening.symbol)]
                applied_actions = {
                    e.action_id
                    for e in originals
                    if type(e) is CapitalSplitApplied or type(e) is CapitalDistributionEntitled
                }
                splits = tuple(s for s in archive.splits or () if s.effective_date == session)
                distributions = tuple(
                    d for d in archive.distributions or () if d.ex_date == session
                )
                _check(not (splits and distributions))
                for split in splits:
                    action_id = content_hash(("capital-assumed-split-v1", opening.symbol, split))
                    if action_id not in applied_actions:
                        append(
                            CapitalSplitApplied(
                                event_id("split", action_id),
                                cursor(),
                                *bound,
                                action_id,
                                split.record_hash,
                                split.new_shares_per_old_share,
                                prices[opening.symbol],
                            )
                        )
                for distribution in distributions:
                    action_id = content_hash(
                        ("capital-assumed-distribution-v1", opening.symbol, distribution)
                    )
                    if action_id not in applied_actions:
                        append(
                            CapitalDistributionEntitled(
                                event_id("entitlement", action_id),
                                cursor(),
                                *bound,
                                action_id,
                                distribution.record_hash,
                                distribution.amount_per_share,
                                prices[opening.symbol],
                                distribution.pay_date,
                            )
                        )

            settled = {e.fill_id for e in originals if type(e) is CapitalSaleSettlement}
            for _, event in unique:
                if type(event) is LifecycleFillEvent and event.fill.side is Side.SELL:
                    fill_date = event.cursor.occurred_at.astimezone(_ZONE).date()
                    sale_index = dates.index(fill_date)
                    if event.fill.id not in settled:
                        _check(sale_index + 2 >= current)
                    if event.fill.id not in settled and sale_index + 2 == current:
                        append(
                            CapitalSaleSettlement(
                                event_id("T+2", event.fill.id), cursor(), event.fill.id
                            )
                        )
                        settled.add(event.fill.id)

            paid = {e.entitlement_id for e in originals if type(e) is CapitalDistributionPaid}
            for entitlement, amount in entitlements:
                if entitlement.action_id not in paid and entitlement.pay_date <= session:
                    first_payment_session = next(
                        (index for index, day in enumerate(dates) if day >= entitlement.pay_date),
                        None,
                    )
                    _check(first_payment_session == current)
                    append(
                        CapitalDistributionPaid(
                            event_id("payment", entitlement.action_id),
                            cursor(),
                            entitlement.account_id,
                            entitlement.opening_order_id,
                            entitlement.symbol,
                            entitlement.action_id,
                            amount,
                        )
                    )
                    paid.add(entitlement.action_id)

            if (
                not account.complete
                and account.quantity == 0
                and account.unsettled_proceeds == 0
                and account.distribution_receivable == 0
                and all(
                    event.fill.id in settled
                    for _, event in unique
                    if type(event) is LifecycleFillEvent and event.fill.side is Side.SELL
                )
                and all(entitlement.action_id in paid for entitlement, _ in entitlements)
                and not _active(candidate_events)
            ):
                fees = account.fees - prefixes[opening_index].fees
                append(
                    CapitalEpisodeFeesFinal(
                        event_id("final-fees", identity.id),
                        cursor(),
                        fees,
                        identity.account_id,
                        identity.id,
                    )
                )
            return tuple(result)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise ValueError("capital_due_facts_invalid") from None
