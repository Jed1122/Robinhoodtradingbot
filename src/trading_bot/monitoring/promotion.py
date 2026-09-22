"""Identity-bound promotion observations and configuration-derived progress."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from trading_bot.clock import require_utc
from trading_bot.config.models import PromotionSettings
from trading_bot.domain import DomainValidationError
from trading_bot.domain.decimal_utils import (
    _require_exact_bool,
    _require_exact_enum,
    _require_nonempty,
    _require_nonnegative_int,
    _require_sha256_hex,
    _require_tuple,
)
from trading_bot.market_data import content_hash


class PromotionStage(StrEnum):
    SIMULATION = "simulation"
    PAPER = "paper"
    SHADOW = "shadow"
    MICRO_LIVE = "micro_live"
    NORMAL_LIVE = "normal_live"


_OBSERVATION_STAGES = frozenset(
    {
        PromotionStage.PAPER,
        PromotionStage.SHADOW,
        PromotionStage.MICRO_LIVE,
        PromotionStage.NORMAL_LIVE,
    }
)
_CONNECTED_STAGES = frozenset(
    {
        PromotionStage.SHADOW,
        PromotionStage.MICRO_LIVE,
        PromotionStage.NORMAL_LIVE,
    }
)
_NORMAL_PROMOTION_SOURCE_STAGES = frozenset(
    {
        PromotionStage.PAPER,
        PromotionStage.SHADOW,
        PromotionStage.MICRO_LIVE,
    }
)


@dataclass(frozen=True, slots=True)
class PromotionIdentity:
    """Exact account, provider, strategy, configuration, and code identity."""

    account_fingerprint: str
    provider_evidence_hash: str
    strategy_version: str
    strategy_eligibility_hash: str
    config_hash: str
    code_hash: str

    def __post_init__(self) -> None:
        _require_sha256_hex(self.account_fingerprint, "account_fingerprint")
        _require_sha256_hex(self.provider_evidence_hash, "provider_evidence_hash")
        _require_nonempty(self.strategy_version, "strategy_version")
        _require_sha256_hex(self.strategy_eligibility_hash, "strategy_eligibility_hash")
        _require_sha256_hex(self.config_hash, "config_hash")
        _require_sha256_hex(self.code_hash, "code_hash")


def _observation_reason_codes(
    *,
    stage: PromotionStage,
    identity_verified: bool,
    provider_evidence_verified: bool,
    strategy_eligible: bool,
    authenticated_reads: bool,
    data_validated: bool,
    outcomes_complete: bool,
    reconciliation_clean: bool,
    fixture_data: bool,
    runtime_scope_valid: bool,
    order_state_known: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not identity_verified:
        reasons.append("identity_unverified")
    if not provider_evidence_verified:
        reasons.append("provider_evidence_unverified")
    if not strategy_eligible:
        reasons.append("strategy_ineligible")
    if stage in _CONNECTED_STAGES and not authenticated_reads:
        reasons.append("authenticated_reads_missing")
    if not data_validated:
        reasons.append("live_data_invalid")
    if not outcomes_complete:
        reasons.append("outcomes_incomplete")
    if not reconciliation_clean:
        reasons.append("reconciliation_dirty")
    if fixture_data:
        reasons.append("fixture_data")
    if not runtime_scope_valid:
        reasons.append("runtime_scope_invalid")
    if not order_state_known:
        reasons.append("unknown_order_state")
    return tuple(reasons)


def _observation_hash(
    *,
    stage: PromotionStage,
    cycle_id: str,
    identity: PromotionIdentity,
    started_at: datetime,
    completed_at: datetime,
    data_hash: str,
    identity_verified: bool,
    provider_evidence_verified: bool,
    strategy_eligible: bool,
    authenticated_reads: bool,
    data_validated: bool,
    outcomes_complete: bool,
    reconciliation_clean: bool,
    fixture_data: bool,
    runtime_scope_valid: bool,
    order_state_known: bool,
    reason_codes: tuple[str, ...],
) -> str:
    return str(
        content_hash(
            {
                "authenticated_reads": authenticated_reads,
                "runtime_scope_valid": runtime_scope_valid,
                "completed_at": completed_at,
                "cycle_id": cycle_id,
                "data_hash": data_hash,
                "fixture_data": fixture_data,
                "identity": identity,
                "identity_verified": identity_verified,
                "order_state_known": order_state_known,
                "outcomes_complete": outcomes_complete,
                "provider_evidence_verified": provider_evidence_verified,
                "reason_codes": reason_codes,
                "reconciliation_clean": reconciliation_clean,
                "stage": stage,
                "started_at": started_at,
                "strategy_eligible": strategy_eligible,
                "data_validated": data_validated,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class PromotionObservation:
    """One append-only cycle record whose eligibility cannot be caller-selected."""

    stage: PromotionStage
    cycle_id: str
    identity: PromotionIdentity
    started_at: datetime
    completed_at: datetime
    data_hash: str
    identity_verified: bool
    provider_evidence_verified: bool
    strategy_eligible: bool
    authenticated_reads: bool
    data_validated: bool
    outcomes_complete: bool
    reconciliation_clean: bool
    fixture_data: bool
    runtime_scope_valid: bool
    order_state_known: bool
    eligible: bool
    reason_codes: tuple[str, ...]
    evidence_hash: str

    @classmethod
    def create(
        cls,
        *,
        stage: PromotionStage,
        cycle_id: str,
        identity: PromotionIdentity,
        started_at: datetime,
        completed_at: datetime,
        data_hash: str,
        identity_verified: bool,
        provider_evidence_verified: bool,
        strategy_eligible: bool,
        authenticated_reads: bool,
        data_validated: bool,
        outcomes_complete: bool,
        reconciliation_clean: bool,
        fixture_data: bool,
        runtime_scope_valid: bool,
        order_state_known: bool,
    ) -> PromotionObservation:
        reasons = _observation_reason_codes(
            stage=stage,
            identity_verified=identity_verified,
            provider_evidence_verified=provider_evidence_verified,
            strategy_eligible=strategy_eligible,
            authenticated_reads=authenticated_reads,
            data_validated=data_validated,
            outcomes_complete=outcomes_complete,
            reconciliation_clean=reconciliation_clean,
            fixture_data=fixture_data,
            runtime_scope_valid=runtime_scope_valid,
            order_state_known=order_state_known,
        )
        return cls(
            stage=stage,
            cycle_id=cycle_id,
            identity=identity,
            started_at=started_at,
            completed_at=completed_at,
            data_hash=data_hash,
            identity_verified=identity_verified,
            provider_evidence_verified=provider_evidence_verified,
            strategy_eligible=strategy_eligible,
            authenticated_reads=authenticated_reads,
            data_validated=data_validated,
            outcomes_complete=outcomes_complete,
            reconciliation_clean=reconciliation_clean,
            fixture_data=fixture_data,
            runtime_scope_valid=runtime_scope_valid,
            order_state_known=order_state_known,
            eligible=not reasons,
            reason_codes=reasons,
            evidence_hash=_observation_hash(
                stage=stage,
                cycle_id=cycle_id,
                identity=identity,
                started_at=started_at,
                completed_at=completed_at,
                data_hash=data_hash,
                identity_verified=identity_verified,
                provider_evidence_verified=provider_evidence_verified,
                strategy_eligible=strategy_eligible,
                authenticated_reads=authenticated_reads,
                data_validated=data_validated,
                outcomes_complete=outcomes_complete,
                reconciliation_clean=reconciliation_clean,
                fixture_data=fixture_data,
                runtime_scope_valid=runtime_scope_valid,
                order_state_known=order_state_known,
                reason_codes=reasons,
            ),
        )

    def __post_init__(self) -> None:
        _require_exact_enum(self.stage, PromotionStage, "stage")
        if self.stage not in _OBSERVATION_STAGES:
            raise DomainValidationError("stage cannot produce a promotion observation")
        _require_sha256_hex(self.cycle_id, "cycle_id")
        if type(self.identity) is not PromotionIdentity:
            raise DomainValidationError("identity must be a PromotionIdentity")
        require_utc(self.started_at)
        require_utc(self.completed_at)
        if self.completed_at < self.started_at:
            raise DomainValidationError("completed_at cannot precede started_at")
        _require_sha256_hex(self.data_hash, "data_hash")
        for value, name in (
            (self.identity_verified, "identity_verified"),
            (self.provider_evidence_verified, "provider_evidence_verified"),
            (self.strategy_eligible, "strategy_eligible"),
            (self.authenticated_reads, "authenticated_reads"),
            (self.data_validated, "data_validated"),
            (self.outcomes_complete, "outcomes_complete"),
            (self.reconciliation_clean, "reconciliation_clean"),
            (self.fixture_data, "fixture_data"),
            (self.runtime_scope_valid, "runtime_scope_valid"),
            (self.order_state_known, "order_state_known"),
            (self.eligible, "eligible"),
        ):
            _require_exact_bool(value, name)
        _require_tuple(self.reason_codes, "reason_codes")
        if any(type(code) is not str or not code for code in self.reason_codes):
            raise DomainValidationError("reason_codes must contain nonempty strings")
        expected_reasons = _observation_reason_codes(
            stage=self.stage,
            identity_verified=self.identity_verified,
            provider_evidence_verified=self.provider_evidence_verified,
            strategy_eligible=self.strategy_eligible,
            authenticated_reads=self.authenticated_reads,
            data_validated=self.data_validated,
            outcomes_complete=self.outcomes_complete,
            reconciliation_clean=self.reconciliation_clean,
            fixture_data=self.fixture_data,
            runtime_scope_valid=self.runtime_scope_valid,
            order_state_known=self.order_state_known,
        )
        if self.reason_codes != expected_reasons or self.eligible is not (not expected_reasons):
            raise DomainValidationError("promotion observation eligibility is inconsistent")
        _require_sha256_hex(self.evidence_hash, "evidence_hash")
        expected_hash = _observation_hash(
            stage=self.stage,
            cycle_id=self.cycle_id,
            identity=self.identity,
            started_at=self.started_at,
            completed_at=self.completed_at,
            data_hash=self.data_hash,
            identity_verified=self.identity_verified,
            provider_evidence_verified=self.provider_evidence_verified,
            strategy_eligible=self.strategy_eligible,
            authenticated_reads=self.authenticated_reads,
            data_validated=self.data_validated,
            outcomes_complete=self.outcomes_complete,
            reconciliation_clean=self.reconciliation_clean,
            fixture_data=self.fixture_data,
            runtime_scope_valid=self.runtime_scope_valid,
            order_state_known=self.order_state_known,
            reason_codes=self.reason_codes,
        )
        if self.evidence_hash != expected_hash:
            raise DomainValidationError("promotion observation evidence hash is inconsistent")


@dataclass(frozen=True, slots=True)
class TimedPromotionEvidence:
    """Hash reference with an explicit, bounded validity window."""

    evidence_hash: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_sha256_hex(self.evidence_hash, "evidence_hash")
        require_utc(self.observed_at)
        require_utc(self.expires_at)
        if self.expires_at <= self.observed_at:
            raise DomainValidationError("external promotion evidence must have positive lifetime")


@dataclass(frozen=True, slots=True)
class MicroOrderReviewEvidence:
    """Current review summary proving every completed interval was reviewed."""

    attestation: TimedPromotionEvidence
    total_micro_orders: int
    reviewed_through_order: int
    review_interval: int

    def __post_init__(self) -> None:
        if type(self.attestation) is not TimedPromotionEvidence:
            raise DomainValidationError("micro review attestation is invalid")
        _require_nonnegative_int(self.total_micro_orders, "total_micro_orders")
        _require_nonnegative_int(self.reviewed_through_order, "reviewed_through_order")
        _require_nonnegative_int(self.review_interval, "review_interval")
        if self.review_interval == 0:
            raise DomainValidationError("review_interval must be positive")
        if self.reviewed_through_order > self.total_micro_orders:
            raise DomainValidationError("micro review cannot cover unobserved orders")


@dataclass(frozen=True, slots=True)
class PromotionExternalEvidence:
    security_clearance: TimedPromotionEvidence | None = None
    manual_acknowledgement: TimedPromotionEvidence | None = None
    micro_runtime_controls: TimedPromotionEvidence | None = None
    micro_order_review: MicroOrderReviewEvidence | None = None
    slippage_assessment: TimedPromotionEvidence | None = None
    drawdown_assessment: TimedPromotionEvidence | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.security_clearance, "security_clearance"),
            (self.manual_acknowledgement, "manual_acknowledgement"),
            (self.micro_runtime_controls, "micro_runtime_controls"),
            (self.slippage_assessment, "slippage_assessment"),
            (self.drawdown_assessment, "drawdown_assessment"),
        ):
            if value is not None and type(value) is not TimedPromotionEvidence:
                raise DomainValidationError(f"{name} must be TimedPromotionEvidence")
        if self.micro_order_review is not None and type(self.micro_order_review) is not (
            MicroOrderReviewEvidence
        ):
            raise DomainValidationError("micro_order_review must be MicroOrderReviewEvidence")


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    stage: PromotionStage
    identity: PromotionIdentity
    settings_hash: str
    source_observation_hashes: tuple[str, ...]
    observation_hashes: tuple[str, ...]
    unique_observations: int
    calendar_days: int
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    external: PromotionExternalEvidence

    def __post_init__(self) -> None:
        _require_exact_enum(self.stage, PromotionStage, "stage")
        if type(self.identity) is not PromotionIdentity:
            raise DomainValidationError("identity must be PromotionIdentity")
        _require_sha256_hex(self.settings_hash, "settings_hash")
        for values, name in (
            (self.source_observation_hashes, "source_observation_hashes"),
            (self.observation_hashes, "observation_hashes"),
        ):
            _require_tuple(values, name)
            if any(type(value) is not str for value in values):
                raise DomainValidationError(f"{name} must contain hashes")
            for value in values:
                _require_sha256_hex(value, name)
            if values != tuple(sorted(set(values))):
                raise DomainValidationError(f"{name} must be sorted and unique")
        if not set(self.observation_hashes) <= set(self.source_observation_hashes):
            raise DomainValidationError("counted observations must come from source evidence")
        _require_nonnegative_int(self.unique_observations, "unique_observations")
        _require_nonnegative_int(self.calendar_days, "calendar_days")
        if self.unique_observations != len(self.observation_hashes):
            raise DomainValidationError("unique observation count is inconsistent")
        if self.calendar_days > self.unique_observations:
            raise DomainValidationError("calendar days exceed unique observations")
        if (self.first_observed_at is None) is not (self.last_observed_at is None):
            raise DomainValidationError("promotion observation bounds are incomplete")
        if self.first_observed_at is None:
            if self.unique_observations or self.calendar_days:
                raise DomainValidationError("empty promotion evidence has nonzero progress")
        else:
            if self.last_observed_at is None:
                raise DomainValidationError("promotion observation bounds are incomplete")
            first = require_utc(self.first_observed_at)
            last = require_utc(self.last_observed_at)
            if not self.unique_observations or first > last:
                raise DomainValidationError("promotion observation bounds are invalid")
        if type(self.external) is not PromotionExternalEvidence:
            raise DomainValidationError("external evidence is invalid")


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    eligible: bool
    reasons: tuple[str, ...]
    evidence_hash: str
    evidence: PromotionEvidence
    override_allowed: bool = False

    def __post_init__(self) -> None:
        _require_exact_bool(self.eligible, "eligible")
        _require_tuple(self.reasons, "reasons")
        if any(type(reason) is not str or not reason for reason in self.reasons):
            raise DomainValidationError("promotion reasons must be nonempty strings")
        if len(set(self.reasons)) != len(self.reasons):
            raise DomainValidationError("promotion reasons must be unique")
        if self.eligible is not (not self.reasons):
            raise DomainValidationError("promotion decision eligibility is inconsistent")
        _require_sha256_hex(self.evidence_hash, "evidence_hash")
        if type(self.evidence) is not PromotionEvidence:
            raise DomainValidationError("evidence must be PromotionEvidence")
        _require_exact_bool(self.override_allowed, "override_allowed")
        if self.override_allowed:
            raise DomainValidationError("promotion decisions cannot be overridden")
        expected_hash = str(
            content_hash(
                {
                    "evidence": self.evidence,
                    "reasons": self.reasons,
                }
            )
        )
        if self.evidence_hash != expected_hash:
            raise DomainValidationError("promotion decision evidence hash is inconsistent")


def _require_current_external_evidence(
    reasons: list[str],
    *,
    name: str,
    evidence: TimedPromotionEvidence | None,
    now: datetime,
) -> bool:
    if evidence is None:
        reasons.append(f"{name}_missing")
        return False
    if evidence.observed_at > now:
        reasons.append(f"{name}_future")
        return False
    if evidence.expires_at <= now:
        reasons.append(f"{name}_expired")
        return False
    return True


class PromotionEvaluator:
    """Derive progress from immutable observations and canonical settings."""

    def __init__(self, settings: PromotionSettings) -> None:
        if type(settings) is not PromotionSettings:
            raise TypeError("settings must be PromotionSettings")
        self._settings = settings

    def evaluate(
        self,
        *,
        stage: PromotionStage,
        identity: PromotionIdentity,
        observations: tuple[PromotionObservation, ...],
        now: datetime,
        external: PromotionExternalEvidence | None = None,
    ) -> PromotionDecision:
        _require_exact_enum(stage, PromotionStage, "stage")
        if type(identity) is not PromotionIdentity:
            raise TypeError("identity must be PromotionIdentity")
        _require_tuple(observations, "observations")
        if any(type(item) is not PromotionObservation for item in observations):
            raise TypeError("observations must contain PromotionObservation records")
        now = require_utc(now)
        external = external or PromotionExternalEvidence()
        if type(external) is not PromotionExternalEvidence:
            raise TypeError("external must be PromotionExternalEvidence")

        if stage is PromotionStage.PAPER:
            relevant_stages = frozenset({PromotionStage.PAPER})
        elif stage is PromotionStage.SHADOW:
            relevant_stages = frozenset({PromotionStage.SHADOW})
        elif stage is PromotionStage.MICRO_LIVE:
            relevant_stages = frozenset(
                {PromotionStage.PAPER, PromotionStage.SHADOW, PromotionStage.MICRO_LIVE}
            )
        elif stage is PromotionStage.NORMAL_LIVE:
            relevant_stages = frozenset(
                {*_NORMAL_PROMOTION_SOURCE_STAGES, PromotionStage.NORMAL_LIVE}
            )
        else:
            relevant_stages = frozenset()

        matching = tuple(
            item
            for item in observations
            if item.identity == identity and item.stage in relevant_stages
        )
        source_hashes = tuple(sorted({item.evidence_hash for item in matching}))
        future_observations = tuple(item for item in matching if item.completed_at > now)
        current = tuple(item for item in matching if item.completed_at <= now)
        grouped: dict[tuple[PromotionStage, str], list[PromotionObservation]] = {}
        for item in current:
            grouped.setdefault((item.stage, item.cycle_id), []).append(item)

        conflicting_keys = frozenset(
            key for key, items in grouped.items() if len({item.evidence_hash for item in items}) > 1
        )
        unique = tuple(
            sorted(
                (
                    min(items, key=lambda item: item.evidence_hash)
                    for key, items in grouped.items()
                    if key not in conflicting_keys
                ),
                key=lambda item: (item.completed_at, item.stage, item.cycle_id),
            )
        )
        eligible = tuple(item for item in unique if item.eligible)
        paper = tuple(item for item in eligible if item.stage is PromotionStage.PAPER)
        shadow = tuple(item for item in eligible if item.stage is PromotionStage.SHADOW)
        micro = tuple(item for item in eligible if item.stage is PromotionStage.MICRO_LIVE)
        normal = tuple(item for item in unique if item.stage is PromotionStage.NORMAL_LIVE)
        combined = (*paper, *shadow, *micro)

        if stage is PromotionStage.PAPER:
            counted = paper
        elif stage is PromotionStage.SHADOW:
            counted = shadow
        elif stage is PromotionStage.MICRO_LIVE:
            counted = (*paper, *shadow)
        elif stage is PromotionStage.NORMAL_LIVE:
            counted = combined
        else:
            counted = ()

        dates = frozenset(item.completed_at.date() for item in counted)
        settings_hash = str(content_hash(self._settings.model_dump(mode="json")))
        evidence = PromotionEvidence(
            stage=stage,
            identity=identity,
            settings_hash=settings_hash,
            source_observation_hashes=source_hashes,
            observation_hashes=tuple(sorted(item.evidence_hash for item in counted)),
            unique_observations=len(counted),
            calendar_days=len(dates),
            first_observed_at=min((item.completed_at for item in counted), default=None),
            last_observed_at=max((item.completed_at for item in counted), default=None),
            external=external,
        )

        reasons: list[str] = []
        if stage is PromotionStage.SIMULATION:
            reasons.append("simulation_is_not_promotable")
        elif stage is PromotionStage.PAPER:
            if len(paper) < self._settings.paper_min_eligible_unique_cycles:
                reasons.append("insufficient_paper_cycles")
        elif stage is PromotionStage.SHADOW:
            if len(frozenset(item.completed_at.date() for item in shadow)) < (
                self._settings.shadow_min_calendar_days
            ):
                reasons.append("insufficient_shadow_calendar_days")
        elif stage is PromotionStage.MICRO_LIVE:
            if len(paper) < self._settings.paper_min_eligible_unique_cycles:
                reasons.append("insufficient_paper_cycles")
            if len(frozenset(item.completed_at.date() for item in shadow)) < (
                self._settings.shadow_min_calendar_days
            ):
                reasons.append("insufficient_shadow_calendar_days")
        elif stage is PromotionStage.NORMAL_LIVE:
            if len(paper) < self._settings.paper_min_eligible_unique_cycles:
                reasons.append("insufficient_paper_cycles")
            if len(frozenset(item.completed_at.date() for item in shadow)) < (
                self._settings.shadow_min_calendar_days
            ):
                reasons.append("insufficient_shadow_calendar_days")
            if len(combined) < self._settings.normal_min_valid_observations:
                reasons.append("insufficient_connected_observations")
            if len(frozenset(item.completed_at.date() for item in combined)) < (
                self._settings.normal_min_combined_calendar_days
            ):
                reasons.append("insufficient_connected_calendar_days")
            if not micro:
                reasons.append("micro_live_observations_missing")

        if conflicting_keys:
            reasons.append("conflicting_cycle_evidence")
        if future_observations:
            reasons.append("future_observation")
        progress_candidates = (
            tuple(item for item in unique if item.stage in _NORMAL_PROMOTION_SOURCE_STAGES)
            if stage is PromotionStage.NORMAL_LIVE
            else unique
        )
        if progress_candidates:
            latest_at = max(item.completed_at for item in progress_candidates)
            latest = tuple(item for item in progress_candidates if item.completed_at == latest_at)
        else:
            latest = ()
        if latest and any(not item.eligible for item in latest):
            reasons.append("latest_observation_ineligible")
        if stage is PromotionStage.NORMAL_LIVE and normal:
            latest_normal_at = max(item.completed_at for item in normal)
            latest_normal = tuple(item for item in normal if item.completed_at == latest_normal_at)
            if any(not item.eligible for item in latest_normal):
                reasons.append("latest_normal_observation_ineligible")
        if stage in {PromotionStage.MICRO_LIVE, PromotionStage.NORMAL_LIVE}:
            if self._settings.no_critical_security_findings_required:
                _require_current_external_evidence(
                    reasons,
                    name="security_clearance",
                    evidence=external.security_clearance,
                    now=now,
                )
            if self._settings.current_manual_acknowledgement_required:
                _require_current_external_evidence(
                    reasons,
                    name="manual_acknowledgement",
                    evidence=external.manual_acknowledgement,
                    now=now,
                )
            _require_current_external_evidence(
                reasons,
                name="micro_runtime_controls",
                evidence=external.micro_runtime_controls,
                now=now,
            )
        if stage is PromotionStage.NORMAL_LIVE:
            review = external.micro_order_review
            if review is None:
                reasons.append("micro_order_review_missing")
            elif _require_current_external_evidence(
                reasons,
                name="micro_order_review",
                evidence=review.attestation,
                now=now,
            ):
                if review.total_micro_orders == 0:
                    reasons.append("micro_orders_missing")
                if review.review_interval != self._settings.micro_order_review_interval:
                    reasons.append("micro_order_review_interval_mismatch")
                required_reviewed_through = (
                    review.total_micro_orders // self._settings.micro_order_review_interval
                ) * self._settings.micro_order_review_interval
                if review.reviewed_through_order < required_reviewed_through:
                    reasons.append("micro_order_review_incomplete")
            _require_current_external_evidence(
                reasons,
                name="slippage_assessment",
                evidence=external.slippage_assessment,
                now=now,
            )
            _require_current_external_evidence(
                reasons,
                name="drawdown_assessment",
                evidence=external.drawdown_assessment,
                now=now,
            )

        reasons_tuple = tuple(dict.fromkeys(reasons))
        digest = str(content_hash({"evidence": evidence, "reasons": reasons_tuple}))
        return PromotionDecision(not reasons_tuple, reasons_tuple, digest, evidence)


__all__ = [
    "MicroOrderReviewEvidence",
    "PromotionDecision",
    "PromotionEvaluator",
    "PromotionEvidence",
    "PromotionExternalEvidence",
    "PromotionIdentity",
    "PromotionObservation",
    "PromotionStage",
    "TimedPromotionEvidence",
]
