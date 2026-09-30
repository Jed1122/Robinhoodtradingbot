"""Independent acceptance tests for the existing, unvalidated long-option extension.

These tests were added after the core put implementation; they are not initial TDD.
All observations and replay cash flows are fabricated, not market evidence.
"""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import LoadedConfig, load_config
from trading_bot.config import hashing as config_hashing
from trading_bot.domain import ConfigHash, DataHash, InstrumentId
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.options import OptionKind
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.options_fixtures import synthetic_options_request
from trading_bot.simulation.options_replay import replay_options
from trading_bot.strategies.options.momentum import OptionsMomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    FeatureValue,
    FeatureVector,
    StrategyAction,
    StrategyContext,
)

D = Decimal
NOW = datetime(2026, 9, 18, 15, tzinfo=UTC)
FEATURE_NAMES = (
    "total_return_pct",
    "moving_average_short",
    "moving_average_long",
    "latest_close",
)


def bearish_context(
    changes: dict[str, FeatureValue] | None = None, *, missing: str | None = None
) -> StrategyContext:
    values: dict[str, FeatureValue] = {
        "total_return_pct": D("-12.5"),
        "moving_average_short": D("95"),
        "moving_average_long": D("100"),
        "latest_close": D("90"),
    }
    values.update(changes or {})
    if missing is not None:
        values.pop(missing)
    vector = FeatureVector(InstrumentId("SYN"), NOW, tuple(values.items()), DataHash("a" * 64))
    return StrategyContext(
        NOW,
        FeatureSnapshot(NOW, (vector,), DataHash("b" * 64)),
        ConfigHash("c" * 64),
        (InstrumentId("SYN"),),
    )


@pytest.fixture
def put_strategy() -> OptionsMomentumStrategy:
    return OptionsMomentumStrategy(kind=OptionKind.PUT, short_window=20, long_window=100)


def test_aligned_bearish_features_emit_a_purchased_put_candidate(
    put_strategy: OptionsMomentumStrategy,
) -> None:
    context = bearish_context()
    (decision,) = put_strategy.decide(context)
    assert decision.action is StrategyAction.ENTER_LONG
    assert decision.score == D("12.5")
    assert decision.reason_codes == ("bearish_momentum_confirmed",)
    assert decision.instrument_id == InstrumentId("SYN")
    assert decision.decided_at == NOW
    assert decision.config_hash == ConfigHash("c" * 64)
    assert decision.data_hash == DataHash("a" * 64)
    assert decision.strategy_version == "unvalidated-options-put-momentum-20-100-v1"
    assert put_strategy.descriptor.research_only


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_return_pct", D("0")),
        ("total_return_pct", D("1")),
        ("moving_average_short", D("100")),
        ("moving_average_short", D("105")),
        ("latest_close", D("100")),
        ("latest_close", D("105")),
    ],
)
def test_any_unconfirmed_bearish_condition_holds_even_when_the_other_two_pass(
    put_strategy: OptionsMomentumStrategy, field: str, value: Decimal
) -> None:
    (decision,) = put_strategy.decide(bearish_context({field: value}))
    assert decision.action is StrategyAction.HOLD
    assert decision.score == D("0")
    assert decision.reason_codes == ("bearish_momentum_not_confirmed",)


@pytest.mark.parametrize("field", FEATURE_NAMES)
def test_missing_bearish_feature_does_not_become_a_put_signal(
    put_strategy: OptionsMomentumStrategy, field: str
) -> None:
    (decision,) = put_strategy.decide(bearish_context(missing=field))
    assert decision.action is StrategyAction.HOLD
    assert decision.score == D("0")


@pytest.mark.parametrize("field", FEATURE_NAMES)
@pytest.mark.parametrize(
    "value", [None, D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), True, -1, "-1"]
)
def test_nonfinite_or_nondecimal_feature_never_confirms_a_put(
    put_strategy: OptionsMomentumStrategy, field: str, value: FeatureValue
) -> None:
    (decision,) = put_strategy.decide(bearish_context({field: value}))
    assert decision.action is StrategyAction.HOLD
    assert decision.score == D("0")


@pytest.mark.parametrize("kind", ["put", "call", None, True])
def test_option_kind_must_be_an_exact_enum_not_an_implicit_direction(kind: object) -> None:
    with pytest.raises(DomainValidationError):
        OptionsMomentumStrategy(kind=kind, short_window=20, long_window=100)  # type: ignore[arg-type]


