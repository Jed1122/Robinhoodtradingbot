"""Non-authoritative train-only ranking of complete declared research outcomes.

The evaluator must derive every declaration from owned original-event runs.
This pure ranking neither authenticates results nor supplies account permission.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.domain import require_bounded_decimal
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_signals import CapitalCandidate, capital_candidates


@dataclass(frozen=True, slots=True)
class CapitalTrainingOutcome:
    candidate: CapitalCandidate
    net_pnl: Decimal | None
    complete: bool
    last_outcome_at: datetime
    input_hash: str
    roundtrip_friction_pct: Decimal = Decimal(".40")


@dataclass(frozen=True, slots=True)
class CapitalTrainingSelection:
    capital: Decimal
    selected: CapitalCandidate | None
    selected_net_pnl: Decimal
    excluded: tuple[CapitalCandidate, ...]
    reason: str
    panel_hash: str
    friction_pct: Decimal = field(default=Decimal(".40"), init=False)
    independent_opportunities: None = field(default=None, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    economic_admitted: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def select_capital_training(
    outcomes: tuple[CapitalTrainingOutcome, ...],
    *,
    loaded: LoadedConfig,
    capital: Decimal,
    training_cutoff: datetime,
    selection_at: datetime,
) -> CapitalTrainingSelection:
    """Rank complete .40%-friction declared dollar P&L, cash at nonpositive.

    Exact frozen grid order breaks ties. No test-period values are admitted;
    neither source/finality authentication nor independent support is inferred.
    Costs, cutoff and original run hashes must be bound by the owning evaluator.
    """
    cfg = _config(loaded)
    require_bounded_decimal(capital, "research capital", positive=True)
    training_cutoff = require_utc(training_cutoff)
    selection_at = require_utc(selection_at)
    if (
        capital not in cfg.capital_research.capital_tiers
        or training_cutoff >= selection_at
        or type(outcomes) is not tuple
        or len(outcomes) != 28
    ):
        raise ValueError("capital_training_invalid")
    best: CapitalCandidate | None = None
    best_profit = Decimal(0)
    excluded: list[CapitalCandidate] = []
    for outcome, candidate in zip(outcomes, capital_candidates(), strict=True):
        if (
            type(outcome) is not CapitalTrainingOutcome
            or type(outcome.candidate) is not CapitalCandidate
        ):
            raise ValueError("capital_training_invalid")
        outcome.candidate.__post_init__()
        _require_sha256_hex(outcome.input_hash, "original training run")
        require_bounded_decimal(outcome.roundtrip_friction_pct, "training friction", positive=True)
        if (
            outcome.candidate != candidate
            or type(outcome.complete) is not bool
            or require_utc(outcome.last_outcome_at) > training_cutoff
            or outcome.complete != (outcome.net_pnl is not None)
            or outcome.roundtrip_friction_pct != Decimal(".40")
        ):
            raise ValueError("capital_training_invalid")
        if outcome.net_pnl is None:
            excluded.append(candidate)
            continue
        require_bounded_decimal(outcome.net_pnl, "training dollar profit")
        if outcome.net_pnl > best_profit:
            best, best_profit = candidate, outcome.net_pnl
    return CapitalTrainingSelection(
        capital,
        best,
        best_profit,
        tuple(excluded),
        "positive_complete_training_winner" if best else "no_complete_positive_candidate",
        content_hash(
            (
                "capital-training-selection-v1",
                loaded.config_hash,
                capital,
                training_cutoff,
                selection_at,
                Decimal(".40"),
                outcomes,
            )
        ),
    )
