"""Crash — "How close is this person to making me lose my fucking patience?" (spec §15)

An interpersonal frustration system, NOT a moderation/safety system and NOT
the inverse of affection. Someone Mai loves can still strongly activate
Crash. Outputs a tier (neutral/annoyed/snap/crash) in addition to a raw
activation score — Partcore treats "crash" as a hard override (§16.1).
"""
from __future__ import annotations

from relationships.models import PartContext, PartResult
from relationships.parts.base import Part, clamp01, weighted_mean

DEFAULT_CRASH_THRESHOLDS = {"annoyed": 0.35, "snap": 0.60, "crash": 0.85}


def _tier(activation: float, thresholds: dict) -> str:
    if activation >= thresholds.get("crash", DEFAULT_CRASH_THRESHOLDS["crash"]):
        return "crash"
    if activation >= thresholds.get("snap", DEFAULT_CRASH_THRESHOLDS["snap"]):
        return "snap"
    if activation >= thresholds.get("annoyed", DEFAULT_CRASH_THRESHOLDS["annoyed"]):
        return "annoyed"
    return "neutral"


class Crash(Part):
    name = "Crash"

    def evaluate(self, ctx: PartContext) -> PartResult:
        r = ctx.relationship
        frustration = ctx.needs.get("frustration", 0.0)
        anger = ctx.needs.get("anger", 0.0)

        pet_peeves = [o for o in ctx.observations if o.get("type") == "pet_peeve"]
        pet_peeve_salience = clamp01(max((o.get("salience", 0.5) for o in pet_peeves), default=0.0))
        repeated_pet_peeve = len(pet_peeves) >= 2

        activation = clamp01(
            weighted_mean(
                [r.get("resentment", 0.0), frustration, anger, pet_peeve_salience],
                [0.30, 0.30, 0.15, 0.25],
            )
        )

        thresholds = ctx.config.get("crash_thresholds", DEFAULT_CRASH_THRESHOLDS)
        tier = _tier(activation, thresholds)

        reason_codes: list[str] = []
        if repeated_pet_peeve:
            reason_codes.append("repeated_pet_peeve")
        if r.get("resentment", 0.0) >= 0.4:
            reason_codes.append("existing_resentment")
        if frustration >= 0.5:
            reason_codes.append("global_frustration")

        return PartResult(
            part=self.name,
            activation=activation,
            vote=tier,
            reason_codes=reason_codes,
            tier=tier,
        )