# Captured independently from committed pre-put replay/fixture implementations at
# 7155612d708ab59642791adfc827bb088e8c9c42. These bind the complete canonical result,
# including its input and intent hashes, without requiring Git or old code in CI.
LEGACY_CALL_RESULT_HASHES = (
    ("completed", "100", "418fc0a300ec1842da7c68fd7a3d0ca1863d10f0a632df20e2ce9cd8ad125607"),
    ("completed", "2500", "c64798b32e315a0134453d2ad7e66c05e25dd4d0c8c9a228cda85bdcdcb3cd5a"),
    ("loss", "100", "580b3d9be21b413a6aa17777f813d46566be58c82d23dc928d858a791fbdedbc"),
    ("loss", "2500", "9d01754d4d9876874ce0e08547d265e5395971c741a8c66e38c8c9b8a4e7b31c"),
    ("open", "100", "a7600b72aa777da3df98bde122c1f99776c9a8ae3f477c91238757d12dfc3208"),
    ("open", "2500", "9d3414b83e9b034a1d56b5b2178858cd003621e2c93e1855fef0ae51de87ea27"),
    ("unfilled", "100", "412967cc1728a5e5c53e58c3ffd82d95088075101aad891696ee0196f4c71f59"),
    ("unfilled", "2500", "7cf51bd9dd98df62b69c12a65ec5c78791fb73d15bc1913536fc1b827a060a68"),
    ("unknown", "100", "d8850168e9ef8c866cd83408095446d61161994a470166f5823c3580a284211e"),
    ("unknown", "2500", "e4e390c1c5ac0a9ace59fd88248b3e3c2465bd4a83935b71fde3c4f9c9bf5b33"),
    ("unsettled", "100", "08e52c48daa53140fe45a8ce682bd9fc072737e4e8ee72a1b573739c299675bf"),
    ("unsettled", "2500", "ffdd623e8c579c29d706439625f58e1a0842379d2f0320099180150424939fb1"),
    ("cancel_race", "100", "7e3af0f50b8d3dfc7247163df4feace793cebb216d3b3d7d422846040b8e5f08"),
    ("cancel_race", "2500", "48b0c9a8d4781e64e42536757db27945d3dd51fd00d60e26ed7b81da4635036b"),
    ("canceled", "100", "a061f359d597589551e4ad1724f0bde381256175c3909d8b938f3fbffa73cb84"),
    ("canceled", "2500", "2cd5a01d81821a2dc280285f70240369a69fcfd88ad2bcc163fdf9b4c00f87bb"),
    ("rejected", "100", "1a0bc8d063c6ce22da18bbc456d6969036c7a553c5e0c873b4d83b991a26a0fc"),
    ("rejected", "2500", "cf6d7da5529a49f2111eff48357176d71458db767eb23a4d12133e49dee94c28"),
)


@pytest.fixture
def options_config(monkeypatch: pytest.MonkeyPatch) -> LoadedConfig:
    # These golden results bind the pre-shortlist schema, not today's configuration
    # identity. Project ONLY the three subsequently added research sections out before
    # the real serializer hashes it. Production always binds the full current graph.
    original = config_hashing._hash_payload

    def legacy_config_identity(payload):
        legacy = deepcopy(payload)
        for name in ("config", "safety_envelope"):
            del legacy[name]["options"]["research_shortlist"]
            del legacy[name]["options"]["native_data"]
            del legacy[name]["options"]["research_study"]
        return original(legacy)

    monkeypatch.setattr(config_hashing, "_hash_payload", legacy_config_identity)
    config_dir = Path(__file__).parents[3] / "configs"
    loaded = load_config(
        config_dir / "base.yaml",
        config_dir / "options/simulation.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )
    # Independent original identity: all other policy changes must still fail.
    assert loaded.config_hash == "c742c2ffc44bc850c08a8560080c3b2b0ca65394fd5bebbd177167fbf1b9197b"
    return loaded


@pytest.mark.parametrize(("scenario", "capital", "expected_hash"), LEGACY_CALL_RESULT_HASHES)
def test_call_fixture_preserves_exact_pre_put_result_identity(
    options_config: LoadedConfig, scenario: str, capital: str, expected_hash: str
) -> None:
    request = synthetic_options_request(options_config, D(capital), scenario)
    assert request.contract.kind is OptionKind.CALL
    result = replay_options(request)
    assert content_hash(result) == expected_hash
    assert not result.production_eligible
    assert not result.evidence_promotable
