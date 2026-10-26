"""Short fictional algebra and owned ledger facts, never actual monetary outcomes."""

import importlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.execution import cancel_order, fill_order, settle
from trading_bot.hybrid.models import Account, FillFact, PaperOrder
from trading_bot.research.hybrid_policies import (
    CalendarSession,
    StrategyProposal,
    UnavailablePolicy,
)
from trading_bot.research.stock_dividend_book import adopt_dividend_account, create_dividend_book
from trading_bot.research.stock_economic_policies import (
    STOCK_POLICY_SYMBOLS,
    EconomicPolicyClose,
    KnownPolicyCondition,
    UnavailablePolicyCondition,
)
from trading_bot.research.stock_economic_replay import (
    EconomicReplayCostMark,
    EconomicReplayRecord,
    EconomicReplaySnapshot,
)
from trading_bot.research.stock_operating_costs import ModeledOperatingCostPlan

D = Decimal
ZERO, CAPITAL, TAX = D(0), D(1000), D(".25")
MODULE = "trading_bot.research.stock_monetary_metrics"


def api():
    assert importlib.util.find_spec(MODULE) is not None, "monetary metric consumer missing"
    return importlib.import_module(MODULE)


def calendar(count=3, *, first=199):
    day = datetime(2025, 1, 6, tzinfo=UTC)
    return tuple(
        CalendarSession(
            first + i,
            day + timedelta(days=i, hours=14, minutes=30),
            day + timedelta(days=i, hours=21),
        )
        for i in range(count)
    )


def curve(values, *, indices=None, prefix=None):
    m = api()
    expected = calendar(len(values))
    indices = tuple(range(len(values))) if indices is None else indices
    points = tuple(
        m._CurveObservation(
            expected[i].index,
            expected[i].closes_at,
            values[i],
            "unknown_cost" if values[i] is None else None,
        )
        for i in indices
    )
    return m._curve(points, expected=expected, prefix=prefix)


def test_flat_curve_zero_volatility_keeps_undefined_ratios_and_counts():
    result = curve((D(1000), D(1000), D(1000)))
    metrics = dict(result.metrics)
    assert result.expected_mark_count == result.observed_mark_count == 3
    assert result.expected_return_count == 2
    assert result.simple_returns == (D(0), D(0))
    assert metrics["total_return"].value == metrics["annualized_volatility"].value == 0
    assert metrics["sharpe"].value is metrics["sortino"].value is metrics["calmar"].value is None
    assert "zero_return_variance" in metrics["sharpe"].status
    assert result.qualified is result.live_authorized is False


def test_one_return_does_not_invent_sample_volatility_or_drop_return():
    result = curve((D(100), D(110)))
    metrics = dict(result.metrics)
    assert result.simple_returns == (D(".1"),)
    assert metrics["total_return"].value == D(".1")
    assert metrics["annualized_volatility"].value is metrics["sharpe"].value is None
    assert "fewer_than_two_returns" in metrics["annualized_volatility"].status
    with localcontext() as context:
        context.prec = 50
        assert result.log_returns == (D("1.1").ln(),)


def test_missing_native_close_keeps_independent_expected_denominator():
    result = curve((D(100), D(110), D(121)), indices=(0, 2))
    assert result.expected_mark_count == 3 and result.observed_mark_count == 2
    assert result.expected_return_count == 2 and result.missing_indices == (200,)
    assert all(value.value is None for _, value in result.metrics)
    assert result.simple_returns == (None, None)


@pytest.mark.parametrize("bad", [None, D(0), D(-1), D("NaN"), True])
def test_unknown_or_invalid_wealth_does_not_become_a_selected_partial_path(bad):
    result = curve((D(100), bad, D(110)))
    assert result.expected_return_count == 2
    assert all(value.value is None for _, value in result.metrics)
    assert result.log_returns == (None, None)


