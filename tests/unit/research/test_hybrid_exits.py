from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest

from trading_bot.research.hybrid_backtest import compare_exit_models
from trading_bot.research.hybrid_sources import PublicResearchClient
from trading_bot.research.hybrid_strategies import PriceBar


def history(values: tuple[tuple[int, int], ...]) -> tuple[PriceBar, ...]:
    return tuple(
        PriceBar(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i), Decimal(op), Decimal(close))
        for i, (op, close) in enumerate(values)
    )


def run(bars: tuple[PriceBar, ...], tax: Decimal | None = Decimal(0)) -> dict[str, Any]:
    return compare_exit_models(
        bars,
        slippage_bps=Decimal(0),
        fee_per_order=Decimal(0),
        operating_cost_per_bar=Decimal(0),
        tax_rate=tax,
    )


def test_missing_costs_or_tax_are_never_treated_as_observed_zero() -> None:
    bars = history(((100, 100), (100, 120), (120, 120)))
    assert compare_exit_models(bars)["status"] == "insufficient_evidence"
    result = run(bars, None)
    assert result["qualified"] is False
    assert all(m["after_tax_return"] is None for m in result["models"])


def test_exit_models_delay_decisions_and_do_not_guarantee_stop_prices() -> None:
    result = run(history(((100, 200), (100, 120), (80, 80), (80, 80))))
    models = {m["model"]: m for m in result["models"]}
    # First +20% close triggers a full target sale at next open's 80, not 115 or 120.
    assert models["fixed_target"]["pre_tax_return"] == pytest.approx(-0.2)
    assert models["fixed_target"]["trades"][1]["price"] == "80"
    assert models["partial_exit"]["trades"][1]["quantity"] == "5.00"
    # Peak 120 is observed at close, following 80 close triggers trailing exit at next open.
    assert models["trend_trailing"]["trades"][1]["bar_index"] == 3
    assert models["buy_hold"]["initial_capital"] == "1000"
    assert models["principal_retention"]["trades"][1]["quantity"] == str(
        Decimal(200) / Decimal(120)
    )


def test_tax_applies_to_realized_gain_and_metrics_remain_unqualified() -> None:
    bars = history(((100, 100), (100, 120), (120, 120), (120, 120)))
    result = run(bars, Decimal(".25"))
    model = result["models"][0]
    assert model["pre_tax_return"] == pytest.approx(0.2)
    assert model["after_tax_return"] == pytest.approx(0.15)
    assert Decimal(model["tax_paid"]) == Decimal("50")
    assert model["profit_factor"] is None
    assert model["sharpe"] is not None
    assert model["qualified"] is False
    assert model["max_drawdown"] >= 0
    assert model["turnover"] > 0


def test_entry_and_operating_fees_are_funded_without_borrowing() -> None:
    result = cast(
        dict[str, Any],
        compare_exit_models(
            history(((100, 100), (100, 100), (100, 100))),
            starting_capital=Decimal(1000),
            slippage_bps=Decimal(0),
            fee_per_order=Decimal(1),
            operating_cost_per_bar=Decimal(2),
            tax_rate=Decimal(0),
        ),
    )
    model = result["models"][0]
    assert model["pre_tax_return"] == pytest.approx(-0.006)
    assert model["operating_costs"] == "4"
    assert model["fees"] == "2"
    assert all(Decimal(t["quantity"]) >= 0 for t in model["trades"])


def test_source_stream_limit_user_agent_and_secret_error_redaction() -> None:
    seen: list[str | None] = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent"))
        return httpx.Response(200, content=b"x" * 128)

    client = PublicResearchClient(
        httpx.MockTransport(response),
        sec_user_agent="Research test contact@example.invalid",
        max_response_bytes=64,
    )
    with pytest.raises(ValueError, match="public source"):
        client.sec_facts("XYZ", "1", datetime(2026, 1, 1, tzinfo=UTC))
    assert seen == ["Research test contact@example.invalid"]
    key = "private-test-only-credential"

    def error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(str(request.url), request=request)

    client = PublicResearchClient(httpx.MockTransport(error))
    with pytest.raises(ValueError) as exc:
        client.fred_observations("DGS10", datetime(2026, 1, 1, tzinfo=UTC), api_key=key)
    assert key not in str(exc.value)


def test_thresholds_are_once_per_episode_and_reference_holding_is_twenty_sessions() -> None:
    values = ((100, 100), (100, 120), *((120, 120),) * 21)
    result = run(history(values))
    models = {m["model"]: m for m in result["models"]}
    assert len(models["principal_retention"]["trades"]) == 3  # buy, trim, terminal
    assert len(models["partial_exit"]["trades"]) == 3  # two reached rungs share next-open sale
    assert models["fixed_holding"]["trades"][1]["bar_index"] == 21
    assert models["partial_exit"]["win_rate"] is None  # partial sales are not independent episodes


def test_declared_slippage_and_small_capital_never_create_borrowing() -> None:
    bars = history(((100, 100), (100, 100), (100, 100)))
    result = cast(
        dict[str, Any],
        compare_exit_models(
            bars,
            slippage_bps=Decimal(100),
            fee_per_order=Decimal(0),
            operating_cost_per_bar=Decimal(0),
            tax_rate=Decimal(0),
        ),
    )
    assert result["models"][3]["pre_tax_return"] == pytest.approx(99 / 101 - 1)
    blocked = cast(
        dict[str, Any],
        compare_exit_models(
            bars,
            starting_capital=Decimal(1),
            slippage_bps=Decimal(0),
            fee_per_order=Decimal(1),
            operating_cost_per_bar=Decimal(1),
            tax_rate=Decimal(0),
        ),
    )
    assert all(m["status"] == "insufficient_capital" for m in blocked["models"])
    with pytest.raises(ValueError):
        compare_exit_models(
            bars,
            slippage_bps=Decimal("NaN"),
            fee_per_order=Decimal(0),
            operating_cost_per_bar=Decimal(0),
        )


def test_stream_aborts_before_consuming_remainder_and_fred_sources_omit_key() -> None:
    chunks: list[int] = []

    class Body(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for i in range(4):
                chunks.append(i)
                yield b"x" * 40

    client = PublicResearchClient(
        httpx.MockTransport(lambda r: httpx.Response(200, stream=Body())), max_response_bytes=64
    )
    with pytest.raises(ValueError):
        client.sec_facts("XYZ", "1", datetime(2026, 1, 1, tzinfo=UTC))
    assert chunks == [0, 1]
    key = "testcredentialonly"
    client = PublicResearchClient(
        httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "observations": [
                        {"date": "2025-01-01", "realtime_start": "2025-01-02", "value": "1"}
                    ]
                },
            )
        )
    )
    facts = client.fred_observations("DGS10", datetime(2026, 1, 1, tzinfo=UTC), api_key=key)
    assert key not in repr(facts)
    assert facts[0].source_url == "https://api.stlouisfed.org/fred/series/observations"
