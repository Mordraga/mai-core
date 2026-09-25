"""Familiar — "Do I know you?" (spec §10)"""
from __future__ import annotations

from relationships.models import PartContext, PartResult
from relationships.parts.base import Part, clamp01


class Familiar(Part):
    name = "Familiar"

    def evaluate(self, ctx: PartContext) -> PartResult:
        familiarity = ctx.relationship.get("familiarity", 0.0)
        reliability = ctx.relationship.get("reliability", 0.5)
        recurring = sum(1 for o in ctx.observations if o.get("type") == "recurring_behavior")
        recurring_boost = clamp01(recurring / 5.0)

        activation = clamp01(0.6 * familiarity + 0.2 * reliability + 0.2 * recurring_boost)

        reason_codes: list[str] = []
        if familiarity >= 0.7:
            reason_codes.append("established_regular")
        elif familiarity <= 0.15:
            reason_codes.append("new_or_unknown_face")
        if recurring:
            reason_codes.append("recurring_behavior_recognized")

        vote = "engage" if activation >= 0.4 else "idle"
        return PartResult(part=self.name, activation=activation, vote=vote, reason_codes=reason_codes)