def test_same_curve_prior_peak_is_distinct_from_segment_peak():
    m = api()
    days = calendar(4, first=198)
    prefix = tuple(
        m._CurveObservation(days[i].index, days[i].closes_at, v)
        for i, v in enumerate((D(120), D(100)))
    )
    points = tuple(
        m._CurveObservation(days[i].index, days[i].closes_at, v)
        for i, v in zip((1, 2, 3), (D(100), D(90), D(100)), strict=True)
    )
    result = m._curve(points, expected=days[1:], prefix=prefix)
    metrics = dict(result.metrics)
    assert metrics["max_drawdown"].value == D(".1")
    assert metrics["inherited_max_drawdown"].value == D(".25")
    assert result.inherited_peak == 120


def test_ambient_context_cannot_change_curve_math_or_hash():
    values = (D(100), D(110), D(99))
    expected = curve(values)
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        context.capitals = 0
        actual = curve(values)
        assert context.prec == 5 and context.rounding == ROUND_DOWN
        assert actual == expected and actual.evidence_hash == expected.evidence_hash


def snapshot(index=200, *, cash=CAPITAL, long=ZERO, tax=ZERO, rights=ZERO, reserved=ZERO):
    at = calendar(3)[index - 199].closes_at
    return EconomicReplaySnapshot(
        index, at, cash + rights + long, cash, reserved, tax, D(0), rights, long, D(0)
    )


def close_cost(snap, *, unpaid=ZERO, unknown=(), paid=ZERO):
    plan = ModeledOperatingCostPlan("fictional-algebra", ())
    return EconomicReplayCostMark(
        snap.session_index,
        snap.at,
        "close",
        snap.gross_equity + paid,
        snap.gross_equity,
        None if unknown else snap.gross_equity - unpaid,
        paid,
        unpaid,
        unknown,
        D(0) if unknown else max(D(0), snap.cash - snap.tax_reserve - unpaid),
        D(1000),
        D(1000),
        max(D(1000), snap.gross_equity),
        False,
        False,
        plan.evidence_hash,
        "c" * 64,
    )


def project(snap, mark, rate=TAX, *, baseline=False):
    return api()._project_row(
        snap,
        mark,
        rate=rate,
        plan=ModeledOperatingCostPlan("fictional-algebra", ()),
        activation_at=calendar()[1].opens_at,
        baseline=baseline,
    )


def test_earned_dividend_payment_transfers_provision_without_changing_wealth():
    earned = snapshot(long=D(1000), cash=D(0), rights=D(4))
    paid = snapshot(index=201, long=D(1000), cash=D(4), tax=D(1))
    before, after = project(earned, close_cost(earned)), project(paid, close_cost(paid))
    assert before.gross == after.gross == before.net == after.net == D(1004)
    assert before.after_provision == after.after_provision == D(1003)


def test_reservations_are_owned_assets_and_paid_cost_is_not_subtracted_twice():
    value = snapshot(cash=D(988), tax=D(20), reserved=D(300))
    result = project(value, close_cost(value, paid=D(12)))
    assert result.gross == result.net == D(988)
    assert result.after_provision == D(968)


def test_unknown_due_cost_and_unknown_tax_have_distinct_unavailability():
    value = snapshot()
    unknown = project(value, close_cost(value, unknown=("data",)))
    assert unknown.net is unknown.after_provision is None
    assert unknown.unknown_ids == ("data",)
    no_tax_assumption = project(value, close_cost(value), rate=None)
    assert no_tax_assumption.net == 1000 and no_tax_assumption.after_provision is None
    assert no_tax_assumption.after_reason == "tax_rate_unknown"
    with pytest.raises(ValueError):
        project(value, close_cost(value), rate=D(".30"))


def test_baseline_has_no_fabricated_cost_mark_and_missing_later_mark_is_unavailable():
    base = snapshot(index=199)
    assert project(base, None, baseline=True).net == 1000
    absent = project(snapshot(), None)
    assert absent.net is absent.after_provision is None
    assert absent.net_reason == "missing_close_cost_mark"


