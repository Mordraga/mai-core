"""Crash — "How close is this person to making me lose my fucking patience?"
(spec section 15)

Crash is an interpersonal frustration system, NOT a moderation/safety
system, NOT a dislike score, and NOT the inverse of affection — someone Mai
loves can strongly activate Crash. Live pet-peeve hits come from
`relationships.preferences` via the "pet_peeve:<name>" flags instincts.py
already scans for in the current message. Remembered pet-peeve hits come
from `profile["observations"]` — entries relationships/mutation.py's LLM
inference persisted from past exchanges (spec Phase 4) — each one's
`reinforced_count` counting how many times it's actually recurred, not
just whether it exists. `pet_peeve_hits` stays available as an explicit
override/testing hook and stacks on top of both.

Votes on the neutral/annoyed/snap/crash ladder from spec 15.1. "crash" is
the hard-override vote PartCore checks before anything else.
"""
from __future__ import annotations

from relationships.models import PartVote


class Crash:
    name = "Crash"

    def react(
        self,
        profile: dict,
        needs: dict,
        flags: list[str],
        message: str,
        recent_messages: list[str] | None = None,
        pet_peeve_hits: int = 0,
    ) -> PartVote:
        r = profile.get("relationship", {}) if isinstance(profile, dict) else {}

        resentment = float(r.get("resentment", 0.0))
        frustration = float(needs.get("frustration", 0.0))
        anger = float(needs.get("anger", 0.0))
        try:
            accumulated_hits = max(0, int(pet_peeve_hits))
        except (TypeError, ValueError):
            accumulated_hits = 0

        observations = profile.get("observations", []) if isinstance(profile, dict) else []
        remembered_hits = sum(
            int(obs.get("reinforced_count", 1))
            for obs in observations
            if isinstance(obs, dict) and obs.get("type") == "pet_peeve"
        )
        accumulated_hits += remembered_hits

        live_peeve_names = [f.split(":", 1)[1] for f in flags if f.startswith("pet_peeve:")]

        pressure = resentment * 0.35 + frustration * 0.35 + anger * 0.3
        pressure = min(1.0, pressure + (0.45 * len(live_peeve_names)) + (0.1 * accumulated_hits))

        if "command_spam" in flags:
            pressure = min(1.0, pressure + 0.15)

        hit_note = f"[hit:{','.join(live_peeve_names)}]" if live_peeve_names else ""

        if pressure >= 0.85:
            return PartVote(self.name, "crash", f"[crash:crash_out][pressure:{pressure:.2f}]{hit_note}")
        if pressure >= 0.65:
            return PartVote(self.name, "snap", f"[crash:snap][pressure:{pressure:.2f}]{hit_note}")
        if pressure >= 0.4:
            return PartVote(self.name, "annoyed", f"[crash:annoyed][pressure:{pressure:.2f}]{hit_note}")
        return PartVote(self.name, "neutral", f"[crash:idle][pressure:{pressure:.2f}]{hit_note}")
