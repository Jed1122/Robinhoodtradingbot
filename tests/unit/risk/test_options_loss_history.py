"""Exact cash-flow-neutral losses; a date/deposit/restart never clears hard latches."""

import importlib
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from tests.unit.risk.test_options_economics import config
from trading_bot.domain import AccountId

D = Decimal
OPEN = datetime(2026, 9, 18, 13, 30, tzinfo=UTC)
CLOSE = OPEN.replace(hour=20, minute=0)
ACCOUNT = AccountId("synthetic:risk")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("risk history cannot use a network")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def api():
    try:
        return importlib.import_module("trading_bot.risk.options_loss_history")
    except ModuleNotFoundError:
        pytest.fail("options loss-history reducer not implemented")


def point(name="initial", value="100", *, at=OPEN, flow="0", **changes):
    values = dict(
        event_id=name,
        account_id=ACCOUNT,
        config_hash=str(config().config_hash),
        observed_at=at,
        session_id="2026-09-18",
        session_open=OPEN,
        session_close=CLOSE,
        previous_session_close=None,
        liquidation_equity=D(value),
        cumulative_external_flows=D(flow),
        source_hash="a" * 64,
        complete=True,
    )
    return api().OptionsLossPoint(**(values | changes))


def evaluate(*points, at=None, loaded=None):
    return api().evaluate_options_loss_history(
        config() if loaded is None else loaded,
        points,
        as_of=points[-1].observed_at if at is None else at,
    )


def next_session(last, value, *, flow="0", name="monday", **changes):
    opening = OPEN + timedelta(days=3)
    changes = (
        dict(
            session_id="2026-09-21",
            session_open=opening,
            session_close=opening.replace(hour=20, minute=0),
            previous_session_close=last.session_close,
        )
        | changes
    )
    return point(
        name,
        value,
        at=opening,
        flow=flow,
        **changes,
    )


def test_deposits_and_withdrawals_do_not_hide_losses_or_raise_authorized_reference():
    initial = point()
    loss = point("loss", "89", at=OPEN + timedelta(seconds=1))
    deposit = point("deposit", "1089", flow="1000", at=OPEN + timedelta(seconds=2))
    withdrawal = point("withdrawal", "1039", flow="950", at=OPEN + timedelta(seconds=3))
    result = evaluate(initial, loss, deposit, withdrawal)
    assert result.flow_adjusted_equity == D("89")
    assert result.daily_loss_usd == D("11")
    assert result.weekly_loss_usd == D("11")
    assert result.drawdown_loss_usd == D("11")
    assert result.reference_equity == D("100")
    assert result.daily_halt and result.weekly_halt and result.drawdown_halt
    assert set(result.entry_reasons) >= {
        "daily_loss_latched",
        "weekly_loss_latched",
        "drawdown_latched",
    }
    assert result.paused and not result.production_eligible and not result.economic_evidence


def test_gains_do_not_raise_the_initial_risk_reference():
    result = evaluate(point(), point("gain", "150", at=OPEN + timedelta(seconds=1)))
    assert result.reference_equity == D("100")
    assert result.peak_equity == D("150")
    assert result.daily_loss_usd == 0
    assert result.entry_reasons == ()


def test_same_session_recovery_does_not_clear_daily_halt():
    result = evaluate(
        point(),
        point("loss", "98", at=OPEN + timedelta(seconds=1)),
        point("recovery", "100", at=OPEN + timedelta(seconds=2)),
    )
    assert result.daily_loss_usd == 0
    assert result.daily_halt and not result.weekly_halt
    assert result.entry_reasons == ("daily_loss_latched",)


def test_explicit_prior_close_allows_new_daily_basis_but_weekly_latch_survives():
    close = point("friday-close", "94", at=CLOSE)
    monday = next_session(close, "94")
    result = evaluate(point(), close, monday)
    assert result.daily_loss_usd == result.weekly_loss_usd == 0
    assert not result.daily_halt and result.weekly_halt and not result.drawdown_halt
    assert result.entry_reasons == ("weekly_loss_latched",)
    assert evaluate(point(), close, monday) == result