def ledger_case(*, runner=False, cancel_tail=False, ambiguous=False, rate=TAX):
    """Genuine short paused-account transitions; all identities deliberately opaque."""
    sessions = calendar(5)
    value = create_dividend_book(
        Account(),
        account_at=sessions[0].closes_at,
        sessions=sessions,
        calendar_source_hash="b" * 64,
        tax_rate=rate,
    )
    records = []
    policy = HybridSettings(tax_rate=rate)

    def adopt(account, at):
        nonlocal value
        value = adopt_dividend_account(value, account, at=at)

    def order_fill(oid, fid, side, quantity, price, fee, index, *, order_quantity=None):
        at = sessions[index - 199].opens_at
        if not any(order.id == oid for order in value.account.orders):
            order = PaperOrder(
                id=oid,
                symbol="AXP",
                side=side,
                sleeve="tactical",
                quantity=quantity if order_quantity is None else order_quantity,
                episode_id="allocation-alpha",
                reserved_cash=(quantity if order_quantity is None else order_quantity) * price + fee
                if side == "buy"
                else D(0),
            )
            adopt(
                Account.model_validate(
                    value.account.model_dump() | {"orders": (*value.account.orders, order)}
                ),
                at,
            )
        fill = FillFact(id=fid, order_id=oid, quantity=quantity, price=price, fee=fee, at=at)
        due = sessions[4].opens_at if side == "sell" else None
        adopt(fill_order(value.account, fill, policy, settlement_at=due), at)
        proceeds, basis, gain = (
            (D(0), D(0), D(0))
            if side == "buy"
            else ((D(119), D(101), D(18)) if oid == "copper" else (D(258), D(212), D(46)))
        )
        records.append(
            EconomicReplayRecord(
                index,
                at,
                "AXP",
                side,
                "filled",
                "fictional",
                oid,
                quantity,
                price,
                fee,
                due,
                proceeds,
                basis,
                gain,
            )
        )

    if ambiguous:
        order_fill("blue", "q", "buy", D(1), D(100), D(0), 200, order_quantity=D(2))
        order_fill("blue", "x", "buy", D(1), D(100), D(0), 200)
        return value, tuple(records), sessions
    order_fill("blue", "q", "buy", D(2), D(100), D(2), 200)
    order_fill("green", "x", "buy", D(1), D(110), D(1), 200)
    if cancel_tail:
        order = PaperOrder(
            id="unfilled-tail",
            symbol="AXP",
            side="buy",
            sleeve="tactical",
            quantity=D(1),
            reserved_cash=D(10),
            episode_id="allocation-alpha",
        )
        adopt(
            Account.model_validate(
                value.account.model_dump() | {"orders": (*value.account.orders, order)}
            ),
            sessions[2].opens_at,
        )
    order_fill("copper", "y", "sell", D(1), D(120), D(1), 201)
    if not runner:
        order_fill("violet", "z", "sell", D(2), D(130), D(2), 202)
    if cancel_tail:
        adopt(cancel_order(value.account, "unfilled-tail"), sessions[4].opens_at)
    adopt(settle(value.account, sessions[4].opens_at), sessions[4].opens_at)
    adopt(value.account, sessions[4].closes_at)
    return value, tuple(records), sessions


def audited(**kwargs):
    value, records, sessions = ledger_case(**kwargs)
    result = api()._audit_executions(
        value, records, calendar=sessions, rate=D(".25"), native_last_index=203
    )
    return result, sessions


def test_closed_episode_aggregates_two_entries_and_partial_rungs_once():
    result, sessions = audited()
    assert result.available and len(result.episodes) == 1
    episode = result.episodes[0]
    assert episode.completed and episode.proceeds == 377 and episode.disposed_basis == 313
    assert episode.pnl == 64 and episode.holding_intervals == episode.holding_days == 2
    stats = api()._episode_metrics(
        result, baseline_at=sessions[0].closes_at, terminal_at=sessions[-1].closes_at
    )
    metrics = dict(stats.metrics)
    assert metrics["completed_count"].value == metrics["positive_count"].value == 1
    assert metrics["win_rate"].value == 1 and metrics["average_win"].value == 64
    assert (
        metrics["profit_factor"].value is None
        and metrics["profit_factor"].status == "no_negative_pnl"
    )


