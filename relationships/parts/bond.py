"""Bond — "What are you to me?" (spec section 11)

Interprets the persistent relationship: warmth, loyalty, protectiveness,
disappointment, tenderness. Bond does not imply niceness — a strong bond can
make anger more intense because the person matters, so Bond can vote
"engage" in the same interaction where Crash ends up winning.
"""
from __future__ import annotations

from relationships.models import PartVote

# Which relationships.preferences.LIKES names build warmth toward *this*
# person specifically — speaking her native language, kindness toward her
# witch, and real attention.
_BOND_LIKED_NAMES = {"witchcraft", "loyalty_to_witch", "genuine_compliment"}


class Bond:
    name = "Bond"

    def react(
        self,
        profile: dict,
        needs: dict,
        flags: list[str],
        message: str,
        recent_messages: list[str] | None = None,
    ) -> PartVote:
        r = profile.get("relationship", {}) if isinstance(profile, dict) else {}
        f = profile.get("friendship", {}) if isinstance(profile, dict) else {}

        liked_hits = [flag.split(":", 1)[1] for flag in flags if flag.startswith("liked:")]
        liked_hits = [name for name in liked_hits if name in _BOND_LIKED_NAMES]

        strength = (
            float(r.get("affection", 0.0)) * 0.3
            + float(r.get("trust", 0.0)) * 0.15
            + float(r.get("respect", 0.0)) * 0.15
            + float(r.get("reciprocity", 0.0)) * 0.15
            + float(r.get("reliability", 0.0)) * 0.1
            + float(r.get("closeness_desire", 0.0)) * 0.15
        )
        strength = min(1.0, strength + 0.15 * len(liked_hits))
        virtue = float(f.get("virtue", 0.0))

        hit_note = f"[hit:{','.join(liked_hits)}]" if liked_hits else ""

        if strength >= 0.55 or virtue >= 0.6:
            return PartVote(self.name, "engage", f"[bond:relational][strength:{strength:.2f}]{hit_note}")

        if float(r.get("affection", 0.0)) >= 0.6 and float(r.get("resentment", 0.0)) >= 0.4:
            # Loved but currently friction-laden — Bond still has skin in
            # the game, it just reads as tension rather than warmth.
            return PartVote(self.name, "tender_friction", f"[bond:mixed][affection:{r.get('affection', 0.0):.2f}][resentment:{r.get('resentment', 0.0):.2f}]")

        return PartVote(self.name, "neutral", f"[bond:idle][strength:{strength:.2f}]{hit_note}")
