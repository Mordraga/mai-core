"""Desire — "Do I want you closer?" (spec section 12)

Not automatically sexual. closeness_desire (persistent relationship state)
and arousal (transient global need) are kept as separate reads and never
merged into one number, per spec: spice/arousal/closeness_desire must stay
distinguishable.
"""
from __future__ import annotations

from relationships.models import PartVote

# Which relationships.preferences.LIKES names pull her closer — bold
# flirting and genuine attention, specifically.
_DESIRE_LIKED_NAMES = {"bold_flirting", "genuine_compliment"}


class Desire:
    name = "Desire"

    def react(
        self,
        profile: dict,
        needs: dict,
        flags: list[str],
        message: str,
        recent_messages: list[str] | None = None,
    ) -> PartVote:
        r = profile.get("relationship", {}) if isinstance(profile, dict) else {}

        closeness = float(r.get("closeness_desire", 0.0))
        interest = float(r.get("interest", 0.0))
        affection = float(r.get("affection", 0.0))
        enjoyment = float(r.get("enjoyment", 0.0))
        social_need = float(needs.get("social_need", 0.0))
        arousal = float(needs.get("arousal", 0.0))

        liked_hits = [f.split(":", 1)[1] for f in flags if f.startswith("liked:")]
        liked_hits = [name for name in liked_hits if name in _DESIRE_LIKED_NAMES]

        pull = closeness * 0.35 + interest * 0.2 + affection * 0.2 + enjoyment * 0.15 + social_need * 0.1
        pull = min(1.0, pull + 0.15 * len(liked_hits))

        hit_note = f"[hit:{','.join(liked_hits)}]" if liked_hits else ""

        if pull >= 0.6:
            tag = "flirty" if arousal >= 0.5 else "attentive"
            return PartVote(self.name, "engage", f"[desire:{tag}][pull:{pull:.2f}][arousal:{arousal:.2f}]{hit_note}")

        if closeness <= 0.15 and social_need <= 0.3 and not liked_hits:
            return PartVote(self.name, "cool", f"[desire:distant][pull:{pull:.2f}]")

        return PartVote(self.name, "neutral", f"[desire:idle][pull:{pull:.2f}]{hit_note}")