def test_unsold_runner_is_open_and_not_a_winning_partial_sale():
    result, sessions = audited(runner=True)
    assert result.available and result.episodes[0].completed is False
    stats = api()._episode_metrics(
        result, baseline_at=sessions[0].closes_at, terminal_at=sessions[-1].closes_at
    )
    metrics = dict(stats.metrics)
    assert metrics["completed_count"].value == 0 and metrics["open_count"].value == 1
    assert (
        metrics["win_rate"].value is None and metrics["win_rate"].status == "no_completed_episodes"
    )


def test_cancellation_timing_does_not_become_a_guessed_cut_completion():
    result, sessions = audited(cancel_tail=True)
    assert result.available and result.episodes[0].completed is True
    full = api()._episode_metrics(
        result, baseline_at=sessions[0].closes_at, terminal_at=sessions[-1].closes_at
    )
    assert dict(full.metrics)["completed_count"].value == 1
    train = api()._episode_metrics(
        result, baseline_at=sessions[0].closes_at, terminal_at=sessions[3].closes_at
    )
    late = api()._episode_metrics(
        result, baseline_at=sessions[3].closes_at, terminal_at=sessions[-1].closes_at
    )
    assert train.ambiguous_episode_ids == late.ambiguous_episode_ids == ("allocation-alpha",)
    assert (
        dict(train.metrics)["completed_count"].value
        is dict(late.metrics)["completed_count"].value
        is None
    )
    assert dict(train.metrics)["open_count"].value is None
    assert dict(late.metrics)["open_count"].value == 0


def test_ambiguous_same_key_fills_never_use_identity_spelling_to_choose():
    result, _ = audited(ambiguous=True)
    assert not result.available and "ambiguous_fill_record_join" in result.reasons


def test_inconsistent_disposal_basis_makes_execution_statistics_unavailable():
    value, records, sessions = ledger_case()
    records = (*records[:2], replace(records[2], disposed_basis=D(1)), *records[3:])
    result = api()._audit_executions(
        value, records, calendar=sessions, rate=D(".25"), native_last_index=203
    )
    assert not result.available and "disposal_record_mismatch" in result.reasons


def policy_closes():
    sessions = calendar(3)
    result = []
    family = "quality_momentum"
    for i, session in enumerate(sessions):
        conditions = []
        for symbol in STOCK_POLICY_SYMBOLS:
            if i == 1 and symbol == "AXP":
                proposal = StrategyProposal(
                    symbol,
                    family,
                    session.closes_at,
                    sessions[2].opens_at,
                    "hold",
                    "fictional known inactive",
                    1,
                    20,
                    ("fictional",),
                )
                conditions.append(KnownPolicyCondition(symbol, family, False, proposal))
            else:
                code = "warmup" if i == 0 else "no_next_open" if i == 2 else "annual_missing"
                conditions.append(
                    UnavailablePolicyCondition(
                        symbol,
                        family,
                        UnavailablePolicy(
                            symbol, family, session.closes_at, "fictional " + code, code
                        ),
                    )
                )
        result.append(
            EconomicPolicyClose(
                session.index, session.closes_at, family, (), tuple(conditions), "a" * 64
            )
        )
    return tuple(result), sessions


def test_policy_coverage_keeps_all_peers_and_terminal_audit_outside_execution_denominator():
    closes, sessions = policy_closes()
    result = api()._policy_coverage(closes, expected=sessions, family="quality_momentum")
    assert result.expected_audit_slots == result.observed_audit_slots == 24
    assert result.expected_executable_slots == 16 and result.terminal_audit_slots == 8
    assert result.known_inactive_count == 1 and result.known_active_count == 0
    assert result.unavailable_count == 15
    assert dict(result.unavailable_by_code) == {"annual_missing": 7, "warmup": 8}
    assert tuple(row.symbol for row in result.by_symbol) == STOCK_POLICY_SYMBOLS
    assert result.by_symbol[0].known_inactive_count == 1
    assert all(row.unavailable_count == 2 for row in result.by_symbol[1:])


