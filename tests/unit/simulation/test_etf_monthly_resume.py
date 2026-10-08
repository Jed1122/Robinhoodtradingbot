"""Pure prefix recovery, not deployed persistence or runtime proof."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar
from tests.unit.simulation.test_etf_monthly_screen import api, inputs


@pytest.mark.parametrize(
    "day", [date(2016, 10, 31), date(2016, 11, 1), date(2016, 11, 2), date(2016, 11, 8)]
)
def test_prefix_resume_is_identical_to_one_uninterrupted_owner(day):
    req = inputs()
    prefix = api().run_etf_monthly_screen(req, through_session=day)
    checkpoint = api().checkpoint_etf_monthly_screen(prefix)
    resumed = api().resume_etf_monthly_screen(req, checkpoint)
    full = api().run_etf_monthly_screen(req)
    assert resumed == full and resumed.result_hash == full.result_hash
    assert resumed.events == full.events and resumed.account.trial == full.account.trial
    api().verify_etf_monthly_result(prefix)
    api().verify_etf_monthly_result(full)


@pytest.mark.parametrize(
    "field,value",
    [("next_session_index", -1), ("request_hash", "a" * 64), ("events", ()), ("stop", None)],
)
def test_checkpoint_tampering_denies_before_advancing(field, value):
    req = inputs()
    point = api().run_etf_monthly_screen(req, through_session=date(2016, 11, 1)).checkpoint
    with pytest.raises(ValueError):
        api().resume_etf_monthly_screen(req, replace(point, **{field: value}))


@pytest.mark.parametrize(
    "field", ["protocol_hash", "config_hash", "code_hash", "source_prefix_hash"]
)
def test_every_bound_identity_is_checked(field):
    req = inputs()
    point = api().run_etf_monthly_screen(req, through_session=date(2016, 11, 1)).checkpoint
    with pytest.raises(ValueError):
        api().resume_etf_monthly_screen(req, replace(point, **{field: "f" * 64}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("month_window", ()),
        ("daily_window", ()),
        ("decisions", ()),
        ("entry_index", None),
        ("entry_stop", Decimal("9")),
        ("target", None),
        ("obligations", ()),
        ("retained_reasons", ("invented",)),
        ("attempts", ()),
        ("points", ()),
        ("next_session_index", True),
    ],
)
def test_saved_owner_facts_are_never_adopted(field, value):
    req = inputs()
    point = api().run_etf_monthly_screen(req, through_session=date(2016, 11, 1)).checkpoint
    with pytest.raises(ValueError):
        api().resume_etf_monthly_screen(req, replace(point, **{field: value}))


@pytest.mark.parametrize(
    "day", [date(2016, 10, 28), date(2016, 11, 2), date(2016, 11, 3), date(2016, 11, 4)]
)
def test_exit_and_settlement_splits_preserve_loss_and_future_inputs(day):
    req = inputs()
    rows = tuple(
        daily_bar(r.session_date, Decimal("98")) if r.session_date >= date(2016, 11, 2) else r
        for r in req.bars
    )
    req = replace(req, bars=rows)
    prefix = api().run_etf_monthly_screen(req, through_session=day)
    full = api().run_etf_monthly_screen(req)
    assert api().resume_etf_monthly_screen(req, prefix.checkpoint) == full
    assert full.account.trial.consumed_loss == Decimal(".62736")
    changed = replace(req, bars=(*rows[:-1], daily_bar(rows[-1].session_date, Decimal("99"))))
    with pytest.raises(ValueError):
        api().resume_etf_monthly_screen(changed, prefix.checkpoint)


def test_terminal_prefix_pending_and_missing_source_resume_without_invented_events():
    req = inputs(date(2016, 10, 31))
    terminal = api().run_etf_monthly_screen(req)
    assert api().resume_etf_monthly_screen(req, terminal.checkpoint) == terminal
    object.__setattr__(terminal.checkpoint, "evidence_promotable", True)
    with pytest.raises(ValueError):
        api().resume_etf_monthly_screen(req, terminal.checkpoint)
    with pytest.raises(ValueError):
        api().resume_etf_monthly_screen(req, None)
    missing = replace(inputs(), bars=inputs().bars[:-2])
    stopped = api().run_etf_monthly_screen(missing)
    assert api().resume_etf_monthly_screen(missing, stopped.checkpoint) == stopped
