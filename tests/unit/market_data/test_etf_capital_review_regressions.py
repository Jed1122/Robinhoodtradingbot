"""Independent reproductions of whole-intake review findings; fabricated only."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.unit.market_data.test_alpaca_capital_native import body, request
from tests.unit.market_data.test_etf_capital_dataset import dataset, sources
from tests.unit.market_data.test_etf_capital_features import inputs
from tests.unit.market_data.test_etf_capital_inventory import calendar
from trading_bot.market_data.etf_capital_actions import CapitalSplit
from trading_bot.market_data.etf_capital_archive import write_capital_daily_archive
from trading_bot.market_data.etf_capital_features import capital_split_feature_bars


@pytest.mark.parametrize(
    "ratio, low, volume",
    [
        (Decimal("3"), Decimal("6"), Decimal("300")),
        (Decimal("1.5"), Decimal("12"), Decimal("150")),
    ],
)
def test_legitimate_split_ratios_have_bounded_feature_prices(ratio, low, volume):
    captured, action = inputs((CapitalSplit(date(2023, 1, 4), ratio, "d" * 64),))
    result = capital_split_feature_bars(
        captured, calendar(), action, as_of_session=date(2023, 1, 4)
    )
    assert result.raw_bars[0].open == Decimal("20")
    assert result.feature_bars[0].low == low
    assert result.feature_bars[0].volume == volume
    assert Decimal("6") < result.feature_bars[0].open < Decimal("14")


def test_nested_page_qualification_flag_is_not_copied_away():
    captured, actions = sources()
    object.__setattr__(captured[0].pages[0], "source_qualified", True)
    with pytest.raises(ValueError):
        dataset(captured, actions)


@pytest.mark.parametrize("selected", ["archive", "action"])
def test_direct_feature_api_rejects_altered_source_flags(selected):
    captured, action = inputs()
    object.__setattr__(captured if selected == "archive" else action, "source_qualified", True)
    with pytest.raises(ValueError):
        capital_split_feature_bars(captured, calendar(), action, as_of_session=date(2023, 1, 4))


def test_source_kind_cannot_be_relabelled_authenticated():
    captured, actions = sources()
    object.__setattr__(actions[0], "source_kind", "authenticated-provider-v99")
    with pytest.raises(ValueError):
        dataset(captured, actions)


def test_projection_hash_rejects_altered_execution_flag():
    captured, action = inputs()
    result = capital_split_feature_bars(
        captured, calendar(), action, as_of_session=date(2023, 1, 4)
    )
    object.__setattr__(result, "execution_enabled", True)
    with pytest.raises(ValueError):
        _ = result.projection_hash


def test_receipt_before_bar_is_rejected_before_private_publication(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(ValueError):
        write_capital_daily_archive(
            root,
            repository_root=repository,
            request=request(),
            bodies=(body(),),
            received_at=(datetime(2000, 1, 1, tzinfo=UTC),),
        )
    assert not tuple(root.iterdir())


@pytest.mark.parametrize("flag", [True, 0, "false"])
def test_inventory_hash_rejects_malformed_eligibility(flag):
    from trading_bot.market_data.etf_capital_inventory import capital_daily_inventory

    captured, _ = inputs()
    result = capital_daily_inventory(
        (captured,), calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6)
    )
    object.__setattr__(result, "source_qualified", flag)
    with pytest.raises(ValueError):
        _ = result.inventory_hash
