"""Tease — "Do I want to fuck with you?" (spec section 13)

Playful antagonism, distinct from Crash. Mai may tease someone she loves or
someone she dislikes — the emotional meaning comes from surrounding
relationship state, not from Tease itself.
"""
from __future__ import annotations

from relationships.models import PartVote

# Which relationships.preferences.LIKES names invite playful engagement —
# chaos, bold flirting, and actually matching her wit are Tease's territory.
# (witchcraft/genuine_compliment/loyalty_to_witch feed Bond/Desire instead.)
_TEASE_LIKED_NAMES = {"chaos_energy", "bold_flirting", "clever_banter"}


class Tease:
    name = "Tease"

    def react(
        self,
        profile: dict,
        needs: dict,
        flags: list[str],
        message: str,
        recent_messages: list[str] | None = None,
    ) -> PartVote:
        r = profile.get("relationship", {}) if isinstance(profile, dict) else {}

        familiarity = float(r.get("familiarity", 0.0))
        enjoyment = float(r.get("enjoyment", 0.0))
        trust = float(r.get("trust", 0.0))
        boredom = float(needs.get("boredom", 0.0))
        energy = float(needs.get("energy", 0.0))

        liked_hits = [f.split(":", 1)[1] for f in flags if f.startswith("liked:")]
        liked_hits = [name for name in liked_hits if name in _TEASE_LIKED_NAMES]

        # Needs shift the threshold, not the score: bored + energetic Mai
        # teases more readily.
        threshold = 0.55 - (boredom * 0.15) - (max(0.0, energy - 0.5) * 0.1)

        # A liked topic hands her something worth teasing about right now —
        # boosts the score directly, same as Desire/Bond do for their own
        # liked-flag hits, so it can carry a total stranger past threshold.
        banter_strength = familiarity * 0.35 + enjoyment * 0.35 + trust * 0.3
        banter_strength = min(1.0, banter_strength + 0.25 * len(liked_hits))

        hit_note = f"[hit:{','.join(liked_hits)}]" if liked_hits else ""

        if banter_strength >= threshold and (familiarity >= 0.3 or liked_hits):
            return PartVote(self.name, "engage", f"[tease:banter][strength:{banter_strength:.2f}][threshold:{threshold:.2f}]{hit_note}")

        return PartVote(self.name, "neutral", f"[tease:idle][strength:{banter_strength:.2f}]{hit_note}")