def test_overnight_loss_counts_against_the_last_verified_close():
    close = point("close", "100", at=CLOSE)
    result = evaluate(point(), close, next_session(close, "98"))
    assert result.daily_loss_usd == D("2")
    assert result.daily_halt


def test_missing_close_or_incomplete_marks_leave_an_unrecoverable_history_gap():
    unclosed = point("unclosed", "100", at=CLOSE - timedelta(seconds=1))
    monday = next_session(unclosed, "100")
    result = evaluate(point(), unclosed, monday)
    assert "risk_history_incomplete" in result.entry_reasons
    assert result.daily_loss_usd is None
    incomplete = point("bad-mark", "100", at=OPEN + timedelta(seconds=1), complete=False)
    fresh = point("fresh", "100", at=OPEN + timedelta(seconds=2))
    assert "risk_history_incomplete" in evaluate(point(), incomplete, fresh).entry_reasons


def test_first_observation_must_establish_unfunded_genesis_at_session_open():
    for initial in (point(at=OPEN + timedelta(seconds=1)), point(flow="1"), point(value="0")):
        with pytest.raises(ValueError):
            evaluate(initial)


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": AccountId("synthetic:other")},
        {"config_hash": "b" * 64},
        {"observed_at": OPEN},
        {"session_close": CLOSE - timedelta(minutes=1)},
        {"session_id": "renamed"},
    ],
)
def test_changed_identity_or_nonmonotonic_time_cannot_reset_history(change):
    changed = point("changed", at=OPEN + timedelta(seconds=1), **change)
    with pytest.raises(ValueError):
        evaluate(point(), changed)


def test_exact_duplicate_is_idempotent_but_conflicting_duplicate_is_rejected():
    initial = point()
    assert evaluate(initial, initial) == evaluate(initial)
    with pytest.raises(ValueError):
        evaluate(initial, replace(initial, liquidation_equity=D("99")))


def test_freshness_and_clock_checks_use_evaluation_time_not_a_new_poll_timestamp():
    initial = point()
    assert "risk_observation_stale" in evaluate(initial, at=OPEN + timedelta(days=1)).entry_reasons
    with pytest.raises(ValueError):
        evaluate(initial, at=OPEN - timedelta(seconds=1))


@pytest.mark.parametrize(
    "change",
    [
        {"liquidation_equity": D("NaN")},
        {"cumulative_external_flows": "0"},
        {"complete": 1},
        {"source_hash": "bad"},
        {"event_id": ""},
        {"session_close": OPEN},
        {"observed_at": CLOSE + timedelta(seconds=1)},
        {"session_open": OPEN.replace(tzinfo=None)},
        {"previous_session_close": OPEN},
    ],
)
def test_invalid_observations_never_enter_the_reducer(change):
    with pytest.raises(ValueError):
        point(**change)


def test_equity_exhaustion_and_external_flow_losses_exceeding_initial_cash_stay_visible():
    result = evaluate(point(), point("insolvent", "-5", at=OPEN + timedelta(seconds=1)))
    assert result.daily_loss_usd == D("105")
    assert result.reference_equity == 0
    assert result.drawdown_halt


def test_arithmetic_is_independent_of_ambient_decimal_context():
    points = (point(value="100.01"), point("loss", "98.0098", at=OPEN + timedelta(seconds=1)))
    with localcontext() as ctx:
        ctx.prec = 3
        result = evaluate(*points)
    assert result.daily_loss_usd == D("2.0002")
    assert result.daily_halt


