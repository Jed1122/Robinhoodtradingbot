from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetBuyingPower,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderId,
    OrderPurpose,
    OrderState,
    OrderType,
    Position,
    Side,
    TimeInForce,
)
from trading_bot.reconciliation import ReconciliationService

NOW = datetime(2026, 7, 17, tzinfo=UTC)
ACCOUNT = AccountId("account-1")
HASH = DataHash("a" * 64)


def account() -> AccountSnapshot:
    return AccountSnapshot(
        ACCOUNT,
        "active",
        Decimal("100"),
        Decimal("100"),
        tuple(AssetBuyingPower(asset, Decimal("100")) for asset in AssetClass),
        False,
        NOW,
        HASH,
    )


def unexpected_order() -> BrokerOrder:
    return BrokerOrder(
        OrderId("local-external"),
        BrokerOrderId("broker-external"),
        ACCOUNT,
        None,
        None,
        InstrumentId("instrument-1"),
        Side.BUY,
        OrderPurpose.ENTRY,
        OrderType.LIMIT,
        TimeInForce.GOOD_FOR_DAY,
        Decimal("1"),
        Decimal("0"),
        Decimal("10"),
        None,
        OrderState.SUBMITTED,
        NOW,
        NOW,
        HASH,
    )


class Clock:
    def now(self) -> datetime:
        return NOW


class Local:
    async def account(self, account_id: AccountId) -> AccountSnapshot:
        return account()

    async def positions(self, account_id: AccountId) -> tuple:
        return ()

    async def orders(self, account_id: AccountId) -> tuple:
        return ()

    async def fills(self, account_id: AccountId) -> tuple:
        return ()


class Broker:
    open_orders = (unexpected_order(),)

    async def get_accounts(self) -> tuple:
        return (account(),)

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot:
        return account()

    async def get_positions(self, account_id: AccountId) -> tuple:
        return ()

    async def get_open_orders(self, account_id: AccountId) -> tuple:
        return self.open_orders

    async def get_recent_orders(self, account_id: AccountId, since: datetime) -> tuple:
        return ()

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple:
        return ()

    async def get_buying_power(self, account_id: AccountId, asset_class: AssetClass) -> Decimal:
        return Decimal("100")

    async def health_check(self) -> object:
        raise AssertionError


class Store:
    result = None

    async def persist(self, result: object) -> None:
        self.result = result


@pytest.mark.asyncio
async def test_unexpected_broker_order_is_material() -> None:
    store = Store()
    service = ReconciliationService(
        Broker(),
        Local(),
        store,
        Clock(),
        enabled_asset_classes=(AssetClass.EQUITY,),
    )  # type: ignore[arg-type]
    result = await service.reconcile(ACCOUNT)
    assert not result.clean
    assert result.differences[0].code == "unexpected_broker_order"
    assert result.differences[0].material
    assert store.result is result


@pytest.mark.asyncio
async def test_other_provider_accounts_do_not_replace_exact_target_selection() -> None:
    class MultipleAccountsBroker(Broker):
        open_orders = ()

        async def get_accounts(self) -> tuple:
            return (
                replace(account(), account_id=AccountId("other-account")),
                account(),
            )

    store = Store()
    service = ReconciliationService(
        MultipleAccountsBroker(),
        Local(),
        store,
        Clock(),
        enabled_asset_classes=(AssetClass.EQUITY,),
    )  # type: ignore[arg-type]

    result = await service.reconcile(ACCOUNT)

    assert result.clean


@pytest.mark.asyncio
async def test_conflicting_duplicate_broker_order_identity_is_material() -> None:
    class DuplicateOrderBroker(Broker):
        open_orders = (
            unexpected_order(),
            replace(
                unexpected_order(),
                filled_quantity=Decimal("0.5"),
                state=OrderState.PARTIALLY_FILLED,
            ),
        )

    store = Store()
    service = ReconciliationService(
        DuplicateOrderBroker(),
        Local(),
        store,
        Clock(),
        enabled_asset_classes=(AssetClass.EQUITY,),
    )  # type: ignore[arg-type]

    result = await service.reconcile(ACCOUNT)

    assert not result.clean
    assert result.differences[0].code == "duplicate_broker_order_identity"


def test_enabled_asset_classes_are_explicit_and_unique() -> None:
    with pytest.raises(ValueError, match="enabled_asset_classes"):
        ReconciliationService(
            Broker(),
            Local(),
            Store(),
            Clock(),
            enabled_asset_classes=(),
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="enabled_asset_classes"):
        ReconciliationService(
            Broker(),
            Local(),
            Store(),
            Clock(),
            enabled_asset_classes=(AssetClass.EQUITY, AssetClass.EQUITY),
        )  # type: ignore[arg-type]


