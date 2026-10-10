"""Private entry facts retain complete original admission; fabricated only."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.simulation.test_etf_capital_daily_entry import OPEN, request
from tests.unit.simulation.test_etf_capital_daily_owner import run
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation import etf_capital_daily_entry as entries
from trading_bot.simulation import etf_capital_risk as risk
from trading_bot.simulation.events import EventCursor

HASHES = {
    "filled": "aa8acdd04229298da23f0848c0bbf2ed523abd423072780d91ff45a2d432ecd7",
    "partial": "406148ac49bd74f87623650c8321b4bde970fc8c84bf8d9903a993437b6b164a",
    "rejected": "0b7f7dc92c18b907aa0ba1f13527de85af39beacb3270b7bdbd052349b43f538",
    "unfilled": "12a44f7c4c16d6e25a53229f785f455a68bfdd2f1c57d3b9b858ac64b9a14b39",
}


def value(outcome="filled"):
    changes = {"outcome": outcome}
    if outcome in ("rejected", "unfilled"):
        changes.update(
            fill_fraction=D(0),
            side_fee=D(0),
            lifecycle_cursors=(EventCursor(2, OPEN + timedelta(seconds=1)),),
        )
    elif outcome == "partial":
        changes["fill_fraction"] = D(".5")
    return request(**changes)


def facts(result):
    return (
        result.admission,
        result.assumed_price,
        result.events,
        result.observations,
        result.account,
        result.input_hash,
    )


@pytest.mark.parametrize("outcome", HASHES)
def test_private_entry_retains_literal_parent_public_results(outcome):
    original = value(outcome)
    expected = entries.simulate_capital_daily_entry(original)
    assert content_hash(expected) == HASHES[outcome]
    with localcontext() as context:
        context.prec = 3
        actual = entries._simulate_owned_capital_daily_entry(
            original, progress=risk._RiskProgress()
        )
    assert facts(actual) == facts(expected)
    assert not actual.source_qualified and not actual.cost_qualified
    assert not actual.execution_enabled and not actual.economic_admitted
    assert not actual.evidence_promotable


def test_private_denial_keeps_unknown_fee_and_parent_hash():
    original = request(episode_fee_bound=None)
    expected = entries.simulate_capital_daily_entry(original)
    assert (
        content_hash(expected) == "3f27e66a86f9f7660de2e2d8dba760fd26578b4879bfa547b448493ae63aa950"
    )
    actual = entries._simulate_owned_capital_daily_entry(original, progress=risk._RiskProgress())
    assert not actual.admission.allowed
    assert actual.events == ()
    assert facts(actual) == facts(expected)


@pytest.mark.parametrize("outcome", ["filled", "unfilled"])
def test_complete_original_and_generated_risk_without_discarded_full_graph(outcome, monkeypatch):
    original = value(outcome)
    expected = entries.simulate_capital_daily_entry(original)
    real_points = risk._replay_risk_points
    calls, rendered = [], []
    progress = risk._RiskProgress()

    def points(**kwargs):
        calls.append((len(kwargs["events"]), kwargs["_last_only"], kwargs["_progress"]))
        return real_points(**kwargs)

    real_render = risk._risk_result

    def render(*args, **kwargs):
        rendered.append(1)
        return real_render(*args, **kwargs)

    monkeypatch.setattr(entries, "_replay_risk_points", points, raising=False)
    monkeypatch.setattr(risk, "_risk_result", render)
    actual = entries._simulate_owned_capital_daily_entry(original, progress=progress)
    assert calls == [(0, True, progress), (len(actual.events), True, progress)]
    assert rendered == []
    assert facts(actual) == facts(expected)


def test_private_generated_suffix_failure_then_clean_retry(monkeypatch):
    original = value()
    real_generate = entries._generate_capital_daily_entry

    def invalid(*args, **kwargs):
        result = real_generate(*args, **kwargs)
        return replace(
            result,
            observations=(
                *result.observations[:-1],
                replace(result.observations[-1], source_count=len(result.events) + 1),
            ),
        )

    progress = risk._RiskProgress()
    monkeypatch.setattr(entries, "_generate_capital_daily_entry", invalid)
    with pytest.raises(ValueError):
        entries._simulate_owned_capital_daily_entry(original, progress=progress)
    monkeypatch.setattr(entries, "_generate_capital_daily_entry", real_generate)
    assert facts(entries._simulate_owned_capital_daily_entry(original, progress=progress)) == facts(
        entries.simulate_capital_daily_entry(original)
    )


def test_late_conflicting_original_denies_before_generation(monkeypatch):
    existing = entries.simulate_capital_daily_entry(value())
    fill = existing.events[-1]
    original = request(
        events=(*existing.events, replace(fill, fill=replace(fill.fill, price=D(99)))),
        observations=(replace(request().observations[0], source_count=4),),
    )
    generated = []

    def generate(*args, **kwargs):
        generated.append(1)
        raise AssertionError("invalid originals must deny first")

    monkeypatch.setattr(entries, "_generate_capital_daily_entry", generate, raising=False)
    with pytest.raises(ValueError):
        entries._simulate_owned_capital_daily_entry(original, progress=risk._RiskProgress())
    assert generated == []


def test_mutating_returned_entry_account_never_poison_continuation():
    original = value()
    progress = risk._RiskProgress()
    expected = entries.simulate_capital_daily_entry(original)
    actual = entries._simulate_owned_capital_daily_entry(original, progress=progress)
    object.__setattr__(actual.account, "cash", D(999))
    assert facts(entries._simulate_owned_capital_daily_entry(original, progress=progress)) == facts(
        expected
    )


@pytest.mark.parametrize(
    "outcome,mark",
    [
        ("filled", D(50)),
        ("filled", D(80)),
        ("filled", D(100)),
        ("filled", D(200)),
        ("partial", D(100)),
        ("unfilled", None),
    ],
)
def test_fresh_shared_gate_preserves_loss_and_incomplete_account_denials(outcome, mark):
    first = entries.simulate_capital_daily_entry(value(outcome))
    later = OPEN + timedelta(days=1)
    original = request(
        events=first.events,
        observations=(
            *first.observations,
            risk.CapitalRiskObservation(
                EventCursor(50, later), len(first.events), mark, True, True
            ),
        ),
        decision_at=OPEN,
        opened=EventCursor(100, later),
        lifecycle_cursors=(
            EventCursor(101, later + timedelta(seconds=1)),
            EventCursor(102, later + timedelta(seconds=2)),
        ),
    )
    expected = entries.simulate_capital_daily_entry(original)
    actual = entries._simulate_owned_capital_daily_entry(original, progress=risk._RiskProgress())
    assert facts(actual) == facts(expected)
    assert not actual.admission.allowed
    assert actual.events == first.events
    assert actual.account.available_cash <= actual.account.cash


def test_modified_observation_reconstructs_instead_of_adopting_prior_decision():
    original = value()
    progress = risk._RiskProgress()
    entries._simulate_owned_capital_daily_entry(original, progress=progress)
    changed = replace(
        original,
        observations=(
            replace(
                original.observations[0], daily_reset_reconciled=False, weekly_reset_reviewed=False
            ),
        ),
    )
    expected = entries.simulate_capital_daily_entry(changed)
    actual = entries._simulate_owned_capital_daily_entry(changed, progress=progress)
    assert facts(actual) == facts(expected)
    assert not actual.admission.allowed


@pytest.mark.parametrize("progress", [None, False, {}])
def test_private_entry_rejects_untyped_progress(progress):
    with pytest.raises(ValueError):
        entries._simulate_owned_capital_daily_entry(value(), progress=progress)


def test_owner_uses_private_entry_but_keeps_whole_parent_result(monkeypatch):
    from trading_bot.simulation import etf_capital_daily_owner as owner

    public_calls = []
    real_public = entries.simulate_capital_daily_entry

    def public(original):
        public_calls.append(1)
        return real_public(original)

    monkeypatch.setattr(owner, "simulate_capital_daily_entry", public, raising=False)
    result = run()
    assert (
        content_hash(result) == "53b36d68811a0d2e14a8177b26e73a066f9268318f253e7ffd5374eaba336a32"
    )
    assert public_calls == []
