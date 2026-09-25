"""Bond — "What are you to me?" (spec §11)"""
from __future__ import annotations

from relationships.models import PartContext, PartResult
from relationships.parts.base import Part, clamp01, weighted_mean


class Bond(Part):
    name = "Bond"

    def evaluate(self, ctx: PartContext) -> PartResult:
        r = ctx.relationship
        activation = clamp01(
            weighted_mean(
                [r.get("affection", 0.0), r.get("trust", 0.5), r.get("respect", 0.5),
                 r.get("reciprocity", 0.5), r.get("reliability", 0.5), r.get("closeness_desire", 0.0)],
                [0.30, 0.15, 0.15, 0.15, 0.10, 0.15],
            )
        )

        reason_codes: list[str] = []
        if r.get("affection", 0.0) >= 0.75:
            reason_codes.append("strong_affection")
        if r.get("closeness_desire", 0.0) >= 0.7:
            reason_codes.append("wants_them_around")
        if r.get("resentment", 0.0) >= 0.5 and r.get("affection", 0.0) >= 0.5:
            reason_codes.append("loved_but_resentful")

        vote = "engage" if activation >= 0.45 else "idle"
        return PartResult(part=self.name, activation=activation, vote=vote, reason_codes=reason_codes)
