"""Bounded historical REST quote interpretation, never capacity or source admission.

Protocol reference: https://docs.alpaca.markets/us/reference/stockquotesingle-1.md
(public reference updated 2026-05-27, audited 2026-10-02). No reference is fetched
here. Date-era units are descriptive; the native codec's conservative transition
window is unchanged. Conditions are assigned to sides, not approved for execution.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Literal

from trading_bot.market_data.alpaca_native import AlpacaQuoteRecord

_PROTOCOL_REFERENCE_SHA256 = "82feb537497fb2f1518dd921987831780239e6e798ae225b15ccaaacb697a9a8"
_MANDATORY_REASONS = (
    "condition_eligibility_unverified",
    "control_coverage_unverified",
    "fractional_terms_unverified",
)


class AlpacaQuoteSemanticsError(ValueError):
    """Sanitized validation failure without record values or provider text."""

    def __init__(self) -> None:
        super().__init__("alpaca_quote_semantics_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise AlpacaQuoteSemanticsError()


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaQuoteSemantics:
    """Immutable descriptive projection bound to the unchanged native record."""

    record: AlpacaQuoteRecord
    record_hash: str = field(default="", init=False)
    protocol_reference_sha256: str = field(default=_PROTOCOL_REFERENCE_SHA256, init=False)
    bid_condition: str | None = field(default=None, init=False)
    ask_condition: str | None = field(default=None, init=False)
    bid_size_shares: Decimal | None = field(default=None, init=False)
    ask_size_shares: Decimal | None = field(default=None, init=False)
    reasons: tuple[str, ...] = field(default=(), init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            _check(type(self.record) is AlpacaQuoteRecord)
            _check(
                self.source_qualified is False
                and self.execution_enabled is False
                and self.evidence_promotable is False
                and type(self.protocol_reference_sha256) is str
                and self.protocol_reference_sha256 == _PROTOCOL_REFERENCE_SHA256
            )
            # Validate the original first: replace resets init=False flags and is
            # therefore insufficient on its own to detect unsafe flag mutation.
            self.record.__post_init__()
            _check(replace(self.record) == self.record)
            conditions = self.record.conditions
            bid_condition = ask_condition = None
            if len(conditions) == 1:
                bid_condition = ask_condition = conditions[0]
            elif len(conditions) == 2:
                bid_condition, ask_condition = conditions

            bid_size = ask_size = None
            reasons = set(self.record.observation_reasons) | set(_MANDATORY_REASONS)
            if self.record.size_unit == "shares":
                # Exact uint32-to-Decimal construction ignores ambient context.
                # This is a unit projection, not available execution capacity.
                bid_size = Decimal(self.record.bid_size)
                ask_size = Decimal(self.record.ask_size)
            elif self.record.size_unit == "round_lots":
                reasons.add("round_lot_conversion_unverified")
            else:
                reasons.add("size_transition_unverified")

            object.__setattr__(self, "record_hash", self.record.record_hash)
            object.__setattr__(self, "bid_condition", bid_condition)
            object.__setattr__(self, "ask_condition", ask_condition)
            object.__setattr__(self, "bid_size_shares", bid_size)
            object.__setattr__(self, "ask_size_shares", ask_size)
            object.__setattr__(self, "reasons", tuple(sorted(reasons)))
        except (ValueError, TypeError, ArithmeticError, RecursionError, AttributeError):
            raise AlpacaQuoteSemanticsError() from None


def interpret_alpaca_quote(record: AlpacaQuoteRecord) -> AlpacaQuoteSemantics:
    """Describe exact native syntax without admitting conditions, controls or fills."""
    return AlpacaQuoteSemantics(record)
