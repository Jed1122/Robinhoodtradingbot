"""A fixed offline study identity; registration is not economic acceptance."""

import hashlib
from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import DomainValidationError, require_utc
from trading_bot.config import LoadedConfig, enforce_safety_envelope
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.models import AppConfig, SafetyEnvelope
from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash


@dataclass(frozen=True, slots=True)
class EtfStudy:
    policy: InitVar[LoadedConfig]
    canonical_config: str
    config_hash: str
    code_hash: str
    source_plan_hash: str
    cost_plan_hash: str
    requested_start: datetime
    requested_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    risk_equity_reference: Decimal
    seed: int
    holdout_previously_examined: bool
    policy_id: Literal["spy-cash-momentum-20-100-v1"] = field(
        default="spy-cash-momentum-20-100-v1", init=False
    )
    symbols: tuple[str, ...] = field(default=("SPY",), init=False)
    windows: tuple[int, int] = field(default=(20, 100), init=False)
    rebalance_sessions: int = field(default=5, init=False)
    capital_tiers: tuple[Decimal, ...] = field(
        default=(Decimal("500"), Decimal("1000")), init=False
    )
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self, policy: LoadedConfig) -> None:
        validated = _checked_policy(policy)
        if (
            self.canonical_config != validated.canonical_json.decode()
            or self.config_hash != validated.config_hash
            or self.seed != validated.config.research.seed
            or self.risk_equity_reference != validated.config.portfolio.expected_starting_equity_usd
        ):
            raise DomainValidationError("study record contradicts canonical policy")
        for name, digest in (
            ("config_hash", self.config_hash),
            ("code_hash", self.code_hash),
            ("source_plan_hash", self.source_plan_hash),
            ("cost_plan_hash", self.cost_plan_hash),
        ):
            _require_sha256_hex(digest, name)
        if type(self.canonical_config) is not str or len(self.canonical_config) > 1048576:
            raise DomainValidationError("invalid study configuration preimage")
        if hashlib.sha256(self.canonical_config.encode()).hexdigest() != self.config_hash:
            raise DomainValidationError("study configuration identity mismatch")
        for value in (
            self.requested_start,
            self.requested_end,
            self.holdout_start,
            self.holdout_end,
        ):
            require_utc(value)
        if (self.requested_start, self.requested_end, self.holdout_start, self.holdout_end) != (
            datetime(2016, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
        ):
            raise DomainValidationError("study windows are fixed before evaluation")
        require_bounded_decimal(self.risk_equity_reference, "risk reference", positive=True)
        if self.risk_equity_reference != Decimal("100"):
            raise DomainValidationError("starting cash cannot replace risk authority")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise DomainValidationError("invalid study seed")
        if type(self.holdout_previously_examined) is not bool:
            raise DomainValidationError("holdout disclosure must be explicit")

    @property
    def non_promotability_reasons(self) -> tuple[str, ...]:
        return ("research_registration_only",) + (
            ("holdout_previously_examined",) if self.holdout_previously_examined else ()
        )

    @property
    def study_hash(self) -> DataHash:
        return content_hash({"schema": "etf-study-v1", "study": self})


def _checked_policy(loaded: LoadedConfig) -> LoadedConfig:
    if (
        type(loaded) is not LoadedConfig
        or type(loaded.config) is not AppConfig
        or type(loaded.safety_envelope) is not SafetyEnvelope
    ):
        raise DomainValidationError("canonical loaded configuration is required")
    # Revalidate even model_copy/model_construct inputs before using policy values.
    config = AppConfig.model_validate(loaded.config.model_dump(mode="python"))
    envelope = SafetyEnvelope.model_validate(loaded.safety_envelope.model_dump(mode="python"))
    enforce_safety_envelope(config, envelope)
    canonical, digest = hash_loaded_config(config, envelope)
    if (canonical, digest) != (loaded.canonical_json, loaded.config_hash):
        raise DomainValidationError("canonical configuration identity mismatch")
    if not config.equity_strategies.etf_pilot.enabled:
        raise DomainValidationError("ETF research registration is disabled")
    return LoadedConfig(config, envelope, canonical, digest)


def freeze_etf_study(
    loaded: LoadedConfig,
    *,
    code_hash: str,
    source_plan_hash: str,
    cost_plan_hash: str,
    holdout_previously_examined: bool,
) -> EtfStudy:
    validated = _checked_policy(loaded)
    config = validated.config
    settings = config.equity_strategies.etf_pilot
    return EtfStudy(
        policy=validated,
        canonical_config=validated.canonical_json.decode(),
        config_hash=validated.config_hash,
        code_hash=code_hash,
        source_plan_hash=source_plan_hash,
        cost_plan_hash=cost_plan_hash,
        requested_start=datetime.fromisoformat(settings.requested_start).replace(tzinfo=UTC),
        requested_end=datetime.fromisoformat(settings.requested_end).replace(tzinfo=UTC),
        holdout_start=datetime.fromisoformat(settings.holdout_start).replace(tzinfo=UTC),
        holdout_end=datetime.fromisoformat(settings.requested_end).replace(tzinfo=UTC),
        risk_equity_reference=config.portfolio.expected_starting_equity_usd,
        seed=config.research.seed,
        holdout_previously_examined=holdout_previously_examined,
    )
