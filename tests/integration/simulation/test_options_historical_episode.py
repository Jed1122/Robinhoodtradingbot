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
