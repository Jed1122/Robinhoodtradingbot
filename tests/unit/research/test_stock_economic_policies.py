"""Fictional full-cohort policies and owned economic sessions; no real outcomes."""

import importlib
import importlib.util
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, Inexact, localcontext

import pytest

from trading_bot.market_data.stock_events import normalize_filing_index
from trading_bot.market_data.stock_filing_facts import normalize_filing_facts
from trading_bot.research.hybrid_policies import (
    CalendarSession,
    PolicyEvent,
    PolicyInput,
    SessionObservation,
    UniverseMembership,
)
from trading_bot.research.hybrid_strategies import FAMILIES, PriceBar
from trading_bot.research.stock_annual_quality import (
    AnnualQualityPeriods,
    AnnualQualityRequest,
    build_annual_quality,
)
from trading_bot.research.stock_economic_replay import (
    ModeledAsset,
    ModeledExecutionDirective,
    SettlementDay,
    StockEconomicReplayProtocol,
    advance_stock_economic_session,
    begin_stock_economic_replay,
    finish_stock_economic_replay,
    make_fictional_replay_inputs,
)

D = Decimal
SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY")
HASH = "a" * 64
DEFAULT_VOLUME = D(1000)


def api():
    name = "trading_bot.research.stock_economic_policies"
    assert importlib.util.find_spec(name) is not None, "typed policy orchestration API missing"
    return importlib.import_module(name)


def fixture(*, count=207, closes=None, directives=()):
    day = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    calendar = []
    while len(calendar) < count + 12:
        if day.weekday() < 5:
            calendar.append(
                CalendarSession(len(calendar), day, day + timedelta(hours=6, minutes=30))
            )
        day += timedelta(days=1)
    assets = []
    for slot, symbol in enumerate((*SYMBOLS, "SPY")):
        prices = tuple(D(100) if symbol == "SPY" else D(100) + D(i) / 10 for i in range(count))
        if closes and symbol in closes:
            prices = tuple(map(D, closes[symbol]))
        assets.append(
            ModeledAsset(
                symbol,
                "passive_comparison" if symbol == "SPY" else "stock_candidate",
                f"sector-{slot}",
                D(50000000),
                True,
                calendar[0].closes_at,
                tuple(
                    PriceBar(calendar[i].closes_at, value, value) for i, value in enumerate(prices)
                ),
                (False,) * count,
            )
        )
    settlement, cursor = [], calendar[0].opens_at.date()
    while cursor <= calendar[-1].opens_at.date():
        settlement.append(
            SettlementDay(cursor, "ordinary_supported" if cursor.weekday() < 5 else "closed", HASH)
        )
        cursor += timedelta(days=1)
    return make_fictional_replay_inputs(
        tuple(assets),
        tuple(calendar),
        tuple(settlement),
        long_term_allocations=(("SPY", D(".75")),),
        execution_directives=directives,
        calendar_source_hash=HASH,
    )


def request(data, index, *, volume=DEFAULT_VOLUME, observations=None):
    return PolicyInput(
        data.calendar[: min(index + 2, len(data.assets[0].bars))],
        tuple(
            SessionObservation(asset.symbol, i, asset.bars[i], volume)
            for asset in data.assets[:8]
            for i in range(max(0, index - 252), index + 1)
        )
        if observations is None
        else observations,
        tuple(
            UniverseMembership(
                symbol,
                data.calendar[0].closes_at,
                data.calendar[0].closes_at,
                True,
                "member-" + symbol,
            )
            for symbol in SYMBOLS
        ),
        data.calendar[index].closes_at,
        True,
    )


def begin(data, family="trend", **protocol):
    return begin_stock_economic_replay(
        data,
        StockEconomicReplayProtocol(**protocol),
        policy_frame=api().EconomicPolicyFrame(family, request(data, 199)),
    )


def advance(state, *, data_request=None, family=None):
    index = state.next_session
    return advance_stock_economic_session(
        state,
        session_index=index,
        policy_frame=api().EconomicPolicyFrame(
            family or state.policy_family,
            request(state.inputs, index) if data_request is None else data_request,
        ),
    )


def through(state, last):
    while state.next_session <= last:
        state = advance(state)
    return state