def test_missing_policy_close_does_not_shrink_stock_opportunity_denominator():
    closes, sessions = policy_closes()
    result = api()._policy_coverage(
        (closes[0], closes[2]), expected=sessions, family="quality_momentum"
    )
    assert result.expected_audit_slots == 24 and result.observed_audit_slots == 16
    assert result.expected_executable_slots == result.unavailable_count == 16
    assert result.missing_slots == tuple((200, symbol) for symbol in STOCK_POLICY_SYMBOLS)


def test_policy_execution_windows_partition_without_terminal_or_shared_return():
    closes, sessions = policy_closes()
    result = api()._policy_coverage(closes, expected=sessions, family="quality_momentum")
    first = api()._policy_window(result, baseline_index=199, terminal_index=200)
    second = api()._policy_window(result, baseline_index=200, terminal_index=201)
    assert first.expected_executable_slots == second.expected_executable_slots == 8
    assert first.unavailable_count == 8
    assert second.known_inactive_count == 1 and second.unavailable_count == 7


def short_case(*, rate=TAX, unknown=False):
    from trading_bot.research.stock_economic_replay import StockEconomicReplayProtocol
    from trading_bot.research.stock_retrospective_replay import RetrospectiveCaseSpec

    m = api()
    value, records, sessions = ledger_case(rate=rate)
    # Values are hand-checked marked observations around the owned short ledger.
    components = (
        (1000, 0, 0, 0),
        (687, 0, 330, 0),
        (687, 119, 240, 18),
        (687, 377, 0, 64),
        (1064, 0, 0, 64),
    )
    snapshots = tuple(
        EconomicReplaySnapshot(
            session.index,
            session.closes_at,
            D(cash + claims + stock),
            D(cash),
            ZERO,
            D(gain) * (D(1) if rate is None else rate),
            D(claims),
            ZERO,
            ZERO,
            D(stock),
        )
        for session, (cash, claims, stock, gain) in zip(sessions, components, strict=True)
    )
    marks = tuple(
        close_cost(row, unknown=("data",) if unknown and row.session_index == 201 else ())
        for row in snapshots[1:]
    )
    plan = ModeledOperatingCostPlan("fictional-algebra", ())
    spec = RetrospectiveCaseSpec("trend", StockEconomicReplayProtocol(tax_rate=rate), plan)
    closes = tuple(
        EconomicPolicyClose(
            session.index,
            session.closes_at,
            "trend",
            (),
            tuple(
                UnavailablePolicyCondition(
                    symbol,
                    "trend",
                    UnavailablePolicy(
                        symbol,
                        "trend",
                        session.closes_at,
                        "fictional evidence not supplied",
                        "fixture_missing",
                    ),
                )
                for symbol in STOCK_POLICY_SYMBOLS
            ),
            "a" * 64,
        )
        for session in sessions
    )
    return m._CaseMetricFacts(
        spec, value, snapshots, marks, records, closes, sessions, 203, "d" * 64
    )


def short_windows():
    m = api()
    return (
        m._MetricWindow("full", 199, 203),
        m._MetricWindow("train", 199, 201),
        m._MetricWindow("late", 201, 203),
    )


def test_case_paths_turnover_and_exposure_use_same_owned_ledger_and_all_closes():
    result = api()._summarize_case(short_case(), windows=short_windows())
    full = result.segments[0]
    assert dict(full.gross.metrics)["total_return"].value == D(".064")
    assert dict(full.net.metrics)["total_return"].value == D(".064")
    assert dict(full.after_provision.metrics)["total_return"].value == D(".048")
    exposure, execution = dict(full.exposure_metrics), dict(full.execution_metrics)
    assert exposure["mean_gross_equity"].value == D("1047.75")
    with localcontext() as context:
        context.prec = 50
        assert execution["two_way_turnover"].value == D(690) / D("1047.75")
    assert execution["execution_fees_to_starting_capital"].value == D(".006")
    assert execution["paid_operating_expenses_to_starting_capital"].value == 0
    assert result.policy_coverage.unavailable_count == 32
    assert result.expected_policy_audit_slots == 40


