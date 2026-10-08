"""Distinct frozen adaptive-development study, never execution authorization."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import DomainValidationError, require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.config.models import AppConfig, SafetyEnvelope
from trading_bot.domain import ConfigHash, DataHash
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash

POLICY_ID = "spy-cash-monthly-sma10-protected-development-v1"
START = datetime(2016, 1, 1, tzinfo=UTC)
HOLDOUT = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 1, tzinfo=UTC)
CAPITALS = (Decimal("500"), Decimal("1000"))


def _check(ok: bool) -> None:
    if not ok:
        raise DomainValidationError("etf_monthly_invalid")


def _checked_loaded(loaded: LoadedConfig) -> LoadedConfig:
    _check(type(loaded) is LoadedConfig)
    _check(type(loaded.config) is AppConfig and type(loaded.safety_envelope) is SafetyEnvelope)
    restored = restore_loaded_config(loaded.canonical_json, loaded.config_hash)
    _check(restored.config == loaded.config and restored.safety_envelope == loaded.safety_envelope)
    cfg = restored.config
    equity = cfg.equity_strategies
    _check(equity.research_candidate_strategy_ids == (POLICY_ID,))
    _check(equity.research_universe_symbols == ("SPY",) and not equity.etf_pilot.enabled)
    _check(cfg.portfolio.expected_starting_equity_usd == Decimal("100"))
    _check(cfg.research.seed == 20260710)
    _check(equity.maximum_holding_bars == 100)
    _check(equity.stop_loss_atr_multiplier == Decimal("2.0"))
    _check(equity.exit_reward_to_initial_risk == Decimal("2.0"))
    _check(equity.exit_on_regime_change and equity.research_unselected_symbols_exit_to_cash)
    return restored


@dataclass(frozen=True, slots=True)
class EtfMonthlyStudy:
    canonical_config: str
    config_hash: str
    code_hash: str
    source_plan_hash: str
    cost_plan_hash: str
    operating_basis_hash: str
    seed: int
    risk_equity_reference: Decimal
    holdout_exposure: Literal["unknown", "examined", "operator-disclosed-unexamined"]
    source_requested_start: datetime = START
    source_requested_end: datetime = END
    requested_start: datetime = START
    requested_end: datetime = HOLDOUT
    holdout_start: datetime = HOLDOUT
    holdout_end: datetime = END
    policy_id: str = field(default=POLICY_ID, init=False)
    capital_tiers: tuple[Decimal, ...] = field(default=CAPITALS, init=False)
    development_previously_examined: Literal[True] = field(default=True, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    economic_admitted: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            _check(
                self.source_qualified is False
                and self.cost_qualified is False
                and self.execution_enabled is False
                and self.economic_admitted is False
                and self.evidence_promotable is False
                and self.live_authorized is False
            )
            _check(type(self.canonical_config) is str)
            loaded = _checked_loaded(
                restore_loaded_config(self.canonical_config.encode(), ConfigHash(self.config_hash))
            )
            for digest in (
                self.config_hash,
                self.code_hash,
                self.source_plan_hash,
                self.cost_plan_hash,
                self.operating_basis_hash,
            ):
                _require_sha256_hex(digest, "monthly study identity")
            _check(type(self.seed) is int and self.seed == loaded.config.research.seed)
            _check(
                type(self.risk_equity_reference) is Decimal
                and self.risk_equity_reference == Decimal("100")
            )
            _check(
                type(self.holdout_exposure) is str
                and self.holdout_exposure
                in ("unknown", "examined", "operator-disclosed-unexamined")
            )
            dates = (
                self.source_requested_start,
                self.source_requested_end,
                self.requested_start,
                self.requested_end,
                self.holdout_start,
                self.holdout_end,
            )
            for value in dates:
                require_utc(value)
            _check(dates == (START, END, START, HOLDOUT, HOLDOUT, END))
            _check(type(self.policy_id) is str and self.policy_id == POLICY_ID)
            _check(
                type(self.capital_tiers) is tuple
                and self.capital_tiers == CAPITALS
                and all(type(value) is Decimal for value in self.capital_tiers)
            )
            _check(self.development_previously_examined is True)
        except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
            raise DomainValidationError("etf_monthly_invalid") from None

    @property
    def study_hash(self) -> DataHash:
        return content_hash({"schema": "etf-monthly-study-v1", "study": self})


def freeze_etf_monthly_study(
    loaded: LoadedConfig,
    *,
    code_hash: str,
    source_plan_hash: str,
    cost_plan_hash: str,
    operating_basis_hash: str,
    holdout_exposure: Literal["unknown", "examined", "operator-disclosed-unexamined"],
) -> EtfMonthlyStudy:
    checked = _checked_loaded(loaded)
    return EtfMonthlyStudy(
        checked.canonical_json.decode(),
        checked.config_hash,
        code_hash,
        source_plan_hash,
        cost_plan_hash,
        operating_basis_hash,
        checked.config.research.seed,
        checked.config.portfolio.expected_starting_equity_usd,
        holdout_exposure,
    )


def monthly_policy(study: EtfMonthlyStudy) -> LoadedConfig:
    _check(type(study) is EtfMonthlyStudy)
    study.__post_init__()
    return _checked_loaded(
        restore_loaded_config(study.canonical_config.encode(), ConfigHash(study.config_hash))
    )
