"""Reviewed REST schema facts, separate from legacy and executable semantics.

Reviewed 2026-10-02: https://docs.alpaca.markets/us/reference/stockquotes-1.md
(updated 2026-05-27). The reference documents historical raw size units and side
flags. It does not establish round-lot multipliers, condition eligibility, LULD,
controls, completeness, fractional fills or historical availability. No network,
raw-price serialization, record rewriting or admission capability exists here.
"""

from dataclasses import dataclass, field, replace
from typing import Literal

from trading_bot.market_data.alpaca_native import AlpacaQuoteRecord
from trading_bot.market_data.recording import content_hash

REFERENCE_SHA256 = "d408356bc3fc73d19fbab43a01501f05d1e888da60e21a03460cd3d2d7696cd9"
REFERENCE_URL = "https://docs.alpaca.markets/us/reference/stockquotes-1.md"


@dataclass(frozen=True, slots=True)
class AlpacaRestQuoteAssessment:
    record_hash: str
    documented_size_unit: Literal["round_lots", "shares"] | None
    raw_bid_size: int
    raw_ask_size: int
    bid_condition: str | None
    ask_condition: str | None
    condition_scope_documented: bool
    quality: Literal["inactive_side", "crossed", "locked", "zero_size", "two_sided_uncrossed"]
    reasons: tuple[str, ...]
    protocol_reference_sha256: str = field(default=REFERENCE_SHA256, init=False)
    round_lot_multiplier: None = field(default=None, init=False)
    execution_qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def report_hash(self) -> str:
        return content_hash(("alpaca-rest-quote-schema-assessment-v1", self))


def assess_alpaca_rest_quote(record: AlpacaQuoteRecord) -> AlpacaRestQuoteAssessment:
    """Qualify interpretation of documented fields only, never execution inputs.

    Preserve the prior conservative UTC/NY union for the unspecified cutover time.
    Round lots remain round lots; do not infer a multiplier from a price or ticker.
    Every side/quality combination retains the independent execution blockers.
    """
    try:
        if type(record) is not AlpacaQuoteRecord:
            raise ValueError
        record.__post_init__()
        if replace(record) != record:
            raise ValueError
        unit = record.size_unit
        bid_condition = ask_condition = None
        if len(record.conditions) == 1:
            bid_condition = ask_condition = record.conditions[0]
        elif len(record.conditions) == 2:
            bid_condition, ask_condition = record.conditions
        reasons = [
            "condition_eligibility_and_luld_unverified",
            "historical_control_and_continuity_unverified",
            "fractional_execution_unverified",
            "retrieval_not_historical_availability",
        ]
        if unit == "transition_unverified":
            reasons.append("size_transition_timezone_unresolved")
        elif unit == "round_lots":
            reasons.append("round_lot_multiplier_unverified")
        if bid_condition is None:
            reasons.append("condition_scope_unsupported")
        quality: Literal[
            "inactive_side", "crossed", "locked", "zero_size", "two_sided_uncrossed"
        ] = "two_sided_uncrossed"
        if record.bid == 0 or record.ask == 0:
            quality = "inactive_side"
        elif record.bid > record.ask:
            quality = "crossed"
        elif record.bid == record.ask:
            quality = "locked"
        elif record.bid_size == 0 or record.ask_size == 0:
            quality = "zero_size"
        return AlpacaRestQuoteAssessment(
            record.record_hash,
            None if unit == "transition_unverified" else unit,
            record.bid_size,
            record.ask_size,
            bid_condition,
            ask_condition,
            bid_condition is not None,
            quality,
            tuple(reasons),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("alpaca_rest_reference_invalid") from None
