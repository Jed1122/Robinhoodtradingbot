"""Source-verified manufactured native files are engineering evidence only."""

import hashlib
import importlib
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401

pytest.importorskip("databento_dbn")


def api():
    try:
        return importlib.import_module("trading_bot.simulation.options_historical")
    except ModuleNotFoundError:
        pytest.fail("source-bound historical episode runner is not implemented")


def case(tmp_path, monkeypatch, capital="10000", **fixture_options):
    module = api()
    from tests.integration.simulation._historical_episode_fixtures import episode_inputs
    from trading_bot.market_data.options_session_inputs import _ns
    from trading_bot.market_data.options_source_models import PrivateArtifactRef
    from trading_bot.research.options_account_journal import initial_account_path
    from trading_bot.research.options_study_registration import freeze_options_study

    inputs = episode_inputs(tmp_path, monkeypatch, **fixture_options)
    root = tmp_path / "frozen"
    root.mkdir(mode=0o700)
    freeze_options_study(
        inputs.spec,
        history=inputs.history,
        loaded=inputs.loaded,
        output_root=root,
        repository_root=inputs.repository_root,
    )
    path = root / (inputs.spec.study_hash + ".json")
    body = path.read_bytes()
    initial = initial_account_path(
        study_hash=inputs.spec.study_hash,
        capital=Decimal(capital),
        start_ns=_ns(inputs.shortlist.session.current.opens_at),
        loaded=inputs.loaded,
        scenario=inputs.scenario,
    )
    request = module.HistoricalOptionsRequest(
        spec=inputs.spec,
        history=inputs.history,
        shortlist=inputs.shortlist,
        stream=inputs.stream,
        scenario=inputs.scenario,
        initial=initial,
        calendars=inputs.calendars,
        subsequent_history=inputs.subsequent_history,
        frozen_spec=PrivateArtifactRef(path, hashlib.sha256(body).hexdigest(), len(body)),
    )
    return module, inputs, request


def run(module, inputs, request):
    return module.run_historical_options_episode(
        request,
        loaded=inputs.loaded,
        repository_root=inputs.repository_root,
    )


def test_source_verified_native_round_trip_has_exact_after_fee_cash(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch)
    result = run(module, inputs, request)
    assert result.status == "completed", result.reasons
    assert result.net_cash_flow == Decimal("-2.00")
    assert result.fees == Decimal("1.00")
    assert result.clock.state.cash == Decimal("9998.00")
    assert result.clock.state.trial.consumed_loss == Decimal("2.00")
    assert len(result.intents) == 2
    assert result.clock.reconciliation_reasons == ()
    assert not result.production_eligible and not result.economic_eligible
    assert not result.evidence_promotable
    assert run(module, inputs, request) == result


def test_100_dollars_denies_without_inventing_fractional_option(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch, capital="100")
    result = run(module, inputs, request)
    assert result.status == "denied"
    assert "per_trade_risk" in result.reasons
    assert not result.intents and result.net_cash_flow == 0 and result.fees == 0


def delayed_expiry_quotes(monkeypatch, *, late_native=False):
    """Manufacture a missed close, then new quotes after its 300-second lifetime."""
    from tests.integration.simulation import _historical_episode_fixtures as fixtures

    original = fixtures.record
    first_start = None

    def record(**values):
        nonlocal first_start
        if first_start is None:
            first_start = values["stamp"] - 1000
        expiry_eve = first_start + 29 * 86400 * 10**9
        if expiry_eve <= values["stamp"] < expiry_eve + 86400 * 10**9:
            if values["sequence"] == 2 and not values["underlying"]:
                values["bid"] = 80000000
            if values["sequence"] >= 3:
                values["stamp"] += 301 * 10**9
                values["recv"] += 301 * 10**9
                if late_native and values["sequence"] == 3:
                    offset = values["recv"] - values["stamp"]
                    values["stamp"] = (
                        expiry_eve + 300 * 10**9 + (2000 if values["underlying"] else 0)
                    )
                    values["recv"] = expiry_eve + 300 * 10**9 + 2000 + offset
        return original(**values)

    monkeypatch.setattr(fixtures, "record", record)