def position() -> Position:
    return Position(
        ACCOUNT,
        InstrumentId("instrument-1"),
        AssetClass.EQUITY,
        Decimal("0.5"),
        Decimal("10"),
        Decimal("5"),
        NOW,
        HASH,
    )


def order() -> BrokerOrder:
    return replace(
        unexpected_order(),
        order_type=OrderType.STOP_LIMIT,
        stop_price=Decimal("9"),
        filled_quantity=Decimal("0.5"),
        state=OrderState.PARTIALLY_FILLED,
    )


def fill() -> Fill:
    return Fill(
        FillId("fill-1"),
        order().broker_order_id,
        ACCOUNT,
        InstrumentId("instrument-1"),
        Side.BUY,
        Decimal("0.5"),
        Decimal("10"),
        Decimal("0"),
        NOW - timedelta(minutes=2),
        HASH,
    )


class MatchingLocal(Local):
    snapshot = account()
    position_rows = (position(),)
    order_rows = (order(),)
    fill_rows = (fill(),)

    async def account(self, account_id: AccountId) -> AccountSnapshot:
        return self.snapshot

    async def positions(self, account_id: AccountId) -> tuple:
        return self.position_rows

    async def orders(self, account_id: AccountId) -> tuple:
        return self.order_rows

    async def fills(self, account_id: AccountId) -> tuple:
        return self.fill_rows


class MatchingBroker(Broker):
    snapshot = account()
    position_rows = (position(),)
    open_orders = (order(),)
    recent_orders = ()
    fill_rows = (fill(),)

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot:
        return self.snapshot

    async def get_positions(self, account_id: AccountId) -> tuple:
        return self.position_rows

    async def get_recent_orders(self, account_id: AccountId, since: datetime) -> tuple:
        return self.recent_orders

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple:
        return self.fill_rows


async def reconciled(local=None, broker=None):
    store = Store()
    service = ReconciliationService(
        MatchingBroker() if broker is None else broker,
        MatchingLocal() if local is None else local,
        store,
        Clock(),
        enabled_asset_classes=(AssetClass.EQUITY,),
    )
    result = await service.reconcile(ACCOUNT)
    assert store.result is result
    return result


@pytest.mark.asyncio
async def test_matching_nonempty_state_and_single_cross_view_order_overlap_are_clean():
    broker = MatchingBroker()
    broker.recent_orders = broker.open_orders
    result = await reconciled(broker=broker)
    assert result.clean and result.differences == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["local", "broker", "both"])
async def test_returned_account_snapshots_must_match_requested_account(source):
    local, broker = MatchingLocal(), MatchingBroker()
    foreign = replace(account(), account_id=AccountId("foreign-private-marker"))
    if source in {"local", "both"}:
        local.snapshot = foreign
    if source in {"broker", "both"}:
        broker.snapshot = foreign

    # Wrong-scope account snapshots must stop the read before collecting rows.
    async def forbidden_positions(account_id):
        raise AssertionError("collected rows after wrong-scope account state")

    local.positions = forbidden_positions
    broker.get_positions = forbidden_positions
    result = await reconciled(local, broker)
    assert not result.clean
    expected_sources = ("local", "broker") if source == "both" else (source,)
    assert {f"{item}_account_identity_mismatch" for item in expected_sources} <= {
        item.code for item in result.differences
    }
    assert "foreign-private-marker" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,factory", [("position", position), ("order", order), ("fill", fill)])
@pytest.mark.parametrize("source", ["local", "broker", "both"])
async def test_each_returned_row_must_match_requested_account(kind, factory, source):
    local, broker = MatchingLocal(), MatchingBroker()
    row = replace(factory(), account_id=AccountId("foreign-private-marker"))
    if source in {"local", "both"}:
        setattr(local, f"{kind}_rows", (row,))
    if source in {"broker", "both"}:
        setattr(broker, "open_orders" if kind == "order" else f"{kind}_rows", (row,))
    result = await reconciled(local, broker)
    assert not result.clean
    expected_sources = ("local", "broker") if source == "both" else (source,)
    assert {f"{item}_{kind}_account_mismatch" for item in expected_sources} <= {
        item.code for item in result.differences
    }
    assert "foreign-private-marker" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": Decimal("0.6")},
        {"average_price": Decimal("20")},
        {"average_price": None},
        {"market_value": Decimal("50")},
        {"asset_class": AssetClass.CRYPTO},
    ],
)
async def test_position_economics_and_asset_class_drift_are_material(changes):
    broker = MatchingBroker()
    broker.position_rows = (replace(position(), **changes),)
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == "position_state_mismatch" for item in result.differences)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"order_type": OrderType.LIMIT, "stop_price": None},
        {"order_type": OrderType.STOP_LOSS, "limit_price": None},
        {"time_in_force": TimeInForce.GOOD_TIL_CANCELED},
        {"limit_price": Decimal("100")},
        {"stop_price": Decimal("90")},
    ],
)
async def test_changed_executable_order_terms_are_material(changes):
    broker = MatchingBroker()
    broker.open_orders = (replace(order(), **changes),)
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == "order_state_mismatch" for item in result.differences)


