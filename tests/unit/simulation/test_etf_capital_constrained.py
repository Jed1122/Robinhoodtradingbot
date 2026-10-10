"""Literal policy-managed SPY accounting; fabricated originals, not evidence."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import Inexact, localcontext

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument
from tests.unit.research.test_etf_capital_prepared import long_source
from trading_bot.domain import InstrumentId, Side
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.simulation.etf_capital_account import CapitalAccountSubmission


@pytest.fixture(scope="module")
def original():
    value = long_source(225, flat=True)
    archives = []
    for archive in value.archives:
        page = archive.pages[0]
        records = tuple(
            replace(
                r,
                bar=replace(r.bar, open=D(300), high=D(301), low=D(299), close=D(300), vwap=D(300)),
            )
            for r in page.records
        )
        archives.append(replace(archive, pages=(replace(page, records=records),)))
    return replace(value, archives=tuple(archives))


def changed_spy(original, prices, *, splits=(), distributions=()):
    spy, *rest = original.archives
    page = spy.pages[0]
    records = list(page.records)
    for index, values in prices.items():
        opened, high, low, closed = map(D, values)
        row = records[index]
        records[index] = replace(
            row, bar=replace(row.bar, open=opened, high=high, low=low, close=closed, vwap=closed)
        )
    return replace(
        original,
        archives=(replace(spy, pages=(replace(page, records=tuple(records)),)), *rest),
        actions=(
            replace(original.actions[0], splits=splits, distributions=distributions),
            *original.actions[1:],
        ),
    )


def request(original, *, count=2, **changes):
    from trading_bot.simulation.etf_capital_constrained import (
        CapitalConstrainedDay,
        CapitalConstrainedRequest,
    )

    sessions = original.calendar.sessions[199 : 199 + count]
    days = tuple(
        CapitalConstrainedDay(s.session_date, i == 0, True, True) for i, s in enumerate(sessions)
    )
    instruments = tuple(
        instrument(
            id=InstrumentId("fixture-" + symbol),
            symbol=symbol,
            observed_at=sessions[0].opens_at,
            price_increment=D(".000001"),
        )
        for symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF")
    )
    return replace(
        CapitalConstrainedRequest(
            original, D(100), days, instruments, D(".1"), D(".01"), D(".02"), D(".10")
        ),
        **changes,
    )


def run(value):
    from trading_bot.simulation.etf_capital_constrained import replay_capital_constrained

    return replay_capital_constrained(value)


def test_private_constrained_common_preparation_preserves_original_accounts(original, monkeypatch):
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.research.etf_capital_prepared import _prepare_owned_capital_days
    from trading_bot.simulation import etf_capital_constrained as module

    private = module._replay_owned_capital_constrained
    value = request(original, count=4)
    public = run(value)
    owned = _own_capital_source(original)
    schedule = tuple(d.session for d in value.days)
    prepared = _prepare_owned_capital_days(owned, sessions=schedule)
    superset = _prepare_owned_capital_days(
        owned, sessions=tuple(s.session_date for s in original.calendar.sessions[197:205])
    )

    def deny(*args, **kwargs):
        pytest.fail("private constrained replay repeated ownership or preparation")

    monkeypatch.setattr(module, "_own_capital_source", deny)
    monkeypatch.setattr(module, "_prepare_owned_capital_days", deny)
    assert private(value, owned=owned, prepared=prepared) == public
    wider = private(value, owned=owned, prepared=superset)
    assert wider.account == public.account and wider.events == public.events
    assert wider.points == public.points and wider.risk == public.risk
    assert wider.input_hash != public.input_hash
    assert wider.execution_enabled is False and wider.evidence_promotable is False


def test_private_constrained_mismatched_preparation_denies_before_owner(original, monkeypatch):
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.research.etf_capital_prepared import _prepare_owned_capital_days
    from trading_bot.simulation import etf_capital_constrained as module

    private = module._replay_owned_capital_constrained
    value = request(original)
    owned = _own_capital_source(original)
    prepared = _prepare_owned_capital_days(owned, sessions=tuple(d.session for d in value.days))

    def deny(*args, **kwargs):
        pytest.fail("invalid market identity reached execution owner")

    monkeypatch.setattr(module, "_replay_capital_owner", deny)
    for invalid in (
        replace(prepared, source_hash="c" * 64),
        replace(prepared, days=prepared.days[:1]),
    ):
        with pytest.raises(ValueError, match="capital_constrained_invalid"):
            private(value, owned=owned, prepared=invalid)


def test_first_close_is_only_instruction_and_next_open_sizes_literal_spy(original):
    first = run(request(original, count=1))
    assert first.events == () and first.account.cash == 100
    assert first.points[0].policy.action == "entry"
    value = run(request(original))
    assert value.account.quantity == D(".066")
    assert value.account.cash == D("80.1801")
    assert value.points[-1].equity == D("99.9801")
    assert value.points[-1].opening.symbol == "SPY"
    assert value.points[-1].opening.stop_distance == 4
    assert not hasattr(value.points[-1].opening, "candidate")
    assert value.points[-1].policy.reason == "constrained_opening_retained"
    assert not any(
        (
            value.source_qualified,
            value.cost_qualified,
            value.execution_enabled,
            value.economic_admitted,
            value.evidence_promotable,
        )
    )


def test_constant_prices_do_not_trigger_strategy_regime_exit_or_terminal_sale(original):
    value = run(request(original, count=21))
    assert value.account.quantity == D(".066")
    assert value.points[-2].policy.action == "hold"
    assert value.points[-1].policy.reason == "maximum_hold"
    assert value.points[-1].opening.entry_session == original.calendar.sessions[200].session_date
    assert value.account.complete is False
    exited = run(request(original, count=22))
    assert exited.account.quantity == 0 and exited.account.cash == D("99.9502")
    assert exited.account.unsettled_proceeds == D("19.7701")
    assert exited.account.complete is False
    complete = run(request(original, count=24))
    assert complete.account.complete is True
    assert complete.account.available_cash == complete.account.cash == D("99.9502")


def test_later_atr_cannot_replace_bound_original_stop(original):
    changed = changed_spy(original, {201: ("300", "304", "296.5", "300")})
    value = run(request(changed, count=3))
    assert value.account.quantity == D(".066")
    assert value.points[-1].opening.stop_distance == 4
    assert value.account.cash == D("80.1801")


def test_open_gap_uses_worse_open_and_cannot_reverse_same_session(original):
    changed = changed_spy(original, {201: ("290", "291", "289", "290")})
    value = run(request(changed, count=3))
    assert value.account.cash == D("99.29053")
    assert value.account.quantity == 0 and value.account.fees == D(".03")
    assert tuple(
        e.request.order.side for e in value.events if type(e) is CapitalAccountSubmission
    ) == (Side.BUY, Side.SELL)


def test_ambiguous_entry_day_range_is_stop_first_without_extra_buy(original):
    changed = changed_spy(original, {200: ("300", "310", "295", "300")})
    value = run(request(changed))
    assert value.account.cash == D("99.69622705")
    assert value.account.quantity == 0
    assert len(tuple(e for e in value.events if type(e) is CapitalAccountSubmission)) == 2


def test_split_rebases_quantity_protection_not_original_clock(original):
    day = original.calendar.sessions[201].session_date
    changed = changed_spy(
        original,
        {201: ("150", "150.5", "149.5", "150")},
        splits=(CapitalSplit(day, D(2), "a" * 64),),
    )
    value = run(request(changed, count=3))
    assert value.account.quantity == D(".132")
    assert value.account.cash == D("80.1801")
    assert value.points[-1].equity == D("99.9801")
    assert value.points[-1].opening.stop_distance == 2
    assert value.points[-1].opening.entry_session == original.calendar.sessions[200].session_date


def test_ex_entitlement_and_payment_preserve_nav_without_reinvestment(original):
    ex, pay = (original.calendar.sessions[i].session_date for i in (201, 202))
    dividend = CapitalDistribution(ex, ex, pay, D(1), "b" * 64)
    changed = changed_spy(
        original, {i: ("299", "300", "298", "299") for i in (201, 202)}, distributions=(dividend,)
    )
    unpaid = run(request(changed, count=3))
    assert unpaid.account.distribution_receivable == D(".066")
    assert unpaid.account.cash == D("80.1801")
    assert unpaid.points[-1].equity == D("99.9801")
    paid = run(request(changed, count=4))
    assert paid.account.distribution_receivable == 0
    assert paid.account.cash == D("80.2461")
    assert paid.account.quantity == D(".066")
    assert paid.points[-1].equity == D("99.9801")


@pytest.mark.parametrize(
    "outcome,fraction,quantity,cash",
    (
        ("partial", ".5", ".033", "90.08505"),
        ("unfilled", "0", "0", "100"),
        ("rejected", "0", "0", "100"),
    ),
)
def test_incomplete_and_rejected_entries_do_not_invent_execution(
    original, outcome, fraction, quantity, cash
):
    value = run(
        request(
            original,
            count=3,
            entry_outcome=outcome,
            entry_fill_fraction=D(fraction),
            entry_fee=D(".01") if outcome == "partial" else D(0),
        )
    )
    assert value.account.quantity == D(quantity) and value.account.cash == D(cash)
    if outcome != "rejected":
        assert value.account.complete is False
        assert value.account.available_cash < value.account.cash


def test_unknown_fee_and_unreviewed_week_gate_deny(original):
    assert run(request(original, episode_fee_bound=None)).events == ()
    value = request(original)
    value = replace(value, days=tuple(replace(d, weekly_review_assumed=False) for d in value.days))
    denied = run(value)
    assert denied.events == ()
    assert denied.risk.points[-1].decision.reason_code == "weekly_reset_review_required"


def test_overnight_split_cannot_reuse_old_atr_for_pending_entry(original):
    day = original.calendar.sessions[200].session_date
    changed = changed_spy(
        original,
        {200: ("150", "150.5", "149.5", "150")},
        splits=(CapitalSplit(day, D(2), "c" * 64),),
    )
    value = run(request(changed))
    assert value.points[0].policy.action == "entry" and value.events == ()


@pytest.mark.parametrize("change", ("gap", "duplicate", "bool", "tier", "flags", "source"))
def test_mutated_or_unsupported_inputs_fail_closed(original, change):
    value = request(original, count=3)
    if change == "gap":
        value = replace(value, days=(value.days[0], value.days[2]))
    elif change == "duplicate":
        value = replace(value, days=(value.days[0], value.days[0]))
    elif change == "bool":
        value = replace(value)
        object.__setattr__(value.days[0], "entry_decision_allowed", 1)
    elif change == "tier":
        value = replace(value, initial_cash=D(101))
    elif change == "flags":
        object.__setattr__(value, "economic_admitted", True)
    else:
        value = replace(value, dataset=object())
    with pytest.raises(ValueError, match=r"^capital_constrained_invalid$"):
        run(value)


def test_hostile_context_preserves_cash_and_original_identity(original):
    value = request(original)
    expected = run(value)
    with localcontext() as context:
        context.prec = 3
        context.Emax = 1
        context.traps[Inexact] = True
        assert run(value) == expected


def test_zero_atr_or_insufficient_history_cannot_invent_entry():
    from tests.unit.research.test_etf_capital_prepared import prepare
    from trading_bot.config.loader import restore_loaded_config
    from trading_bot.research.etf_capital_constrained_policy import _capital_constrained_policy

    for count, reason in ((199, "insufficient_history"), (200, "zero_atr")):
        source = long_source(count, flat=True)
        prepared = prepare(source, (source.calendar.sessions[-1].session_date,))
        value = _capital_constrained_policy(
            loaded=restore_loaded_config(source.canonical_config, source.config_hash),
            prepared=prepared,
            day_index=0,
            opening=None,
        )
        assert (value.action, value.symbol, value.stop_distance, value.reason) == (
            "wait",
            None,
            None,
            reason,
        )


def test_known_hold_deadline_precedes_unavailable_entry_history():
    from tests.unit.research.test_etf_capital_prepared import prepare
    from trading_bot.config.loader import restore_loaded_config
    from trading_bot.research.etf_capital_constrained_policy import (
        _capital_constrained_policy,
        _CapitalConstrainedOpening,
    )

    source = long_source(20, flat=True)
    prepared = prepare(source, (source.calendar.sessions[-1].session_date,))
    value = _capital_constrained_policy(
        loaded=restore_loaded_config(source.canonical_config, source.config_hash),
        prepared=prepared,
        day_index=0,
        opening=_CapitalConstrainedOpening("SPY", source.calendar.sessions[0].session_date, D(4)),
    )
    assert (value.action, value.reason, value.stop_distance) == ("exit", "maximum_hold", D(4))


@pytest.mark.parametrize("invalid", ("source", "index", "opening", "future", "symbol"))
def test_private_instruction_rejects_mismatched_source_clock_or_opening(original, invalid):
    from tests.unit.research.test_etf_capital_prepared import prepare
    from trading_bot.config.loader import restore_loaded_config
    from trading_bot.research.etf_capital_constrained_policy import (
        _capital_constrained_policy,
        _CapitalConstrainedOpening,
    )

    prepared = prepare(original, (original.calendar.sessions[199].session_date,))
    opening = None
    index = 0
    if invalid == "source":
        prepared = object()
    elif invalid == "index":
        index = True
    elif invalid == "opening":
        opening = object()
    elif invalid == "future":
        opening = _CapitalConstrainedOpening(
            "SPY", original.calendar.sessions[200].session_date, D(4)
        )
    else:
        opening = _CapitalConstrainedOpening(
            "SPY", original.calendar.sessions[198].session_date, D(4)
        )
        object.__setattr__(opening, "symbol", "QQQ")
    with pytest.raises(ValueError, match="capital_constrained_invalid"):
        _capital_constrained_policy(
            loaded=restore_loaded_config(original.canonical_config, original.config_hash),
            prepared=prepared,
            day_index=index,
            opening=opening,
        )


def test_public_reference_owns_originals_and_copy_and_rejects_intermediate_tokens(
    original, monkeypatch
):
    from trading_bot.market_data import etf_capital_owned as module
    from trading_bot.research.etf_capital_prepared import _prepare_capital_days

    validate = module._validate_originals
    validated = []

    def record(value):
        validated.append(value)
        return validate(value)

    monkeypatch.setattr(module, "_validate_originals", record)
    result = run(request(original))
    assert result.account.cash == D("80.1801")
    assert len(validated) == 2 and validated[0] is original and validated[1] is not original
    owned = module._own_capital_source(original)
    prepared = _prepare_capital_days(
        original, sessions=(original.calendar.sessions[199].session_date,)
    )
    for token in (owned, prepared):
        with pytest.raises(ValueError, match="capital_constrained_invalid"):
            run(replace(request(original), dataset=token))


@pytest.mark.parametrize("boundary", ("opening", "result"))
def test_miswired_private_owner_cannot_widen_public_reference_types(
    original, monkeypatch, boundary
):
    from trading_bot.simulation import etf_capital_constrained as module

    real = module._replay_capital_owner

    def wrong_owner(terms, *, count, frame_at, policy_at, identity):
        if boundary == "opening":
            return policy_at(0, original.calendar.sessions[199].closes_at, object())
        result = real(terms, count=count, frame_at=frame_at, policy_at=policy_at, identity=identity)
        return replace(result, points=(replace(result.points[0], policy=None),))

    monkeypatch.setattr(module, "_replay_capital_owner", wrong_owner)
    with pytest.raises(ValueError, match="capital_constrained_invalid"):
        run(request(original, count=1))
