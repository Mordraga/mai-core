"""Tease — "Do I want to fuck with you?" (spec §13)

Playful antagonism, distinct from Crash — the emotional meaning comes from
the surrounding relationship state, not from Tease itself.
"""
from __future__ import annotations

from relationships.models import PartContext, PartResult
from relationships.parts.base import Part, clamp01, weighted_mean


class Tease(Part):
    name = "Tease"

    def evaluate(self, ctx: PartContext) -> PartResult:
        r = ctx.relationship
        boredom = ctx.needs.get("boredom", 0.2)
        energy = ctx.needs.get("energy", 0.7)
        banter = sum(1 for o in ctx.observations if o.get("type") == "established_banter")
        banter_boost = clamp01(banter / 5.0)

        activation = clamp01(
            weighted_mean(
                [r.get("familiarity", 0.0), r.get("enjoyment", 0.5), r.get("trust", 0.5),
                 r.get("affection", 0.0), boredom, energy, banter_boost],
                [0.20, 0.20, 0.10, 0.10, 0.15, 0.10, 0.15],
            )
        )

        reason_codes: list[str] = []
        if banter:
            reason_codes.append("established_banter")
        if boredom >= 0.6:
            reason_codes.append("high_boredom")
        if r.get("affection", 0.0) >= 0.6:
            reason_codes.append("teasing_someone_loved")

        vote = "engage" if activation >= 0.45 else "idle"
        return PartResult(part=self.name, activation=activation, vote=vote, reason_codes=reason_codes)