def test_unknown_liability_keeps_gross_path_but_not_a_selected_net_subsample():
    full = api()._summarize_case(short_case(unknown=True), windows=short_windows()).segments[0]
    assert dict(full.gross.metrics)["total_return"].value == D(".064")
    assert all(value.value is None for _, value in full.net.metrics)
    assert full.net.expected_return_count == 4
    assert full.unknown_liability_indices == (201,) and full.unknown_liability_ids == ("data",)


def test_metric_rate_cannot_be_relabelled_after_simulation():
    facts = short_case()
    changed = replace(
        facts, spec=replace(facts.spec, protocol=replace(facts.spec.protocol, tax_rate=ZERO))
    )
    with pytest.raises(ValueError):
        api()._summarize_case(changed, windows=short_windows())
    none = api()._summarize_case(short_case(rate=None), windows=short_windows()).segments[0]
    assert all(value.value is None for _, value in none.after_provision.metrics)
    assert dict(none.net.metrics)["total_return"].value == D(".064")


def test_missing_portfolio_mark_never_changes_expected_metric_count():
    facts = short_case()
    facts = replace(facts, snapshots=(*facts.snapshots[:2], *facts.snapshots[3:]))
    full = api()._summarize_case(facts, windows=short_windows()).segments[0]
    assert full.gross.expected_mark_count == 5 and full.gross.observed_mark_count == 4
    assert full.gross.missing_indices == (201,)
    assert dict(full.execution_metrics)["two_way_turnover"].value is None


def test_unavailable_case_never_turns_into_successful_starting_cash_curve():
    facts = short_case()
    result = api()._unavailable_case(
        facts.spec,
        source_root=facts.source_root,
        reasons=("annual_inventory_unavailable",),
        windows=short_windows(),
    )
    assert result.status == "unavailable"
    assert all(
        segment.gross is segment.net is segment.after_provision is None
        for segment in result.segments
    )
    assert result.segments[0].expected_return_count == 4


def registration(**changes):
    m = api()
    return m.MonetaryMetricRegistration(
        **(
            dict(
                source_root="a" * 64,
                expected_case_hashes=("b" * 64,),
                code_revision="c" * 40,
                code_tree="d" * 40,
                source_inventory_hash="e" * 64,
                expected_native_calendar_hash="f" * 64,
                unavailable_comparison_slots=(
                    m.MetricUnavailableSlot("broad_market", "not_registered"),
                ),
            )
            | changes
        )
    )


def test_registration_binds_definitions_and_rejects_duplicate_or_invalid_identity():
    m = api()
    value = registration()
    assert value.definition_hash == m.DEFINITION_HASH
    assert (
        value.clarification_hash
        == "67e6e721af67cf7091d12eb72f0c14d405e73ca5868b5277e0b8b41e897fdc13"
    )
    with pytest.raises(ValueError):
        registration(expected_case_hashes=("b" * 64, "b" * 64))
    with pytest.raises(ValueError):
        registration(code_revision="not-a-revision")
    with pytest.raises(ValueError):
        registration(definition_hash="0" * 64)
    with pytest.raises(ValueError):
        registration(unavailable_comparison_slots=(m.MetricUnavailableSlot("x", "missing"),) * 2)


def test_public_consumer_rejects_private_short_facts_instead_of_relabelling_them():
    with pytest.raises(ValueError):
        api().summarize_retrospective_monetary_result(
            short_case(), fresh_inputs=None, registration=registration()
        )


def test_public_metric_profile_requires_completed706_result():
    from tests.unit.research.test_stock_retrospective_replay import begin
    from tests.unit.research.test_stock_retrospective_replay_inputs import prepared
    from trading_bot.research.stock_retrospective_replay import RetrospectiveEconomicReplayResult

    m = api()
    data = prepared()
    state = begin(data=data)
    registered = registration(
        source_root=state.source_root,
        expected_case_hashes=tuple(case.spec_hash for case in state.cases),
        expected_native_calendar_hash=m.monetary_native_calendar_hash(data.calendar),
    )
    with pytest.raises(ValueError):
        m.summarize_retrospective_monetary_result(
            RetrospectiveEconomicReplayResult(state, state.source_root),
            fresh_inputs=data,
            registration=registered,
        )


