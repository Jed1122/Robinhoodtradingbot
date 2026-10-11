"""Private original-prefix continuation, fictional balances and rollback controls."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from trading_bot.simulation import etf_capital_account as account

from .test_etf_capital_account import script
from .test_etf_capital_action_account import action
from .test_etf_capital_risk import point
from .test_etf_capital_risk_progress import progress_points


def owned(progress, events, *, capital=D("100"), actions=True):
    return account._account_prefixes_owned(
        progress, initial_cash=capital, events=events, actions=actions
    )


@pytest.mark.parametrize("actions", (False, True))
def test_growing_original_prefixes_equal_batch_with_literal_final_account(actions, monkeypatch):
    calls = []
    real = account.replay_order_lifecycle

    def replay(request):
        calls.append(request.order.id)
        return real(request)

    monkeypatch.setattr(account, "replay_order_lifecycle", replay)
    progress = None
    tape = script()
    results = []
    for count in range(11):
        progress, prefixes = owned(progress, tape[:count], actions=actions)
        results.append(prefixes)
    assert len(calls) == 8  # only new submission/control/fill transitions, not old orders
    assert (results[5][-1].cash, results[5][-1].available_cash) == (D("90.06"), D("90"))
    final = results[-1][-1]
    assert (final.cash, final.quantity, final.fees, final.complete) == (
        D("100.11"),
        D(0),
        D(".09"),
        True,
    )
    assert not final.execution_enabled and not final.evidence_promotable
    batch = (
        account.replay_capital_action_account_prefixes
        if actions
        else account.replay_capital_account_prefixes
    )
    for count, prefixes in enumerate(results):
        assert prefixes == batch(initial_cash=D("100"), events=tape[:count])


@pytest.mark.parametrize("kind", ("split", "distribution", "payment"))
def test_actions_have_literal_basis_receivable_and_atomic_nav(kind):
    tape = (*script()[:5], action("split" if kind == "split" else "distribution"))
    if kind == "payment":
        tape = (*tape, action("payment", 6))
    progress, _ = owned(None, tape[:5])
    _, prefixes = owned(progress, tape)
    result = prefixes[-1]
    assert result.marked_equity == D("99.96")
    assert (result.quantity, result.average_price) == (
        (D(".2"), D("49.5")) if kind == "split" else (D(".1"), D("99"))
    )
    assert result.cash == (D("90.16") if kind == "payment" else D("90.06"))
    assert result.distribution_receivable == (D(".10") if kind == "distribution" else D(0))
    assert prefixes == account.replay_capital_action_account_prefixes(
        initial_cash=D(100), events=tape
    )


def test_duplicate_delivery_positions_do_not_advance_cash_or_unique_clock():
    tape = script()
    tape = (*tape[:3], tape[2], *tape[3:], tape[1])
    progress = None
    for count in range(len(tape) + 1):
        progress, prefixes = owned(progress, tape[:count])
        assert len(prefixes) == count + 1
        assert prefixes == account.replay_capital_action_account_prefixes(
            initial_cash=D(100), events=tape[:count]
        )
    assert prefixes[3] == prefixes[4]
    assert prefixes[-1].cash == D("100.11")


@pytest.mark.parametrize("changed", ("fee", "shorter", "mode", "representation", "capital"))
def test_changed_binding_or_originals_reconstruct_instead_of_adopting(changed):
    tape = script()[:3]
    progress, _ = owned(None, tape)
    capital, actions = D("100"), True
    if changed == "fee":
        tape = (*tape[:2], replace(tape[2], fill=replace(tape[2].fill, fee=D(".05"))))
    elif changed == "shorter":
        tape = tape[:1]
    elif changed == "mode":
        actions = False
    elif changed == "representation":
        capital = D("100.0")
    else:
        capital, tape = D("250"), ()
    current, prefixes = owned(progress, tape, capital=capital, actions=actions)
    batch = (
        account.replay_capital_action_account_prefixes
        if actions
        else account.replay_capital_account_prefixes
    )
    assert prefixes == batch(initial_cash=capital, events=tape)
    assert current is not progress
    if changed == "fee":
        assert prefixes[-1].cash == D("90.05")
    if changed == "capital":
        assert prefixes[-1].cash == D(250)
    if changed == "representation":
        assert current.binding != progress.binding
        assert prefixes[0].cash.as_tuple() == capital.as_tuple()


def test_retained_nested_originals_and_returned_records_are_detached():
    tape = script()[:3]
    original = deepcopy(tape)
    progress, outputs = owned(None, tape)
    object.__setattr__(tape[0].request.order, "id", "mutated")
    object.__setattr__(tape[2].fill, "fee", D(1))
    object.__setattr__(outputs[-1], "cash", D(123))
    _, result = owned(progress, original)
    assert result[-1].cash == D("90.06")
    assert result == account.replay_capital_action_account_prefixes(
        initial_cash=D(100), events=original
    )


@pytest.mark.parametrize("tampering", ("subclass", "submission_flag", "action_flag", "identifier"))
def test_old_original_admission_runs_before_canonical_reuse(tampering):
    tape = (*script()[:5], action())
    progress, _ = owned(None, tape)
    bad = deepcopy(tape)
    if tampering == "subclass":

        class Sub(account.CapitalAccountSubmission):
            pass

        bad = (Sub(bad[0].symbol, bad[0].request, bad[0].episode_fee_bound), *bad[1:])
    elif tampering == "submission_flag":
        object.__setattr__(bad[0], "execution_enabled", True)
    elif tampering == "action_flag":
        object.__setattr__(bad[-1], "source_qualified", True)
    else:
        object.__setattr__(bad[0].request.order, "client_order_id", "x" * 257)
    with pytest.raises(ValueError, match="capital_account_invalid"):
        owned(progress, bad)
    _, retry = owned(progress, tape)
    assert retry[-1].marked_equity == D("99.96")


@pytest.mark.parametrize("failure", ("fill", "split", "payment", "settlement", "finality"))
def test_failed_whole_suffix_leaves_nested_containers_and_clean_retry_unchanged(failure):
    if failure == "split":
        prefix, clean = script()[:5], (*script()[:5], action("split"))
        bad = (*prefix, action("split", ratio=D(7)))  # nonterminating adjusted basis
    elif failure == "payment":
        prefix = (*script()[:5], action())
        clean = (*prefix, action("payment", 6))
        bad = (*clean, replace(action("payment", 7), entitlement_id="missing"))
    else:
        prefix, clean = script()[:2], script()
        if failure == "fill":
            bad = (*prefix, replace(script()[2], fill=replace(script()[2].fill, quantity=D(9))))
        elif failure == "settlement":
            bad = (*clean[:9], replace(clean[8], event_id="again", cursor=clean[9].cursor))
        else:
            bad = (*clean[:9], replace(clean[9], total_fees=D(1)))
    progress, before = owned(None, prefix)
    with pytest.raises(ValueError, match="capital_account_invalid"):
        owned(progress, bad)
    _, unchanged = owned(progress, prefix)
    assert unchanged == before
    _, retry = owned(progress, clean)
    assert retry == account.replay_capital_action_account_prefixes(
        initial_cash=D(100), events=clean
    )


def test_original_decimal_context_and_equal_time_cursor_semantics_are_preserved():
    at = script()[4].cursor.occurred_at
    tape = (
        *script()[:5],
        replace(action(), cursor=replace(action().cursor, occurred_at=at)),
        replace(action("payment", 6), cursor=replace(action("payment", 6).cursor, occurred_at=at)),
    )
    progress, _ = owned(None, tape[:5])
    with localcontext() as context:
        context.prec = 3
        _, prefixes = owned(progress, tape)
    assert prefixes[-1].cash == D("90.16")
    assert prefixes[-1].marked_equity == D("99.96")


def test_fresh_risk_frontier_failure_does_not_publish_account_candidate():
    from trading_bot.simulation.etf_capital_risk import _RiskProgress

    progress = _RiskProgress()
    progress_points(progress, (), (point(0, 0),))
    original = progress.accounts
    broken = point(1, 10)
    object.__setattr__(broken, "daily_reset_reconciled", 1)
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        progress_points(progress, script(), (point(0, 0), broken))
    assert progress.accounts is original
    result = progress_points(progress, script(), (point(0, 0), point(1, 10)))
    assert result[-1].equity == D("100.11")


@pytest.mark.parametrize(
    "name",
    (
        "replay_capital_account",
        "replay_capital_account_v1",
        "replay_capital_action_account",
        "replay_capital_account_prefixes",
        "replay_capital_action_account_prefixes",
    ),
)
def test_public_account_apis_do_not_accept_continuation(name):
    with pytest.raises(TypeError):
        getattr(account, name)(initial_cash=D(100), events=(), _resume=object())
