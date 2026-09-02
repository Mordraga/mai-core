"""Curiosity — "Do I want to understand you?" (spec section 14)

Particularly important when an individual contradicts Mai's collective
expectations of The Crypt. `expectation_violation` is accepted now and
always 0.0/neutral in this pass — The Crypt collective prior is spec Phase
5 and not built yet; this keeps the interface ready so Phase 5 only has to
pass a real number in, not change this Part's signature.
"""
from __future__ import annotations

from relationships.models import PartVote


class Curiosity:
    name = "Curiosity"

    def react(
        self,
        profile: dict,
        needs: dict,
        flags: list[str],
        message: str,
        recent_messages: list[str] | None = None,
        expectation_violation: float = 0.0,
    ) -> PartVote:
        r = profile.get("relationship", {}) if isinstance(profile, dict) else {}

        interest = float(r.get("interest", 0.0))
        familiarity = float(r.get("familiarity", 0.0))
        try:
            violation = max(0.0, min(1.0, float(expectation_violation)))
        except (TypeError, ValueError):
            violation = 0.0

        pull = interest * 0.6 + violation * 0.4

        # Low familiarity + moderate-high interest reads as "who is this,
        # exactly" — new-face curiosity, distinct from established-contrast
        # curiosity driven by expectation violation.
        if violation >= 0.5:
            return PartVote(self.name, "engage", f"[curiosity:contrast][pull:{pull:.2f}][violation:{violation:.2f}]")

        if interest >= 0.7:
            return PartVote(self.name, "engage", f"[curiosity:fascinated][pull:{pull:.2f}]")

        if familiarity < 0.25 and interest >= 0.4:
            return PartVote(self.name, "engage", f"[curiosity:new_face][pull:{pull:.2f}]")

        return PartVote(self.name, "neutral", f"[curiosity:idle][pull:{pull:.2f}]")