def test_expired_protective_close_rearms_on_later_native_quote(tmp_path, monkeypatch):
    from trading_bot.domain.enums import OrderState
    from trading_bot.simulation.options_historical_models import HISTORICAL_TERMINAL

    delayed_expiry_quotes(monkeypatch)
    module, inputs, request = case(tmp_path, monkeypatch)
    result = run(module, inputs, request)
    assert result.status == "completed", result.reasons
    assert len(result.intents) == 3
    assert result.clock.orders[1].state is OrderState.EXPIRED
    assert result.clock.orders[2].state is OrderState.FILLED
    assert result.intents[1].created_at.date() == result.intents[2].created_at.date()
    assert result.intents[2].created_at > result.intents[1].expires_at
    assert result.net_cash_flow == Decimal("-2.00") and result.fees == Decimal("1.00")
    assert not result.clock.state.positions and not result.clock.reconciliation_reasons

    # Receipt restoration must reproduce the same bounded reattempt, not add one.
    from trading_bot.market_data.options_quote_stream import iter_quote_events
    from trading_bot.market_data.options_session_inputs import _ns

    events = tuple(
        iter_quote_events(
            request.stream, loaded=inputs.loaded, repository_root=inputs.repository_root
        )
    )
    cut = next(
        i for i, e in enumerate(events) if e.available_ns > _ns(result.intents[1].expires_at)
    )
    partial = module.run_historical_options_episode(
        request, loaded=inputs.loaded, repository_root=inputs.repository_root, event_limit=cut
    )
    assert len(partial.intents) == 2
    assert partial.clock.orders[-1].state not in HISTORICAL_TERMINAL
    checkpoint = module.encode_episode_checkpoint(request, partial, loaded=inputs.loaded)
    assert (
        module.resume_historical_options_episode(
            request,
            checkpoint=checkpoint,
            expected_sha256=hashlib.sha256(checkpoint).hexdigest(),
            loaded=inputs.loaded,
            repository_root=inputs.repository_root,
        )
        == result
    )


def test_delayed_pre_terminal_native_quote_cannot_rearm_close(tmp_path, monkeypatch):
    from trading_bot.domain.options import OptionQuote, executable_quote_reasons
    from trading_bot.market_data.options_quote_stream import iter_quote_events
    from trading_bot.market_data.options_session_inputs import _ns
    from trading_bot.market_data.options_source_verify import ceil_available_at

    delayed_expiry_quotes(monkeypatch, late_native=True)
    module, inputs, request = case(tmp_path, monkeypatch)
    result = run(module, inputs, request)
    assert result.status == "completed", result.reasons
    assert len(result.intents) == 3
    # Tick 3 was received after expiry but observed before it. Only tick 4 may rearm.
    expiry_eve = _ns(inputs.stream.sessions[1].opens_at)
    assert _ns(result.intents[2].created_at) == expiry_eve + 301 * 10**9 + 4000
    c = result.intents[1].structure.legs[0].contract
    delayed = next(
        e
        for e in iter_quote_events(
            request.stream, loaded=inputs.loaded, repository_root=inputs.repository_root
        )
        if e.symbol == c.standardized_id
        and e.event_ns == expiry_eve + 300 * 10**9
        and e.record is not None
        and isinstance(e.record.value, OptionQuote)
    )
    assert not delayed.quality_reasons
    assert not executable_quote_reasons(
        c,
        delayed.record.value,
        as_of=ceil_available_at(delayed.available_ns),
        max_age_seconds=inputs.loaded.config.freshness.max_executable_quote_age_seconds,
        max_underlying_skew_seconds=inputs.loaded.config.market_data.max_cross_response_timestamp_skew_seconds,
        allow_locked=inputs.loaded.config.options.allow_locked_quotes,
    )


@pytest.mark.parametrize("outcome", ["reject", "ambiguous"])
def test_close_outcomes_never_duplicate_pending_or_unknown_exposure(tmp_path, monkeypatch, outcome):
    from trading_bot.domain.enums import OrderState, Side
    from trading_bot.simulation import options_historical_execution

    # Explicit fabricated acknowledgement draws: entries accepted, closes fail.
    def draw(order, seed, purpose):
        return (
            0
            if purpose == "acknowledgement" and order.intent.structure.legs[0].side is Side.SELL
            else 999999
        )

    monkeypatch.setattr(options_historical_execution, "_draw", draw)
    module, inputs, request = case(tmp_path, monkeypatch, scenario_changes={outcome + "_ppm": 1})
    result = run(module, inputs, request)
    assert result.status == "incomplete"
    assert result.clock.state.positions[0].units == 1
    assert result.net_cash_flow == Decimal("-10.50") and result.fees == Decimal("0.50")
    assert result.clock.state.trial.reserved_risk == Decimal("11")
    if outcome == "ambiguous":
        assert len(result.intents) == 2
        assert result.clock.orders[1].state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    else:
        assert 2 < len(result.intents) <= result.processed_events
        assert all(o.state is OrderState.REJECTED for o in result.clock.orders[1:])
        transitions = dict(
            (ident, t.available_ns)
            for ident, t in result.clock.transitions
            if t.current is OrderState.REJECTED
        )
        for before, after in zip(result.clock.orders[1:], result.clock.orders[2:], strict=False):
            assert after.decision_ns > transitions[before.intent.intent_id]
    assert "expiry_exit_deadline_reached" in result.reasons