def test_actual_trend_policy_enters_despite_scripted_false_and_records_all_eight():
    data = fixture()
    state = begin(data)
    assert state.policy_family == "trend"
    assert tuple(c.symbol for c in state.policy_closes[0].conditions) == SYMBOLS
    assert all(
        isinstance(c, api().KnownPolicyCondition) and c.active
        for c in state.policy_closes[0].conditions
    )
    assert any(intent.sleeve == "tactical" for intent in state.pending)
    entered = advance(state)
    assert any(lot.sleeve == "tactical" for lot in entered.book.account.lots)
    assert entered.policy_closes[-1].held_positions == tuple(
        (s, "trend")
        for s in sorted(
            {lot.symbol for lot in entered.book.account.lots if lot.sleeve == "tactical"}
        )
    )
    assert all(
        c.proposal.decision
        == ("hold" if (c.symbol, "trend") in entered.policy_closes[-1].held_positions else "enter")
        for c in entered.policy_closes[-1].conditions
    )


def test_unavailable_held_frame_preserves_last_defined_and_does_not_force_exit():
    state = advance(begin(fixture()))
    previous = state.previous_signals
    missing = replace(request(state.inputs, 201), observations=())
    state = advance(state, data_request=missing)
    assert all(
        isinstance(c, api().UnavailablePolicyCondition) for c in state.policy_closes[-1].conditions
    )
    assert state.previous_signals == previous
    assert not any(p.reason == "family_signal_exit" for p in state.pending)
    state = advance(state)
    assert not any(p.side == "buy" and p.sleeve == "tactical" for p in state.pending)


def test_defined_family_failure_exits_once_at_the_next_open():
    prices = ["100"] * 199 + ["100.01", "100.01", "99.99"] + ["100"] * 5
    state = through(begin(fixture(closes={"AXP": prices})), 201)
    intent = next(p for p in state.pending if p.symbol == "AXP")
    assert intent.side == "sell" and intent.reason == "family_signal_exit"
    state = advance(state)
    sale = [r for r in state.records if r.symbol == "AXP" and r.reason == "family_signal_exit"]
    assert len(sale) == 1 and sale[0].at == state.inputs.calendar[202].opens_at


def test_missing_one_momentum_member_preserves_the_full_unavailable_denominator():
    data = fixture(count=255)
    supplied = request(data, 252)
    supplied = replace(
        supplied,
        observations=tuple(
            row
            for row in supplied.observations
            if not (row.symbol == "OXY" and row.session_index == 0)
        ),
    )
    close = api().evaluate_economic_policy_close(
        api().EconomicPolicyFrame("momentum", supplied),
        session_index=252,
        information_at=data.calendar[252].closes_at,
        next_open=data.calendar[253].opens_at,
        held_positions=(),
    )
    assert tuple(c.symbol for c in close.conditions) == SYMBOLS
    assert all(
        isinstance(c, api().UnavailablePolicyCondition) and c.outcome.code == "missing_history"
        for c in close.conditions
    )


def test_unavailable_does_not_disable_known_price_stop():
    values = [str(D(100) + D(i) / 10) for i in range(207)]
    values[201] = "110"
    state = advance(begin(fixture(closes={"AXP": values})))
    state = advance(state, data_request=replace(request(state.inputs, 201), observations=()))
    assert any(p.symbol == "AXP" and p.reason == "initial_stop" for p in state.pending)


def test_rejected_entry_is_not_held_and_continuous_true_cannot_retry():
    state = begin(fixture(directives=(ModeledExecutionDirective(200, "AXP", reject=True),)))
    state = advance(state)
    assert ("AXP", "trend") not in state.policy_closes[-1].held_positions
    assert not any(p.symbol == "AXP" and p.side == "buy" for p in state.pending)