def test_case_audits_once_for_three_windows_and_retains_scope_limits(monkeypatch):
    m = api()
    facts = short_case()
    original_execution, original_policy = m._audit_executions, m._policy_coverage
    counts = {"execution": 0, "policy": 0}

    def execution(*args, **kwargs):
        counts["execution"] += 1
        return original_execution(*args, **kwargs)

    def policy(*args, **kwargs):
        counts["policy"] += 1
        return original_policy(*args, **kwargs)

    monkeypatch.setattr(m, "_audit_executions", execution)
    monkeypatch.setattr(m, "_policy_coverage", policy)
    result = m._summarize_case(facts, windows=short_windows())
    assert counts == {"execution": 1, "policy": 1}
    assert "quarterly_5pp_rebalancing_not_implemented_or_evaluated" in result.replay_limitations
    assert result.qualified is result.live_authorized is result.full_task5_complete is False


def test_past_owned_runner_is_known_open_when_all_orders_already_filled():
    result, sessions = audited(runner=True)
    stats = api()._episode_metrics(
        result, baseline_at=sessions[0].closes_at, terminal_at=sessions[2].closes_at
    )
    assert dict(stats.metrics)["open_count"].value == 1
    assert dict(stats.metrics)["active_order_count"].value == 0


@pytest.mark.parametrize("rate", [D(".3"), D("NaN"), D("sNaN"), True, 0.25])
def test_nonregistered_or_nonfinite_rates_fail_with_stable_value_error(rate):
    value = snapshot()
    with pytest.raises(ValueError):
        project(value, close_cost(value), rate=rate)


def test_case_evidence_retains_full_spec_and_rejects_relabelled_tax_identity():
    facts = short_case()
    result = api()._summarize_case(facts, windows=short_windows())
    assert result.case_spec == facts.spec
    assert result.account_evidence_hash == facts.book.evidence_hash
    with pytest.raises(ValueError):
        _ = replace(result, tax_rate=ZERO).evidence_hash
    with pytest.raises(ValueError):
        _ = replace(result, family="mean_reversion").evidence_hash


def unavailable_report():
    from trading_bot.research.hybrid_strategies import FAMILIES
    from trading_bot.research.stock_monetary_admission import MonetaryCaseDependency
    from trading_bot.research.stock_retrospective_replay_inputs import RetrospectiveReplayConvention

    m = api()
    facts = short_case()
    case = m._unavailable_case(
        facts.spec, source_root=facts.source_root, reasons=("fixture_unavailable",)
    )
    deps = tuple(
        MonetaryCaseDependency(symbol, family, "unavailable", ("fixture_unavailable",))
        for symbol in STOCK_POLICY_SYMBOLS
        for family in FAMILIES
    )
    reg = registration(
        source_root=facts.source_root, expected_case_hashes=(facts.spec.evidence_hash,)
    )
    return m.MonetaryMetricReport(
        reg,
        "a" * 64,
        (case,),
        deps,
        tuple((symbol, "quality_stock_allocator_unavailable") for symbol in STOCK_POLICY_SYMBOLS),
        RetrospectiveReplayConvention(),
    )


def test_report_missing_inventory_must_keep_exact56_pairs_not_only_count():
    report = unavailable_report()
    assert len(report.full_constrained_cases) == 56
    bad = (
        replace(report.full_constrained_cases[0], symbol="SPY"),
        *report.full_constrained_cases[1:],
    )
    with pytest.raises(ValueError):
        _ = replace(report, full_constrained_cases=bad).evidence_hash


def test_report_cannot_wrap_short_private_curves_as_full706_metrics():
    report = unavailable_report()
    short = api()._summarize_case(short_case(), windows=short_windows())
    with pytest.raises(ValueError):
        _ = replace(report, cases=(short,)).evidence_hash


