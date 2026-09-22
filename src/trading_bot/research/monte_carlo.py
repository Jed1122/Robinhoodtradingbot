"""Seeded trade resampling and explicit insufficient-sample PBO estimates."""

import random
from dataclasses import dataclass
from decimal import Decimal


def resample_trade_sequences(
    trades: tuple[Decimal, ...], *, samples: int, seed: int
) -> tuple[tuple[Decimal, ...], ...]:
    if not trades or samples < 1:
        raise ValueError("resampling requires trades and positive sample count")
    rng = random.Random(seed)  # nosec B311 - deterministic research simulation, not security
    return tuple(tuple(trades[rng.randrange(len(trades))] for _ in trades) for _ in range(samples))


@dataclass(frozen=True, slots=True)
class PboEstimate:
    value: Decimal | None
    status: str
    combinations: int


def estimate_pbo(
    in_sample_scores: tuple[tuple[Decimal, ...], ...],
    out_of_sample_scores: tuple[tuple[Decimal, ...], ...],
) -> PboEstimate:
    if len(in_sample_scores) != len(out_of_sample_scores) or len(in_sample_scores) < 4:
        return PboEstimate(None, "insufficient_sample", len(in_sample_scores))
    overfit = 0
    for inside, outside in zip(in_sample_scores, out_of_sample_scores, strict=True):
        if not inside or len(inside) != len(outside):
            return PboEstimate(None, "insufficient_sample", len(in_sample_scores))
        winner = max(range(len(inside)), key=inside.__getitem__)
        median = sorted(outside)[len(outside) // 2]
        overfit += outside[winner] < median
    return PboEstimate(
        Decimal(overfit) / Decimal(len(in_sample_scores)), "defined", len(in_sample_scores)
    )


__all__ = ["PboEstimate", "estimate_pbo", "resample_trade_sequences"]