@pytest.mark.parametrize(
    "family,maximum",
    [
        ("mean_reversion", 5),
        ("breakout", 20),
        ("pead", 20),
        ("revision_momentum", 30),
        ("trend", 40),
    ],
)
def test_actual_first_fill_owns_family_age_through_unavailable_frames(family, maximum):
    data = fixture(count=245)
    if family == "mean_reversion":
        prices = ["100"] * 194 + ["130"] * 5 + ["123"] * (245 - 199)
        data = fixture(count=245, closes={"AXP": prices})
    opening_request = request(data, 199)
    if family == "breakout":
        opening_request = replace(
            opening_request,
            observations=tuple(
                replace(row, volume=D(2000)) if row.session_index == 199 else row
                for row in opening_request.observations
            ),
        )
    if family in ("pead", "revision_momentum"):
        kind = "earnings" if family == "pead" else "revision"
        event_indexes = (198,) if family == "pead" else (197, 198)
        opening_request = replace(
            opening_request,
            events=tuple(
                PolicyEvent(
                    "AXP",
                    kind,
                    f"fictional-{kind}-{i}",
                    i,
                    data.calendar[i].closes_at,
                    data.calendar[i].closes_at,
                    D(".10"),
                )
                for i in event_indexes
            ),
        )
    state = begin_stock_economic_replay(
        data,
        StockEconomicReplayProtocol(),
        policy_frame=api().EconomicPolicyFrame(family, opening_request),
    )
    assert any(p.symbol == "AXP" and p.side == "buy" for p in state.pending)
    while state.next_session <= 199 + maximum:
        index = state.next_session
        state = advance(state, data_request=replace(request(data, index), observations=()))
        if index < 199 + maximum:
            assert not any(
                p.symbol == "AXP" and p.reason == "holding_time_exit" for p in state.pending
            )
    rule = next(r for r in state.policy_episodes if r.episode_id.endswith("AXP:200:tactical"))
    assert rule.family == family and rule.maximum_holding_sessions == maximum
    assert any(p.symbol == "AXP" and p.reason == "holding_time_exit" for p in state.pending)
    executed = advance(
        state, data_request=replace(request(data, state.next_session), observations=())
    )
    sale = next(
        r
        for r in executed.records
        if r.symbol == "AXP" and r.reason == "holding_time_exit" and r.outcome == "filled"
    )
    assert sale.at == data.calendar[200 + maximum].opens_at


def test_policy_mode_family_and_observation_clocks_cannot_change():
    state = begin(fixture())
    with pytest.raises(ValueError):
        advance_stock_economic_session(state, session_index=200)
    with pytest.raises(ValueError):
        advance(state, family="momentum")
    with pytest.raises(ValueError):
        advance(state, data_request=request(state.inputs, 201))
    with pytest.raises(ValueError):
        api().EconomicPolicyFrame(
            "trend", replace(request(state.inputs, 200), held_positions=(("AXP", "trend"),))
        )
    with pytest.raises(ValueError, match="policy_state_family_history_mismatch"):
        advance(replace(state, policy_family="momentum"), family="momentum")
    with pytest.raises(ValueError, match="policy_state_family_history_mismatch"):
        advance_stock_economic_session(replace(state, policy_family=None), session_index=200)


def test_full_cohort_and_explicit_passive_baseline_are_required():
    data = fixture()
    with pytest.raises(ValueError):
        begin(replace(data, assets=data.assets[1:]))
    with pytest.raises(ValueError):
        begin(replace(data, long_term_allocations=()))
    with pytest.raises(ValueError):
        api().EconomicPolicyFrame(
            "trend", replace(request(data, 199), universe=request(data, 199).universe[:-1])
        )


def test_seven_isolated_cases_keep_unavailable_families_and_quality_slots():
    data = fixture(count=203)
    result = api().run_seven_family_fictional_replay(
        data, tuple(request(data, i) for i in range(199, 203)), StockEconomicReplayProtocol()
    )
    assert tuple(case.family for case in result.cases) == FAMILIES
    assert len({id(case.replay.book.account) for case in result.cases}) == 7
    assert all(
        tuple(symbol for symbol, _ in case.long_term_quality.slots) == SYMBOLS
        for case in result.cases
    )
    assert all(case.long_term_quality.status == "unavailable" for case in result.cases)
    assert all(case.replay.book.account.starting_capital == D(1000) for case in result.cases)
    assert all(
        case.policy_closes[-1].information_at == data.calendar[202].closes_at
        for case in result.cases
    )
    assert all(
        all(
            condition.outcome.code == "missing_calendar"
            for condition in case.policy_closes[-1].conditions
        )
        for case in result.cases
    )
    assert result.full_task5_complete is result.live_authorized is result.qualified is False
    assert not hasattr(result, "winner")