@pytest.mark.asyncio
async def test_fill_time_drift_is_material_for_tax_and_settlement_accounting():
    broker = MatchingBroker()
    broker.fill_rows = (replace(fill(), occurred_at=NOW - timedelta(days=1)),)
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == "fill_state_mismatch" for item in result.differences)


@pytest.mark.asyncio
@pytest.mark.parametrize("open_count,recent_count", [(2, 0), (0, 2), (2, 1), (1, 2), (2, 2)])
async def test_duplicate_orders_within_one_view_are_never_erased(open_count, recent_count):
    broker = MatchingBroker()
    broker.open_orders = (order(),) * open_count
    broker.recent_orders = (order(),) * recent_count
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == "duplicate_broker_order_identity" for item in result.differences)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2])
async def test_missing_or_ambiguous_account_selection_stops_before_account_reads(count):
    local, broker = MatchingLocal(), MatchingBroker()

    async def accounts():
        return (account(),) * count

    async def forbidden_account(account_id):
        raise AssertionError("collected account state without an exact selection")

    broker.get_accounts = accounts
    local.account = forbidden_account
    broker.get_account_state = forbidden_account
    result = await reconciled(local, broker)
    assert not result.clean
    assert tuple(item.code for item in result.differences) == ("account_identity_mismatch",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,code",
    [
        ({"provider_state": "restricted"}, "account_provider_state_mismatch"),
        ({"restricted": True}, "account_restricted_mismatch"),
        ({"equity": Decimal("101")}, "account_equity_mismatch"),
        ({"cash": Decimal("99")}, "account_cash_mismatch"),
    ],
)
async def test_matching_account_identity_does_not_hide_account_state_drift(changes, code):
    broker = MatchingBroker()
    broker.snapshot = replace(account(), **changes)
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == code for item in result.differences)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,factory", [("position", position), ("order", order), ("fill", fill)])
@pytest.mark.parametrize("source", ["local", "broker"])
async def test_duplicate_rows_are_material_even_when_other_state_matches(kind, factory, source):
    local, broker = MatchingLocal(), MatchingBroker()
    target = local if source == "local" else broker
    attribute = "open_orders" if source == "broker" and kind == "order" else f"{kind}_rows"
    setattr(target, attribute, (factory(), factory()))
    result = await reconciled(local, broker)
    assert not result.clean
    assert any(
        item.code == f"duplicate_{source}_{kind}_identity" for item in result.differences
    )


@pytest.mark.asyncio
async def test_conflicting_cross_view_order_rows_are_not_treated_as_one_overlap():
    broker = MatchingBroker()
    broker.recent_orders = (replace(order(), limit_price=Decimal("11")),)
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == "duplicate_broker_order_identity" for item in result.differences)


@pytest.mark.asyncio
async def test_foreign_recent_order_cannot_be_hidden_by_the_open_order_view():
    broker = MatchingBroker()
    broker.recent_orders = (
        replace(
            order(),
            account_id=AccountId("foreign-account-private-marker"),
            broker_order_id=BrokerOrderId("foreign-order-private-marker"),
            instrument_id=InstrumentId("foreign-instrument-private-marker"),
        ),
    )
    result = await reconciled(broker=broker)
    assert not result.clean
    assert any(item.code == "broker_order_account_mismatch" for item in result.differences)
    assert "private-marker" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2])
async def test_missing_or_ambiguous_local_buying_power_is_material(count):
    local = MatchingLocal()
    local.snapshot = replace(
        account(), buying_power=(AssetBuyingPower(AssetClass.EQUITY, Decimal("100")),) * count
    )
    result = await reconciled(local=local)
    assert not result.clean
    assert any(item.code == "missing_local_buying_power" for item in result.differences)


@pytest.mark.asyncio
async def test_changed_buying_power_remains_material():
    broker = MatchingBroker()

    async def buying_power(account_id, asset_class):
        return Decimal("99")

    broker.get_buying_power = buying_power
    result = await reconciled(broker=broker)
    assert not result.clean
    assert tuple(item.code for item in result.differences) == ("buying_power_mismatch",)