def cohort_audit(pnls, *, same_session=False):
    sessions = calendar(4)
    value = create_dividend_book(
        Account(),
        account_at=sessions[0].closes_at,
        sessions=sessions,
        calendar_source_hash="b" * 64,
        tax_rate=TAX,
    )
    records = []
    policy = HybridSettings(tax_rate=TAX)

    def adopt(account, at):
        nonlocal value
        value = adopt_dividend_account(value, account, at=at)

    for side, index in (("buy", 200), ("sell", 200 if same_session else 201)):
        for i, pnl in enumerate(pnls):
            price = D(10) if side == "buy" else D(10) + pnl
            at = sessions[index - 199].opens_at
            oid, fid = f"opaque-{i}-{side}", f"fact-{i}-{side}"
            order = PaperOrder(
                id=oid,
                symbol="AXP",
                side=side,
                sleeve="tactical",
                quantity=D(1),
                episode_id=f"episode-{i}",
                reserved_cash=price if side == "buy" else ZERO,
            )
            adopt(
                Account.model_validate(
                    value.account.model_dump() | {"orders": (*value.account.orders, order)}
                ),
                at,
            )
            fill = FillFact(id=fid, order_id=oid, quantity=D(1), price=price, fee=ZERO, at=at)
            due = sessions[-1].opens_at if side == "sell" else None
            adopt(fill_order(value.account, fill, policy, settlement_at=due), at)
            records.append(
                EconomicReplayRecord(
                    index,
                    at,
                    "AXP",
                    side,
                    "filled",
                    "fictional",
                    oid,
                    D(1),
                    price,
                    ZERO,
                    due,
                    price if side == "sell" else ZERO,
                    D(10) if side == "sell" else ZERO,
                    pnl if side == "sell" else ZERO,
                )
            )
    adopt(settle(value.account, sessions[-1].opens_at), sessions[-1].opens_at)
    adopt(value.account, sessions[-1].closes_at)
    return api()._audit_executions(
        value, tuple(records), calendar=sessions, rate=TAX, native_last_index=sessions[-1].index
    ), sessions


def test_positive_negative_and_zero_episodes_keep_all_completed_in_denominator():
    audit, sessions = cohort_audit((D(2), D(-1), ZERO), same_session=True)
    assert audit.available and len(audit.episodes) == 3
    result = api()._episode_metrics(
        audit, baseline_at=sessions[0].closes_at, terminal_at=sessions[-1].closes_at
    )
    metrics = dict(result.metrics)
    assert metrics["completed_count"].value == 3 and metrics["zero_count"].value == 1
    with localcontext() as context:
        context.prec = 50
        assert metrics["win_rate"].value == D(1) / 3
    assert metrics["profit_factor"].value == 2
    assert metrics["average_win"].value == 2 and metrics["average_loss"].value == -1
    assert metrics["mean_holding_intervals"].value == metrics["mean_holding_days"].value == 0


def test_missing_winner_cohort_is_none_while_defined_zero_profit_factor_stays_zero():
    audit, sessions = cohort_audit((D(-1), ZERO), same_session=True)
    metrics = dict(
        api()
        ._episode_metrics(
            audit, baseline_at=sessions[0].closes_at, terminal_at=sessions[-1].closes_at
        )
        .metrics
    )
    assert metrics["profit_factor"].value == metrics["win_rate"].value == 0
    assert metrics["average_win"].value is None
    assert metrics["average_win"].status == "no_positive_episodes"


def test_unavailable_case_identity_hash_owns_ambient_decimal_capitals():
    from trading_bot.research.stock_economic_replay import StockEconomicReplayProtocol
    from trading_bot.research.stock_retrospective_replay import RetrospectiveCaseSpec

    m = api()
    spec = RetrospectiveCaseSpec(
        "trend",
        StockEconomicReplayProtocol(fee_usd=D("1e-8")),
        ModeledOperatingCostPlan("fictional", ()),
    )
    expected = m._unavailable_case(spec, source_root="a" * 64, reasons=("missing",))
    expected_hash = expected.evidence_hash
    with localcontext() as context:
        context.capitals = 0
        actual = m._unavailable_case(spec, source_root="a" * 64, reasons=("missing",))
        assert actual == expected
        assert actual.evidence_hash == expected_hash
        assert expected.evidence_hash == expected_hash