def test_final_no_next_session_resume_and_legacy_mode_are_preserved():
    data = fixture(count=204)
    first = begin(data)
    resumed = through(advance(first), 203)
    full = through(begin(data), 203)
    assert resumed.evidence_hash == full.evidence_hash
    result = finish_stock_economic_replay(full)
    assert all(fill.at <= data.calendar[203].opens_at for fill in result.book.account.fills)
    legacy = begin_stock_economic_replay(data, StockEconomicReplayProtocol())
    assert legacy.policy_family is None and legacy.policy_closes == legacy.policy_episodes == ()
    assert not any(p.sleeve == "tactical" for p in legacy.pending)
    with pytest.raises(ValueError):
        advance_stock_economic_session(
            legacy,
            session_index=200,
            policy_frame=api().EconomicPolicyFrame("trend", request(data, 200)),
        )


def test_future_owned_price_changes_cannot_change_an_earlier_policy_or_order():
    original = fixture()
    changed = replace(
        original,
        assets=tuple(
            replace(
                asset,
                bars=(
                    *asset.bars[:205],
                    replace(asset.bars[205], open=D(999), close=D(999)),
                    *asset.bars[206:],
                ),
            )
            for asset in original.assets
        ),
    )
    first, second = through(begin(original), 201), through(begin(changed), 201)
    assert first.pending == second.pending
    assert first.records == second.records and first.snapshots == second.snapshots
    assert tuple(c.evidence_hash for c in first.policy_closes) == tuple(
        c.evidence_hash for c in second.policy_closes
    )


def test_policy_arithmetic_and_evidence_ignore_hostile_ambient_context():
    data = fixture()
    baseline = advance(begin(data)).evidence_hash
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert advance(begin(data)).evidence_hash == baseline


def test_policy_digest_retains_valid_unused_native_numbers_through_annual_evidence():
    data = fixture()

    def bundle(unused_value):
        fid = "fictional-policy-digest-original"
        received = datetime(2026, 10, 26, tzinfo=UTC)
        filing = normalize_filing_index(
            {
                "data": {
                    "symbol": "AXP",
                    "filings": [
                        {
                            "filing_id": fid,
                            "date_filed": "2024-02-09",
                            "form_type": "10-K",
                            "description": "Fictional digest test",
                        }
                    ],
                }
            },
            received_at=received,
            observation_sha256="b" * 64,
            requested_symbol="AXP",
        ).records[0]
        definitions = (
            ("NetIncomeLoss", "20", "2023-01-01", "2023-12-31"),
            ("RevenuesNetOfInterestExpense", "150", "2023-01-01", "2023-12-31"),
            ("RevenuesNetOfInterestExpense", "100", "2022-01-01", "2022-12-31"),
            ("StockholdersEquity", "80", None, "2022-12-31"),
            ("StockholdersEquity", "120", None, "2023-12-31"),
            ("LongTermDebt", "30", None, "2023-12-31"),
            ("ShortTermBorrowings", "10", None, "2023-12-31"),
            ("NetIncomeLoss", unused_value, "2020-01-01", "2020-12-31"),
        )
        rows = []
        for concept, value, start, end in definitions:
            row = {
                "filing_id": fid,
                "concept": concept,
                "entity": "0000999996",
                "period": f"{start}/{end}" if start else end,
                "axises": [],
                "char_value": "",
                "end_date": end,
                "unit": "iso4217:USD",
                "decimals": 0,
                "value": value,
            }
            if start:
                row["start_date"] = start
            rows.append(row)
        facts = normalize_filing_facts(
            {"data": {"facts": rows}, "guide": "Fictional"},
            received_at=received,
            observation_sha256="c" * 64,
            requested_filing_ids=(fid,),
            requested_concepts=tuple(dict.fromkeys(row[0] for row in definitions)),
        )
        return build_annual_quality(
            AnnualQualityRequest(
                filing,
                (facts,),
                "0000999996",
                AnnualQualityPeriods(
                    date(2023, 1, 1), date(2023, 12, 31), date(2022, 1, 1), date(2022, 12, 31)
                ),
                datetime(2024, 2, 11, tzinfo=UTC),
            )
        )

    states = [
        begin_stock_economic_replay(
            data,
            StockEconomicReplayProtocol(),
            policy_frame=api().EconomicPolicyFrame(
                "trend", replace(request(data, 199), annual_quality=(bundle(value),))
            ),
        )
        for value in ("1e1000", "2e1000")
    ]
    assert (
        states[0].policy_closes[0].input_evidence_hash
        != states[1].policy_closes[0].input_evidence_hash
    )
    assert tuple(c.active for c in states[0].policy_closes[0].conditions) == tuple(
        c.active for c in states[1].policy_closes[0].conditions
    )


