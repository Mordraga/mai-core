"""
Part interface — each Part is a pure function of PartContext -> PartResult (§16).

No I/O, no LLM calls here: Parts only decide activation/vote/reason_codes.
MythoMax still writes the actual words (§2.3).
"""
from __future__ import annotations

from relationships.models import PartContext, PartResult


class Part:
    name: str = "Part"

    def evaluate(self, ctx: PartContext) -> PartResult:
        raise NotImplementedError


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def weighted_mean(values: list[float], weights: list[float]) -> float:
    total_weight = sum(weights)
    if total_weight <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight
