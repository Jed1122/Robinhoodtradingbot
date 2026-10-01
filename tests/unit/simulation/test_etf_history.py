"""Causal fixture decisions cannot masquerade as execution or actual research."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.domain import AssetClass, Bar, BarInterval, CorporateAction, MarketClock
from trading_bot.market_data.etf_source import (
    EtfActionEvent,
    EtfObservedBar,
    EtfSessionEvent,
    _ns,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_study import freeze_etf_study
from trading_bot.strategies.protocol import StrategyAction

CONFIGS = Path(__file__).parents[3] / "configs"
START = datetime(2016, 1, 1, tzinfo=UTC)
D = Decimal
DEFAULT_CASH = D("500")
DEFAULT_WIDTH = D("1")


def study(**kwargs):
    policy = load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "backtest.yaml",
        CONFIGS / "safety-envelope.yaml",
        {"TRADING_BOT__EQUITY_STRATEGIES__ETF_PILOT__ENABLED": "true"},
    )
    return freeze_etf_study(
        policy,
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        holdout_previously_examined=False,
        **kwargs,
    )


def bar(index, close, *, ordinal=None, available=None, revision=None, width=DEFAULT_WIDTH):
    end = START + timedelta(days=index, hours=21)
    number = index if ordinal is None else ordinal
    body = (index, str(close), number, available, revision, str(width))
    digest = content_hash(body)
    price = D(close)
    return EtfObservedBar(
        digest,
        number,
        _ns(end),
        _ns(end) + 1 if available is None else available,
        "SPY",
        revision,
        Bar(
            "SPY",
            BarInterval.ONE_DAY,
            end - timedelta(hours=7),
            end,
            price,
            price + width,
            price - width,
            price,
            D("10000"),
            "synthetic",
            digest,
        ),
    )


def session(day, ordinal, *, nanos=0, **flags):
    now = START + timedelta(days=day, hours=14, minutes=30)
    digest = content_hash((day, ordinal, nanos, flags))
    return EtfSessionEvent(
        digest,
        ordinal,
        _ns(now) + nanos,
        _ns(now) + nanos,
        "SPY",
        None,
        MarketClock(
            AssetClass.EQUITY,
            "XNYS",
            now + timedelta(microseconds=(nanos + 999) // 1000),
            flags.get("is_open", True),
            flags.get("halted", False),
            flags.get("trading_disabled", False),
            flags.get("cancel_only", False),
            now + timedelta(days=1),
            now + timedelta(hours=6, minutes=30),
        ),
    )


def bars(count=750):
    return tuple(bar(index, D("100") + D(index) / 100) for index in range(count))


def request(events, cash=DEFAULT_CASH, frozen_study=None):
    from trading_bot.simulation.etf_history import EtfFixturePrefixRequest

    return EtfFixturePrefixRequest(study() if frozen_study is None else frozen_study, events, cash)


def run(events, cash=DEFAULT_CASH, **kwargs):
    from trading_bot.simulation.etf_history import run_etf_fixture_prefix

    return run_etf_fixture_prefix(request(events, cash), **kwargs)


@pytest.mark.parametrize("count", [0, 99])
def test_missing_feature_history_denies_without_inventing_bars(count):
    result = run((*bars(count), session(751, count)))
    assert len(result.decisions) == 1
    assert result.decisions[0].signal is None
    assert "feature_history_insufficient" in result.decisions[0].reasons
    assert result.cash == D("500") and result.shares == 0


def test_hundred_bars_compute_signal_but_do_not_waive_750_bar_warmup():
    result = run((*bars(100), session(751, 100)))
    decision = result.decisions[0]
    assert decision.signal.action is StrategyAction.ENTER_LONG
    assert "study_warmup_incomplete" in decision.reasons
    assert decision.cadence_index is None and not decision.admission_allowed


def test_features_use_exact_latest_100_bars_and_fixed_risk_reference():
    history = (bar(0, D("1000000")), *bars()[1:])
    for cash in (D("500"), D("1000")):
        result = run((*history, session(751, 750)), cash)
        decision = result.decisions[0]
        assert decision.signal.action is StrategyAction.ENTER_LONG
        assert len(decision.selected_bar_hashes) == 100
        assert decision.selected_bar_hashes[0] == history[650].source_record_hash
        assert decision.cadence_index == 0
        assert result.risk_equity_reference == D("100")
        assert result.cash == cash and result.shares == result.reserved_cash == 0
        assert not result.execution_enabled and not result.evidence_promotable
        assert not decision.admission_allowed
        assert "execution_not_implemented" in decision.reasons


@pytest.mark.parametrize(
    "closes",
    [
        (D("200"),) + (D("90"),) * 79 + (D("100"),) * 20,
        (D("90"),) * 80 + (D("110"),) * 19 + (D("89"),),
    ],
)
def test_momentum_requires_positive_return_and_latest_price_not_just_averages(closes):
    history = bars(650) + tuple(bar(650 + i, price) for i, price in enumerate(closes))
    result = run((*history, session(751, 750)))
    assert result.decisions[0].signal.action is StrategyAction.HOLD
    assert "momentum_not_confirmed" in result.decisions[0].signal.reason_codes


def test_five_session_cadence_is_anchored_after_warmup_and_skips_repeat_snapshots():
    events = bars() + tuple(session(751 + i, 750 + i) for i in range(7))
    result = run(events)
    assert [d.cadence_index for d in result.decisions] == [0, 1, 2, 3, 4, 5, 6]
    assert [d.on_cadence for d in result.decisions] == [
        True,
        False,
        False,
        False,
        False,
        True,
        False,
    ]
    repeated = (*events[:751], session(751, 751, nanos=1))
    assert len(run(repeated).decisions) == 1


def test_nanosecond_availability_equal_to_decision_is_not_prior_information():
    opening = session(751, 750)
    history = (*bars()[:-1], bar(749, D("107.49"), available=opening.available_at_ns))
    result = run((*history, opening))
    assert len(result.decisions[0].selected_bar_hashes) == 100
    assert history[-1].source_record_hash not in result.decisions[0].selected_bar_hashes
    assert "study_warmup_incomplete" in result.decisions[0].reasons
    later = session(752, 751)
    assert run((*history, opening, later)).decisions[-1].cadence_index == 0


def test_future_correction_changes_only_later_decisions():
    original = bars()
    opening = session(751, 750)
    correction = bar(
        749,
        D("1"),
        ordinal=751,
        available=opening.available_at_ns + 1,
        revision=original[-1].source_record_hash,
        width=D("0.5"),
    )
    before = run((*original, opening))
    after = run((*original, opening, correction, session(756, 752)))
    assert after.decisions[0] == before.decisions[0]
    assert after.decisions[0].decision_hash == before.decisions[0].decision_hash
    assert after.decisions[-1].signal.action is StrategyAction.HOLD
    assert after.decisions[-1].selected_bar_hashes[-1] == correction.source_record_hash


def test_zero_atr_is_explicitly_ineligible():
    history = tuple(bar(index, D("100"), width=D("0")) for index in range(750))
    assert "atr_unavailable" in run((*history, session(751, 750))).decisions[0].reasons


@pytest.mark.parametrize("flag", ["halted", "trading_disabled", "cancel_only"])
def test_blocked_session_does_not_advance_eligible_cadence(flag):
    result = run((*bars(), session(751, 750, **{flag: True}), session(752, 751)))
    assert result.decisions[0].cadence_index is None
    assert "session_not_eligible" in result.decisions[0].reasons
    assert result.decisions[1].cadence_index == 0


def test_visible_effective_action_is_denied_not_silently_adjusted():
    opening = session(751, 751)
    observed = START + timedelta(days=750, hours=22)
    digest = content_hash("action")
    action = EtfActionEvent(
        digest,
        750,
        _ns(observed),
        _ns(observed),
        "SPY",
        None,
        CorporateAction("SPY", "dividend", observed.date(), observed, None, D("1"), digest),
    )
    result = run((*bars(), action, opening))
    assert result.decisions[0].signal is None
    assert "corporate_action_normalization_unimplemented" in result.decisions[0].reasons


def test_unknown_or_conflicting_source_order_denies():
    from trading_bot.simulation.etf_history import EtfHistoryError

    events = bars(2)
    for bad in (list(events), (events[1], events[0]), (*events, events[0]), (object(),)):
        with pytest.raises(EtfHistoryError, match="etf_history_invalid"):
            request(bad)


@pytest.mark.parametrize("cash", [True, D("100"), D("1001"), D("NaN"), "500"])
def test_cash_cannot_change_study_capital_or_risk_authority(cash):
    from trading_bot.simulation.etf_history import EtfHistoryError

    with pytest.raises(EtfHistoryError):
        request((), cash)


def test_default_decimal_context_cannot_change_decision_identity():
    events = (*bars(), session(751, 750))
    req = request(events)
    from trading_bot.simulation.etf_history import run_etf_fixture_prefix

    with localcontext() as ctx:
        ctx.prec = 8
        first = run_etf_fixture_prefix(req)
    with localcontext() as ctx:
        ctx.prec = 50
        second = run_etf_fixture_prefix(req)
    assert first == second


def test_resume_reconstructs_prefix_and_equals_uninterrupted_result():
    from trading_bot.simulation.etf_history import (
        resume_etf_fixture_prefix,
        run_etf_fixture_prefix,
    )

    events = bars() + tuple(session(751 + i, 750 + i) for i in range(7))
    req = request(events)
    full = run_etf_fixture_prefix(req)
    for ordinal in (0, 749, 750, 753, 756):
        prefix = run_etf_fixture_prefix(req, through_ordinal=ordinal)
        assert prefix.checkpoint.paused and not prefix.checkpoint.execution_enabled
        assert resume_etf_fixture_prefix(req, prefix.checkpoint) == full


def test_restart_rejects_changed_observed_bytes_study_cash_or_forged_checkpoint():
    from trading_bot.simulation.etf_history import (
        EtfHistoryError,
        resume_etf_fixture_prefix,
        run_etf_fixture_prefix,
    )

    events = (*bars(), session(751, 750))
    req = request(events)
    point = run_etf_fixture_prefix(req, through_ordinal=749).checkpoint
    mutated = (bar(0, D("200")), *events[1:])
    with pytest.raises(EtfHistoryError):
        resume_etf_fixture_prefix(request(mutated), point)
    with pytest.raises(EtfHistoryError):
        resume_etf_fixture_prefix(request(events, D("1000")), point)
    with pytest.raises(EtfHistoryError):
        resume_etf_fixture_prefix(req, replace(point, prefix_hash="f" * 64))
    with pytest.raises((FrozenInstanceError, AttributeError)):
        point.paused = False


def test_irrelevant_future_extension_does_not_rewrite_checkpoint_or_decisions():
    from trading_bot.simulation.etf_history import (
        resume_etf_fixture_prefix,
        run_etf_fixture_prefix,
    )

    original = (*bars(), session(751, 750))
    before = run(original)
    extended = request((*original, session(752, 751)))
    assert run_etf_fixture_prefix(extended, through_ordinal=750).checkpoint == before.checkpoint
    assert (
        resume_etf_fixture_prefix(extended, before.checkpoint).decisions[0] == before.decisions[0]
    )


def test_study_policy_is_recovered_without_reading_current_files_or_environment(monkeypatch):
    from trading_bot.simulation.etf_history import run_etf_fixture_prefix

    req = request((*bars(), session(751, 750)))
    monkeypatch.setenv("TRADING_BOT__PORTFOLIO__EXPECTED_STARTING_EQUITY_USD", "1000")
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("mutable config read"))
    assert run_etf_fixture_prefix(req).risk_equity_reference == D("100")


def test_late_session_snapshot_does_not_create_a_retroactive_eligible_session():
    opening = session(751, 750)
    late = replace(opening, available_at_ns=_ns(opening.payload.next_close_at))
    decision = run((*bars(), late)).decisions[0]
    assert decision.cadence_index is None
    assert "session_observation_expired" in decision.reasons


def test_missing_next_close_cannot_advance_cadence():
    opening = session(751, 750)
    unknown = replace(opening, payload=replace(opening.payload, next_close_at=None))
    assert "session_boundaries_unknown" in run((*bars(), unknown)).decisions[0].reasons


@pytest.mark.parametrize("ordinal", [True, -1, 999, "0"])
def test_invalid_or_unknown_stop_cursor_is_rejected(ordinal):
    from trading_bot.simulation.etf_history import EtfHistoryError

    with pytest.raises(EtfHistoryError):
        run(bars(1), through_ordinal=ordinal)


def test_empty_paused_checkpoint_resumes_without_inventing_positions():
    from trading_bot.simulation.etf_history import resume_etf_fixture_prefix

    empty = run(())
    assert empty.checkpoint.processed_count == 0 and empty.checkpoint.last_ordinal is None
    assert empty.checkpoint.last_available_at_ns is None
    assert resume_etf_fixture_prefix(request(()), empty.checkpoint) == empty
    assert empty.result_hash == run(()).result_hash
    assert not empty.account_replay_complete


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason_codes", ["momentum_confirmed"]),
        ("reason_codes", ([],)),
        ("strategy_version", []),
        ("decided_at", datetime(2018, 1, 21)),
        ("decided_at", START),
        ("config_hash", "invalid"),
        ("data_hash", "invalid"),
    ],
)
def test_observation_rejects_mutable_or_inconsistent_nested_signal(field, value):
    observation = run((*bars(100), session(751, 100))).decisions[0]
    altered = replace(observation.signal, **{field: value})
    with pytest.raises(ValueError):
        replace(observation, signal=altered)


def test_result_revalidates_nested_observations_before_binding_checkpoint():
    base = run((*bars(100), session(751, 100)))
    observation = base.decisions[0]
    object.__setattr__(observation.signal, "reason_codes", ["momentum_confirmed"])
    checkpoint = replace(base.checkpoint, decisions_hash=content_hash((observation,)))
    with pytest.raises(ValueError):
        replace(base, checkpoint=checkpoint, decisions=(observation,))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("windows", (20, 99)),
        ("symbols", ("QQQ",)),
        ("rebalance_sessions", 1),
        ("capital_tiers", (D("500"),)),
        ("execution_enabled", True),
        ("evidence_promotable", True),
    ],
)
def test_reconstructed_study_must_match_all_frozen_fields(field, value):
    from trading_bot.simulation.etf_history import EtfHistoryError

    frozen = study()
    object.__setattr__(frozen, field, value)
    with pytest.raises(EtfHistoryError):
        request((), frozen_study=frozen)


def test_intraday_intervals_cannot_masquerade_as_750_daily_warmup_bars():
    from trading_bot.simulation.etf_history import EtfHistoryError

    history = []
    for index in range(750):
        original = bar(index, D("100") + D(index) / 100)
        begin = START + timedelta(hours=14, microseconds=index * 2)
        end = begin + timedelta(microseconds=1)
        history.append(
            replace(
                original,
                event_at_ns=_ns(end),
                available_at_ns=_ns(end) + 1,
                payload=replace(original.payload, starts_at=begin, ends_at=end),
            )
        )
    with pytest.raises(EtfHistoryError):
        run((*history, session(751, 750)))


def test_daily_bar_with_shifted_start_cannot_silently_replace_unlinked_original():
    from trading_bot.simulation.etf_history import EtfHistoryError

    original = bar(0, D("100"))
    conflict = bar(0, D("200"), ordinal=1, available=original.available_at_ns + 1)
    conflict = replace(
        conflict,
        payload=replace(
            conflict.payload, starts_at=conflict.payload.starts_at + timedelta(minutes=1)
        ),
    )
    with pytest.raises(EtfHistoryError):
        request((original, conflict))


def test_fixture_daily_bar_must_stay_within_one_local_session_date():
    from trading_bot.simulation.etf_history import EtfHistoryError

    original = bar(1, D("100"))
    overnight = replace(
        original,
        payload=replace(original.payload, starts_at=original.payload.starts_at - timedelta(days=1)),
    )
    with pytest.raises(EtfHistoryError):
        request((overnight,))


def test_delayed_cross_day_clock_cannot_count_an_extra_eligible_session():
    opening = session(751, 750)
    delayed = replace(
        opening,
        available_at_ns=opening.available_at_ns + 86_400_000_000_000,
        payload=replace(
            opening.payload,
            next_open_at=opening.payload.next_open_at + timedelta(days=2),
            next_close_at=opening.payload.next_close_at + timedelta(days=2),
        ),
    )
    actual = session(752, 751, nanos=1)
    decisions = run((*bars(), delayed, actual)).decisions
    assert [item.cadence_index for item in decisions] == [None, 0]
    assert "session_identity_inconsistent" in decisions[0].reasons


def test_next_open_must_belong_to_a_later_local_session_date():
    opening = session(751, 750)
    inconsistent = replace(
        opening,
        payload=replace(
            opening.payload, next_open_at=opening.payload.next_close_at + timedelta(hours=1)
        ),
    )
    decision = run((*bars(), inconsistent)).decisions[0]
    assert decision.cadence_index is None
    assert "session_identity_inconsistent" in decision.reasons
