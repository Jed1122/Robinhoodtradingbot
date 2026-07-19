"""Operator-side activation helpers; signing never starts trading."""

from trading_bot.authorization import ACKNOWLEDGEMENT


def validate_acknowledgement(value: str) -> None:
    if value != ACKNOWLEDGEMENT:
        raise ValueError("exact acknowledgement is required")


__all__ = ["validate_acknowledgement"]
