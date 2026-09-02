"""Familiar — "Do I know you?" (spec section 10)

Recognition and established social history. Familiar may influence other
Parts without always becoming the active voice, and is PartCore's fallback
default when nothing else engages.
"""
from __future__ import annotations

from relationships.models import PartVote


class Familiar:
    name = "Familiar"

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
        stream_count = int(profile.get("stream_count", 0)) if isinstance(profile, dict) else 0
        has_recent_history = bool(recent_messages)

        if "greeting" in flags and familiarity >= 0.4:
            return PartVote(self.name, "recognize", f"[familiar:greeting][familiarity:{familiarity:.2f}]")

        if familiarity >= 0.7 and (has_recent_history or stream_count >= 5):
            return PartVote(self.name, "recognize", f"[familiar:regular][familiarity:{familiarity:.2f}]")

        if familiarity < 0.15 and not has_recent_history:
            return PartVote(self.name, "unfamiliar", f"[familiar:new_face][familiarity:{familiarity:.2f}]")

        return PartVote(self.name, "neutral", f"[familiar:idle][familiarity:{familiarity:.2f}]")