def test_new_records_cannot_promote_or_mutate_authority():
    frame = begin(fixture()).policy_closes[0]
    with pytest.raises(FrozenInstanceError):
        frame.qualified = True
    with pytest.raises((ValueError, TypeError)):
        replace(frame, qualified=True)


def test_seven_family_result_rejects_forged_nested_authority():
    data = fixture(count=201)
    result = api().run_seven_family_fictional_replay(
        data, tuple(request(data, i) for i in range(199, 201)), StockEconomicReplayProtocol()
    )
    object.__setattr__(result.cases[0].replay, "qualified", True)
    with pytest.raises(ValueError):
        _ = result.evidence_hash


def test_forged_owned_family_limit_is_rejected_instead_of_extending_a_holding():
    state = advance(begin(fixture()))
    rule = state.policy_episodes[0]
    object.__setattr__(rule, "maximum_holding_sessions", 400)
    with pytest.raises(ValueError):
        advance(state)


def test_future_observation_and_mutable_frame_flags_are_rejected():
    state = begin(fixture())
    values = (
        *request(state.inputs, 200).observations,
        SessionObservation("AXP", 201, state.inputs.assets[0].bars[201], D(1000)),
    )
    with pytest.raises(ValueError):
        advance(state, data_request=replace(request(state.inputs, 200), observations=values))
    frame = api().EconomicPolicyFrame("trend", request(state.inputs, 200))
    object.__setattr__(frame, "live_authorized", True)
    with pytest.raises(ValueError):
        advance_stock_economic_session(state, session_index=200, policy_frame=frame)


@pytest.mark.parametrize("field", ["open", "close"])
def test_policy_price_prefix_cannot_disagree_with_owned_fictional_bars(field):
    state = begin(fixture())
    supplied = request(state.inputs, 200)
    changed = replace(supplied.observations[0].bar, **{field: D("199")})
    observations = (replace(supplied.observations[0], bar=changed), *supplied.observations[1:])
    with pytest.raises(ValueError, match="policy_observation_scope_mismatch"):
        advance(state, data_request=replace(supplied, observations=observations))


def test_policy_older_calendar_row_cannot_disagree_with_owned_calendar():
    state = begin(fixture())
    supplied = request(state.inputs, 200)
    sessions = (
        replace(
            supplied.sessions[0], opens_at=supplied.sessions[0].opens_at + timedelta(minutes=1)
        ),
        *supplied.sessions[1:],
    )
    with pytest.raises(ValueError, match="policy_calendar_scope_mismatch"):
        advance(state, data_request=replace(supplied, sessions=sessions))


def test_partial_entry_has_one_first_fill_rule_and_an_owned_profit_rung_survives_unknown():
    data = fixture(directives=(ModeledExecutionDirective(200, "AXP", fill_fraction=D(".5")),))
    state = advance(begin(data))
    assert len([r for r in state.policy_episodes if "AXP:200:tactical" in r.episode_id]) == 1
    owned = [r for r in state.episodes if "AXP:200:tactical" in r.episode_id]
    assert len(owned) == 1 and owned[0].entered_session == 200

    prices = [str(D(100) + D(i) / 10) for i in range(207)]
    prices[201] = "139.2"
    prices[202:] = ["136.8"] * 5
    data = fixture(
        closes={"AXP": prices},
        directives=(ModeledExecutionDirective(202, "AXP", fill_fraction=D(".5")),),
    )
    state = through(begin(data), 201)
    state = advance(state, data_request=replace(request(data, 202), observations=()))
    progress = next(p for p in state.book.account.exit_progress if p.symbol == "AXP")
    assert 0 < progress.filled < progress.target
    resumed = next(p for p in state.pending if p.symbol == "AXP")
    assert resumed.reason == "resume_owned_profit_rung"
    assert resumed.exit_order.threshold == progress.threshold
    assert resumed.exit_order.quantity <= progress.target - progress.filled
