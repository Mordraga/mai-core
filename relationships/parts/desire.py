"""Desire — "Do I want you closer?" (spec §12)

Not automatically sexual — at low/moderate arousal it reads as wanting
attention/interaction/attachment. Arousal (transient) and closeness_desire
(persistent) are deliberately kept as separate inputs, never merged into a
single "horny meter".
"""
from __future__ import annotations

from relationships.models import PartContext, PartResult
from relationships.parts.base import Part, clamp01, weighted_mean


class Desire(Part):
    name = "Desire"

    def evaluate(self, ctx: PartContext) -> PartResult:
        r = ctx.relationship
        arousal = ctx.needs.get("arousal", 0.0)
        social_need = ctx.needs.get("social_need", 0.5)

        activation = clamp01(
            weighted_mean(
                [r.get("closeness_desire", 0.0), r.get("interest", 0.5), r.get("affection", 0.0),
                 r.get("enjoyment", 0.5), arousal, social_need],
                [0.30, 0.15, 0.15, 0.15, 0.15, 0.10],
            )
        )
        if ctx.task == "flirt":
            activation = clamp01(activation + 0.1)

        reason_codes: list[str] = []
        if r.get("closeness_desire", 0.0) >= 0.7:
            reason_codes.append("high_closeness_desire")
        if arousal >= 0.6 and ctx.task == "flirt":
            reason_codes.append("arousal_flirt_context")
        elif r.get("closeness_desire", 0.0) >= 0.4:
            reason_codes.append("wants_attention_not_sexual")

        vote = "engage" if activation >= 0.45 else "idle"
        return PartResult(part=self.name, activation=activation, vote=vote, reason_codes=reason_codes)
