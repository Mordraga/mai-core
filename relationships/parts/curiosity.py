"""Curiosity — "Do I want to understand you?" (spec §14)

Particularly important when an individual contradicts Mai's collective
expectations of The Crypt (§22/§23) — the collective relationship is a
prior, not a verdict; individual evidence dominates as familiarity grows.
"""
from __future__ import annotations

from relationships.models import PartContext, PartResult
from relationships.parts.base import Part, clamp01, weighted_mean

_DIVERGENCE_KEYS = ("enjoyment", "affection", "trust", "reliability", "respect")


def expectation_divergence(relationship: dict, crypt_relationship: dict) -> float:
    """Mean absolute distance between an individual and the collective prior."""
    if not crypt_relationship:
        return 0.0
    diffs = [
        abs(relationship.get(key, 0.5) - crypt_relationship.get(key, 0.5))
        for key in _DIVERGENCE_KEYS
    ]
    return clamp01(sum(diffs) / len(diffs))


class Curiosity(Part):
    name = "Curiosity"

    def evaluate(self, ctx: PartContext) -> PartResult:
        r = ctx.relationship
        divergence = expectation_divergence(r, ctx.crypt_relationship)
        familiarity = r.get("familiarity", 0.0)
        # Divergence matters most while the individual model is still thin —
        # individual evidence should dominate as familiarity grows (§22).
        weighted_divergence = divergence * (1.0 - 0.6 * familiarity)

        activation = clamp01(
            weighted_mean(
                [r.get("interest", 0.5), weighted_divergence],
                [0.55, 0.45],
            )
        )

        reason_codes: list[str] = []
        if weighted_divergence >= 0.35:
            reason_codes.append("violates_crypt_expectation")
        if r.get("interest", 0.5) >= 0.8:
            reason_codes.append("psychologically_interesting")

        vote = "engage" if activation >= 0.45 else "idle"
        return PartResult(part=self.name, activation=activation, vote=vote, reason_codes=reason_codes)