def test_missing_and_wrong_input_shapes_fail_closed():
    with pytest.raises(ValueError):
        api().evaluate_options_loss_history(config(), (), as_of=OPEN)
    with pytest.raises(ValueError):
        api().evaluate_options_loss_history(config(), [point()], as_of=OPEN)
    with pytest.raises(ValueError):
        api().evaluate_options_loss_history(config(), (object(),), as_of=OPEN)


def test_zero_limits_are_not_permission_to_trade_and_config_identity_is_verified():
    from trading_bot.config.hashing import hash_loaded_config

    loaded = config()
    limits = loaded.config.loss_limits.model_copy(
        update={
            "max_daily_loss_pct": D(0),
            "max_weekly_loss_pct": D(0),
            "max_peak_to_trough_drawdown_pct": D(0),
        }
    )
    changed = loaded.config.model_copy(update={"loss_limits": limits})
    canonical, digest = hash_loaded_config(changed, loaded.safety_envelope)
    stricter = replace(loaded, config=changed, canonical_json=canonical, config_hash=digest)
    result = evaluate(point(config_hash=str(digest)), loaded=stricter)
    assert result.daily_halt and result.weekly_halt and result.drawdown_halt
    with pytest.raises(ValueError):
        evaluate(point(), loaded=replace(loaded, config_hash="b" * 64))
    with pytest.raises(ValueError):
        evaluate(point(), loaded=object())


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": AccountId("live-account")},
        {"event_id": "x" * 129},
        {"session_id": " "},
        {"config_hash": "not-hash"},
    ],
)
def test_only_bounded_synthetic_identities_are_accepted(change):
    with pytest.raises(ValueError):
        point(**change)


def test_missing_previous_close_does_not_clear_existing_daily_latch():
    close = point("close", "89", at=CLOSE)
    missing = next_session(close, "100", previous_session_close=None)
    result = evaluate(point(), close, missing)
    assert result.daily_halt and result.weekly_halt and result.drawdown_halt
    assert "risk_history_incomplete" in result.entry_reasons


def test_same_week_rollover_does_not_rebase_weekly_loss():
    from datetime import timedelta

    friday = point("close", "100", at=CLOSE)
    monday = next_session(friday, "97")
    monday_close = replace(monday, event_id="mon-close", observed_at=monday.session_close)
    tuesday = replace(
        monday,
        event_id="tuesday",
        liquidation_equity=D("94"),
        session_id="2026-09-22",
        observed_at=monday.session_open + timedelta(days=1),
        session_open=monday.session_open + timedelta(days=1),
        session_close=monday.session_close + timedelta(days=1),
        previous_session_close=monday.session_close,
    )
    result = evaluate(point(), friday, monday, monday_close, tuesday)
    assert result.weekly_loss_usd == D("6")
    assert result.daily_loss_usd == D("3")
    assert result.weekly_halt


def test_duplicate_old_events_do_not_change_current_time_and_future_is_rejected():
    initial = point()
    loss = point("loss", "90", at=OPEN + timedelta(seconds=1))
    assert evaluate(initial, loss, initial, at=loss.observed_at) == evaluate(initial, loss)
    with pytest.raises(ValueError):
        evaluate(initial, loss, at=OPEN)


def test_incomplete_genesis_and_disabled_or_excessive_history_fail_closed():
    from trading_bot.config.hashing import hash_loaded_config

    with pytest.raises(ValueError):
        evaluate(point(complete=False))
    loaded = config()
    with pytest.raises(ValueError):
        api().evaluate_options_loss_history(
            loaded, (point(),) * (loaded.config.options.replay_max_records + 1), as_of=OPEN
        )
    changed = loaded.config.model_copy(
        update={
            "options": loaded.config.options.model_copy(update={"enabled": False}),
        }
    )
    canonical, digest = hash_loaded_config(changed, loaded.safety_envelope)
    with pytest.raises(ValueError):
        evaluate(
            point(config_hash=str(digest)),
            loaded=replace(
                loaded,
                config=changed,
                canonical_json=canonical,
                config_hash=digest,
            ),
        )