def test_changed_study_or_frozen_file_never_opens_outcomes(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        run(module, inputs, replace(request, spec=replace(request.spec, code_hash="a" * 64)))
    request.frozen_spec.path.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        run(module, inputs, request)


def test_missing_later_signal_evidence_is_incomplete_not_silently_held(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch)
    result = run(module, inputs, replace(request, subsequent_history=()))
    assert result.status == "incomplete"
    assert "signal_history_unavailable" in result.reasons
    assert not result.economic_eligible


@pytest.mark.parametrize("events", [1, 8, 16])
def test_source_reverified_episode_restart_matches_uninterrupted(tmp_path, monkeypatch, events):
    module, inputs, request = case(tmp_path, monkeypatch)
    partial = module.run_historical_options_episode(
        request,
        loaded=inputs.loaded,
        repository_root=inputs.repository_root,
        event_limit=events,
    )
    assert partial.status == "incomplete" and partial.processed_events == events
    checkpoint = module.encode_episode_checkpoint(request, partial, loaded=inputs.loaded)
    restored = module.resume_historical_options_episode(
        request,
        checkpoint=checkpoint,
        expected_sha256=hashlib.sha256(checkpoint).hexdigest(),
        loaded=inputs.loaded,
        repository_root=inputs.repository_root,
    )
    assert restored == run(module, inputs, request)


def test_completed_episode_checkpoint_is_idempotently_reverified(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch)
    completed = run(module, inputs, request)
    checkpoint = module.encode_episode_checkpoint(request, completed, loaded=inputs.loaded)
    assert (
        module.resume_historical_options_episode(
            request,
            checkpoint=checkpoint,
            expected_sha256=hashlib.sha256(checkpoint).hexdigest(),
            loaded=inputs.loaded,
            repository_root=inputs.repository_root,
        )
        == completed
    )


def test_execution_cannot_exceed_frozen_outcome_horizon(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch, outcome_days=1)
    with pytest.raises(ValueError):
        run(module, inputs, request)


def test_episode_restart_rejects_changed_prefix_and_source_files(tmp_path, monkeypatch):
    module, inputs, request = case(tmp_path, monkeypatch)
    partial = module.run_historical_options_episode(
        request,
        loaded=inputs.loaded,
        repository_root=inputs.repository_root,
        event_limit=8,
    )
    checkpoint = module.encode_episode_checkpoint(request, partial, loaded=inputs.loaded)
    with pytest.raises(ValueError):
        module.resume_historical_options_episode(
            request,
            checkpoint=checkpoint,
            expected_sha256="a" * 64,
            loaded=inputs.loaded,
            repository_root=inputs.repository_root,
        )
    request.stream.feeds[0].manifest.path.write_bytes(b"tampered after checkpoint")
    with pytest.raises(ValueError):
        module.resume_historical_options_episode(
            request,
            checkpoint=checkpoint,
            expected_sha256=hashlib.sha256(checkpoint).hexdigest(),
            loaded=inputs.loaded,
            repository_root=inputs.repository_root,
        )


@pytest.mark.parametrize("trend,expected", [("put", "completed"), ("mixed", "denied")])
def test_bearish_and_mixed_signals_do_not_default_to_call_or_put(
    tmp_path, monkeypatch, trend, expected
):
    module, inputs, request = case(tmp_path, monkeypatch, trend=trend)
    result = run(module, inputs, request)
    assert result.status == expected, result.reasons
    assert len(result.priced_candidates) == 2
    if trend == "put":
        assert result.intents[0].structure.legs[0].contract.kind.value == "put"
        assert result.net_cash_flow == Decimal("-2")
    else:
        assert result.intents == () and result.reasons == ("no_momentum_candidate",)


@pytest.mark.parametrize(
    "change,status,reason",
    [
        ({"reject_ppm": 1000000}, "completed", None),
        ({"unfilled_ppm": 1000000}, "completed", None),
        ({"ambiguous_ppm": 1000000}, "incomplete", "unknown_order"),
        ({"settlement_delay_ns": 40 * 86400 * 10**9}, "incomplete", "settlement_pending"),
    ],
)
def test_historical_outcomes_do_not_invent_fills_or_settlement(
    tmp_path, monkeypatch, change, status, reason
):
    module, inputs, request = case(tmp_path, monkeypatch, scenario_changes=change)
    result = run(module, inputs, request)
    assert result.status == status
    if reason:
        assert reason in result.reasons
    if "settlement_delay_ns" not in change:
        assert result.net_cash_flow == 0 and result.fees == 0
    assert not result.economic_eligible
